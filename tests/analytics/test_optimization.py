"""Integrated Optuna checks with controlled synthetic text and no provider egress."""
from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import json
from threading import Barrier, Lock
from types import SimpleNamespace

import httpx
import numpy as np
import optuna
from PIL import Image
from pydantic import SecretStr, ValidationError
import pytest
from sklearn.metrics import balanced_accuracy_score, cohen_kappa_score

from src.data.models import content_hash
from src.inference.experimental import CloudParameters
from src.inference.services import SocApi
from src.optimization.contracts import Distribution, SearchOptions
from src.optimization.studies import open_study, recover_interrupted, storage, trial_rows
from src.optimization.workspace import OptimizationWorkspace, build_request, default_options
from src.reports.optimization_presentation import (
    contour_plot, distribution_plot, history_plot, importance_plot, parallel_plot, slice_plot,
    space_table, stability_plot, stability_table, trials_table, winners_table,
)
from src.reports.figures import export_png
from src.training.jobs import ExperimentManager, _execute, prepare
from src.training.local import LocalSearch
from src.training.metrics import REVIEW, objective_metrics
from src.training.runs import JobSpec
from src.utils.errors import AnalyticsError, ServiceError


def spec(settings, *, trials=10, **updates):
    raw = dict(source="sintetico", target="tipo", seed=settings.seed, trials=trials, models=("tfidf_logreg",),
               local=settings.training.local, optimization=default_options(settings))
    raw.update(updates)
    return JobSpec.model_validate(raw)


@pytest.fixture
def optimization(settings):
    state = {"role": "analista", "audit": [], "audit_ok": True}

    def respond(request):
        if request.headers.get("Authorization") != "Bearer fixture-token":
            return httpx.Response(401)
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"id": "actor-optuna", "username": "analista", "role": state["role"], "active": 1})
        if request.url.path.endswith("/analitica/eventos"):
            if not state["audit_ok"]:
                return httpx.Response(503)
            state["audit"].append(json.loads(request.content))
            return httpx.Response(204)
        return httpx.Response(404)

    manager = ExperimentManager(settings, SocApi(settings.api, transport=httpx.MockTransport(respond)))
    yield OptimizationWorkspace(manager), SecretStr("fixture-token"), state
    manager.close()


@pytest.mark.parametrize("change", [
    {"kind": "float", "low": 0, "high": 1, "log": True},
    {"kind": "float", "low": 2, "high": 1},
    {"kind": "float", "low": float("nan"), "high": 1},
    {"kind": "int", "low": 1.2, "high": 3},
    {"kind": "int", "low": 1, "high": 3, "step": 0},
    {"kind": "float", "low": 1, "high": 3, "step": .1, "log": True},
    {"kind": "categorical", "choices": [1, 1]},
    {"kind": "categorical", "choices": [1], "low": 1},
])
def test_invalid_distributions_are_rejected_before_execution(change):
    with pytest.raises(ValidationError):
        Distribution.model_validate(change)


