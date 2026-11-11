"""Read the registered SOC sources and project their actual schemas."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import csv
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import file_digest
import json
import logging
from math import isfinite
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile

from pydantic import SecretStr, ValidationError

from backend.config import Settings
from scripts.vcdb import ARCHIVE_HASH, DATASET, REVISION, ReviewedCase, ReviewedSet, canonical_text, index_archive, references, validate_sample
from scripts.vcdb_review import Preparation, exposed, make_packet, verify_queue
from src.data.catalog import DatasetCatalog, DatasetSpec
from src.data.models import Annotation, DataInventory, DataRecord, DataSource, HoldoutState, SEVERITIES, TARGETS, TYPES, content_hash
from src.utils.errors import DatasetError, ServiceError
from src.utils.privacy import ALIAS, PrivacyError, RedactionSession, load_policy

LOGGER = logging.getLogger("soc_analytics.data.sources")
SOURCE_ERRORS = (OSError, UnicodeError, ValueError, TypeError, KeyError, csv.Error, BadZipFile, DatasetError)


def text_value(value: object) -> str | None:
    """Preserve meaningful source strings and actual numeric identifiers."""
    if isinstance(value, str):
        return value.strip() or None
    if type(value) is int:
        return str(value)
    return None


def values(value: object, separator: str | None = None) -> tuple[str, ...]:
    """Return distinct nonmissing categories; repeated tags count once per row."""
    items = value if isinstance(value, (list, tuple)) else value.split(separator) if isinstance(value, str) and separator else [value]
    return tuple(sorted({label for item in items if (label := text_value(item))
                         and label.casefold() not in {"unknown", "not available", "n/a", "na", "nan", "null"}}))


def stamp(path: Path) -> tuple[int, int]:
    info = path.stat()
    return info.st_mtime_ns, info.st_size


@contextmanager
def source_file(path: Path) -> Iterator[str]:
    """Fingerprint a source and reject a snapshot changed while reading."""
    before = stamp(path)
    with path.open("rb") as handle:
        digest = file_digest(handle, "sha256").hexdigest()
    yield digest
    if stamp(path) != before:
        raise DatasetError("La fuente cambió durante la lectura. Actualiza el inventario.")


def _reference_path(value: object) -> tuple[str, str] | None:
    """Keep exact article paths, excluding credentials, host-only links and query URLs."""
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
        path = url.path.rstrip("/")
        if url.scheme in ("http", "https") and url.hostname and path and not (url.username or url.password or url.query):
            return url.hostname.removeprefix("www."), path.casefold()
    except ValueError:
        pass
    return None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _soc_labels(row: Mapping, provenance: str, reviewers: int = 0) -> tuple[dict[str, Annotation], list[str]]:
    labels, issues = {}, []
    for field, allowed in (("tipo", TYPES), ("severidad", SEVERITIES), ("activo_afectado", None)):
        value = row.get(field)
        if value is None or value == "":
            continue
        if not isinstance(value, str) or not value.strip() or (
            allowed is not None and value not in allowed
        ) or (field == "activo_afectado" and len(value) > 160):
            issues.append(field + "_invalido")
            continue
        labels[field] = Annotation((value.strip(),), provenance, reviewers)
    return labels, issues


def _original(spec: DatasetSpec, locator: object, row: Mapping, *, incident: object, family: str,
              article_urls: object = (), **attributes) -> DataRecord:
    incident_id = text_value(incident)
    links = ["incidente:" + content_hash([family, incident_id.casefold()])] if incident_id else []
    if isinstance(article_urls, (list, tuple)):
        links.extend("referencia:" + content_hash(key) for url in article_urls if (key := _reference_path(url)))
    issues = list(attributes.pop("issues", ()))
    if incident_id is None:
        issues.append("identificador_ausente")
    try:
        digest = content_hash(row)
    except (ValueError, UnicodeError):
        issues.append("estructura_invalida")
        digest = content_hash([spec.id, locator, "registro inválido"])
    return DataRecord(
        key=content_hash([spec.id, locator]), source_id=spec.id, incident_id=incident_id or "Sin ID original",
        base_sha256=digest, source_label=spec.name, links=tuple(sorted(set(links))),
        issues=tuple(issues), **attributes,
    )


def _protected(record: DataRecord, redactor: RedactionSession, limit: int) -> DataRecord:
    """Remove detected sensitive values before sending records to any analytical view."""
    session = redactor.new_session()
    issues = list(record.issues)

    def protect(value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) > limit:
            issues.append("texto_fuera_de_limite")
            return None
        try:
            return session.protect(value)
        except PrivacyError:
            issues.append("proteccion_texto_no_disponible")
            return None

    def labels(items: dict[str, Annotation]) -> dict[str, Annotation]:
        result = {}
        for field, annotation in items.items():
            safe = annotation.values if field in ("tipo", "severidad", "clase_simulada", "severidad_simulada") else tuple(
                sorted({value for text in annotation.values if (value := protect(text))})
            )
            if any(ALIAS.search(value) for value in safe):
                issues.append("etiqueta_protegida")
                safe = tuple(value for value in safe if not ALIAS.search(value))
            if safe:
                result[field] = replace(annotation, values=safe)
        return result

    title, description = protect(record.title), protect(record.description)
    group = protect(record.group)
    links = record.links
    if record.group:
        links += ("grupo:" + content_hash(record.group.casefold()),)
    return replace(
        record, title=title, description=description, group=group, links=links,
        text_sha256=canonical_text(record.description) if record.description else None,
        incident_id=protect(record.incident_id) or "ID protegido", origin=protect(record.origin) or "Origen protegido",
        reviewer=protect(record.reviewer), notes=protect(record.notes),
        labels=labels(record.labels), predictions=labels(record.predictions),
        categories={key: value for key, text in record.categories.items() if (value := protect(text)) and not ALIAS.search(value)},
        issues=tuple(sorted(set(issues))),
    )


def _source(spec: DatasetSpec, **changes) -> DataSource:
    data = {"id": spec.id, "name": spec.name, "format": spec.kind, "location": spec.path or "FastAPI · PostgreSQL",
            "provenance": spec.provenance, "limitation": spec.limitation, "revision": spec.revision,
            "status": "disponible"}
    data.update(changes)
    return DataSource(**data)


def _locator(identifier: object, seen: Counter, position: int) -> tuple[str, str | int, int]:
    identifier = text_value(identifier)
    if identifier is None:
        return "fila", position, 0
    seen[identifier] += 1
    return "id", identifier, seen[identifier]


class SourceReader:
    """Produce one private, reproducible inventory of the existing sources."""

    def __init__(self, catalog: DatasetCatalog) -> None:
        self.catalog = catalog
        self.settings = catalog.settings

    def _history_paths(self) -> tuple[Path, ...]:
        if "vcdb_index" not in self.catalog.sources:
            return ()
        directory = self.settings.path(self.settings.data.sealed_holdout_file).parent
        exclusions = self.settings.path(self.settings.data.prior_pilot_exclusions_file)
        return (exclusions, *(self.settings.path(path) for path in sorted(directory.glob("*/results.json"))))

    def fingerprint(self) -> tuple[tuple[str, int, int], ...]:
        path = self.settings.path(self.settings.data.sealed_holdout_file)
        return self.catalog.fingerprint() + (
            ("__holdout__", *(stamp(path) if path.is_file() else (0, 0))),
            ("__analysis__", *stamp(self.settings.source_file)),
        ) + tuple((item.relative_to(self.settings.root).as_posix(), *(stamp(item) if item.is_file() else (0, 0)))
                  for item in self._history_paths())

    def _document(self, spec: DatasetSpec) -> tuple[dict, list, str]:
        path = self.settings.path(spec.path)
        with source_file(path) as digest:
            document = self.catalog.read_manifest(path)
        rows = document.get("candidates" if spec.kind == "json_index" else "cases")
        if not isinstance(rows, list) or len(rows) > self.settings.data.max_source_rows:
            raise DatasetError("El manifiesto no tiene una colección válida dentro del límite de filas.")
        if spec.id == "vcdb_holdout_queue":
            verify_queue(document)
            if any(not isinstance(row["source_id"], str) or not row["source_id"] for row in rows):
                raise DatasetError("La cola contiene un identificador inválido.")
        if spec.id == "vcdb_holdout_preparation":
            ids = [Preparation.model_validate(row).source_id for row in rows]
            if len(set(ids)) != len(ids) or any(not identifier for identifier in ids):
                raise DatasetError("La preparación debe registrar un identificador único por fila.")
        return document, rows, digest

    def _archive(self, spec: DatasetSpec, reserved: set[str], exposed_ids: set[str], exposed_urls: set[tuple[str, str]],
                 eligible: dict, protect) -> tuple[DataSource, dict[str, DataRecord]]:
        path = self.settings.path(spec.path)
        records, members, columns, schema_versions = [], {}, set(), Counter()
        with source_file(path) as digest, ZipFile(path) as archive:
            if digest != ARCHIVE_HASH:
                raise DatasetError("La huella VCDB difiere de la revisión original fijada.")
            entries = [item for item in archive.infolist()
                       if item.filename.endswith(".json") and "/data/json/validated/" in item.filename]
            if not entries or len(entries) > self.settings.data.max_source_rows:
                raise DatasetError("La cantidad de registros VCDB está fuera del límite configurado.")
            for index, member in enumerate(entries):
                member_id = PurePosixPath(member.filename).stem.casefold()
                issues = []
                try:
                    if member.file_size > self.settings.ui.max_zip_member_bytes:
                        raise ValueError
                    raw = json.loads(archive.read(member))
                    if not isinstance(raw, dict):
                        raise ValueError
                except (ValueError, UnicodeError):
                    raw, issues = {}, ["estructura_invalida"]
                columns.update(raw)
                schema_versions.update([text_value(raw.get("schema_version")) or "sin versión"])
                campaign = text_value(raw.get("campaign_id"))
                action = raw.get("action")
                asset = raw.get("asset")
                native_assets = asset.get("assets") if isinstance(asset, dict) else None
                native_assets = values([item.get("variety") for item in native_assets if isinstance(item, dict)]) if isinstance(native_assets, list) else ()
                labels = {}
                if member_id not in reserved:
                    if isinstance(action, dict) and action:
                        labels["tipo_fuente"] = Annotation(values(list(action)), "fuente_externa")
                    if native_assets:
                        labels["activo_fuente"] = Annotation(native_assets, "fuente_externa")
                    if member_id in eligible:
                        labels["tipo"] = Annotation(values(eligible[member_id]["suggested_types"]), "provisional")
                urls = references(raw) if isinstance(raw.get("reference"), str) else []
                seen_in_pilot = member_id in exposed_ids or any(_reference_path(url) in exposed_urls for url in urls)
                partition = "reservado" if member_id in reserved else "piloto" if seen_in_pilot else "sin_asignar"
                record = _original(spec, (member.filename, index), raw, incident=raw.get("incident_id"), family="vcdb",
                    article_urls=urls, nature="real", partition=partition, origin="registro VERIS",
                    description=text_value(raw.get("summary")), group=campaign, labels=labels, issues=issues,
                    pilot_exposure=seen_in_pilot,
                    categories={"security_incident": text_value(raw.get("security_incident")) or "Sin estado"})
                links = (*record.links, "vcdb:" + content_hash(member_id))
                if campaign:
                    links += ("campana_vcdb:" + content_hash(campaign.casefold()),)
                record = protect(replace(record, links=links))
                records.append(record)
                members[member_id] = record
        return _source(spec, sha256=digest, revision=REVISION, columns=tuple(sorted(columns)), records=tuple(records),
                       notes=("Versiones VERIS observadas: " + ", ".join(f"{k} ({v})" for k, v in sorted(schema_versions.items())),)), members

    def _vcdb_rows(self, spec: DatasetSpec, document: dict, raw_rows: list, digest: str, members: dict[str, DataRecord],
                   eligible: dict, reserved: set[str], exposed: set[str], protect) -> DataSource:
        seen, records, columns = Counter(), [], set()
        for position, raw in enumerate(raw_rows):
            row = raw if isinstance(raw, dict) else {}
            columns.update(row)
            member_id = (text_value(row.get("source_id")) or "").casefold()
            parent = members.get(member_id)
            issues = [] if isinstance(raw, dict) else ["estructura_invalida"]
            if member_id and parent is None:
                issues.append("vcdb_original_no_encontrado")
            labels, reviewer = {}, None
            partition = "reservado" if member_id in reserved else "piloto" if member_id in exposed else "sin_asignar"
            if spec.id == "vcdb_pilot":
                partition = "piloto"
                valid_reviews = 0
                try:
                    case = ReviewedCase.model_validate(row)
                    entry = eligible.get(member_id)
                    if document.get("revision") != REVISION or document.get("stage") != "pilot" or not entry or case.source_url not in entry["source_urls"]:
                        raise ValueError
                    valid_reviews = len(case.reviews)
                    reviewer = ", ".join(review.reviewer for review in case.reviews)
                except (ValueError, ValidationError):
                    issues.append("referencia_piloto_invalida")
                labels, invalid = _soc_labels(row, "propuesta")
                issues.extend(invalid)
                if valid_reviews and "tipo" in labels:
                    labels["tipo"] = Annotation(labels["tipo"].values, "piloto_revisado", valid_reviews)
            elif spec.kind == "json_index" and member_id not in reserved:
                suggested = values(row.get("suggested_types"))
                if any(value not in TYPES for value in suggested):
                    issues.append("tipo_invalido")
                valid = tuple(value for value in suggested if value in TYPES)
                if valid:
                    labels["tipo"] = Annotation(valid, "provisional")
            disposition = row.get("disposition")
            status = "excluido" if disposition == "exclude" else "revisado" if reviewer else "pendiente"
            if disposition not in (None, "include", "exclude"):
                issues.append("disposicion_invalida")
            record = _original(spec, _locator(member_id, seen, position), row, incident=member_id, family="vcdb",
                article_urls=row.get("source_urls", [row.get("source_url")]), nature="real", partition=partition,
                origin=text_value(row.get("source_stage")) or spec.id, title=text_value(row.get("titulo")),
                description=text_value(row.get("descripcion")), group=text_value(row.get("group")), labels=labels,
                reviewer=reviewer, notes=text_value(row.get("exclusion_reason")), review_state=status, issues=issues,
                expects_text=spec.id != "vcdb_holdout_queue",
                categories={"disposición": str(disposition)} if disposition in ("include", "exclude") else {})
            record = protect(record)
            if member_id:
                record = replace(record, links=record.links + ("vcdb:" + content_hash(member_id),))
            if parent and spec.id in ("vcdb_index", "vcdb_holdout_queue"):
                record = replace(record, description=parent.description, text_sha256=parent.text_sha256,
                                 base_sha256=content_hash([record.base_sha256, parent.base_sha256]))
            records.append(record)
        return _source(spec, sha256=digest, revision=REVISION, columns=tuple(sorted(columns)), records=tuple(records))

    def _csv(self, spec: DatasetSpec, protect) -> DataSource:
        path = self.settings.path(spec.path)
        if path.stat().st_size > self.settings.data.max_csv_bytes:
            raise DatasetError("El CSV supera el límite de lectura configurado.")
        records, seen = [], Counter()
        with source_file(path) as digest, path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            original = next(reader, [])
            columns, repeats = [], Counter()
            for name in original:
                repeats[name] += 1
                candidate = name if repeats[name] == 1 else f"{name}__{repeats[name]}"
                while candidate in columns:
                    candidate += "_"
                columns.append(candidate)
            identifier = "synthetic_id" if spec.synthetic else "incident_id"
            if identifier not in columns:
                raise DatasetError("El CSV no contiene su identificador de registro esperado.")
            for position, cells in enumerate(reader):
                if position >= self.settings.data.max_source_rows:
                    raise DatasetError("El CSV supera el límite de filas configurado.")
                issues = ["columnas_inconsistentes"] if len(cells) != len(columns) else []
                row = dict(zip(columns, cells))
                if spec.synthetic:
                    record = self._simulation(spec, row, _locator(row.get(identifier), seen, position), issues)
                else:
                    record = self._eurepoc(spec, row, _locator(row.get(identifier), seen, position), issues)
                records.append(protect(record))
        repeated = [key for key, count in repeats.items() if count > 1]
        notes = ("Encabezados repetidos preservados con sufijo: " + ", ".join(repeated),) if repeated else ()
        return _source(spec, sha256=digest, columns=tuple(columns), original_columns=tuple(original),
                       records=tuple(records), notes=notes)

    @staticmethod
    def _simulation(spec: DatasetSpec, row: dict, locator: object, issues: list[str]) -> DataRecord:
        labels = {}
        for column, field, size in (("type_truth", "clase_simulada", len(TYPES)),
                                    ("severity_index", "severidad_simulada", len(SEVERITIES))):
            value = row.get(column)
            if value in tuple(str(index) for index in range(size)):
                labels[field] = Annotation((value,), "simulacion")
            elif value:
                issues.append(field + "_invalida")
        numbers = {}
        for column in ("confidence_assumed", "manual_active_minutes_assumed", "guarded_active_minutes_assumed",
                       "response_deadline_minutes", "resolution_deadline_minutes"):
            value = _number(row.get(column))
            if value is not None and value >= 0 and (column != "confidence_assumed" or value <= 1):
                numbers[column] = value
            elif row.get(column):
                issues.append("numero_invalido")
        return _original(spec, locator, row, incident=row.get("synthetic_id"), family="simulacion", nature="sintetica",
            partition="simulada", origin="simulación académica", expects_text=False, labels=labels,
            numbers=numbers, issues=issues)

    @staticmethod
    def _eurepoc(spec: DatasetSpec, row: dict, locator: object, issues: list[str]) -> DataRecord:
        tags = values(row.get("incident_type"), ";")
        numbers = {}
        for column in ("number_attributions", "number_political_responses", "unweighted_intensity", "weighted_intensity"):
            value = _number(row.get(column))
            if value is not None:
                numbers[column] = value
            elif text_value(row.get(column)) and values(row.get(column)):
                issues.append("numero_invalido")
        return _original(spec, locator, row, incident=row.get("incident_id"), family="eurepoc", nature="real",
            partition="sin_asignar", origin="registro EuRepoC", title=text_value(row.get("name")),
            description=text_value(row.get("description")), article_urls=references({"reference": text_value(row.get("source_url"))}),
            labels={"tipo_fuente": Annotation(tags, "fuente_externa")} if tags else {}, numbers=numbers,
            categories={key: value for key in ("source_disclosure", "receiver_category") if (value := text_value(row.get(key)))},
            issues=issues)

    def _operational(self, spec: DatasetSpec, token: SecretStr, protect) -> DataSource:
        reports = self.catalog.api.reports(token)
        if len(reports) > self.settings.data.max_source_rows:
            raise DatasetError("La respuesta operativa supera el límite de registros.")
        seen, records, revisions = Counter(), [], {}
        for position, row in enumerate(reports):
            report_id = text_value(row.get("id"))
            origin = text_value(row.get("origen")) or "sin origen"
            title = text_value(row.get("titulo"))
            is_demo = origin == "demo" or bool(title and title.startswith("[DEMO]"))
            predictions, issues = _soc_labels(row, "demo" if is_demo else "prediccion")
            review = None
            if report_id:
                try:
                    review = self.catalog.api.report_review(report_id, token)
                    revisions[report_id] = review
                except ServiceError as error:
                    if error.status_code in (401, 403):
                        raise
                    issues.append("revision_operativa_no_consultada")
                    revisions[report_id] = {"estado": "no consultada"}
            labels, reviewer, reviewed_at = dict(predictions), None, None
            if review:
                reviewed_at = text_value(review.get("reviewed_at"))
                reviewer = text_value(review.get("reviewed_by"))
                try:
                    if review.get("report_id") != report_id or not reviewer or not reviewed_at:
                        raise ValueError
                    timestamp = datetime.fromisoformat(reviewed_at)
                    if timestamp.tzinfo is None:
                        raise ValueError
                    reviewed_at = timestamp.astimezone(timezone.utc).isoformat()
                    reviewed, invalid = _soc_labels(review, "demo" if is_demo else "revision_operativa", 0 if is_demo else 1)
                    if invalid or not all(field in reviewed for field in ("tipo", "severidad")):
                        raise ValueError
                    labels = reviewed
                except ValueError:
                    issues.append("revision_operativa_invalida")
                    reviewer, reviewed_at = None, None
            confidence = _number(row.get("confianza"))
            numbers = {"confianza": confidence} if confidence is not None and 0 <= confidence <= 1 else {}
            if row.get("confianza") is not None and not numbers:
                issues.append("confianza_invalida")
            if origin not in ("demo", "langflow", "fallback"):
                issues.append("origen_invalido")
            # Routing timestamps are fingerprinted for the source, but do not invalidate a text edit.
            context = {key: row.get(key) for key in ("id", "titulo", "descripcion", *TARGETS, "origen")}
            context["revision"] = revisions.get(report_id)
            record = _original(spec, _locator(report_id, seen, position), context, incident=report_id,
                family="operacional", nature="demo" if is_demo else "real", partition="demo" if is_demo else "sin_asignar",
                origin=origin, title=title, description=text_value(row.get("descripcion")), labels=labels,
                predictions=predictions, numbers=numbers, issues=issues, reviewer=reviewer, reviewed_at=reviewed_at,
                review_state="revisado" if reviewer else "pendiente")
            records.append(protect(record))
        return _source(spec, sha256=content_hash({"reports": reports, "reviews": revisions}),
                       hash_scope="respuesta de hasta 100 reportes y sus revisiones consultadas por FastAPI",
                       columns=tuple(sorted({key for row in reports for key in row})), records=tuple(records))

    def read_operational(self, token: SecretStr) -> DataSource:
        """Recheck the bounded API snapshot before persisting an edit or manifest."""
        redactor = RedactionSession(known_secrets=Settings.from_env().privacy_secrets())
        return self._operational(self.catalog.source("operational_reports"), token,
                                 lambda record: _protected(record, redactor, self.settings.data.max_text_characters))

    def _holdout(self, queue_document: dict, queue: set[str], preparation_document: dict, preparation: list,
                 eligible: dict, history: tuple[set[str], set[tuple[str, str]]] | None) -> HoldoutState:
        decisions = {row.get("source_id") for row in preparation if isinstance(row, dict)
                     and isinstance(row.get("source_id"), str) and row.get("disposition") in ("include", "exclude")}
        pending = len(queue - decisions)
        path = self.settings.path(self.settings.data.sealed_holdout_file)
        if not path.is_file():
            return HoldoutState(len(queue), pending, "ausente")
        digest = None
        try:
            from scripts.soc_dataset import check_prior_pilots
            with source_file(path) as digest:
                sample = ReviewedSet.model_validate(self.catalog.read_manifest(path))
                validate_sample(sample, eligible)
                if sample.stage != "holdout" or history is None:
                    raise ValueError
                prepared = make_packet(queue_document, preparation_document, eligible, history=history)["cases"]
                if prepared.keys() != {case.source_id for case in sample.cases} or any(
                    any(getattr(case, field) != value for field, value in prepared[case.source_id].items())
                    for case in sample.cases
                ):
                    raise ValueError
                check_prior_pilots(sample, path.parent)
            return HoldoutState(len(queue), pending, "validado_tipo", digest, len(sample.cases), True,
                                dict(Counter(case.tipo for case in sample.cases)))
        except SOURCE_ERRORS:
            return HoldoutState(len(queue), pending, "inválido o pendiente de revisión", digest)

    def read(self, token: SecretStr) -> DataInventory:
        """Read all sources after authorization by the workspace and retain safe projections."""
        before = self.fingerprint()
        try:
            policy = load_policy()
        except PrivacyError:
            raise DatasetError("La política de privacidad no está disponible para abrir los datos.") from None
        redactor = RedactionSession(policy=policy, known_secrets=Settings.from_env().privacy_secrets())

        def protect(record: DataRecord) -> DataRecord:
            return _protected(record, redactor, self.settings.data.max_text_characters)

        documents, sources = {}, {}
        for spec in self.catalog.sources.values():
            if spec.kind in ("json_index", "json_cases"):
                try:
                    documents[spec.id] = self._document(spec)
                except SOURCE_ERRORS as error:
                    sources[spec.id] = self._unavailable(spec, error)
        queue_document, queue_rows, _ = documents.get("vcdb_holdout_queue", ({}, [], ""))
        prep_document, preparation, _ = documents.get("vcdb_holdout_preparation", ({}, [], ""))
        queue = {value for row in queue_rows if isinstance(row, dict) and (value := text_value(row.get("source_id")))}
        prep_ids = {row["source_id"] for row in preparation}
        if queue_document and prep_document and prep_ids != queue:
            error = DatasetError("La preparación debe corresponder a todos los identificadores de la cola.")
            sources["vcdb_holdout_preparation"] = self._unavailable(self.catalog.source("vcdb_holdout_preparation"), error)
            prep_document, preparation = {}, []
        reserved = queue | prep_ids
        pilot = documents.get("vcdb_pilot", ({}, [], ""))[1]
        exposed_ids = {value for row in pilot if isinstance(row, dict) and (value := text_value(row.get("source_id")))}
        eligible, history_hashes, historical = {}, {}, None
        exposed_urls = set()
        if "vcdb_index" in documents and "vcdb_original" in self.catalog.sources:
            try:
                original = self.catalog.source("vcdb_original")
                eligible, _ = index_archive(self.settings.path(original.path))
                doc, rows, _ = documents["vcdb_index"]
                indexed = {row["source_id"]: row for row in rows}
                metadata = doc.get("summary")
                if len(indexed) != len(rows) or indexed != eligible or not isinstance(metadata, dict) or metadata.get("dataset") != DATASET:
                    raise DatasetError("El índice guardado difiere del índice reproducido desde el original VCDB.")
                exposed_ids.update(key for key, item in eligible.items() if item["suggested_partition"] == "pilot")
            except SOURCE_ERRORS as error:
                sources["vcdb_index"] = self._unavailable(self.catalog.source("vcdb_index"), error)
                eligible = {}
        if eligible:
            try:
                paths = self._history_paths()
                historical = exposed(eligible, pilot_file=self.settings.path(self.catalog.source("vcdb_pilot").path),
                                     exclusions_file=paths[0],
                                     output_directory=self.settings.path(self.settings.data.sealed_holdout_file).parent)
                for path in paths:
                    with source_file(path) as digest:
                        history_hashes[path.relative_to(self.settings.root).as_posix()] = digest
                exposed_ids.update(historical[0])
                exposed_urls.update(historical[1])
            except SOURCE_ERRORS as error:
                LOGGER.warning("Evidencia histórica VCDB no disponible (%s)", type(error).__name__)
                historical, history_hashes = None, {}
        members = {}
        for spec in self.catalog.sources.values():
            if spec.kind == "vcdb_archive":
                try:
                    sources[spec.id], members = self._archive(spec, reserved, exposed_ids, exposed_urls, eligible, protect)
                except SOURCE_ERRORS as error:
                    sources[spec.id] = self._unavailable(spec, error)
        for spec in self.catalog.sources.values():
            if spec.id in sources:
                continue
            try:
                if spec.kind in ("json_cases", "json_index"):
                    doc, rows, digest = documents[spec.id]
                    sources[spec.id] = self._vcdb_rows(spec, doc, rows, digest, members, eligible, reserved, exposed_ids, protect)
                elif spec.kind == "csv":
                    sources[spec.id] = self._csv(spec, protect)
                else:
                    sources[spec.id] = self._operational(spec, token, protect)
            except ServiceError as error:
                if error.status_code in (401, 403):
                    raise
                sources[spec.id] = self._unavailable(spec, error)
            except SOURCE_ERRORS as error:
                sources[spec.id] = self._unavailable(spec, error)
        holdout = self._holdout(queue_document, queue, prep_document, preparation, eligible, historical)
        if before != self.fingerprint() or policy.digest != load_policy().digest:
            raise DatasetError("Cambió una fuente o la política de privacidad. Actualiza el inventario.")
        return DataInventory(tuple(sources[key] for key in self.catalog.sources), holdout, policy.digest, before, history_hashes)

    @staticmethod
    def _unavailable(spec: DatasetSpec, error: Exception) -> DataSource:
        LOGGER.warning("Fuente no disponible en el inventario: %s (%s)", spec.id, type(error).__name__)
        status = "ausente" if isinstance(error, FileNotFoundError) else "error de lectura"
        message = str(error) if isinstance(error, (DatasetError, ServiceError)) else "Comprueba la ubicación, estructura y permisos de la fuente."
        return _source(spec, status=status, notes=(message,))
