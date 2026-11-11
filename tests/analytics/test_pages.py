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
from src.utils.errors import ServiceError
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


def settle_tasks(app, *keys):
    for _ in range(8):
        pending = [key for key in keys if key in app.session_state]
        if not pending:
            break
        for key in pending:
            app.session_state[key].result(timeout=10)
        app.run()
    assert not app.exception


def test_source_selection_and_save_survive_session_refresh(ui_runtime, monkeypatch):
    clock = [monotonic()]
    monkeypatch.setattr("src.utils.streamlit_runtime.monotonic", lambda: clock[0])
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=30)
    app.session_state["auth_session"] = session().model_copy(update={"checked_at": clock[0]})
    app.run().switch_page("pages/02_Registros.py").run()
    settle_tasks(app, "records_task")
    assert app.session_state["records_task_result"] == []
    app.switch_page("pages/01_Fuentes.py").run()
    settle_tasks(app, "catalog_access")
    app.selectbox(key="preview_source").select("article_simulation").run()

    clock[0] += ui_runtime.settings.ui.session_check_seconds + 1
    app.button(key="preview_check").click().run()
    settle_tasks(app, "identity_task", "preview_task")
    assert app.selectbox(key="preview_source").value == "article_simulation"
    assert app.session_state["preview_task_result"]["source_id"] == "article_simulation"

    clock[0] += ui_runtime.settings.ui.session_check_seconds + 1
    app.button(key="record_check").click().run()
    settle_tasks(app, "identity_task", "record_task")
    assert app.selectbox(key="preview_source").value == "article_simulation"
    records = ui_runtime.runs.records()
    assert len(records) == 1
    assert records[0]["dataset"]["source_id"] == "article_simulation"
    assert records[0]["audit_state"] == "confirmada"
    app.switch_page("pages/02_Registros.py").run()
    settle_tasks(app, "records_task")
    assert len(app.dataframe[0].value) == 1
    assert app.dataframe[0].value.iloc[0]["Fuente"] == "article_simulation"


def test_session_refresh_still_blocks_a_revoked_session(ui_runtime, monkeypatch):
    app = AppTest.from_file(str(PROJECT_ROOT / "pages/01_Fuentes.py"), default_timeout=30)
    app.session_state["auth_session"] = session()
    app.run()
    settle_tasks(app, "catalog_access")
    app.selectbox(key="preview_source").select("article_simulation").run()
    app.session_state["auth_session"] = session().model_copy(update={"checked_at": monotonic() - 60})

    def revoked(token):
        raise ServiceError("Sesión revocada", 401)

    monkeypatch.setattr(ui_runtime.api, "me", revoked)
    app.button(key="preview_check").click().run()
    settle_tasks(app, "identity_task")
    assert "auth_session" not in app.session_state
    assert not app.dataframe
    assert not app.selectbox


def test_entrypoint_with_real_configuration_and_token_free_resources():
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert app.title and app.dataframe
    assert "auth_session" not in app.session_state