def test_model_domains_resources_directions_and_cloud_policy(settings):
    options = default_options(settings)
    for update in ({"direction": "minimize"}, {"sampler": "grid"}, {"metric": "critical_recall"},
                   {"space": {"temperature": {"kind": "float", "low": 0, "high": 1}}},
                   {"space": {"min_df": {"kind": "float", "low": 1, "high": 2}}},
                   {"space": {"c": {"kind": "categorical", "choices": ["1.0", "2.0"]}}},
                   {"space": {"min_df": {"kind": "float", "low": 1.1, "high": 2.1}}}):
        with pytest.raises((ValidationError, AnalyticsError)):
            spec(settings, optimization={**options.model_dump(mode="json"), **update})
    with pytest.raises(AnalyticsError, match="límites"):
        prepare(spec(settings, optimization=options.model_copy(update={"parallel_trials": 3})), settings)
    with pytest.raises(AnalyticsError, match="Grid"):
        prepare(spec(settings, optimization={**options.model_dump(mode="json"), "sampler": "grid",
            "space": {"c": {"kind": "categorical", "choices": [.1, 1.]}}}), settings)
    cloud = CloudParameters(prompts=("vigente",), thresholds=(.75,), budget_usd=0, approve=False)
    base = dict(source="real", target="tipo", seed=42, trials=1, manifest_version="20261111T120000000000Z_1234567890ab", cloud=cloud)
    cloud_options = default_options(settings, cloud=True).model_dump(mode="json")
    for field in ("groq_model", "gemini_model", "temperature", "max_tokens", "fallback"):
        with pytest.raises(ValidationError):
            JobSpec(**base, optimization={**cloud_options, "space": {field: {"kind": "categorical", "choices": ["changed"]}}})
    with pytest.raises(ValidationError, match="una solicitud"):
        JobSpec(**base, optimization={**cloud_options, "parallel_trials": 2})


def test_reference_metrics_and_no_conditional_kappa_objective():
    labels = ("critica", "alta", "media", "baja")
    truth = ["critica", "critica", "alta", "alta", "media", "media", "baja", "baja"]
    predicted = ["alta", "critica", "alta", "media", "media", "baja", "baja", "baja"]
    result = objective_metrics(truth, predicted, labels, "severidad")
    assert result["balanced_accuracy"] == balanced_accuracy_score(truth, predicted)
    assert result["critical_recall"] == result["critical_fnr"] == .5
    assert result["kappa_quadratic"] == pytest.approx(cohen_kappa_score(truth, predicted, labels=list(labels), weights="quadratic"))
    predicted[1] = REVIEW
    assert objective_metrics(truth, predicted, labels, "severidad")["kappa_quadratic"] is None


def test_penalty_definition_joint_ngram_domains_and_exact_steps(settings):
    from src.optimization.search import ConfiguredSearch
    with pytest.raises(ValidationError, match="extremo"):
        Distribution(kind="int", low=1, high=5, step=3)
    joint = default_options(settings).model_dump(mode="json")
    joint["space"] = {"ngram_min": {"kind": "categorical", "choices": [3]}, "ngram_max": {"kind": "categorical", "choices": [3]}}
    assert spec(settings, optimization=joint).optimization.space["ngram_min"].choices == (3,)
    options = SearchOptions.model_validate({**default_options(settings).model_dump(mode="json"), "metric": "penalized_f1",
                                           "critical_penalty": .4, "review_penalty": .2})
    base = SimpleNamespace(name="fixture", evaluate=lambda *_args: {"score": .8, "metrics": {"f1_macro": .8, "critical_fnr": .5, "review_rate": .25}})
    assert ConfiguredSearch(base, options).evaluate((), (), {}, "inner", lambda: None)["objective"] == pytest.approx(.55)


@pytest.mark.parametrize("sampler", ["tpe", "random", "grid"])
def test_standard_storage_and_sequential_sampler_recovery(settings, tmp_path, sampler):
    options = default_options(settings).model_copy(update={"sampler": sampler})
    options = SearchOptions.model_validate({**options.model_dump(mode="json"),
        "space": {"c": {"kind": "categorical", "choices": [.01, .1, 1., 10.]}} if sampler == "grid" else
                 {"c": {"kind": "float", "low": .01, "high": 10., "log": True}}})
    count = 4 if sampler == "grid" else 10

    def objective(trial):
        value = options.space["c"].suggest(trial, "c")
        return -(value - .7)**2

    first = tmp_path / "first"
    first.mkdir()
    identity = {"partition": "fixture", "search": options.model_dump(mode="json")}
    full = open_study(first, "fold", options, 42, 1, identity)
    full.optimize(objective, n_trials=count)
    second = tmp_path / "second"
    second.mkdir()
    partial = open_study(second, "fold", options, 42, 1, identity)
    partial.optimize(objective, n_trials=2)
    recovered = open_study(second, "fold", options, 42, 1, identity)
    recovered.optimize(objective, n_trials=count - 2)
    assert [trial.params for trial in full.trials] == [trial.params for trial in recovered.trials]
    assert [trial.value for trial in full.trials] == [trial.value for trial in recovered.trials]
    with pytest.raises(AnalyticsError, match="mismos datos"):
        open_study(second, "fold", options, 42, 1, {**identity, "partition": "changed"})


