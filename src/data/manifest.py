"""Versioned data evidence and eligibility, without building model partitions."""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict
from hashlib import file_digest
import json
import os
from pathlib import Path
import re

from pydantic import ValidationError

from backend.report_input import ReportInput
from src.data.models import DataInventory, DataRecord, SEVERITIES, TARGETS, TYPES, content_hash
from src.data.quality import Groups, Similarity, quality_checks
from src.data.revisions import operation_identity
from src.data.statistics import coverage
from src.utils.config import AnalyticsSettings
from src.utils.errors import DatasetError
from src.utils.reproducibility import software_versions

VERSION_ID = re.compile(r"^\d{8}T\d{12}Z_[0-9a-f]{12}$")


def holdout_status(inventory: DataInventory, groups: Groups) -> dict:
    """Derive test availability from the reviewed artifact and observed overlap."""
    observed = asdict(inventory.holdout)
    reasons = []
    if inventory.holdout.preparation_pending:
        reasons.append(f"{inventory.holdout.preparation_pending} decisiones de preparación pendientes.")
    if not inventory.holdout.type_review_verified:
        reasons.append("Falta un manifiesto de prueba con revisión independiente de tipo verificada.")
    if groups.conflicts:
        reasons.append(f"{len(groups.conflicts)} grupos conectan casos reservados y expuestos en piloto.")
    stamp = next(({"mtime_ns": mtime, "bytes": size} for name, mtime, size in inventory.input_fingerprint
                  if name == "__holdout__" and size), None)
    observed.update({
        "test_ready_by_target": {"tipo": not reasons, "severidad": False, "activo_afectado": False},
        "reviewed_counts_by_target": {"tipo": inventory.holdout.reviewed_type_counts, "severidad": {}, "activo_afectado": {}},
        "artifact_stat": stamp if inventory.holdout.type_review_verified else None,
        "reasons": reasons,
        "field_scope": "El contrato de revisión independiente existente documenta el tipo. "
                       "Para severidad y activo falta evidencia independiente por campo.",
    })
    return observed


def _candidate(record: DataRecord, groups: Groups) -> bool:
    if record.nature != "real" or record.review_state == "excluido" or groups.by_record[record.key] in groups.reserved:
        return False
    if any(issue in record.issues for issue in ("estructura_invalida", "identificador_ausente", "columnas_inconsistentes")):
        return False
    if not any(record.label(field).human_reference for field in TARGETS):
        return False
    try:
        ReportInput(titulo=record.title, descripcion=record.description)
    except ValidationError:
        return False
    return True


def _hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        return file_digest(handle, "sha256").hexdigest()


def manifest_content(inventory: DataInventory, groups: Groups, similarity: Similarity,
                     settings: AnalyticsSettings) -> dict:
    """Build canonical data evidence without texts, credentials or reviewer identities."""
    sources, eligible, revisions = [], {field: [] for field in TARGETS}, []
    for source in inventory.sources:
        sources.append({
            "id": source.id, "name": source.name, "format": source.format, "location": source.location,
            "provenance": source.provenance, "revision": source.revision, "status": source.status,
            "sha256": source.sha256, "hash_scope": source.hash_scope, "rows": len(source.records),
            "schema": list(source.columns), "original_headers": list(source.original_columns),
            "notes": list(source.notes), "limitations": source.limitation,
            "nature_counts": dict(Counter(record.nature for record in source.records)),
            "label_coverage": coverage(source.records),
            "quality": [asdict(item) for item in quality_checks(inventory, groups, similarity, settings.data, source.id)],
        })
        for record in sorted(source.records, key=lambda row: row.key):
            if record.revision_sha256:
                revisions.append({"source_id": source.id, "record_key": record.key,
                                  "version": record.applied_version, "sha256": record.revision_sha256})
            if not _candidate(record, groups):
                continue
            group = groups.by_record[record.key]
            for field in TARGETS:
                label = record.label(field)
                if label.human_reference and len(label.values) == 1:
                    eligible[field].append({
                        "source_id": source.id, "record_key": record.key, "group_id": group,
                        "base_sha256": record.base_sha256, "revision_sha256": record.revision_sha256,
                        "reference": label.provenance, "review_count": label.reviewers,
                        "label": label.values[0],
                        "possible_reserved_overlap": group in similarity.reserved_risk_groups,
                    })
    return {
        "schema_version": 1, "phase": 1, "seed": settings.seed,
        "scope": "Inventario y candidatos por objetivo. Las asignaciones de Desarrollo y Validación corresponden a la fase siguiente.",
        "config": settings.data.model_dump(mode="json"),
        "config_sha256": _hash(settings.source_file), "catalog_sha256": _hash(settings.path(settings.registry_file)),
        "requirements_sha256": _hash(settings.root / "requirements.txt"),
        "requirements_lock_sha256": _hash(settings.root / "requirements.lock.txt"),
        "privacy_policy_sha256": inventory.privacy_sha256, "software": software_versions(settings.software),
        "pilot_evidence_sha256": inventory.pilot_evidence_sha256,
        "taxonomy": {"tipo": list(TYPES), "severidad": list(SEVERITIES)},
        "sources": sources, "revisions": revisions,
        "groups": {
            "method": "Componentes por ID de incidente, campaña VCDB, grupo declarado, referencia de artículo y descripción exacta normalizada.",
            "by_record": groups.by_record, "reserved": sorted(groups.reserved),
            "pilot_exposure": sorted(groups.exposed), "conflicts": sorted(groups.conflicts),
            "similarity_records": similarity.compared_records, "similarity_pairs": similarity.pairs,
            "possible_reserved_overlap": sorted(similarity.reserved_risk_groups),
        },
        "quality": [asdict(item) for item in quality_checks(inventory, groups, similarity, settings.data)],
        "holdout": holdout_status(inventory, groups),
        "eligibility": {
            "criteria": "Registro real con texto protegido que cumple el contrato del reporte, referencia humana del objetivo "
                        "y grupo fuera de reserva. La similitud pendiente se indica en cada candidato afectado.",
            "candidates_by_target": eligible,
        },
    }


