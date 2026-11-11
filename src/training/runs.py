"""Persistent job inputs, checkpoints, progress and published results."""
from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import file_digest
import json
import logging
from pathlib import Path
import platform
from threading import RLock
from time import sleep
from typing import Literal

from pydantic import Field, model_validator

from scripts.soc_dataset import write_json
from src.data.manifest import VERSION_ID
from src.data.models import LabelField, content_hash
from src.data.revisions import operation_identity
from src.inference.experimental import CloudParameters
from src.training.local import Family
from src.training.partition import Case, Partition, TestSeal
from src.training.settings import LocalParameters, SettingsModel
from src.optimization.contracts import SearchOptions, validate_space
from src.utils.config import AnalyticsSettings
from src.utils.errors import AnalyticsError
from src.utils.reproducibility import software_versions

LOGGER = logging.getLogger("soc_analytics.training")


class JobSpec(SettingsModel):
    """A user selection with only one mode and one supervised target."""

    source: Literal["real", "sintetico"]
    target: LabelField
    seed: int = Field(ge=0, le=2**32 - 1)
    trials: int = Field(ge=1, le=100)
    manifest_version: str | None = None
    models: tuple[Family, ...] = ()
    local: LocalParameters | None = None
    cloud: CloudParameters | None = None
    optimization: SearchOptions | None = None

    @model_validator(mode="after")
    def valid_mode(self) -> JobSpec:
        if self.source == "real":
            if not self.manifest_version or not VERSION_ID.fullmatch(self.manifest_version):
                raise ValueError("Selecciona la versión de datos.")
        elif self.manifest_version or self.target != "tipo" or self.cloud is not None:
            raise ValueError("La prueba técnica solo usa modelos locales para el tipo.")
        if self.cloud:
            if self.models or self.local:
                raise ValueError("Selecciona una sola modalidad.")
        elif not self.local or not self.models or len(set(self.models)) != len(self.models):
            raise ValueError("Selecciona uno o ambos modelos académicos y sus parámetros.")
        if self.optimization:
            validate_space(self.optimization, self.local, self.cloud, self.models, self.target)
        return self

    @property
    def mode(self) -> str:
        return "langflow" if self.cloud else "academico"


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_hash(path: Path) -> str | None:
    if path.is_file():
        with path.open("rb") as handle:
            return file_digest(handle, "sha256").hexdigest()
    return None


def fingerprint(settings: AnalyticsSettings, software: dict[str, str] | None = None) -> dict:
    """Capture the numerical stack and code needed to reproduce an interrupted job."""
    paths = [*sorted((settings.root / "src/training").glob("*.py")),
             *sorted((settings.root / "src/optimization").glob("*.py")), settings.root / "src/inference/experimental.py"]
    return {"python": platform.python_version(), "software": software if software is not None else software_versions(settings.software),
            "requirements_lock_sha256": _file_hash(settings.root / "requirements.lock.txt"),
            "code_sha256": content_hash({path.relative_to(settings.root).as_posix(): _file_hash(path) for path in paths})}