def test_interrupted_trials_remain_failed_without_deletion(settings, tmp_path):
    options = default_options(settings)
    study = open_study(tmp_path, "interrupted", options, 42, 1, {"fixture": 1})
    asked = study.ask()
    asked.suggest_float("x", 0, 1)
    assert recover_interrupted(study) == 1
    assert study.trials[0].state == optuna.trial.TrialState.FAIL and len(study.trials) == 1


def test_configuration_mapping_order_does_not_change_sampling(settings):
    from src.optimization.search import ConfiguredSearch
    from src.optimization.studies import sampler
    original = default_options(settings)
    reversed_options = SearchOptions.model_validate({**original.model_dump(mode="json"), "space": dict(reversed(list(original.space.items())))})
    results = []
    for options in (original, reversed_options):
        base = LocalSearch("tfidf_logreg", settings.training.local, settings.training, settings.seed, ("phishing", "malware"))
        search = ConfiguredSearch(base, options)
        study = optuna.create_study(direction="maximize", sampler=sampler(options, settings.seed, 1))
        def objective(trial):
            parameters = search.suggest(trial)
            return parameters["c"]
        study.optimize(objective, n_trials=10)
        results.append([row.params for row in study.trials])
    assert results[0] == results[1]


def test_ten_trials_nested_integration_configurations_candidate_and_figures(optimization):
    workspace, token, state = optimization
    request = spec(workspace.settings)
    saved = workspace.save_configuration(request, token)
    loaded = workspace.load_configuration(saved["version"], token)
    assert loaded == request
    assert workspace.parse(workspace.serialize(request), token) == request
    preview = workspace.manager.preview(request, token)
    changed = request.model_copy(update={"optimization": request.optimization.model_copy(update={"sampler": "random"})})
    with pytest.raises(AnalyticsError, match="Cambió la partición"):
        workspace.manager.start(changed, token, preview["plan_sha256"])
    identifier = workspace.manager.start(request, token, preview["plan_sha256"])
    result = workspace.manager._running[identifier].result(timeout=180)
    assert result and result["flow_calls"] == result["test_evaluations"] == 0
    family = result["families"]["tfidf_logreg"]
    assert len(family["folds"]) == 5 and all(len(row["inner"]) == 3 for row in family["folds"])
    assert sum(len(row["trials"]) for row in family["folds"]) == 50
    assert all(row["outer_evaluations"] == 1 and row["outer"]["groups_disjoint"] for row in family["folds"])
    snapshot = workspace.inspect(identifier, token)
    assert len(snapshot["studies"]) == 5 and all(len(study["trials"]) == 10 for study in snapshot["studies"])
    recovered = OptimizationWorkspace(ExperimentManager(workspace.settings, workspace.api))
    try:
        assert [s["trials"] for s in recovered.inspect(identifier, token)["studies"]] == [s["trials"] for s in snapshot["studies"]]
    finally:
        recovered.manager.close()
    candidate = workspace.candidate(identifier, token)
    winner = family["validation_selection"]["winner"]["configuration"]
    assert candidate["request"]["local"] == winner and not candidate["production_deployment"]
    assert workspace.load_candidate(candidate["version"], token) == candidate
    transferred = JobSpec.model_validate(candidate["request"])
    assert all(d.choices == (winner[name],) for name, d in transferred.optimization.space.items())
    for table in (space_table(request.optimization), trials_table(snapshot["studies"][0], request.optimization.metric), winners_table(family), stability_table(family, request.optimization)):
        assert table[0] and all(getattr(table[1], name) for name in ("title", "legend", "how_to_read", "finding", "limitations"))
    for function in (history_plot, importance_plot, parallel_plot, slice_plot, contour_plot, distribution_plot):
        figure, guide = function(snapshot["studies"][0], request.optimization, workspace.settings)
        assert guide.finding and guide.limitations
        assert "prueba sintética" in guide.title
        if figure:
            assert figure.axes and any(axis.get_xlabel() for axis in figure.axes)
            if function == contour_plot:
                assert figure.axes[-1].get_ylim()[1] == max(t["score"] for t in snapshot["studies"][0]["trials"] if t["state"] == "COMPLETE")
    figure, _ = history_plot(snapshot["studies"][0], request.optimization, workspace.settings)
    with Image.open(BytesIO(export_png(figure, workspace.settings.figures))) as image:
        assert all(abs(dpi - 600) < 1 for dpi in image.info["dpi"])
    assert stability_plot(family, request.optimization, workspace.settings)[0]
    assert {row["action"] for row in state["audit"]} >= {"guardar_configuracion_optuna", "exportar_candidato_optuna", "autorizar_experimento"}
    state["audit_ok"] = False
    before = set((workspace.directory / "configurations").iterdir())
    with pytest.raises(ServiceError):
        workspace.save_configuration(request, token)
    assert set((workspace.directory / "configurations").iterdir()) == before


