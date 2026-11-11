"""Check grouped quotas, sealed test, isolated preprocessing and restart behavior."""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from hashlib import file_digest
import json

from fastapi.testclient import TestClient
import httpx
from pydantic import SecretStr
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer

from backend.config import Settings
from backend.db import utc_now
from backend.main import create_app
from backend.security import hash_password
from src.data.manifest import ManifestStore
from src.data.models import content_hash
from src.training.dataset import read_manifest, readiness, real_partition
from src.training.demo import demo_partition, technical_cases
from src.inference.services import SocApi
from src.training.jobs import ExperimentManager, _execute, prepare, technical_run, verify_seal_location
from src.training.local import LocalSearch
from src.training.nested import fold_evidence
from src.training.partition import Split, build_partition, nested_folds
from src.training.runs import JobSpec, RunStore
from src.utils.errors import AnalyticsError, DatasetError
from src.utils.reproducibility import software_versions


def demo_spec(settings, *, both: bool = False) -> JobSpec:
    return JobSpec(source="sintetico", target="tipo", seed=settings.seed, trials=2,
                   models=("tfidf_logreg", "tfidf_svm") if both else ("tfidf_logreg",), local=settings.training.local)


def test_partition_uses_exact_quotas_and_disjoint_groups(settings):
    policy, seed = settings.training, settings.seed
    first, second = demo_partition(policy, seed), demo_partition(policy, seed)
    assert first.evidence() == second.evidence()
    assert first.evidence() != demo_partition(policy, seed + 1).evidence()
    assert all(row["counts"] == [28, 6, 6] for row in first.evidence()["by_label"])
    assert (len(first.development), len(first.validation), sum(first.test.counts.values())) == (112, 24, 24)
    development, validation, test = ({row.group for row in first.development},
                                     {row.group for row in first.validation}, set(first.test.groups))
    assert len(development | validation | test) == len(development) + len(validation) + len(test)
    assert not hasattr(first.test, "cases")
    folds = nested_folds(first.development, policy, seed)
    assert len(folds) == 5 and all(len(fold.inner) == 3 for fold in folds)
    assert len(fold_evidence(first.development, folds, policy)) == 5
    bad_inner = replace(folds[0], inner=(Split(folds[0].outer.validation, folds[0].inner[0].validation),
                                          *folds[0].inner[1:]))
    with pytest.raises(DatasetError, match="fuera de su partición"):
        fold_evidence(first.development, (bad_inner, *folds[1:]), policy)


def test_indivisible_groups_and_insufficient_folds_fail_without_fallback(settings):
    cases = technical_cases(10)
    with pytest.raises(DatasetError, match="impiden satisfacer"):
        build_partition(cases, settings.training, settings.seed, content_hash("fixture"))
    rare = tuple(case for case in technical_cases(2) if case.label in ("phishing", "malware"))
    with pytest.raises(DatasetError, match="5 grupos por clase"):
        nested_folds(rare, settings.training, settings.seed)


def test_blocked_manifest_requires_references_and_does_not_open_snapshot(data_workspace, monkeypatch):
    workspace, token, _, _ = data_workspace
    saved = workspace.save_manifest(workspace.open(token), token)
    store = workspace.manifests
    envelope = read_manifest(store, saved["run_id"])
    status = readiness(envelope, "tipo", workspace.settings.training)
    assert status["eligible"] == 1 and not status["ready"]
    assert any("sello" in reason for reason in status["reasons"])
    def denied(*args):
        pytest.fail("Se abrió la copia protegida pese al bloqueo.")
    monkeypatch.setattr(store, "read_development", denied)
    with pytest.raises(DatasetError, match="sello"):
        real_partition(store, envelope, "tipo", workspace.settings.training, workspace.settings.seed)


def test_real_adapter_needs_only_verified_seal_metadata(settings):
    fixture = demo_partition(settings.training, settings.seed)
    accessible = (*fixture.development, *fixture.validation)
    candidates = [{"record_key": row.key, "group_id": row.group, "label": row.label, "possible_reserved_overlap": False}
                  for row in accessible]
    content = {"phase": 1, "groups": {"reserved": list(fixture.test.groups)},
        "eligibility": {"candidates_by_target": {"tipo": candidates}},
        "holdout": {"test_ready_by_target": {"tipo": True}, "reviewed_type_counts": fixture.test.counts,
                    "artifact_sha256": fixture.test.sha256, "reserved_count": 24, "preparation_pending": 0,
                    "reviewed_cases": 24}}
    development = [{"key": row.key, "group": row.group, "title": row.title, "description": row.description,
                    "labels": {"tipo": row.label}} for row in accessible]
    store = ManifestStore(settings)
    saved = store.save(content, lambda _id: None, development=development)
    envelope = read_manifest(store, saved["run_id"])
    assert readiness(envelope, "tipo", settings.training)["ready"]
    assert not settings.path(settings.data.sealed_holdout_file).exists()
    planned = real_partition(store, envelope, "tipo", settings.training, settings.seed)
    assert planned.test.sha256 == fixture.test.sha256
    assert all(row["counts"] == [28, 6, 6] for row in planned.evidence()["by_label"])
    sidecar = store.directory / saved["run_id"] / "development.json"
    sidecar.write_text("[]", encoding="utf-8")
    with pytest.raises(DatasetError, match="huella"):
        real_partition(store, envelope, "tipo", settings.training, settings.seed)


