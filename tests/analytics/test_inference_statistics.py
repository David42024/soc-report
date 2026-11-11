"""Applicability, provenance and descriptive statistics without consuming sealed Test."""
from copy import deepcopy
from io import BytesIO
import json
from types import SimpleNamespace

import numpy as np
from PIL import Image
from pydantic import ValidationError
import pytest

from src.inference.robustness import archived_metric_rows, lexical_coverage, matching_evaluations, statistical_applicability
from src.inference.telemetry import CloudTrace, elapsed, observed_metrics, percentiles, valid_trace
from src.reports.figures import export_png
from src.reports.inference_presentation import latency_figure, metrics_table
from src.utils.config import PROJECT_ROOT
from src.utils.errors import AnalyticsError


def row(index=1, **overrides):
    """Controlled records are fixture observations, never claimed as real performance."""
    return {"id": str(index), "tipo": "phishing", "severidad": "media", "activo_afectado": "servidor",
            "demo": False, "origin": "langflow", "review": None, "human_severity": None,
            "received_at": "2026-11-11T00:00:00+00:00", "classified_at": "2026-11-11T00:00:02+00:00",
            "notified_at": "2026-11-11T00:00:04+00:00", "input": None, **overrides}


def trace(provider="groq", outcome="classified"):
    attempts = [{"provider": "groq", "model": "primary", "outcome": "ok", "seconds": .5}]
    if provider == "gemini":
        attempts[0].update(outcome="http_error", http_status=503)
        attempts.append({"provider": "gemini", "model": "backup", "outcome": "ok", "seconds": 1.5})
    if outcome == "protective":
        attempts[-1].update(outcome="http_error", http_status=429)
    return {"schema_version": 1, "outcome": outcome, "attempts": attempts,
            "technical_fallback": provider == "gemini", "review_reason": "proveedores_no_disponibles" if outcome == "protective" else None}


def test_sample_quantiles_match_numpy_and_keep_missing_values():
    values = [0.1, .8, 2.3, 4.7, 9.1]
    result = percentiles(values)
    assert result == {"n": 5, "p50_s": np.percentile(values, 50), "p95_s": np.percentile(values, 95)}
    assert percentiles([]) == {"n": 0, "p50_s": None, "p95_s": None}
    assert elapsed("2026-11-11T00:00:00Z", "2026-11-11T00:00:01.250+00:00") == 1.25
    for start, end in [("bad", "bad"), (None, None), ("2026-11-11", "2026-11-12"),
                       ("2026-11-11T00:00:03Z", "2026-11-11T00:00:01Z")]:
        assert elapsed(start, end) is None


@pytest.mark.parametrize("change", [
    lambda v: v.update(technical_fallback=True),
    lambda v: v["attempts"].append({"provider": "gemini", "model": "backup", "seconds": 1., "outcome": "ok"}),
    lambda v: v["attempts"][0].update(seconds=float("nan")),
    lambda v: v["attempts"][0].update(model="secret@example.test"),
    lambda v: v.update(outcome="protective", review_reason="proveedores_no_disponibles"),
    lambda v: v.update(extra="private upstream response"),
])
def test_invalid_telemetry_cannot_invent_a_provider_or_latency(change):
    value = trace()
    change(value)
    assert valid_trace({"soc_trace": value}) is None
    with pytest.raises(ValidationError):
        CloudTrace.model_validate(value)


def test_metrics_separate_demo_missing_trace_gemini_and_safe_fallback():
    capture = {"input_sha256": "a" * 64, "prompt_sha256": "b" * 64, "provider": "gemini", "model": "backup", "trace": trace("gemini")}
    data = [row(1, input=capture), row(2, input=capture), row(3, demo=True),
            row(4, origin="fallback", review="langflow_no_disponible", human_severity="critica"),
            row(5, human_severity="critica", input={"response_errors": {"format": True, "taxonomy": True}})]
    result = observed_metrics(data, 20, 10)
    assert result["rows"] == 5 and result["non_demo"] == 4 and result["demo_excluded"] == 1
    assert result["gemini_attempts"] == result["technical_fallbacks"] == result["technical_failures"] == 2
    assert result["safe_origin_fallbacks"] == 1 and result["without_trace"] == 2
    assert result["format_errors"] == result["taxonomy_errors"] == 1
    assert result["critical_reference"] == 2 and result["critical_classified"] == 1
    assert result["critical_protective"] == result["critical_lower"] == 1 and result["critical_lower_rate"] == 1.
    assert result["repeatability"] == {"groups": 1, "observations": 2, "modal_agreement": 1.}
    assert result["latency"]["end_to_end"] == {"n": 4, "p50_s": 4., "p95_s": 4.}
    assert not result["sample_sufficient"] and result["compliance"] == "pendiente_de_evidencia_representativa"
    assert result["target_comparison"] == "p95_observado_inferior_a_meta"


