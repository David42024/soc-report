"""Smoke and access-control tests for every newly available Streamlit page."""
from datetime import datetime, timedelta, timezone
from time import monotonic
from uuid import uuid4

from pydantic import SecretStr
import pytest
from streamlit.testing.v1 import AppTest

from src.data.catalog import DatasetCatalog
from src.inference.services import Session, User
from src.training.experiments import RunRegistry
from src.utils.config import PROJECT_ROOT, load_config
from src.utils.streamlit_runtime import Runtime, _inventory
from src.utils.tasks import TaskRunner


@pytest.fixture
def ui_runtime(api, monkeypatch):
    config = load_config()
    config = config.model_copy(update={"runs_dir": "tmp/analytics-tests/" + uuid4().hex})
    runner = TaskRunner(config.ui.workers)
    runtime = Runtime(config, api, DatasetCatalog(config, api), RunRegistry(config), runner, _inventory)
    monkeypatch.setattr("src.utils.streamlit_runtime.get_runtime", lambda: runtime)
    yield runtime
    runner.close()


def session(role="analista"):
    return Session(token=SecretStr("private-test-token"),
        user=User(id="analyst", username="analista", role=role, active=1),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1), checked_at=monotonic())


@pytest.mark.parametrize("page", ["pages/00_Inicio.py", "pages/01_Fuentes.py", "pages/02_Registros.py"])
def test_each_page_renders_with_interpretations(ui_runtime, page):
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=15)
    app.session_state["auth_session"] = session()
    app.run().switch_page(page).run()
    for key in ("catalog_access", "records_task"):
        if key in app.session_state:
            app.session_state[key].result(timeout=5)
            app.run()
    assert not app.exception
    text = " ".join(element.value for element in app.markdown)
    assert "Cómo leerlo" in text and "Hallazgo clave" in text
    assert "private-test-token" not in str(app)


@pytest.mark.parametrize("role", [None, "auditor", "solicitante"])
def test_private_catalog_requires_existing_read_permission(ui_runtime, role):
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=15)
    if role:
        app.session_state["auth_session"] = session(role)
    app.run().switch_page("pages/01_Fuentes.py").run()
    assert not app.exception
    assert not app.dataframe


def test_home_handles_unavailable_services_without_crashing(ui_runtime):
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=15)
    app.session_state["health_task_error"] = "FastAPI no está disponible."
    app.run()
    assert not app.exception
    assert app.warning


def test_entrypoint_with_real_configuration_and_token_free_resources():
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert app.title and app.dataframe
    assert "auth_session" not in app.session_state