class RunStore:
    """Keep text-bearing work files private and publish metrics-only reports."""

    def __init__(self, settings: AnalyticsSettings) -> None:
        self.settings = settings
        self.directory = settings.path(Path(settings.runs_dir) / settings.training.directory)
        self.software = software_versions(settings.software)
        self._io_lock = RLock()

    def write(self, run_id: str, name: str, payload: dict) -> None:
        """Serialize local readers and tolerate brief Windows sharing locks."""
        with self._io_lock:
            for attempt in range(5):
                try:
                    write_json(self.path(run_id) / name, payload)
                    return
                except PermissionError:
                    if attempt == 4:
                        raise AnalyticsError("El archivo de la ejecución sigue ocupado. Revisa los permisos y el monitor.") from None
                    sleep(.05 * (attempt + 1))

    def path(self, run_id: str) -> Path:
        if not VERSION_ID.fullmatch(run_id):
            raise AnalyticsError("Selecciona una ejecución registrada.")
        directory = (self.directory / run_id).resolve()
        if not directory.is_relative_to(self.directory.resolve()):
            raise AnalyticsError("La ejecución no pertenece al directorio configurado.")
        return directory

    def create(self, spec: JobSpec, partition: Partition, owner: str,
               authorize: Callable[[str], None], quote: dict | None = None) -> str:
        run_id, created_at = operation_identity()
        evidence = partition.evidence()
        work = {"development": [case.model_dump() for case in partition.development],
                "validation": [case.model_dump() for case in partition.validation], "seal": asdict(partition.test)}
        record = {
            "schema_version": 1, "phase": 2, "run_id": run_id, "created_at": created_at, "owner": owner,
            "mode": spec.mode, "request": spec.model_dump(mode="json"), "policy": self.settings.training.model_dump(mode="json"),
            "work_sha256": content_hash(work), "partition_sha256": content_hash(evidence),
            "environment": fingerprint(self.settings, self.software), "budget": quote,
        }
        record["content_sha256"] = content_hash(record)
        authorize(run_id)
        directory = self.path(run_id)
        try:
            directory.mkdir(parents=True, exist_ok=False)
            self.write(run_id, "work.json", work)
            self.write(run_id, "partition.json", evidence)
            self.write(run_id, "run.json", record)
            self.write(run_id, "state.json", {"status": "pendiente", "seconds": 0.0, "events": 0,
                                               "flow_calls": 0, "updated_at": created_at})
        except OSError:
            raise AnalyticsError("No se pudo preparar la ejecución en runs/.") from None
        return run_id

    def read(self, run_id: str, name: str) -> dict:
        """Read a fixed artifact generated by the local runner."""
        try:
            with self._io_lock:
                return json.loads((self.path(run_id) / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise AnalyticsError("La ejecución seleccionada no tiene un registro legible.") from None

    def verified(self, run_id: str, name: Literal["run.json", "result.json"]) -> dict:
        """Validate immutable job metadata and published reports before reuse."""
        data = self.read(run_id, name)
        if (not isinstance(data, dict) or data.get("run_id") != run_id or
                data.get("content_sha256") != content_hash({key: value for key, value in data.items() if key != "content_sha256"})):
            raise AnalyticsError("La huella del registro experimental cambió.")
        return data

    def inputs(self, run_id: str) -> tuple[dict, JobSpec, Partition]:
        record = self.verified(run_id, "run.json")
        work = self.read(run_id, "work.json")
        try:
            evidence = self.read(run_id, "partition.json")
            if (record["work_sha256"] != content_hash(work) or
                    record["partition_sha256"] != content_hash(evidence)):
                raise ValueError
            spec = JobSpec.model_validate(record["request"])
            seal = TestSeal(**{**work["seal"], "groups": tuple(work["seal"]["groups"])})
            partition = Partition(tuple(Case.model_validate(row) for row in work["development"]),
                                  tuple(Case.model_validate(row) for row in work["validation"]), seal,
                                  spec.source, evidence["source_sha256"], spec.manifest_version)
            if content_hash(partition.evidence()) != record["partition_sha256"]:
                raise ValueError
            groups = [{case.group for case in rows} for rows in (partition.development, partition.validation)] + [set(seal.groups)]
            if sum(map(len, groups)) != len(set.union(*groups)):
                raise ValueError
            return record, spec, partition
        except (ValueError, KeyError, TypeError):
            raise AnalyticsError("Las huellas del trabajo o la partición cambiaron.") from None

    def checkpoint(self, run_id: str) -> dict:
        path = self.path(run_id) / "checkpoint.json"
        if not path.is_file():
            return {}
        envelope = self.read(run_id, path.name)
        if content_hash(envelope.get("data")) != envelope.get("sha256") or not isinstance(envelope.get("data"), dict):
            raise AnalyticsError("El punto de control está dañado.")
        return envelope["data"]

    def save_checkpoint(self, run_id: str, payload: dict) -> None:
        self.write(run_id, "checkpoint.json", {"data": payload, "sha256": content_hash(payload)})

    def state(self, run_id: str) -> dict:
        return self.read(run_id, "state.json")

    def save_state(self, run_id: str, state: dict) -> None:
        self.write(run_id, "state.json", state)

    def append_event(self, run_id: str, event: dict) -> None:
        with self._io_lock, (self.path(run_id) / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")

    def recent_events(self, run_id: str) -> list[dict]:
        path = self.path(run_id) / "events.jsonl"
        if not path.is_file():
            return []
        try:
            with self._io_lock, path.open(encoding="utf-8") as handle:
                lines = deque(handle, maxlen=self.settings.training.recent_events)
            return [json.loads(line) for line in lines if line.endswith("\n")]
        except (OSError, ValueError):
            raise AnalyticsError("No se pudo consultar la bitácora del trabajo.") from None

    def versions(self) -> list[dict]:
        result = []
        for path in sorted(self.directory.glob("*/state.json"), reverse=True):
            if not VERSION_ID.fullmatch(path.parent.name):
                continue
            try:
                record = self.verified(path.parent.name, "run.json")
                state = self.state(path.parent.name)
                result.append({"run_id": record["run_id"], "status": state["status"], "mode": record["mode"],
                               "source": record["request"]["source"], "target": record["request"]["target"],
                               "optimization": bool(record["request"].get("optimization"))})
            except (AnalyticsError, KeyError):
                LOGGER.warning("Se omitió una ejecución sin metadatos legibles.")
            if len(result) == self.settings.data.max_history_entries:
                break
        return result
