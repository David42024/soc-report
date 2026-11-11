"""Atomic phase-0 validation records, ready for subsequent experiment phases."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from math import isfinite
from numbers import Real
import os
from pathlib import Path
import platform
import re
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, SecretStr, ValidationError

from src.utils.config import AnalyticsSettings
from src.utils.errors import AnalyticsError
from src.utils.reproducibility import software_versions
from src.utils.security import redact

LOGGER = logging.getLogger("soc_analytics.experiments")

if TYPE_CHECKING:
    from src.data.catalog import DatasetCatalog


class DatasetFingerprint(BaseModel):
    """A fingerprint has an explicit source and scope, never the original rows."""

    source_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hash_scope: str = Field(min_length=1)
    definition: dict[str, Any] | None = None


class StoredRun(BaseModel):
    """Validate stored records before exposing their metadata to the interface."""

    schema_version: Literal[1]
    run_id: str = Field(pattern=r"^\d{8}T\d{12}Z_[0-9a-f]{12}$")
    kind: Literal["environment_validation"]
    phase: Literal[0]
    created_at: datetime
    seed: int
    python_hash_seed_at_start: bool
    dataset: DatasetFingerprint
    config: dict[str, Any]
    metrics: dict[str, float]
    software: dict[str, str]
    python: str
    requirements_sha256: str | None
    requirements_lock_sha256: str | None = None
    dataset_catalog_sha256: str | None = None
    audit_state: Literal["local", "pendiente", "confirmada"] = "local"


class RunRegistry:
    """Store metadata only, with no credentials, report texts or copied datasets."""

    def __init__(self, settings: AnalyticsSettings) -> None:
        self.settings = settings
        self.directory = settings.path(settings.runs_dir)

    def record_validation(self, snapshot: dict, metrics: dict[str, Real], *, audit_state: str = "local") -> dict:
        """Persist config, finite metrics, full hash scope, software and UTC date."""
        if not re.fullmatch(r"[a-z][a-z0-9_]*", str(snapshot.get("source_id", ""))) or not re.fullmatch(r"[0-9a-f]{64}", str(snapshot.get("sha256", ""))):
            raise AnalyticsError("El registro requiere una fuente identificada y una huella SHA-256 válida.")
        if any(not isinstance(value, Real) or not isfinite(value) for value in metrics.values()):
            raise AnalyticsError("Las métricas deben contener números finitos.")
        now = datetime.now(timezone.utc)
        run_id = now.strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid4().hex[:12]
        record = {"schema_version": 1, "run_id": run_id, "kind": "environment_validation", "phase": 0,
                  "created_at": now.isoformat(), "seed": self.settings.seed,
                  "python_hash_seed_at_start": os.environ.get("PYTHONHASHSEED") == str(self.settings.seed),
                  "dataset": {**{key: snapshot[key] for key in ("source_id", "sha256", "hash_scope")},
                              "definition": snapshot.get("definition")},
                  "config": self.settings.model_dump(mode="json"), "metrics": {key: float(value) for key, value in metrics.items()},
                  "software": software_versions(self.settings.software), "python": platform.python_version(),
                  "requirements_sha256": self._file_hash(self.settings.root / "requirements.txt"),
                  "requirements_lock_sha256": self._file_hash(self.settings.root / "requirements.lock.txt"),
                  "dataset_catalog_sha256": self._file_hash(self.settings.path(self.settings.registry_file)), "audit_state": audit_state}
        record = StoredRun.model_validate(redact(record)).model_dump(mode="json")
        try:
            directory = self.directory / run_id
            directory.mkdir(parents=True, exist_ok=False)
            temporary = directory / "record.tmp"
            temporary.write_text(json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
            temporary.replace(directory / "record.json")
        except OSError:
            raise AnalyticsError("No se pudo guardar la verificación en runs/. Revisa los permisos de escritura.") from None
        LOGGER.info("Verificación de entorno registrada %s", run_id)
        return record

    def record_source_validation(self, catalog: DatasetCatalog, snapshot: dict, token: SecretStr) -> dict:
        """Revalidate permission and collect technical counts for this phase only."""
        if not catalog.api.me(token).can("write"):
            raise AnalyticsError("Tu rol no permite registrar esta verificación.")
        source = catalog.source(snapshot["source_id"])
        snapshot = {**snapshot, "definition": source.model_dump(mode="json")}
        profiles = catalog.inspect_all()
        catalog.api.audit_event(token, "registrar_verificacion", source_id=source.id, outcome="iniciado")
        record = self.record_validation(snapshot, {"registered_sources": len(profiles),
            "available_files": sum(item["status"] == "disponible" for item in profiles),
            "preview_rows": len(snapshot["rows"])}, audit_state="pendiente")
        catalog.api.audit_event(token, "registrar_verificacion", source_id=source.id, run_id=record["run_id"])
        record["audit_state"] = "confirmada"
        try:
            path = self.directory / record["run_id"] / "record.json"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
            temporary.replace(path)
        except OSError:
            raise AnalyticsError("La verificación fue auditada; no se pudo actualizar su confirmación local.") from None
        return record

    def authorized_records(self, api, token: SecretStr) -> list[dict]:
        """Read validation reports only after backend authorization and audit."""
        if not api.me(token).can("read"):
            raise AnalyticsError("Tu rol no permite consultar estos informes.")
        rows = self.records()
        api.audit_event(token, "consultar_registros")
        return rows

    @staticmethod
    def _file_hash(path: Path) -> str | None:
        return sha256(path.read_bytes()).hexdigest() if path.is_file() else None

    def records(self) -> list[dict]:
        """Read complete records only, skipping corrupted or incomplete writes."""
        result = []
        for path in sorted(self.directory.glob("*/record.json"), reverse=True):
            if not path.resolve().is_relative_to(self.directory.resolve()):
                continue
            try:
                if path.stat().st_size > self.settings.ui.max_json_bytes:
                    continue
                row = json.loads(path.read_text(encoding="utf-8"))
                parsed = StoredRun.model_validate(redact(row)).model_dump(mode="json")
                if parsed["run_id"] == path.parent.name:
                    result.append(parsed)
            except (OSError, ValueError, AttributeError, ValidationError):
                LOGGER.warning("Se omitió un registro de validación no legible")
        return result
