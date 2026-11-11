"""Immutable versioned XAI reports and independently registered human spans."""
from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path

from src.data.manifest import ManifestStore, VERSION_ID
from src.data.models import content_hash
from src.data.revisions import operation_identity
from src.utils.config import AnalyticsSettings
from src.utils.errors import AnalyticsError


class ExplanationStore:
    """Append artifacts after backend authorization, and verify every read."""

    def __init__(self, settings: AnalyticsSettings) -> None:
        self.directory = settings.path(Path(settings.runs_dir) / settings.explainability.directory)
        self.max_bytes = settings.data.max_csv_bytes
        self.history_limit = settings.data.max_history_entries

    def append(self, kind: str, payload: dict, authorize: Callable[[str], None]) -> dict:
        identifier, date = operation_identity()
        data = {**payload, "kind": kind, "schema_version": 1, "phase": 4, "run_id": identifier, "created_at_utc": date}
        result = {**data, "content_sha256": content_hash(data)}
        raw = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
        if len(raw) > self.max_bytes:
            raise AnalyticsError("El informe XAI supera el tamaño configurado.")
        authorize(identifier)
        try:
            directory = self.directory / identifier
            directory.mkdir(parents=True, exist_ok=False)
            ManifestStore._publish(directory, "result.json", raw)
        except OSError:
            raise AnalyticsError("No se pudo publicar el registro de explicabilidad.") from None
        return result

    def read(self, identifier: str) -> dict:
        if not VERSION_ID.fullmatch(identifier):
            raise AnalyticsError("Selecciona un registro de explicabilidad válido.")
        path = self.directory / identifier / "result.json"
        try:
            if not path.resolve().is_relative_to(self.directory.resolve()) or path.stat().st_size > self.max_bytes:
                raise ValueError
            result = json.loads(path.read_text(encoding="utf-8"))
            original = result.pop("content_sha256")
            if result["run_id"] != identifier or content_hash(result) != original:
                raise ValueError
            return {**result, "content_sha256": original}
        except (OSError, KeyError, TypeError, ValueError):
            raise AnalyticsError("El artefacto de explicabilidad no está disponible o su huella cambió.") from None

    def records(self, kind: str = "explicacion") -> list[dict]:
        records = []
        for path in sorted(self.directory.glob("*/result.json"), reverse=True):
            if VERSION_ID.fullmatch(path.parent.name):
                report = self.read(path.parent.name)
                if report["kind"] == kind:
                    records.append(report)
                if len(records) >= self.history_limit:
                    break
        return records
