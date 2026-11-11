"""Smoke-test the fifth page while a real technical job is in progress."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from threading import Event
from time import monotonic

from PIL import Image
import pytest
from streamlit.testing.v1 import AppTest

from src.inference.services import Session
from src.reports.figures import export_png
from src.reports.training_presentation import fold_plot
from src.training.experiments import RunRegistry
from src.training.jobs import ExperimentManager
from src.training.local import LocalSearch
from src.utils.config import PROJECT_ROOT
from src.utils.streamlit_runtime import Runtime, _inventory
from src.utils.tasks import TaskRunner


@pytest.fixture
def lab_page(data_workspace, monkeypatch):
    workspace, token, _, state = data_workspace
    checked_at = monotonic()
    monkeypatch.setattr("src.utils.streamlit_runtime.monotonic", lambda: checked_at)
    settings, api = workspace.settings, workspace.api
    manager, tasks = ExperimentManager(settings, api), TaskRunner(2)
    runtime = Runtime(settings, api, workspace.reader.catalog, RunRegistry(settings), tasks, _inventory, manager)
    monkeypatch.setattr("src.utils.streamlit_runtime.get_runtime", lambda: runtime)
    app = AppTest.from_file(str(PROJECT_ROOT / "pages/04_Experimentacion.py"), default_timeout=60)
    yield app, manager, workspace, token, state
    tasks.close()
    manager.close()


def sign_in(app, manager, token):
    app.session_state["auth_session"] = Session(token=token, user=manager.api.me(token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=1), checked_at=monotonic())


def settle(app, *keys):
    for key in keys:
        if key in app.session_state:
            app.session_state[key].result(timeout=60)
            app.run()
    assert not app.exception and not app.error


def test_experiment_page_requires_session(lab_page):
    app, _, _, _, _ = lab_page
    app.run()
    assert not app.exception and not app.button and not app.dataframe


def test_cloud_page_reports_exact_readiness_and_zero_budget(lab_page):
    app, manager, workspace, token, _ = lab_page
    workspace.save_manifest(workspace.open(token), token)
    sign_in(app, manager, token)
    app.run()
    settle(app, "exp_list")
    app.radio(key="exp_mode").set_value("langflow").run()
    settle(app, "exp_status")
    assert any("Presupuesto del servidor en 0 USD" in item.value for item in app.info)
    assert any("sello" in item.value for item in app.warning)
    assert not any(item.key == "exp_start_button" for item in app.button)
    assert app.dataframe and not manager.store.versions()


def test_start_monitor_cancel_resume_and_export_in_streamlit(lab_page, monkeypatch):
    app, manager, _, token, audit = lab_page
    entered, released = Event(), Event()
    evaluate = LocalSearch.evaluate

    def controlled(self, train, validation, params, scope, cancel):
        if not entered.is_set():
            entered.set()
            assert released.wait(180)
        cancel()
        return evaluate(self, train, validation, params, scope, cancel)

    monkeypatch.setattr(LocalSearch, "evaluate", controlled)
    sign_in(app, manager, token)
    try:
        app.run()
        settle(app, "exp_list")
        app.number_input(key="exp_trials_academico").set_value(1).run()
        app.button(key="exp_prepare").click().run()
        settle(app, "exp_preview")
        assert "112" in str(app.dataframe[0].value)
        app.button(key="exp_start_button").click().run()
        settle(app, "exp_start", "exp_list", "exp_monitor")
        assert entered.wait(60)
        app.run()
        identifier = manager.store.versions()[0]["run_id"]
        assert manager.monitor(identifier)["active"]
        assert app.button(key="exp_cancel")
        app.radio(key="exp_mode").set_value("langflow").run()
        assert not app.exception
        app.radio(key="exp_mode").set_value("academico").run()
        settle(app, "exp_monitor")
        app.button(key="exp_cancel").click().run()
        settle(app, "exp_control")
        released.set()
        manager._running[identifier].result(timeout=60)
        app.run()
        assert manager.store.state(identifier)["status"] == "cancelado"
        app.button(key="exp_resume").click().run()
        settle(app, "exp_control")
        result = manager._running[identifier].result(timeout=120)
        app.run()
        assert result["test_evaluations"] == 0 and not app.exception and not app.error
        assert app.get("download_button")
        text = " ".join(item.value for item in app.markdown)
        assert "Cómo leerlo" in text and "Hallazgo clave" in text
        actions = {event["action"] for event in audit["audit"]}
        assert actions >= {"autorizar_experimento", "cancelar_experimento", "reanudar_experimento"}
        figure, _ = fold_plot(result, manager.settings.figures)
        with Image.open(BytesIO(export_png(figure, manager.settings.figures))) as png:
            assert png.info["dpi"] == pytest.approx((600, 600), abs=.1)
    finally:
        released.set()