def test_cancel_resume_and_pruning_preserve_trials_and_external_once(optimization, monkeypatch):
    workspace, token, state = optimization
    request = spec(workspace.settings, trials=4)
    request = spec(workspace.settings, trials=4, optimization={**request.optimization.model_dump(mode="json"), "sampler": "grid",
        "pruner": "median", "startup_trials": 1, "warmup_steps": 0, "space": {"c": {"kind": "categorical", "choices": [.1, .2, .3, .4]}}})
    planned = prepare(request, workspace.settings)
    store = workspace.manager.store
    identifier = store.create(request, planned.partition, "actor-optuna", lambda _id: None)
    first, external = {}, []

    def controlled(self, train, validation, parameters, scope, check):
        if scope.startswith("inner"):
            first.setdefault(scope, parameters["c"])
            score = 1. if parameters["c"] == first[scope] else .2
        else:
            score = .6
            if scope.startswith("outer"):
                external.append(scope)
        return {"score": score, "seconds": .001, "metrics": {"f1_macro": score}}

    monkeypatch.setattr(LocalSearch, "evaluate", controlled)
    append = store.append_event
    paused = []

    def pause(run_id, event):
        append(run_id, event)
        if event["event"] == "fin_trial" and not paused:
            paused.append(True)
            (store.path(run_id) / "cancel.requested").touch()

    monkeypatch.setattr(store, "append_event", pause)
    assert _execute(store, identifier) is None
    assert store.state(identifier)["status"] == "cancelado"
    journal = storage(store.path(identifier))
    old = optuna.load_study(study_name="tfidf_logreg-outer-1", storage=journal).trials
    (store.path(identifier) / "cancel.requested").unlink()
    result = _execute(store, identifier)
    assert result and external == [f"outer-{i}" for i in range(1, 6)]
    current = optuna.load_study(study_name="tfidf_logreg-outer-1", storage=journal).trials
    assert len(current) == 4 and all(current[t.number].params == t.params and current[t.number].state == t.state for t in old)
    assert any(t["state"] == "PRUNED" for fold in result["families"]["tfidf_logreg"]["folds"] for t in fold["trials"])


