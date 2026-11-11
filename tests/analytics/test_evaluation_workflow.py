"""Verify one-pass use of Phase 2 artifacts and the real seal's trust boundaries."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
import json
from uuid import UUID

import pytest
from sklearn.pipeline import Pipeline

from scripts.vcdb import REVISION
from src.data.catalog import DatasetCatalog
from src.data.manifest import ManifestStore
from src.data.models import SEVERITIES, TYPES, content_hash
from src.evaluation.dataset import final_selection, load_test
from src.evaluation.predictors import local_model
from src.evaluation.store import EvaluationStore
from src.evaluation.workspace import EvaluationWorkspace, technical_evaluation
from src.inference.services import SocApi
from src.training.jobs import technical_run
from src.training.partition import Case, Partition, TestSeal as Seal
from src.training.runs import JobSpec, RunStore
from src.utils.errors import AnalyticsError, DatasetError, ServiceError
from src.utils.privacy import load_policy


def test_reuses_final_artifacts_without_refitting_or_repeating_inference(settings, monkeypatch):
    spec = JobSpec(source="sintetico", target="tipo", seed=settings.seed, trials=1,
                   models=("tfidf_logreg", "tfidf_svm"), local=settings.training.local)
    phase2, trained = technical_run(settings, spec)
    assert trained["test_evaluations"] == 0
    store = RunStore(settings)
    chosen, record, _, partition = final_selection(store, phase2, "tfidf_logreg")
    assert chosen.configuration == trained["families"]["tfidf_logreg"]["validation_selection"]["winner"]["configuration"]
    original_model = chosen.model_path.read_bytes()
    dataset = load_test(settings, record, spec, partition)
    overlap = replace(partition, development=(*partition.development, dataset.cases[0]))
    with pytest.raises(DatasetError, match="solapamiento"):
        load_test(settings, record, spec, overlap)
    with pytest.raises(DatasetError, match="sello"):
        load_test(settings, record, spec, replace(partition, test=replace(partition.test, sha256="bad")))
    with pytest.raises(DatasetError, match="configuración final"):
        final_selection(store, phase2, "otro_modelo")

    def unexpected(*_args, **_kwargs):
        pytest.fail("El evaluador llamó una operación que ya había terminado.")

    monkeypatch.setattr(Pipeline, "fit", unexpected)
    reports, comparison = technical_evaluation(settings, phase2)
    assert all(report["rows"] == 24 and report["reference"] == "prueba_tecnica" for report in reports)
    assert {report["score_kind"] for report in reports} == {"probability", "margin"}
    assert all(report["uncertainty"]["reason"] for report in reports)
    assert not comparison["comparisons"][0]["correctness"]["p"]
    assert store.verified(phase2, "result.json") == trained
    monkeypatch.setattr("src.evaluation.workspace.local_predictions", unexpected)
    assert technical_evaluation(settings, phase2) == (reports, comparison)
    chosen.model_path.write_bytes(original_model + b"corrupt")
    with pytest.raises(DatasetError, match="huella"):
        local_model(chosen, dataset, settings)


def metadata(configuration: str = "final") -> dict:
    return {"dataset_sha256": "cohorte-controlada", "configuration_sha256": configuration, "source": "sintetico",
            "target": "tipo", "family": "tfidf_logreg", "phase2_run_id": "20261110T220000000000Z_000000000000"}


def test_ledger_reserves_exactly_once_under_concurrency_and_keeps_failures(settings):
    store = EvaluationStore(settings)
    authorizations = []

    def claim(_):
        try:
            return store.reserve(metadata(), authorizations.append)
        except AnalyticsError as error:
            assert "ya tienen una reserva" in str(error)
            return None

    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(claim, range(2)))
    assert len(authorizations) == 1
    identifier = authorizations[0]
    assert sorted(claim is None for claim in claims) == [False, True]
    store.failure(identifier, {"status": "fallida"})
    assert claim(None) is None and store.result(identifier)["status"] == "fallida"


def test_errors_and_export_are_audited_and_role_restricted(data_workspace):
    source, token, _, state = data_workspace
    workspace = EvaluationWorkspace(source.settings, source.api)
    store = workspace.store
    identifier, _ = store.reserve(metadata(), lambda _: None)
    example = {"key": "masked-id", "truth": "malware", "predicted": "phishing", "provider": None, "review_reason": None}
    store.publish(identifier, {"predictions": [example], "status": "completa"},
                  {"masked-id": {"title": "Título protegido", "description": "Contacto [CORREO_1]"}})
    state["role"] = "gestor"
    assert "predictions" not in workspace.result(identifier, token)
    with pytest.raises(AnalyticsError, match="rol"):
        workspace.errors(identifier, token)
    with pytest.raises(AnalyticsError, match="rol"):
        workspace.inspect_error(identifier, "masked-id", token)
    state["role"] = "analista"
    assert workspace.errors(identifier, token) == [example]
    assert workspace.inspect_error(identifier, "masked-id", token)["title"] == "Título protegido"
    assert "Contacto" not in (store.directory / identifier / "result.json").read_text(encoding="utf-8")
    assert state["audit"][-1]["action"] == "inspeccionar_evaluacion"
    state["audit_ok"] = False
    with pytest.raises(ServiceError):
        workspace.inspect_error(identifier, "masked-id", token)


@pytest.fixture
def reviewed_seal(settings):
    """Build a short contract fixture without modifying the registered originals."""
    sample_path = settings.path(settings.data.sealed_holdout_file)
    sample_path.parent.mkdir(parents=True)
    grouped, cases, indexed = {}, [], []
    for i in range(10):
        kind = "malware" if i < 5 else "phishing"
        source = str(UUID(int=i + 1))
        url = f"https://example.test/notice-{i}"
        case = {"source_id": source, "source_url": url, "group": f"grupo-{i}", "source_stage": "initial_public_report",
                "titulo": "Comunicado de un incidente", "descripcion": f"El equipo publicó la observación número {i} tras la revisión.",
                "tipo": kind, "severidad": "media", "redaction_reviewed": True,
                "reviews": [{"reviewer": "equipo uno", "tipo": kind}, {"reviewer": "equipo dos", "tipo": kind}]}
        cases.append(case)
        indexed.append({"source_id": source, "source_urls": [url], "suggested_partition": "holdout_candidate"})
        grouped[content_hash(["vcdb_holdout_preparation", ("id", source, 1)])] = content_hash(["holdout-group", i])

    def dump(path, body):
        path.parent.mkdir(exist_ok=True, parents=True)
        data = json.dumps(body, ensure_ascii=False).encode()
        path.write_bytes(data)
        return sha256(data).hexdigest()

    catalog = DatasetCatalog(settings, SocApi(settings.api))
    index = settings.path(catalog.source("vcdb_index").path)
    index_hash = dump(index, {"candidates": indexed})
    dump(settings.path(catalog.source("vcdb_pilot").path), {"cases": []})
    dump(settings.path(settings.data.prior_pilot_exclusions_file), {"source_ids": []})
    development = tuple(Case(key=content_hash(["dev", kind]), group=content_hash(["train", kind]), label=kind,
                         title="Anotación de desarrollo", description=f"La muestra de desarrollo contiene la clase {kind}.")
                        for kind in ("malware", "phishing"))

    def bind(sample=cases, grouping=grouped):
        seal = dump(sample_path, {"revision": REVISION, "stage": "holdout", "sampling": "Muestra del contrato en pruebas aisladas.",
                                 "cases": sample})
        stat = sample_path.stat()
        group_map = {**grouping, **{case.key: case.group for case in development}}
        reserved = sorted(set(grouping.values()))
        manifest = ManifestStore(settings).save({"phase": 1, "taxonomy": {"tipo": list(TYPES), "severidad": list(SEVERITIES)},
            "config": {"sealed_holdout_file": settings.data.sealed_holdout_file}, "privacy_policy_sha256": load_policy().digest,
            "sources": [{"id": "vcdb_index", "sha256": index_hash}], "groups": {"by_record": group_map, "reserved": reserved},
            "holdout": {"artifact_stat": {"mtime_ns": stat.st_mtime_ns, "bytes": stat.st_size}, "artifact_sha256": seal,
                        "reviewed_cases": 10, "type_review_verified": True, "preparation_pending": 0,
                        "test_ready_by_target": {"tipo": True}}}, lambda _: None)
        part = Partition(development, (), Seal(seal, {"malware": 5, "phishing": 5}, tuple(reserved), "reserva_revisada"),
                         "real", manifest["content_sha256"], manifest["run_id"])
        spec = JobSpec(source="real", target="tipo", seed=settings.seed, trials=1, models=("tfidf_logreg",),
                       local=settings.training.local, manifest_version=manifest["run_id"])
        return spec, part

    return sample_path, index, bind, cases, grouped


def test_real_reader_verifies_human_references_and_hashes(settings, reviewed_seal):
    path, index, bind, _, _ = reviewed_seal
    spec, partition = bind()
    data = load_test(settings, {}, spec, partition)
    assert len(data.cases) == 10 and data.source == "real" and not data.strata
    assert {row.group for row in data.cases} == set(partition.test.groups)
    with pytest.raises(DatasetError, match="referencias verificables"):
        load_test(settings, {}, spec.model_copy(update={"target": "severidad"}), partition)
    index.write_bytes(index.read_bytes() + b" ")
    with pytest.raises(DatasetError, match="no pudieron verificarse"):
        load_test(settings, {}, spec, partition)
    path.unlink()
    with pytest.raises(AnalyticsError, match="sello de Prueba"):
        load_test(settings, {}, spec, partition)


def test_real_reader_rejects_unreviewed_and_insufficient_groups(settings, reviewed_seal):
    _, _, bind, cases, grouped = reviewed_seal
    broken = [{**cases[0], "reviews": cases[0]["reviews"][:1]}, *cases[1:]]
    spec, partition = bind(broken)
    with pytest.raises(DatasetError, match="no pudieron verificarse"):
        load_test(settings, {}, spec, partition)
    first, second, *_ = grouped
    spec, partition = bind(grouping={**grouped, first: grouped[second]})
    with pytest.raises(DatasetError, match="grupos independientes suficientes"):
        load_test(settings, {}, spec, partition)
