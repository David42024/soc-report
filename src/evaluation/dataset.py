"""Open the sealed test set only against a verified final Phase 2 record."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

from backend.config import Settings
from scripts.soc_dataset import check_prior_pilots
from scripts.vcdb import ReviewedSet, canonical_text, validate_sample
from scripts.vcdb_review import exposed, source_key
from src.data.catalog import DatasetCatalog
from src.data.manifest import ManifestStore
from src.data.models import SEVERITIES, TARGETS, TYPES, content_hash
from src.evaluation.contracts import EvaluationSet, class_order, label_value
from src.inference.services import SocApi
from src.training.dataset import read_manifest
from src.training.demo import technical_cases
from src.training.jobs import verify_seal_location
from src.training.partition import Case, Partition
from src.training.runs import JobSpec, RunStore
from src.utils.config import AnalyticsSettings
from src.utils.errors import AnalyticsError, DatasetError
from src.utils.privacy import PrivacyError, RedactionSession


@dataclass(frozen=True, slots=True)
class FinalSelection:
    run_id: str
    family: str
    configuration: dict
    artifact: dict
    source_result_sha256: str
    model_path: Path | None

    def identity(self, target: str) -> str:
        """Ignore run IDs and SVM's unused logistic solver for once-only identity."""
        params = dict(self.configuration)
        if self.family == "tfidf_svm":
            params.pop("solver", None)
        if self.family == "langflow":
            params.pop("prompt", None)
            params["models"] = self.artifact["configured_models"]
        return content_hash({"target": target, "family": self.family, "configuration": params})


def final_selection(store: RunStore, run_id: str, family: str) -> tuple[FinalSelection, dict, JobSpec, Partition]:
    """Use only the selected configuration and artifact published by Phase 2."""
    if store.state(run_id).get("status") != "completo":
        raise DatasetError("Selecciona una corrida de Fase 2 completa.")
    record, spec, partition = store.inputs(run_id)
    result = store.verified(run_id, "result.json")
    try:
        winner = result["families"][family]["validation_selection"]["winner"]
        artifact = result["families"][family]["artifact"]
        if (result["phase"] != 2 or result["test_evaluations"] != 0 or
                result["request"] != record["request"] or result["partition_sha256"] != record["partition_sha256"] or
                content_hash(result["partition"]) != record["partition_sha256"] or
                content_hash(winner["configuration"]) != winner["sha256"] or
                len(result["families"][family]["folds"]) != 5 or
                any(row["outer_evaluations"] != 1 or len(row["inner"]) != 3 for row in result["families"][family]["folds"])):
            raise ValueError
        path = None
        if family == "langflow" and spec.cloud:
            if artifact["configuration"] != winner["configuration"]:
                raise ValueError
        elif family in spec.models:
            if artifact["fit_partition"] != "Desarrollo" or artifact["file"] != family + ".joblib":
                raise ValueError
            directory = store.path(run_id)
            path = (directory / artifact["file"]).resolve()
            if path.parent != directory or not path.is_file():
                raise ValueError
        else:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise DatasetError("La configuración final o sus huellas de Fase 2 no son verificables.") from None
    return FinalSelection(run_id, family, winner["configuration"], artifact, result["content_sha256"], path), record, spec, partition


def _sealed_real(settings: AnalyticsSettings, partition: Partition, spec: JobSpec) -> tuple[tuple[Case, ...], str]:
    if spec.target != "tipo":
        raise DatasetError("La reserva actual solo tiene un contrato de revisión independiente para tipo. Faltan referencias verificables del objetivo.")
    envelope = read_manifest(ManifestStore(settings), spec.manifest_version)
    content = envelope["content"]
    held = content.get("holdout", {})
    groups = content.get("groups", {})
    accessible = (*partition.development, *partition.validation)
    if (envelope["content_sha256"] != partition.source_sha256 or held.get("artifact_sha256") != partition.test.sha256 or
            not held.get("test_ready_by_target", {}).get(spec.target) or not held.get("type_review_verified") or
            held.get("preparation_pending") != 0 or held.get("reviewed_cases") != sum(partition.test.counts.values()) or
            content.get("taxonomy") != {"tipo": list(TYPES), "severidad": list(SEVERITIES)} or groups.get("conflicts") or
            any(row.group in groups.get("possible_reserved_overlap", ()) for row in accessible) or
            any(groups.get("by_record", {}).get(row.key) != row.group for row in accessible) or
            tuple(groups.get("reserved", ())) != partition.test.groups):
        raise DatasetError("El manifiesto de datos, el sello o la taxonomía difieren del plan aprobado.")
    verify_seal_location(settings, envelope)
    try:
        path = settings.path(settings.data.sealed_holdout_file)
        with path.open("rb") as handle:
            payload = handle.read(settings.ui.max_json_bytes + 1)
        if len(payload) > settings.ui.max_json_bytes or sha256(payload).hexdigest() != partition.test.sha256:
            raise ValueError
        sample = ReviewedSet.model_validate_json(payload)
        if sample.stage != "holdout":
            raise ValueError
        catalog = DatasetCatalog(settings, SocApi(settings.api))
        index_path = settings.path(catalog.source("vcdb_index").path)
        with index_path.open("rb") as handle:
            index_bytes = handle.read(settings.ui.max_json_bytes + 1)
        index_source = next(row for row in content["sources"] if row["id"] == "vcdb_index")
        if len(index_bytes) > settings.ui.max_json_bytes or sha256(index_bytes).hexdigest() != index_source["sha256"]:
            raise ValueError
        candidates = json.loads(index_bytes)["candidates"]
        entries = {row["source_id"]: row for row in candidates}
        if len(entries) != len(candidates):
            raise ValueError
        validate_sample(sample, entries)
        check_prior_pilots(sample, path.parent)
        previous_ids, previous_sources = exposed(entries, pilot_file=settings.path(catalog.source("vcdb_pilot").path),
            exclusions_file=settings.path(settings.data.prior_pilot_exclusions_file), output_directory=path.parent)
        if any(row.source_id in previous_ids or source_key(row.source_url) in previous_sources for row in sample.cases):
            raise ValueError
        redactor = RedactionSession(known_secrets=Settings.from_env().privacy_secrets())
        if redactor.policy.digest != content.get("privacy_policy_sha256"):
            raise DatasetError("La política de privacidad cambió desde el manifiesto. Verifica de nuevo el sello de evaluación.")
        cases = []
        identity = []
        sources = defaultdict(set)
        for row in sample.cases:
            key = content_hash(["vcdb_holdout_preparation", ("id", row.source_id.casefold(), 1)])
            group = groups["by_record"][key]
            session = redactor.new_session()
            cases.append(Case(key=key, group=group, label=row.tipo,
                              title=session.protect(row.titulo), description=session.protect(row.descripcion)))
            identity.append((key, row.tipo, canonical_text(row.titulo), canonical_text(row.descripcion)))
            sources[source_key(row.source_url)].add(group)
        if any(len(group_ids) > 1 for group_ids in sources.values()):
            raise ValueError
        return tuple(sorted(cases, key=lambda row: row.key)), content_hash(sorted(identity))
    except (OSError, AttributeError, KeyError, StopIteration, TypeError, ValueError, PrivacyError):
        raise DatasetError("El archivo reservado, sus referencias independientes o los grupos no pudieron verificarse.") from None