def test_timeout_and_untrusted_import_fail_closed(optimization):
    workspace, token, state = optimization
    request = spec(workspace.settings, trials=1, optimization=default_options(workspace.settings).model_copy(update={"timeout_seconds": .001}))
    identifier = workspace.manager.store.create(request, prepare(request, workspace.settings).partition, "actor-optuna", lambda _id: None)
    assert _execute(workspace.manager.store, identifier) is None
    assert "tiempo autorizado" in workspace.manager.store.state(identifier)["message"]
    for raw in (b"!!python/object/apply:os.system ['echo unsafe']", b"[1,2]", b"x" * (workspace.settings.optimization.max_config_bytes + 1)):
        with pytest.raises(AnalyticsError):
            workspace.parse(raw, token)
    state["role"] = "gestor"
    with pytest.raises(AnalyticsError):
        workspace.save_configuration(spec(workspace.settings), token)
    state["role"] = "auditor"
    with pytest.raises(AnalyticsError):
        workspace.list(token)


def test_parallel_local_trials_obey_the_resource_limit(optimization, monkeypatch):
    workspace, token, state = optimization
    request = spec(workspace.settings, trials=2, optimization=default_options(workspace.settings).model_copy(update={"parallel_trials": 2}))
    planned = prepare(request, workspace.settings)
    identifier = workspace.manager.store.create(request, planned.partition, "actor-optuna", lambda _id: None)
    fit = LocalSearch._fit
    barrier, lock = Barrier(2), Lock()
    observed = {"active": 0, "maximum": 0, "count": 0}

    def instrument(self, train, parameters):
        with lock:
            observed["active"] += 1
            observed["maximum"] = max(observed["maximum"], observed["active"])
            observed["count"] += 1
            first = observed["count"] <= 2
        try:
            if first:
                barrier.wait(timeout=20)
            return fit(self, train, parameters)
        finally:
            with lock:
                observed["active"] -= 1

    monkeypatch.setattr(LocalSearch, "_fit", instrument)
    assert _execute(workspace.manager.store, identifier)
    assert observed["maximum"] == 2


def test_streamlit_optuna_and_phase2_candidate_transfer(optimization, monkeypatch):
    """Navigate the actual multipage app and execute the pinned candidate through Phase 2."""
    from datetime import datetime, timedelta, timezone
    from shutil import copyfile, copytree
    from time import monotonic
    from streamlit.testing.v1 import AppTest
    from src.data.catalog import DatasetCatalog
    from src.inference.services import Session
    from src.training.experiments import RunRegistry
    from src.utils.config import PROJECT_ROOT
    from src.utils.streamlit_runtime import Runtime, _inventory, clear_private_state
    from src.utils.tasks import TaskRunner

    workspace, token, state = optimization
    settings = workspace.settings
    copyfile(PROJECT_ROOT / "app.py", settings.root / "app.py")
    copytree(PROJECT_ROOT / "pages", settings.root / "pages")
    tasks = TaskRunner(2)
    checked = monotonic()
    monkeypatch.setattr("src.utils.streamlit_runtime.monotonic", lambda: checked)
    runtime = Runtime(settings, workspace.api, DatasetCatalog(settings, workspace.api), RunRegistry(settings), tasks,
        _inventory, experiments=workspace.manager, optimization=workspace)
    monkeypatch.setattr("src.utils.streamlit_runtime.get_runtime", lambda: runtime)

    def settle(app, *keys):
        for key in keys:
            if key in app.session_state:
                app.session_state[key].result(timeout=180)
                app.run()
        assert not app.exception and not app.error

    try:
        app = AppTest.from_file(str(settings.root / "app.py"), default_timeout=90).run()
        app.switch_page("pages/09_Optuna.py").run()
        assert not app.exception and not app.dataframe
        app.session_state["auth_session"] = Session(token=token, user=workspace.api.me(token), checked_at=checked,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2))
        app.run()
        settle(app, "opt_catalog")
        app.button(key="opt_validate").click().run()
        assert not app.exception and "opt_request" in app.session_state
        app.button(key="opt_save_button").click().run()
        settle(app, "opt_save")
        app.button(key="opt_prepare").click().run()
        settle(app, "opt_preview")
        app.button(key="opt_start_button").click().run()
        settle(app, "opt_start", "opt_catalog", "opt_authorize")
        identifier = app.session_state["opt_latest_run"]
        assert workspace.manager._running[identifier].result(timeout=180)
        app.run()
        settle(app, "opt_authorize")
        app.button(key="opt_inspect_button").click().run()
        settle(app, "opt_inspect")
        assert app.get("image") and app.dataframe
        assert any("Cómo leerlo" in element.value for element in app.markdown)
        app.button(key="opt_candidate_button").click().run()
        settle(app, "opt_candidate")
        app.button(key="opt_transfer").click().run()
        version = app.session_state["exp_candidate_version"]
        app.switch_page("pages/04_Experimentacion.py").run()
        settle(app, "exp_candidate_load", "exp_list")
        assert app.session_state["exp_candidate_load_result"]["version"] == version
        app.button(key="exp_candidate_prepare").click().run()
        settle(app, "exp_candidate_preview")
        app.button(key="exp_candidate_start").click().run()
        settle(app, "exp_start", "exp_list", "exp_monitor")
        runs = [key for key in workspace.manager._running if key != identifier]
        assert len(runs) == 1 and workspace.manager._running[runs[0]].result(timeout=180)
        assert workspace.manager.store.verified(runs[0], "result.json")["request"]["trials"] == 1
        state["role"] = "gestor"
        app.session_state["auth_session"] = app.session_state["auth_session"].model_copy(update={"user": workspace.api.me(token)})
        app.switch_page("pages/09_Optuna.py").run()
        assert not app.exception and not [b for b in app.button if b.key in ("opt_validate", "opt_candidate_button", "opt_transfer")]
        with monkeypatch.context() as patch:
            private = {"opt_request": "private", "opt_candidate_result": "private", "exp_candidate_version": "private", "auth_session": "jwt", "other": "public"}
            patch.setattr("src.utils.streamlit_runtime.st.session_state", private)
            clear_private_state()
            assert private == {"other": "public"}
    finally:
        tasks.close()


