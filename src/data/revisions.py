"""Append-only analytical revisions with optimistic concurrency and SOC audit."""
from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.config import Settings
from scripts.vcdb import canonical_text
from src.data.models import Annotation, DataInventory, DataRecord, MetadataEdit, TARGETS, content_hash
from src.inference.services import User
from src.utils.config import AnalyticsSettings
from src.utils.errors import DatasetError
from src.utils.privacy import ALIAS, PrivacyError, RedactionSession


def operation_identity() -> tuple[str, str]:
    """Produce an audit-compatible identifier and UTC time."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid4().hex[:12], now.isoformat()


class Revision(BaseModel):
    """The protected correction bound to an immutable original and author."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    source_id: str
    record_key: str
    version: int = Field(ge=1)
    run_id: str
    base_sha256: str
    privacy_sha256: str
    previous_sha256: str | None
    actor_id: str
    author: str
    created_at: str
    group_sha256: str | None
    changes: dict[str, Any]
    sha256: str

    def validate_digest(self) -> None:
        if content_hash(self.model_dump(exclude={"sha256"})) != self.sha256:
            raise DatasetError("Una revisión almacenada no conserva su huella de integridad.")


def protect_edit(edit: MetadataEdit, limit: int) -> tuple[dict, str | None, str]:
    """Validate and protect the edited fields before persistence."""
    changes = edit.model_dump(mode="json", exclude_unset=True)
    group = changes.get("grupo")
    try:
        protector = RedactionSession(known_secrets=Settings.from_env().privacy_secrets())
        for field in ("titulo", "descripcion", "activo_afectado", "fuente", "origen", "grupo", "observaciones"):
            if changes.get(field):
                changes[field] = protector.protect(changes[field]).strip() or None
        if len(changes.get("descripcion") or "") > limit:
            raise DatasetError("La descripción protegida supera el límite configurado.")
        MetadataEdit.model_validate(changes)
    except (PrivacyError, ValidationError):
        raise DatasetError("Revisa la longitud y los valores de la edición protegida.") from None
    return changes, content_hash(group.casefold()) if group else None, protector.policy.digest


def apply_revision(record: DataRecord, revision: Revision) -> DataRecord:
    """Apply only the proposed changes and keep predictions separately."""
    patch = revision.changes
    title = patch.get("titulo", record.title)
    description = patch.get("descripcion", record.description)
    text_changed = (title, description) != (record.title, record.description)
    reopened = patch.get("estado") == "pendiente"
    confirmed = set(patch.get("campos_revisados", ()))
    labels = dict(record.labels)
    for field in TARGETS:
        before = record.label(field)
        if field not in patch and not text_changed and field not in confirmed and not (reopened and before.human_reference):
            continue
        current = before.values
        updated = (patch[field],) if patch.get(field) else () if field in patch else current
        updated = tuple(value for value in updated if not ALIAS.search(value))
        if field in confirmed and (len(updated) != 1 or not description):
            raise DatasetError("La confirmación requiere una descripción y un valor visible y válido por campo seleccionado.")
        if not updated:
            labels.pop(field, None)
        elif field in confirmed and record.nature == "real":
            labels[field] = Annotation(updated, "revision_analitica", 1)
        elif record.nature == "demo":
            labels[field] = Annotation(updated, "demo")
        elif record.nature == "sintetica":
            labels[field] = Annotation(updated, "simulacion")
        else:
            labels[field] = Annotation(updated, "propuesta")
    links = record.links
    if "grupo" in patch:
        links = tuple(link for link in links if not link.startswith("grupo:"))
        if revision.group_sha256:
            links += ("grupo:" + revision.group_sha256,)
    digest = record.text_sha256
    if description != record.description:
        if digest:
            links += ("texto:" + digest,)
        digest = canonical_text(description) if description else None
    state = patch.get("estado") or ("pendiente" if text_changed else record.review_state)
    resolved = {field + "_invalido" for field in TARGETS if field in patch}
    return replace(
        record, title=title, description=description, text_sha256=digest, labels=labels, links=links,
        source_label=patch.get("fuente") or record.source_label,
        origin=patch.get("origen") or record.origin, group=patch.get("grupo", record.group),
        review_state=state, notes=patch.get("observaciones", record.notes),
        reviewer=revision.author if confirmed else None if text_changed or reopened else record.reviewer,
        reviewed_at=revision.created_at if confirmed else None if text_changed or reopened else record.reviewed_at,
        version=revision.version, applied_version=revision.version, revision_sha256=revision.sha256,
        issues=tuple(issue for issue in record.issues if issue not in resolved),
    )


