"""Bounded, read-only access to the original sources declared in configuration."""
from __future__ import annotations

import csv
from hashlib import file_digest, sha256
from itertools import islice
import json
import logging
from pathlib import Path
from typing import Any, Literal
from zipfile import BadZipFile, ZipFile

from pydantic import Field, SecretStr, ValidationError, model_validator

from scripts.vcdb import ARCHIVE_HASH
from src.inference.services import SocApi
from src.utils.config import AnalyticsSettings, Model, read_yaml
from src.utils.errors import ConfigurationError, DatasetError

LOGGER = logging.getLogger("soc_analytics.data")


class DatasetSpec(Model):
    """One trusted source, with its provenance and label limitations."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    kind: Literal["vcdb_archive", "json_cases", "json_index", "csv", "api_reports"]
    path: str | None = None
    provenance: str
    labels: tuple[str, ...]
    preview_columns: tuple[str, ...]
    limitation: str
    synthetic: bool = False
    revision: str | None = None

    @model_validator(mode="after")
    def source_location(self) -> DatasetSpec:
        if (self.kind == "api_reports") != (self.path is None):
            raise ValueError("Solo las fuentes locales deben declarar una ruta.")
        return self


class Registry(Model):
    """An explicit registry prevents arbitrary file access from the browser."""

    version: Literal[1]
    datasets: tuple[DatasetSpec, ...]

    @model_validator(mode="after")
    def unique_ids(self) -> Registry:
        if len({item.id for item in self.datasets}) != len(self.datasets):
            raise ValueError("Los identificadores de las fuentes deben ser únicos.")
        return self


class DatasetCatalog:
    """Inspect metadata and previews without copying or modifying source data."""

    def __init__(self, settings: AnalyticsSettings, api: SocApi) -> None:
        self.settings = settings
        self.api = api
        try:
            registry = Registry.model_validate(read_yaml(settings.path(settings.registry_file)))
        except ValidationError:
            raise ConfigurationError("El catálogo de datasets no cumple el esquema esperado.") from None
        self.sources = {item.id: item for item in registry.datasets}
        for item in registry.datasets:
            if item.path is not None:
                settings.path(item.path)

    def source(self, source_id: str) -> DatasetSpec:
        """Resolve an ID, never a caller-supplied filesystem path."""
        try:
            return self.sources[source_id]
        except KeyError:
            raise DatasetError("Selecciona una fuente registrada en el catálogo.") from None

    def fingerprint(self) -> tuple[tuple[str, int, int], ...]:
        """Invalidate cached metadata when a registered local source changes."""
        registry = self.settings.path(self.settings.registry_file).stat()
        values = [("__registry__", registry.st_mtime_ns, registry.st_size)]
        for source in self.sources.values():
            if source.path:
                path = self.settings.path(source.path)
                try:
                    info = path.stat()
                    values.append((source.id, info.st_mtime_ns, info.st_size))
                except OSError:
                    values.append((source.id, 0, 0))
        return tuple(values)

    def read_manifest(self, path: Path) -> dict:
        """Read a bounded JSON object from a configured local file."""
        if path.stat().st_size > self.settings.ui.max_json_bytes:
            raise DatasetError("El manifiesto supera el límite de lectura JSON configurado.")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise DatasetError("El manifiesto debe contener un objeto JSON.")
        return data

    def _json_cases(self, path: Path, kind: str = "json_cases") -> list[dict]:
        cases = self.read_manifest(path).get("candidates" if kind == "json_index" else "cases")
        if not isinstance(cases, list) or any(not isinstance(row, dict) for row in cases):
            raise DatasetError("El manifiesto debe contener una lista de casos.")
        return cases

    def _archive(self, path: Path, *, preview: bool) -> tuple[int, list[dict]]:
        with ZipFile(path) as archive:
            members = [item for item in archive.infolist()
                       if item.filename.endswith(".json") and "/data/json/validated/" in item.filename]
            if not members:
                raise DatasetError("No hay registros VCDB validados en el archivo registrado.")
            rows = []
            for member in members[:self.settings.ui.preview_rows if preview else 1]:
                if member.file_size > self.settings.ui.max_zip_member_bytes:
                    raise DatasetError("Un registro ZIP supera el límite de lectura configurado.")
                row = json.loads(archive.read(member))
                if not isinstance(row, dict):
                    raise DatasetError("Un registro VCDB no cumple el formato esperado.")
                rows.append(row)
            return len(members), rows

    def inspect(self, source_id: str) -> dict:
        """Return dimensions and availability, without treating predictions as truth."""
        source = self.source(source_id)
        result = {"id": source.id, "name": source.name, "format": source.kind, "location": source.path or "FastAPI · sesión JWT",
                  "synthetic": source.synthetic, "labels": list(source.labels), "rows": None, "columns": [],
                  "status": "requiere sesión" if source.kind == "api_reports" else "ausente"}
        if source.path is None:
            return result
        path = self.settings.path(source.path)
        if not path.is_file():
            return result
        try:
            if source.kind == "csv":
                with path.open(encoding="utf-8-sig", newline="") as handle:
                    reader = csv.DictReader(handle, strict=True)
                    count = 0
                    for row in reader:
                        if None in row or any(value is None for value in row.values()):
                            raise DatasetError("El CSV contiene filas con un número de columnas inconsistente.")
                        count += 1
                    result.update(columns=reader.fieldnames or [], rows=count)
            elif source.kind in ("json_cases", "json_index"):
                rows = self._json_cases(path, source.kind)
                result.update(rows=len(rows), columns=sorted({key for row in rows for key in row}),
                              labeled={label: sum(row.get(label) is not None for row in rows) for label in source.labels})
            else:
                count, rows = self._archive(path, preview=False)
                result.update(rows=count, columns=sorted(rows[0]))
            result["status"] = "disponible"
        except (OSError, ValueError, UnicodeError, BadZipFile, DatasetError, csv.Error):
            result["status"] = "formato no válido"
            LOGGER.warning("No se pudo inspeccionar la fuente %s", source.id)
        return result

    def inspect_all(self) -> list[dict]:
        """Inspect registered metadata; callers may cache by fingerprint."""
        return [self.inspect(source_id) for source_id in self.sources]

    def _project_rows(self, rows: list[dict], source: DatasetSpec) -> list[dict[str, Any]]:
        return [{key: json.dumps(row[key], ensure_ascii=False)[:self.settings.ui.preview_characters]
                 if isinstance(row.get(key), (dict, list)) else str(row[key])[:self.settings.ui.preview_characters]
                 if row.get(key) is not None else None for key in source.preview_columns} for row in rows]

    def preview(self, source_id: str, *, token: SecretStr) -> dict:
        """Authorize every access, then read a bounded original preview and its hash."""
        user = self.api.me(token)
        if not user.can("read"):
            raise DatasetError("Tu rol no permite consultar estas fuentes.")
        source = self.source(source_id)
        if source.kind == "api_reports":
            rows = self.api.reports(token)
            digest = sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
            self.api.audit_event(token, "consultar_fuente", source_id=source_id)
            return {"source_id": source_id, "sha256": digest, "hash_scope": "respuesta del endpoint, hasta 100 reportes",
                    "rows": self._project_rows(rows[:self.settings.ui.preview_rows], source), "observed_rows": len(rows)}
        path = self.settings.path(source.path)
        try:
            before = path.stat()
            with path.open("rb") as handle:
                digest = file_digest(handle, "sha256").hexdigest()
            if source.kind == "vcdb_archive" and digest != ARCHIVE_HASH:
                raise DatasetError("La huella VCDB no coincide con la revisión original fijada por el sistema.")
            if source.kind == "csv":
                with path.open(encoding="utf-8-sig", newline="") as handle:
                    rows = list(islice(csv.DictReader(handle, strict=True), self.settings.ui.preview_rows))
                    if any(None in row or any(value is None for value in row.values()) for row in rows):
                        raise DatasetError("La vista CSV contiene columnas inconsistentes.")
            elif source.kind in ("json_cases", "json_index"):
                rows = self._json_cases(path, source.kind)[:self.settings.ui.preview_rows]
            else:
                _, rows = self._archive(path, preview=True)
            after = path.stat()
            if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                raise DatasetError("La fuente cambió durante la lectura. Repite la consulta.")
            LOGGER.info("Fuente consultada %s; huella calculada", source.id)
            self.api.audit_event(token, "consultar_fuente", source_id=source_id)
            return {"source_id": source_id, "sha256": digest, "hash_scope": "archivo original completo",
                    "rows": self._project_rows(rows, source), "observed_rows": len(rows)}
        except (OSError, UnicodeError, ValueError, BadZipFile, csv.Error):
            raise DatasetError("No se pudo leer la fuente registrada. Comprueba su disponibilidad y formato.") from None
