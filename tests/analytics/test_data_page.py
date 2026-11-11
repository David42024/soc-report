"""Streamlit smoke tests for browsing, review and evidence generation."""
from datetime import datetime, timedelta, timezone
import json
from time import monotonic

import pytest
from streamlit.testing.v1 import AppTest

from src.inference.services import Session
from src.training.experiments import RunRegistry
from src.utils.config import PROJECT_ROOT
from src.utils.streamlit_runtime import Runtime, _inventory
from src.utils.tasks import TaskRunner


@pytest.fixture
def data_page(data_workspace, monkeypatch):
    workspace, token, _, state = data_workspace
    # Token renewal has its own API tests. Keep UI steps deterministic under host suspension.
    checked_at = monotonic()
    monkeypatch.setattr("src.utils.streamlit_runtime.monotonic", lambda: checked_at)
    runner = TaskRunner(2)
    runtime = Runtime(workspace.settings, workspace.api, workspace.reader.catalog,
                      RunRegistry(workspace.settings), runner, _inventory)
    monkeypatch.setattr("src.utils.streamlit_runtime.get_runtime", lambda: runtime)
    app = AppTest.from_file(str(PROJECT_ROOT / "pages/03_Datos.py"), default_timeout=25)
    yield app, workspace, token, state
    runner.close()


def _sign_in(app, workspace, token):
    app.session_state["auth_session"] = Session(token=token, user=workspace.api.me(token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=1), checked_at=monotonic())


def _settle(app, *keys):
    for key in (*keys, "identity_task"):
        if key in app.session_state:
            app.session_state[key].result(timeout=10)
            app.run()
    assert not app.exception and not app.error


def _button(app, label):
    return next(item for item in app.button if item.label == label)


def test_data_page_browse_filter_review_and_manifest(data_page):
    app, workspace, token, state = data_page
    _sign_in(app, workspace, token)
    app.run().button(key="data_load").click().run()
    _settle(app, "data_view")
    assert app.title[0].value == "Datos del SOC"
    app.selectbox(key="data_size").select(10).run()
    app.number_input(key="data_page_eurepoc").set_value(2).run()
    assert len(app.dataframe[0].value) == 4
    app.text_input(key="data_search_eurepoc").set_value("interrupción servidor").run()
    app.selectbox(key="data_filter_tipo_fuente_eurepoc").select("Phishing").run()
    assert len(app.dataframe[0].value) == 1 and not app.exception
    record = app.session_state["data_view_result"].inventory.sources[0].records[0]
    app.selectbox(key="data_detail_eurepoc").select(record.key).run()
    assert all("privado@example.test" not in item.value for item in app.text)
    next(item for item in app.text_area if item.label == "Observaciones").set_value("Se comprobó la fuente.")
    next(item for item in app.checkbox if item.label == "Confirmo guardar esta revisión").check()
    _button(app, "Guardar versión").click().run()
    _settle(app, "data_save", "data_view")
    assert any("Revisión 1 guardada" in item.value for item in app.success)
    app.selectbox(key="data_detail_eurepoc").select(record.key).run()
    _button(app, "Consultar historial").click().run()
    _settle(app, "data_history")
    assert any("Historial de revisiones" in item.value for item in app.subheader)
    assert app.session_state["data_history_result"][0].changes == {"observaciones": "Se comprobó la fuente."}
    for section in ("Catálogo", "Calidad", "Estadística", "Manifiestos"):
        app.radio(key="data_section").set_value(section).run()
        assert app.dataframe and not app.exception
        guide = " ".join(item.value for item in app.markdown)
        assert "Cómo leerlo" in guide and "Hallazgo clave" in guide
        if section == "Estadística":
            _button(app, "Calcular frecuencias de términos protegidos").click().run()
            _settle(app, "data_terms")
            assert any("Palabras y términos técnicos" in item.value for item in app.subheader)
    _button(app, "Guardar manifiesto versionado").click().run()
    _settle(app, "data_manifest")
    _button(app, "Preparar descarga del manifiesto guardado").click().run()
    _settle(app, "data_download")
    assert app.get("download_button")
    assert not any("private-test-token" in item.value for item in app.text)
    assert {event["action"] for event in state["audit"]} >= {"consultar_datos", "autorizar_revision_datos",
                                                           "autorizar_manifiesto_datos"}


def test_data_page_requires_session_and_clears_expired_view(data_page):
    app, workspace, token, _ = data_page
    app.run()
    assert not app.exception and not app.dataframe and not app.button
    _sign_in(app, workspace, token)
    app.session_state["auth_session"].expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    app.session_state["data_view_result"] = workspace.open(token)
    app.run()
    assert not app.exception and not app.dataframe and "data_view_result" not in app.session_state


def test_complete_synthetic_demo_across_data_views(data_page):
    app, workspace, token, _ = data_page
    _sign_in(app, workspace, token)
    app.run()
    app.radio(key="data_mode").set_value("Demostración sintética").run()
    _settle(app, "data_view")
    assert len(app.session_state["data_view_result"].inventory.records()) == 640
    for section in ("Explorar", "Catálogo", "Calidad", "Estadística", "Manifiestos"):
        app.radio(key="data_section").set_value(section).run()
        assert app.dataframe and not app.exception
    status = app.dataframe[0].value
    assert set(status["Prueba sintética"]) == {"Disponible"}
    assert set(status["Casos de prueba con etiqueta"]) == {160}
    assert set(status["Cobertura total (%)"]) == {100}
    assert app.get("download_button")
    app.button(key="data_make_manifest").click().run()
    _settle(app, "data_manifest")
    saved = app.session_state["data_manifest_result"]
    _, payload = workspace.read_manifest(saved["run_id"], token)
    assert json.loads(payload)["content"]["synthetic_demo"]["total_cases"] == 640
    app.radio(key="data_mode").set_value("Fuentes existentes").run()
    assert "data_view_result" not in app.session_state
    assert not app.dataframe


def test_read_only_role_sees_report_without_edit_or_manifest_actions(data_page):
    app, workspace, token, state = data_page
    state["role"] = "gestor"
    _sign_in(app, workspace, token)
    view = workspace.open(token)
    app.session_state["data_view_result"] = view
    app.run()
    key = view.inventory.sources[0].records[0].key
    app.selectbox(key="data_detail_eurepoc").select(key).run()
    assert any("Detalle del registro" in item.value for item in app.subheader)
    assert not any(item.label == "Guardar versión" for item in app.button)
    app.radio(key="data_section").set_value("Manifiestos").run()
    assert app.dataframe and not app.exception
    assert not any(item.label == "Guardar manifiesto versionado" for item in app.button)
