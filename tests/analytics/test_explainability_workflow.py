"""Exercise protected XAI archives, role checks and visible human annotations."""
import json

import pytest

from src.explainability.workspace import ExplanationWorkspace
from src.training.jobs import technical_run
from src.training.runs import JobSpec
from src.utils.errors import AnalyticsError, ServiceError


def test_final_models_are_read_only_and_sealed_test_is_excluded(data_workspace):
    data, token, _, state = data_workspace
    workspace = ExplanationWorkspace(data.settings, data.api)
    spec = JobSpec(source="sintetico", target="tipo", seed=data.settings.seed, trials=1,
                   models=("tfidf_logreg",), local=data.settings.training.local)
    identifier, phase2 = technical_run(data.settings, spec)
    before = workspace.training.verified(identifier, "result.json")
    with pytest.raises(AnalyticsError, match="Desarrollo o Validación"):
        workspace.local(identifier, "tfidf_logreg", "test", token)
    result = workspace.local(identifier, "tfidf_logreg", "validation", token)
    report = workspace.detail(result["run_id"], token)
    assert report["summary"]["cases"] == 24 and report["test_inferences"] == report["external_requests"] == 0
    assert workspace.training.verified(identifier, "result.json") == before == phase2
    case = report["cases"][0]
    assert workspace.alignment(report["run_id"], case["key"], token)["applicable"] is False
    span = case["linear"]["tokens"][0]
    annotation = workspace.annotate(report["run_id"], case["key"], [{"start": span["start"], "end": span["end"]}], token)
    aligned = workspace.alignment(report["run_id"], case["key"], token)
    assert aligned["applicable"] and aligned["annotation_id"] == annotation["run_id"]
    assert aligned["independence"] == "retrospectiva_explicacion_visible"
    state["role"] = "gestor"
    assert "cases" not in workspace.summary(report["run_id"], token)
    for call in (lambda: workspace.detail(report["run_id"], token), lambda: workspace.original(case["key"], token),
                 lambda: workspace.local(identifier, "tfidf_logreg", "validation", token)):
        with pytest.raises(AnalyticsError, match="rol"):
            call()
    state["role"] = "analista"
    state["audit_ok"] = False
    with pytest.raises(ServiceError):
        workspace.detail(report["run_id"], token)
    record_path = workspace.store.directory / report["run_id"] / "result.json"
    value = json.loads(record_path.read_text(encoding="utf-8"))
    value["cases"][0]["linear"]["predicted"] = "inventado"
    record_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(AnalyticsError, match="huella cambió"):
        workspace.store.read(report["run_id"])