def test_real_fastapi_optuna_audit_requires_jwt_and_writer_roles(tmp_path):
    from fastapi.testclient import TestClient
    from uuid import uuid4
    from backend.config import Settings
    from backend.db import utc_now
    from backend.main import create_app
    from backend.security import hash_password

    app = create_app(Settings(sqlite_path=tmp_path / "optuna-audit.sqlite3", operator_token="fixture-legacy",
        jwt_secret="phase7-fixture-jwt-secret-at-least-32-characters"))
    identifier = "20261111T120000000000Z_1234567890ab"
    with TestClient(app) as server:
        with app.state.db.session(write=True) as execute:
            password = hash_password("fixture-password")
            for role in ("administrador", "analista", "gestor", "auditor"):
                execute("INSERT INTO users(id,username,password_hash,role,creado_at) VALUES(%s,%s,%s,%s,%s)",
                        (str(uuid4()), role, password, role, utc_now()))
        for role in ("administrador", "analista", "gestor", "auditor"):
            auth = server.post("/api/auth/login", json={"username": role, "password": "fixture-password"}).json()
            headers = {"Authorization": "Bearer " + auth["access_token"]}
            for action in ("consultar_optimizacion", "guardar_configuracion_optuna", "exportar_candidato_optuna"):
                response = server.post("/api/analitica/eventos", headers=headers, json={"action": action, "run_id": identifier})
                allowed = role in ("administrador", "analista") or role == "gestor" and action == "consultar_optimizacion"
                assert response.status_code == (204 if allowed else 403)
        assert server.post("/api/analitica/eventos", headers={"X-Operator-Token": "fixture-legacy"}, json={"action": "consultar_optimizacion"}).status_code == 401
        with app.state.db.session() as execute:
            assert execute("SELECT count(*) AS n FROM audit_log WHERE module='analitica/optimizacion'").fetchone()["n"] == 7