def load_test(settings: AnalyticsSettings, record: dict, spec: JobSpec, partition: Partition) -> EvaluationSet:
    """Verify label support and exact leakage against Development and Validation."""
    if spec.source == "real":
        if partition.test.kind != "reserva_revisada":
            raise DatasetError("La evaluación real requiere el sello de la reserva revisada.")
        rows, dataset_sha = _sealed_real(settings, partition, spec)
    else:
        originals = technical_cases(record["policy"]["demo_groups_per_class"])
        rows = tuple(sorted((row for row in originals if row.group in partition.test.groups), key=lambda row: row.key))
        dataset_sha = content_hash([row.model_dump() for row in rows])
        if (partition.test.kind != "prueba_tecnica_sintetica" or dataset_sha != partition.test.sha256 or
                content_hash([row.model_dump() for row in originals]) != partition.source_sha256):
            raise DatasetError("La reconstrucción técnica no coincide con el sello de Fase 2.")
    opened = (*partition.development, *partition.validation)
    keys, groups = {row.key for row in rows}, {row.group for row in rows}
    texts = {canonical_text(row.description) for row in rows}
    dev_text = {canonical_text(row.description) for row in partition.development}
    val_text = {canonical_text(row.description) for row in partition.validation}
    if len(keys) != len(rows) or len(texts) != len(rows) or keys & {row.key for row in opened} or (
        groups & {row.group for row in opened} or texts & (dev_text | val_text) or dev_text & val_text
        or len({row.key for row in opened}) != len(opened) or not groups <= set(partition.test.groups)
    ):
        raise DatasetError("Se detectaron duplicados o solapamiento con Desarrollo o Validación.")
    if dict(Counter(row.label for row in rows)) != partition.test.counts:
        raise DatasetError("El soporte por clase no coincide con el sello.")
    normalized = [label_value(spec.target, value) for value in partition.labels]
    classes = class_order(spec.target, set(normalized))
    if len(classes) < 2 or len(classes) != len(partition.labels):
        raise DatasetError("La normalización de etiquetas rompe la correspondencia con las clases finales.")
    cases = tuple(row.model_copy(update={"label": label_value(spec.target, row.label)}) for row in rows)
    support = defaultdict(set)
    for row in cases:
        support[row.label].add(row.group)
    if set(support) != set(classes) or (spec.source == "real" and any(
        len(support[label]) < settings.evaluation.min_real_groups_per_class for label in classes
    )):
        raise DatasetError("La reserva carece de grupos independientes suficientes por clase.")
    return EvaluationSet(cases, spec.target, spec.source, partition.test.sha256, dataset_sha,
                         partition.manifest_version, classes)


def readiness(settings: AnalyticsSettings, training: list[dict]) -> dict:
    """Report current real blockers using versioned metadata without opening Test."""
    store = ManifestStore(settings)
    versions = store.list()
    content = read_manifest(store, versions[0]["Versión"])["content"] if versions else {}
    held = content.get("holdout", {})
    return {"seal_present": settings.path(settings.data.sealed_holdout_file).is_file(),
            "manifest_version": versions[0]["Versión"] if versions else None,
            "pending": held.get("preparation_pending"),
            "ready_by_target": {target: bool(held.get("test_ready_by_target", {}).get(target)) for target in TARGETS},
            "candidates": {target: len(content.get("eligibility", {}).get("candidates_by_target", {}).get(target, []))
                           for target in TARGETS},
            "final_real_runs": sum(row["source"] == "real" and row["status"] == "completo" for row in training)}
