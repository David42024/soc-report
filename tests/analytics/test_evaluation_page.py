"""Drive the real Streamlit page and its background evaluation task."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
from time import monotonic

from PIL import Image
import pytest
from streamlit.testing.v1 import AppTest

from src.evaluation.workspace import EvaluationWorkspace
from src.inference.services import Session
from src.reports.evaluation_presentation import confusion_figure
from src.reports.figures import export_png
from src.training.experiments import RunRegistry
from src.training.jobs import technical_run
from src.training.runs import JobSpec
from src.utils.config import PROJECT_ROOT
from src.utils.streamlit_runtime import Runtime, _inventory
from src.utils.tasks import TaskRunner


def settle(app, *keys):
    for key in keys:
        if key in app.session_state:
            app.session_state[key].result(timeout=60)
            app.run()
    assert not app.exception and not app.error


def test_page_uses_seal_confirmation_and_renders_audited_results(data_workspace, monkeypatch):
    data, token, _, state = data_workspace
    settings, api = data.settings, data.api
    workspace, tasks = EvaluationWorkspace(settings, api), TaskRunner(2)
    checked_at = monotonic()
    monkeypatch.setattr("src.utils.streamlit_runtime.monotonic", lambda: checked_at)
    runtime = Runtime(settings, api, data.reader.catalog, RunRegistry(settings), tasks, _inventory, evaluations=workspace)
    monkeypatch.setattr("src.utils.streamlit_runtime.get_runtime", lambda: runtime)
    app = AppTest.from_file(str(PROJECT_ROOT / "pages/05_Evaluacion.py"), default_timeout=60)
    try:
        app.run()
        assert not app.exception and not app.dataframe and not app.button
        spec = JobSpec(source="sintetico", target="tipo", seed=settings.seed, trials=1,
                       models=("tfidf_logreg", "tfidf_svm"), local=settings.training.local)
        phase2, _ = technical_run(settings, spec)
        workspace.evaluate(phase2, "tfidf_svm", token)
        app.session_state["auth_session"] = Session(token=token, user=api.me(token), checked_at=checked_at,
                                                    expires_at=datetime.now(timezone.utc) + timedelta(days=1))
        app.run()
        settle(app, "eval_catalog", "eval_result")
        assert app.radio(key="eval_source").value == "sintetico"
        app.radio(key="eval_source").set_value("real").run()
        assert any("Falta el archivo de Prueba" in item.value for item in app.warning)
        app.radio(key="eval_source").set_value("sintetico").run()
        settle(app, "eval_result")
        app.selectbox(key="eval_selection_sintetico").set_value(phase2 + "|tfidf_logreg").run()
        app.button(key="eval_prepare").click().run()
        settle(app, "eval_preview")
        assert app.button(key="eval_run").disabled
        confirmation = next(item for item in app.checkbox if item.key.startswith("eval_confirm_"))
        confirmation.check().run()
        app.button(key="eval_run").click().run()
        settle(app, "eval_execute", "eval_catalog", "eval_result")
        assert len(workspace.store.list()) == 2
        assert len(app.get("download_button")) == 3
        app.toggle(key="eval_matrix_normalized").set_value(True).run()
        app.button(key="eval_compare_button").click().run()
        settle(app, "eval_compare")
        assert any("Contrastes de aciertos" in item.value for item in app.subheader)
        assert any("Cómo leerlo" in item.value for item in app.markdown)
        assert any("Hallazgo clave" in item.value for item in app.markdown)
        app.button(key="eval_export").click().run()
        settle(app, "eval_export_task")
        assert "predictions" in app.session_state["eval_export_task_result"]
        actions = [event["action"] for event in state["audit"]]
        assert actions.count("autorizar_evaluacion") == 2
        assert "inspeccionar_evaluacion" in actions
        report = app.session_state["eval_result_result"]
        figure, _ = confusion_figure(report["metrics"]["matrix"], settings.figures, True, True)
        with Image.open(BytesIO(export_png(figure, settings.figures))) as png:
            assert png.info["dpi"] == pytest.approx((600, 600), abs=.1)
    finally:
        tasks.close()