def test_sealed_artifact_stamp_detects_replacement_without_opening(settings, monkeypatch):
    path = settings.path(settings.data.sealed_holdout_file)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"sealed test fixture")
    info = path.stat()
    manifest = {"content": {"config": {"sealed_holdout_file": settings.data.sealed_holdout_file},
                 "holdout": {"artifact_stat": {"mtime_ns": info.st_mtime_ns, "bytes": info.st_size}}}}
    orig_open = type(path).open

    def protect(self, *args, **kwargs):
        assert self != path, "La Fase 2 abrió el archivo sellado."
        return orig_open(self, *args, **kwargs)

    monkeypatch.setattr(type(path), "open", protect)
    verify_seal_location(settings, manifest)
    path.unlink()
    with pytest.raises(AnalyticsError, match="sello"):
        verify_seal_location(settings, manifest)


def test_job_settings_cannot_be_changed_under_a_checkpoint(settings):
    spec = demo_spec(settings)
    store = RunStore(settings)
    run_id = store.create(spec, prepare(spec, settings).partition, "fixture", lambda _id: None)
    path = store.path(run_id) / "run.json"
    record = json.loads(path.read_bytes())
    record["request"]["trials"] += 1
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(AnalyticsError, match="huella"):
        store.inputs(run_id)


def test_version_capture_is_stable_and_a_transient_windows_lock_is_retried(settings, monkeypatch):
    import src.training.runs as runs

    observed = []
    versions = software_versions(settings.software)
    monkeypatch.setattr(runs, "software_versions", lambda packages: observed.append(packages) or versions)
    original_write = runs.write_json
    attempts = []

    def occasionally_busy(path, data):
        attempts.append(path.name)
        if len(attempts) == 1:
            raise PermissionError("fixture sharing lock")
        original_write(path, data)

    monkeypatch.setattr(runs, "write_json", occasionally_busy)
    store = RunStore(settings)
    spec = demo_spec(settings).model_copy(update={"trials": 1})
    run_id = store.create(spec, prepare(spec, settings).partition, "fixture", lambda _id: None)
    assert attempts[:2] == ["work.json", "work.json"]
    assert _execute(store, run_id)
    assert len(observed) == 1
    assert store.verified(run_id, "result.json")["environment"]["software"] == versions


def test_every_vectorizer_fit_uses_only_allowed_documents(settings, monkeypatch):
    spec = demo_spec(settings, both=True)
    planned = prepare(spec, settings)
    cases = planned.partition.development
    expected = Counter()
    for fold in planned.folds:
        expected[frozenset(cases[i].text for i in fold.outer.train)] += 2
        for inner in fold.inner:
            expected[frozenset(cases[i].text for i in inner.train)] += 2 * spec.trials
    seen = Counter()
    transform = TfidfVectorizer.fit_transform

    def capture(self, raw_documents, y=None):
        texts = list(raw_documents)
        seen[frozenset(texts)] += 1
        return transform(self, texts, y)

    monkeypatch.setattr(TfidfVectorizer, "fit_transform", capture)
    run_id, result = technical_run(settings, spec)
    assert result and result["test_evaluations"] == result["flow_calls"] == 0
    selection_fits = sum(len(item["validation_selection"]["candidates"]) + 1 for item in result["families"].values())
    expected[frozenset(case.text for case in cases)] += selection_fits
    assert seen == expected
    assert result["partition"]["groups_disjoint"]
    directory = RunStore(settings).path(run_id)
    work = json.loads((directory / "work.json").read_bytes())
    assert set(work) == {"development", "validation", "seal"}
    assert set(work["seal"]) == {"sha256", "counts", "groups", "kind"}
    assert not set(work["seal"]["groups"]) & {row["group"] for row in work["development"] + work["validation"]}
    assert content_hash({k: v for k, v in result.items() if k != "content_sha256"}) == result["content_sha256"]
    for family in result["families"].values():
        assert family["summary"]["folds"] == 5
        assert all(fold["outer_evaluations"] == 1 and len(fold["inner"]) == 3 for fold in family["folds"])
        assert all(len(trial["inner_metrics"]) == 3 for fold in family["folds"] for trial in fold["trials"])
        with (directory / family["artifact"]["file"]).open("rb") as handle:
            assert file_digest(handle, "sha256").hexdigest() == family["artifact"]["sha256"]