class RevisionStore:
    """Isolated SQLite history under the analytical runs directory."""

    def __init__(self, settings: AnalyticsSettings) -> None:
        self.directory = settings.path(Path(settings.runs_dir) / settings.data.directory)
        self.path = self.directory / "revisiones.sqlite3"

    def _connect(self, *, write: bool) -> sqlite3.Connection:
        if write:
            self.directory.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path)
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS revisions (
                    source_id TEXT NOT NULL,
                    record_key TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    run_id TEXT NOT NULL UNIQUE,
                    body TEXT NOT NULL,
                    PRIMARY KEY (source_id, record_key, version)
                );
                CREATE TRIGGER IF NOT EXISTS revision_no_update BEFORE UPDATE ON revisions
                BEGIN SELECT RAISE(ABORT, 'La revisión es inmutable'); END;
                CREATE TRIGGER IF NOT EXISTS revision_no_delete BEFORE DELETE ON revisions
                BEGIN SELECT RAISE(ABORT, 'La revisión es inmutable'); END;
            """)
            return connection
        return sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)

    @staticmethod
    def _decode(row: tuple) -> Revision:
        try:
            revision = Revision.model_validate_json(row[0])
            MetadataEdit.model_validate(revision.changes)
            revision.validate_digest()
            return revision
        except (ValueError, ValidationError):
            raise DatasetError("El historial de revisiones contiene un registro inválido.") from None

    def revisions(self, record: DataRecord | None = None) -> tuple[Revision, ...]:
        """Read a consistent revision history and verify its chain."""
        if not self.path.is_file():
            return ()
        try:
            with closing(self._connect(write=False)) as connection:
                if record is None:
                    rows = connection.execute("SELECT body FROM revisions ORDER BY source_id,record_key,version")
                else:
                    rows = connection.execute(
                        "SELECT body FROM revisions WHERE source_id=? AND record_key=? ORDER BY version",
                        (record.source_id, record.key),
                    )
                history = tuple(self._decode(row) for row in rows)
        except (OSError, sqlite3.Error):
            raise DatasetError("No se pudo consultar el historial de revisiones.") from None
        previous = {}
        for revision in history:
            key = revision.source_id, revision.record_key
            version, digest = previous.get(key, (0, None))
            if revision.version != version + 1 or revision.previous_sha256 != digest:
                raise DatasetError("El historial contiene una secuencia de revisiones incompleta.")
            previous[key] = revision.version, revision.sha256
        return history

    def save(self, record: DataRecord, edit: MetadataEdit, actor: User, *, expected_version: int, limit: int,
             privacy_sha256: str, authorize: Callable[[str], None]) -> Revision:
        """Append after checking the revision number and obtaining a recorded authorization."""
        changes, group_digest, policy_digest = protect_edit(edit, limit)
        if policy_digest != privacy_sha256:
            raise DatasetError("Cambió la política de privacidad. Actualiza el inventario.")
        if not changes:
            raise DatasetError("Introduce al menos un cambio o confirma campos revisados.")
        run_id, created_at = operation_identity()
        try:
            with closing(self._connect(write=True)) as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT body FROM revisions WHERE source_id=? AND record_key=? ORDER BY version DESC LIMIT 1",
                    (record.source_id, record.key),
                ).fetchone()
                previous = self._decode(row) if row else None
                version = previous.version if previous else 0
                if expected_version != record.version or version != expected_version:
                    raise DatasetError("Otra edición cambió este registro. Actualiza los datos y vuelve a abrirlo.")
                body = {
                    "source_id": record.source_id, "record_key": record.key, "version": version + 1,
                    "run_id": run_id, "base_sha256": record.base_sha256, "privacy_sha256": privacy_sha256,
                    "previous_sha256": previous.sha256 if previous else None, "actor_id": actor.id,
                    "author": actor.username, "created_at": created_at, "group_sha256": group_digest, "changes": changes,
                }
                revision = Revision(**body, sha256=content_hash(body))
                apply_revision(record, revision)  # Reject an invalid confirmation before the audit and commit.
                connection.execute("INSERT INTO revisions VALUES (?, ?, ?, ?, ?)",
                    (revision.source_id, revision.record_key, revision.version, revision.run_id, revision.model_dump_json()))
                authorize(revision.run_id)
        except (OSError, sqlite3.Error):
            raise DatasetError("No se pudo guardar la revisión. Revisa los permisos de la carpeta de análisis.") from None
        return revision

    def apply(self, inventory: DataInventory) -> DataInventory:
        """Overlay compatible revisions and expose stale versions for review."""
        by_record = {}
        for revision in self.revisions():
            by_record.setdefault((revision.source_id, revision.record_key), []).append(revision)
        sources = []
        for source in inventory.sources:
            records = []
            for record in source.records:
                revisions = by_record.get((source.id, record.key), ())
                for revision in revisions:
                    if revision.base_sha256 == record.base_sha256 and revision.privacy_sha256 == inventory.privacy_sha256:
                        record = apply_revision(record, revision)
                    else:
                        record = replace(record, version=revision.version)
                if record.applied_version != record.version:
                    record = replace(record, issues=(*record.issues, "revision_desactualizada"))
                records.append(record)
            sources.append(replace(source, records=tuple(records)))
        return replace(inventory, sources=tuple(sources))
