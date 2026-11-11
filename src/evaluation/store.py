"""Durable once-only ledger and versioned evaluation artifacts."""
from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from scripts.soc_dataset import write_json
from src.data.manifest import VERSION_ID
from src.data.models import content_hash
from src.data.revisions import operation_identity
from src.utils.config import AnalyticsSettings
from src.utils.errors import AnalyticsError

SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluation (
  id TEXT PRIMARY KEY, dataset TEXT NOT NULL, configuration TEXT NOT NULL,
  source TEXT NOT NULL, target TEXT NOT NULL, family TEXT NOT NULL, phase2 TEXT NOT NULL,
  created_at TEXT NOT NULL, status TEXT NOT NULL, result TEXT, excerpts TEXT,
  UNIQUE (dataset, configuration)
);
CREATE TABLE IF NOT EXISTS comparison (
  id TEXT PRIMARY KEY, signature TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
  result TEXT NOT NULL
);
"""


def _sealed(result: dict) -> dict:
    return {**result, "content_sha256": content_hash(result)}


def _verified(payload: str, run_id: str) -> dict:
    try:
        result = json.loads(payload)
        digest = result.pop("content_sha256")
        if result["run_id"] == run_id and content_hash(result) == digest:
            return {**result, "content_sha256": digest}
    except (TypeError, KeyError, ValueError):
        pass
    raise AnalyticsError("La huella del registro de evaluación cambió.")


class EvaluationStore:
    """Reserve a cohort/configuration before inference and retain failures."""

    def __init__(self, settings: AnalyticsSettings) -> None:
        self.directory = settings.path(Path(settings.runs_dir) / settings.evaluation.directory)
        self.database = self.directory / "evaluations.sqlite3"
        self.history_limit = settings.data.max_history_entries

    @contextmanager
    def connection(self, *, write: bool = False):
        try:
            if write:
                self.directory.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.database, timeout=12)
            try:
                db.row_factory = sqlite3.Row
                if write:
                    db.executescript(SCHEMA)
                with db:
                    yield db
            finally:
                db.close()
        except (OSError, sqlite3.Error):
            raise AnalyticsError("No se pudo acceder al registro local de evaluación.") from None

    def reserve(self, metadata: dict, authorize: Callable[[str], None]) -> tuple[str, bool]:
        """Return an existing complete result, or atomically authorize a new one."""
        run_id, date = operation_identity()
        dataset, configuration = metadata["dataset_sha256"], metadata["configuration_sha256"]
        with self.connection(write=True) as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT id,status FROM evaluation WHERE dataset=? AND configuration=?",
                                  (dataset, configuration)).fetchone()
            if existing:
                if existing["status"] == "completa":
                    return existing["id"], False
                raise AnalyticsError("Esta configuración y versión de Prueba ya tienen una reserva o ejecución fallida. Se conserva la evaluación única.")
            authorize(run_id)
            db.execute("""INSERT INTO evaluation (id,dataset,configuration,source,target,family,phase2,created_at,status)
                          VALUES (?,?,?,?,?,?,?,?,'reservada')""",
                       (run_id, dataset, configuration, metadata["source"], metadata["target"],
                        metadata["family"], metadata["phase2_run_id"], date))
        return run_id, True

    def publish(self, run_id: str, report: dict, excerpts: dict) -> dict:
        payload = _sealed({**report, "run_id": run_id})
        with self.connection(write=True) as db:
            changed = db.execute("UPDATE evaluation SET status='completa',result=?,excerpts=? WHERE id=? AND status='reservada'",
                                 (json.dumps(payload, ensure_ascii=False), json.dumps(excerpts, ensure_ascii=False), run_id))
            if changed.rowcount != 1:
                raise AnalyticsError("La evaluación perdió su reserva y no pudo publicarse.")
        self.export(run_id, "result.json", payload)
        return payload

    def failure(self, run_id: str, report: dict) -> None:
        payload = _sealed({**report, "run_id": run_id})
        with self.connection(write=True) as db:
            db.execute("UPDATE evaluation SET status='fallida',result=? WHERE id=? AND status='reservada'",
                       (json.dumps(payload, ensure_ascii=False), run_id))
        self.export(run_id, "failure.json", payload)

    def export(self, run_id: str, name: str, report: dict) -> None:
        directory = self.directory / run_id
        try:
            directory.mkdir(exist_ok=True)
            write_json(directory / name, report)
        except OSError:
            # The immutable payload remains available via SQLite and the UI.
            return

    def list(self) -> list[dict]:
        if not self.database.is_file():
            return []
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                """SELECT id AS run_id, dataset AS dataset_sha256, source, target, family, phase2 AS phase2_run_id,
                          created_at, status FROM evaluation ORDER BY created_at DESC LIMIT ?""", (self.history_limit,))]

    def result(self, run_id: str) -> dict:
        if not VERSION_ID.fullmatch(run_id) or not self.database.is_file():
            raise AnalyticsError("Selecciona una evaluación registrada.")
        with self.connection() as db:
            row = db.execute("SELECT result FROM evaluation WHERE id=?", (run_id,)).fetchone()
        if not row or not row["result"]:
            raise AnalyticsError("La evaluación todavía no tiene un resultado publicado.")
        return _verified(row["result"], run_id)

    def excerpt(self, run_id: str, case_key: str) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT excerpts FROM evaluation WHERE id=? AND status='completa'", (run_id,)).fetchone()
        result = json.loads(row["excerpts"] or "{}").get(case_key) if row else None
        if not result:
            raise AnalyticsError("El registro protegido seleccionado no está disponible.")
        return result

    def cohort(self, dataset: str, target: str) -> list[dict]:
        with self.connection() as db:
            rows = list(db.execute(
                "SELECT id,result FROM evaluation WHERE dataset=? AND target=? AND status='completa' ORDER BY id",
                (dataset, target)))
        return [_verified(row["result"], row["id"]) for row in rows]

    def comparison(self, signature: str, report: dict, authorize: Callable[[str], None]) -> dict:
        run_id, date = operation_identity()
        payload = _sealed({**report, "run_id": run_id, "created_at_utc": date})
        with self.connection(write=True) as db:
            db.execute("BEGIN IMMEDIATE")
            stored = db.execute("SELECT id,result FROM comparison WHERE signature=?", (signature,)).fetchone()
            if stored:
                return _verified(stored["result"], stored["id"])
            authorize(run_id)
            db.execute("INSERT INTO comparison VALUES (?,?,?,?)",
                       (run_id, signature, date, json.dumps(payload, ensure_ascii=False)))
        self.export(run_id, "comparison.json", payload)
        return payload

    def comparisons(self) -> list[dict]:
        """Read archived comparisons without recalculating tests or opening predictions."""
        if not self.database.is_file():
            return []
        with self.connection() as db:
            rows = db.execute("SELECT id,result FROM comparison ORDER BY created_at DESC LIMIT ?", (self.history_limit,))
            return [_verified(row["result"], row["id"]) for row in rows]
