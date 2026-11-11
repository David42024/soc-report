"""Exercise the new page, protected details and actual background local XAI."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from time import monotonic

from PIL import Image
import pytest
from streamlit.testing.v1 import AppTest

from src.explainability.workspace import ExplanationWorkspace
from src.inference.services import Session
from src.reports.figures import export_png
from src.reports.xai_presentation import contribution_figure
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


def test_xai_page_analysis_annotation_and_manager_aggregate(data_workspace, monkeypatch):
    data, token, _, state = data_workspace
    settings, api = data.settings, data.api
    workspace, tasks = ExplanationWorkspace(settings, api), TaskRunner(2)
    checked_at = monotonic()
    monkeypatch.setattr("src.utils.streamlit_runtime.monotonic", lambda: checked_at)
    runtime = Runtime(settings, api, data.reader.catalog, RunRegistry(settings), tasks, _inventory, explainability=workspace)
    monkeypatch.setattr("src.utils.streamlit_runtime.get_runtime", lambda: runtime)
    app = AppTest.from_file(str(PROJECT_ROOT / "pages/06_Explicabilidad.py"), default_timeout=60)
    try:
        app.run()
        assert not app.exception and not app.dataframe and not app.button
        spec = JobSpec(source="sintetico", target="tipo", seed=settings.seed, trials=1,
                       models=("tfidf_logreg",), local=settings.training.local)
        technical_run(settings, spec)
        app.session_state["auth_session"] = Session(token=token, user=api.me(token), checked_at=checked_at,
                                                    expires_at=datetime.now(timezone.utc) + timedelta(days=1))
        app.run()
        settle(app, "xai_catalog")
        app.button(key="xai_run").click().run()
        settle(app, "xai_execute", "xai_catalog", "xai_detail")
        assert app.get("html") and len(app.get("download_button")) == 3
        assert any("Cómo leerlo" in item.value for item in app.markdown)
        assert any("Hallazgo clave" in item.value for item in app.markdown)
        app.button(key="xai_overlap").click().run()
        settle(app, "xai_alignment")
        assert any("Faltan anotaciones humanas" in item.value for item in app.info)
        case = app.session_state["xai_detail_result"]["cases"][0]
        span = case["linear"]["tokens"][0]
        app.text_area(key="xai_human_spans").set_value(json.dumps([{"start": span["start"], "end": span["end"]}])).run()
        app.checkbox(key="xai_annotation_confirmed").check().run()
        app.button(key="xai_annotate").click().run()
        settle(app, "xai_annotation")
        app.button(key="xai_overlap").click().run()
        settle(app, "xai_alignment")
        assert app.session_state["xai_alignment_result"]["applicable"]
        figure, guide = contribution_figure(case, settings.figures)
        assert guide.finding
        with Image.open(BytesIO(export_png(figure, settings.figures))) as png:
            assert png.info["dpi"] == pytest.approx((600, 600), abs=.1)
        state["role"] = "gestor"
        manager = AppTest.from_file(str(PROJECT_ROOT / "pages/06_Explicabilidad.py"), default_timeout=60)
        manager.session_state["auth_session"] = Session(token=token, user=api.me(token), checked_at=checked_at,
                                                        expires_at=datetime.now(timezone.utc) + timedelta(days=1))
        manager.run()
        settle(manager, "xai_catalog", "xai_detail")
        assert manager.dataframe and not any(item.key == "xai_case" for item in manager.selectbox)
        assert "cases" not in manager.session_state["xai_detail_result"]
    finally:
        tasks.close()