def test_reference_gates_require_exact_human_evidence_and_do_not_use_synthetic_metrics(settings):
    snapshot = {"input": {"provider": "groq", "model": "effective-model", "prompt_sha256": "c" * 64},
                "routing": {"configuration": {"umbral": .75}}}
    reference = {"source": "real", "reference": "humana_independiente", "family": "langflow",
        "configuration": {"threshold": .75, "prompt_sha256": "c" * 64},
        "operations": {"responses": [{"provider": "groq", "model": "effective-model", "n": 100}]},
        "run_id": "fixture", "target": "tipo", "dataset_sha256": "d" * 64, "configuration_sha256": "e" * 64,
        "rows": 100, "groups": 50, "metrics": {"overall": {"accuracy": .8}},
        "uncertainty": {"metrics": {"accuracy": {"ci95": [.7, .9]}}}}
    variants = [deepcopy(reference) for _ in range(4)]
    variants[0].update(source="sintetico")
    variants[1].update(reference="prueba_tecnica")
    variants[2]["configuration"]["threshold"] = .85
    variants[3]["operations"]["responses"][0]["model"] = "other-model"
    assert matching_evaluations(snapshot, variants) == []
    rows, guide = statistical_applicability(snapshot, variants)
    assert next(r for r in rows if "conforme" in r["Análisis"])["Estado"] == "No aplicable"
    assert "0 evaluaciones" in guide.finding
    rows, _ = archived_metric_rows(snapshot, variants + [reference])
    assert len(rows) == 1 and rows[0]["Estimación"] == .8 and rows[0]["IC inferior"] == .7
    assert lexical_coverage("Una receta de cocina para mañana", settings)["potential_ood"]
    assert not lexical_coverage("Incidente de phishing con malware", settings)["potential_ood"]


def test_latency_chart_interpretations_and_export_are_verifiable(settings):
    data = observed_metrics([row()], 20, 10)
    rows, guide = metrics_table(data)
    assert len(rows) == 4 and "1 reportes" in guide.finding and guide.limitations
    figure, guide = latency_figure(data, settings.figures, settings.reporting)
    assert figure.axes[0].get_ylabel() == "Duración (s)" and figure.axes[0].get_legend()
    with Image.open(BytesIO(export_png(figure, settings.figures))) as image:
        assert image.format == "PNG" and all(abs(dpi - 600) < 1 for dpi in image.info["dpi"])
    assert guide.how_to_read and guide.finding and guide.limitations
    assert tuple(figure.get_size_inches()) == (settings.reporting.figure_width_inches, settings.reporting.figure_height_inches)
    assert latency_figure(observed_metrics([], 20, 10), settings.figures, settings.reporting)[0] is None


@pytest.mark.parametrize("unexpected_change", [False, True])
def test_langflow_source_sync_preserves_other_fields_and_rolls_back(settings, unexpected_change):
    from scripts.verify_inference import component_sync
    from src.utils.langflow import cloud_node, graph_digest

    graph = json.loads((PROJECT_ROOT / settings.flow_validation.export_file).read_bytes())["data"]
    cloud_node(graph)["data"]["node"]["template"]["code"]["value"] = "previous-reviewed-source"
    before = deepcopy(graph)
    state = {"graph": graph, "patches": 0}

    def mutate(method, path, **kwargs):
        assert method == "PATCH"
        state["patches"] += 1
        state["graph"] = deepcopy(kwargs["json"]["data"])
        if unexpected_change and state["patches"] == 1:
            state["graph"]["nodes"][0]["position"] = {"x": 999, "y": 999}

    fake = SimpleNamespace(fetch=lambda: deepcopy(state["graph"]), _path=lambda value: value,
        _request=mutate, operational=SimpleNamespace(privacy_secrets=lambda: ("fixture-unused-server-secret",)),
        check=lambda: {"export_matches_runtime": True})
    if unexpected_change:
        with pytest.raises(AnalyticsError, match="cambios adicionales"):
            component_sync(fake, settings)
        assert state["patches"] == 2 and graph_digest(state["graph"]) == graph_digest(before)
    else:
        result = component_sync(fake, settings)
        assert result["models_prompt_and_bindings_preserved"] and result["export_matches_runtime"]
        current = deepcopy(state["graph"])
        cloud_node(current)["data"]["node"]["template"]["code"]["value"] = "previous-reviewed-source"
        assert graph_digest(current) == graph_digest(before)
        assert json.loads(settings.path(settings.flow_validation.export_file).read_bytes())["data"] == state["graph"]