def test_cancel_and_resume_preserves_completed_external_fold(settings, monkeypatch):
    spec = demo_spec(settings)
    planned = prepare(spec, settings)
    store = RunStore(settings)
    run_id = store.create(spec, planned.partition, "analista", lambda _id: None)
    measured = []
    append = store.append_event

    def pause(identifier, event):
        append(identifier, event)
        if event["event"] == "outer_medido":
            measured.append(event["fold"])
            if measured == [1]:
                (store.path(identifier) / "cancel.requested").touch()

    monkeypatch.setattr(store, "append_event", pause)
    assert _execute(store, run_id) is None
    assert store.state(run_id)["status"] == "cancelado"
    assert len(store.checkpoint(run_id)["families"]["tfidf_logreg"]["folds"]) == 1
    (store.path(run_id) / "cancel.requested").unlink()
    assert _execute(store, run_id)
    assert measured == [1, 2, 3, 4, 5]
    assert store.state(run_id)["status"] == "completo"


def test_interrupted_external_measurement_is_not_repeated(settings, monkeypatch):
    spec = demo_spec(settings)
    store = RunStore(settings)
    run_id = store.create(spec, prepare(spec, settings).partition, "analista", lambda _id: None)
    evaluate = LocalSearch.evaluate
    external_calls = []

    def interrupt(self, train, validation, params, scope, check):
        if scope.startswith("outer"):
            external_calls.append(scope)
            raise RuntimeError("fixture interruption")
        return evaluate(self, train, validation, params, scope, check)

    monkeypatch.setattr(LocalSearch, "evaluate", interrupt)
    assert _execute(store, run_id) is None
    assert _execute(store, run_id) is None
    assert external_calls == ["outer-1"]
    assert "una evaluación" in store.state(run_id)["message"]


def test_backend_experiment_audit_uses_jwt_and_real_roles(tmp_path):
    app = create_app(Settings(sqlite_path=tmp_path / "experiment-audit.sqlite3", operator_token="fixture-operator",
                              legacy_operator_enabled=True, jwt_secret="fixture-experiment-audit-key-at-least-32-bytes"))
    path = "/api/analitica/eventos"
    run_id = "20261111T120000000000Z_1234567890ab"
    with TestClient(app) as client:
        with app.state.db.session(write=True) as execute:
            hashed = hash_password("test-password")
            for role in ("analista", "gestor", "auditor"):
                execute("INSERT INTO users (id,username,password_hash,role,creado_at) VALUES (%s,%s,%s,%s,%s)",
                        (role, role, hashed, role, utc_now()))
        for role, allowed in (("analista", 204), ("gestor", 403), ("auditor", 403)):
            login = client.post("/api/auth/login", json={"username": role, "password": "test-password"}).json()
            headers = {"Authorization": "Bearer " + login["access_token"]}
            assert client.post(path, headers=headers, json={"action": "consultar_experimentos"}).status_code == (403 if role == "auditor" else 204)
            for action in ("autorizar_experimento", "cancelar_experimento", "reanudar_experimento"):
                assert client.post(path, headers=headers, json={"action": action, "run_id": run_id, "outcome": "iniciado"}).status_code == allowed
        assert client.post(path, headers={"Authorization": "Bearer fixture-operator"},
                           json={"action": "consultar_experimentos"}).status_code == 401


def test_training_job_through_existing_api_with_real_jwt(settings):
    app = create_app(Settings(sqlite_path=settings.root / "training-api.sqlite3", legacy_operator_enabled=False,
                              jwt_secret="fixture-training-api-jwt-key-at-least-32-characters"))
    with TestClient(app) as server:
        with app.state.db.session(write=True) as execute:
            execute("INSERT INTO users (id,username,password_hash,role,creado_at) VALUES (%s,%s,%s,%s,%s)",
                    ("analyst-id", "analyst", hash_password("fixture-password"), "analista", utc_now()))
        def forward(request):
            response = server.request(request.method, str(request.url), headers=dict(request.headers), content=request.content)
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)
        api = SocApi(settings.api, transport=httpx.MockTransport(forward))
        manager = ExperimentManager(settings, api)
        session = api.login("analyst", SecretStr("fixture-password"))
        try:
            spec = demo_spec(settings, both=True).model_copy(update={"trials": 1})
            preview = manager.preview(spec, session.token)
            run_id = manager.start(spec, session.token, preview["plan_sha256"])
            result = manager._running[run_id].result(timeout=120)
            assert result and result["test_evaluations"] == result["flow_calls"] == 0
            assert manager.authorize_monitor(run_id, session.token)
            assert manager.monitor(run_id)["state"]["status"] == "completo"
            with app.state.db.session() as execute:
                events = list(execute("SELECT user_id,action FROM audit_log WHERE module='analitica/experimentos'"))
            assert {event["action"] for event in events} >= {"autorizar_experimento", "consultar_experimentos"}
            assert all(event["user_id"] == "analyst-id" for event in events)
        finally:
            api.logout(session.token)
            manager.close()