def development_snapshot(inventory: DataInventory, manifest: dict) -> list[dict]:
    """Project only protected, reviewed candidates outside reserved and suspect groups."""
    labels = defaultdict(dict)
    for target, entries in manifest["eligibility"]["candidates_by_target"].items():
        for entry in entries:
            if not entry["possible_reserved_overlap"]:
                labels[entry["record_key"]][target] = entry["label"]
    return [
        {"key": row.key, "group": manifest["groups"]["by_record"][row.key],
         "title": row.title, "description": row.description, "labels": labels[row.key]}
        for row in sorted(inventory.records(), key=lambda record: record.key) if row.key in labels
    ]


class ManifestStore:
    """Store independent, atomically published manifest versions."""

    def __init__(self, settings: AnalyticsSettings) -> None:
        self.directory = settings.path(Path(settings.runs_dir) / settings.data.directory / "manifiestos")
        self.history_limit = settings.data.max_history_entries
        self.max_bytes = settings.ui.max_json_bytes + settings.data.max_source_rows * 1024
        self.max_development_bytes = settings.data.max_csv_bytes

    @staticmethod
    def _publish(directory: Path, name: str, payload: bytes) -> None:
        temporary = directory / (name + ".tmp")
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(directory / name)

    def save(self, content: dict, authorize: Callable[[str], None], *, development: list[dict] | None = None) -> dict:
        run_id, date = operation_identity()
        development_bytes = None
        if development is not None:
            development_bytes = json.dumps(development, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
            if len(development_bytes) > self.max_development_bytes:
                development_bytes = None
            else:
                content = {**content, "development_snapshot_sha256": content_hash(development)}
        envelope = {"run_id": run_id, "created_at": date, "content_sha256": content_hash(content), "content": content}
        payload = (json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
        if len(payload) > self.max_bytes:
            raise DatasetError("El manifiesto supera el límite de almacenamiento configurado.")
        authorize(run_id)
        directory = self.directory / run_id
        try:
            directory.mkdir(parents=True, exist_ok=False)
            if development_bytes is not None:
                self._publish(directory, "development.json", development_bytes)
            self._publish(directory, "manifest.json", payload)
        except OSError:
            raise DatasetError("No se pudo publicar el manifiesto versionado en runs/.") from None
        return {key: envelope[key] for key in ("run_id", "created_at", "content_sha256")}

    def list(self) -> list[dict]:
        """List complete manifests without loading every artifact into memory."""
        try:
            result = []
            for path in sorted(self.directory.glob("*/manifest.json"), reverse=True):
                if path.resolve().is_relative_to(self.directory.resolve()) and VERSION_ID.fullmatch(path.parent.name):
                    result.append({"Versión": path.parent.name, "Tamaño (bytes)": path.stat().st_size})
                    if len(result) == self.history_limit:
                        break
            return result
        except OSError:
            raise DatasetError("No se pudo leer la lista de manifiestos.") from None

    def read(self, run_id: str) -> bytes:
        if not VERSION_ID.fullmatch(run_id):
            raise DatasetError("Selecciona una versión de manifiesto válida.")
        path = self.directory / run_id / "manifest.json"
        try:
            if not path.resolve().is_relative_to(self.directory.resolve()) or path.stat().st_size > self.max_bytes:
                raise ValueError
            data = path.read_bytes()
            envelope = json.loads(data)
            if envelope["run_id"] != run_id or content_hash(envelope["content"]) != envelope["content_sha256"]:
                raise ValueError
            return data
        except (OSError, ValueError, KeyError, TypeError):
            raise DatasetError("El manifiesto seleccionado no está disponible o su huella no coincide.") from None

    def read_development(self, run_id: str, expected_sha256: str) -> list[dict]:
        """Read the bound development/validation projection. There is no test reader."""
        if not VERSION_ID.fullmatch(run_id):
            raise DatasetError("Selecciona una versión de manifiesto válida.")
        path = self.directory / run_id / "development.json"
        try:
            if not path.resolve().is_relative_to(self.directory.resolve()) or path.stat().st_size > self.max_development_bytes:
                raise ValueError
            rows = json.loads(path.read_bytes())
            if not isinstance(rows, list) or content_hash(rows) != expected_sha256:
                raise ValueError
            return rows
        except (OSError, ValueError, TypeError):
            raise DatasetError("La copia protegida de Desarrollo y Validación no conserva la huella del manifiesto.") from None
