"""Authenticated use cases for the data module."""
from __future__ import annotations

from dataclasses import dataclass
import logging

from pydantic import SecretStr, ValidationError

from src.data.catalog import DatasetCatalog
from src.data.manifest import ManifestStore, development_snapshot, manifest_content
from src.data.models import DataInventory, DataRecord, MetadataEdit
from src.data.quality import Groups, Similarity, find_similar, group_records
from src.data.revisions import Revision, RevisionStore
from src.data.sources import SourceReader
from src.inference.services import User
from src.utils.errors import DatasetError
from src.utils.privacy import load_policy

LOGGER = logging.getLogger("soc_analytics.data")


@dataclass(frozen=True, slots=True)
class DataView:
    original: DataInventory
    inventory: DataInventory
    groups: Groups
    similarity: Similarity

    def record(self, key: str) -> DataRecord:
        for source in self.inventory.sources:
            for record in source.records:
                if record.key == key:
                    return record
        raise DatasetError("Selecciona un registro del inventario actual.")


class DataWorkspace:
    """Orchestrate the local analytical store through the operational identity and audit API."""

    def __init__(self, catalog: DatasetCatalog) -> None:
        self.settings = catalog.settings
        self.api = catalog.api
        self.reader = SourceReader(catalog)
        self.revisions = RevisionStore(self.settings)
        self.manifests = ManifestStore(self.settings)

    def _authorize(self, token: SecretStr, permission: str = "read") -> User:
        user = self.api.me(token)
        if not user.can(permission):
            raise DatasetError("Tu rol no permite esta operación del módulo de datos.")
        return user

    def _view(self, original: DataInventory) -> DataView:
        inventory = self.revisions.apply(original)
        records = inventory.records()
        groups = group_records(records)
        return DataView(original, inventory, groups, find_similar(records, groups, self.settings.data))

    def open(self, token: SecretStr) -> DataView:
        self._authorize(token)
        view = self._view(self.reader.read(token))
        self.api.audit_event(token, "consultar_datos")
        LOGGER.info("Inventario analítico consultado: %d fuentes", len(view.inventory.sources))
        return view

    def _check_sources(self, original: DataInventory) -> None:
        if original.input_fingerprint != self.reader.fingerprint() or original.privacy_sha256 != load_policy().digest:
            raise DatasetError("Cambió una fuente, la configuración o la política de privacidad. Actualiza el inventario.")

    def refresh_revisions(self, original: DataInventory, token: SecretStr) -> DataView:
        self._authorize(token)
        self._check_sources(original)
        view = self._view(original)
        self.api.audit_event(token, "consultar_datos")
        return view

    def save_revision(self, view: DataView, key: str, changes: dict, expected_version: int,
                      confirmed: bool, token: SecretStr) -> Revision:
        actor = self._authorize(token, "review")
        if not confirmed:
            raise DatasetError("Confirma el registro de la revisión antes de guardar.")
        self._check_sources(view.original)
        record = view.record(key)
        if record.source_id == "operational_reports":
            current = next((item for item in self.reader.read_operational(token).records if item.key == key), None)
            if current is None or current.base_sha256 != record.base_sha256:
                raise DatasetError("El reporte operativo cambió. Actualiza el inventario antes de guardar.")
        try:
            edit = MetadataEdit.model_validate(changes)
        except ValidationError as error:
            problems = error.errors(include_input=False, include_context=False, include_url=False)
            fields = ", ".join(sorted({str(issue["loc"][0]) for issue in problems if issue["loc"]}))
            raise DatasetError(f"Revisa los valores de estos campos: {fields}." if fields else
                               "Revisa el estado, los campos confirmados y las observaciones.") from None
        revision = self.revisions.save(record, edit, actor, expected_version=expected_version,
            limit=self.settings.data.max_text_characters, privacy_sha256=view.inventory.privacy_sha256,
            authorize=lambda identifier: self.api.audit_event(token, "autorizar_revision_datos",
                source_id=record.source_id, run_id=identifier, outcome="iniciado"))
        LOGGER.info("Revisión de datos publicada %s, fuente %s", revision.run_id, record.source_id)
        return revision

    def history(self, view: DataView, key: str, token: SecretStr) -> tuple[Revision, ...]:
        self._authorize(token)
        record = view.record(key)
        history = self.revisions.revisions(record)[-self.settings.data.max_history_entries:]
        self.api.audit_event(token, "consultar_datos", source_id=record.source_id)
        return tuple(reversed(history))

    def save_manifest(self, view: DataView, token: SecretStr) -> dict:
        self._authorize(token, "write")
        self._check_sources(view.original)
        operational = next((source for source in view.original.sources if source.id == "operational_reports"), None)
        if operational and operational.sha256 and self.reader.read_operational(token).sha256 != operational.sha256:
            raise DatasetError("Cambió la vista operativa. Actualiza el inventario para guardar su versión actual.")
        current = self.revisions.apply(view.original)
        if current != view.inventory:
            raise DatasetError("Hay revisiones más recientes. Actualiza el inventario antes de guardar el manifiesto.")
        content = manifest_content(view.inventory, view.groups, view.similarity, self.settings)
        self._check_sources(view.original)
        return self.manifests.save(content, lambda identifier: self.api.audit_event(
            token, "autorizar_manifiesto_datos", run_id=identifier, outcome="iniciado"),
            development=development_snapshot(view.inventory, content))

    def list_manifests(self, token: SecretStr) -> list[dict]:
        self._authorize(token)
        records = self.manifests.list()
        self.api.audit_event(token, "consultar_datos")
        return records

    def read_manifest(self, version: str, token: SecretStr) -> tuple[str, bytes]:
        self._authorize(token)
        data = self.manifests.read(version)
        self.api.audit_event(token, "consultar_datos", run_id=version)
        return version, data
