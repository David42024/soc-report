"""Reference identities, evidence failures and human-span validity for text XAI."""
from itertools import combinations
from math import factorial

import numpy as np
import pytest

from src.explainability.evidence import extract_evidence, overlap, text_hash, validate_claims, validate_spans
from src.explainability.analysis import aggregate
from src.explainability.linear import LinearTextExplainer
from src.reports.xai_presentation import term_html
from src.training.demo import technical_cases
from src.training.local import pipeline
from src.utils.errors import AnalyticsError


@pytest.mark.parametrize("family", ["tfidf_logreg", "tfidf_svm"])
@pytest.mark.parametrize("binary", [False, True])
def test_linear_contrast_and_shapley_match_model_and_coalition_enumeration(settings, family, binary):
    cases = technical_cases(3)
    if binary:
        cases = tuple(row for row in cases if row.label in ("phishing", "malware"))
    model = pipeline(family, settings.training.local, settings.seed)
    model.fit([row.text for row in cases], [row.label for row in cases])
    explainer = LinearTextExplainer(model, [row.text for row in cases], settings.explainability)
    text = cases[0].text
    report = explainer.explain(text)
    focus, rival = list(model.classes_).index(report["focus"]), list(model.classes_).index(report["rival"])

    def contrast(x):
        if family == "tfidf_logreg":
            scores = model.named_steps["classifier"].predict_log_proba(np.atleast_2d(x))[0]
            return scores[focus] - scores[rival]
        scores = np.asarray(model.named_steps["classifier"].decision_function(np.atleast_2d(x)))
        return float(scores[0] * (1 if focus == 1 else -1)) if binary else float(scores[0, focus] - scores[0, rival])

    x = model.named_steps["tfidf"].transform([text]).toarray()[0]
    baseline = explainer.mean.copy()
    np.testing.assert_allclose(report["score"], contrast(x), atol=1e-12)
    np.testing.assert_allclose(report["baseline"] + report["shap_sum"], contrast(x), atol=1e-12)
    np.testing.assert_allclose(report["intercept"] + report["contribution_sum"], contrast(x), atol=1e-12)
    assert abs(report["token_projection_residual"]) < 1e-12
    players = np.argsort(abs(x - baseline))[-3:]
    expected = []
    for i in players:
        others = [j for j in players if j != i]
        value = 0.0
        for k in range(len(others) + 1):
            for coalition in combinations(others, k):
                before = baseline.copy()
                before[list(coalition)] = x[list(coalition)]
                after = before.copy()
                after[i] = x[i]
                weight = factorial(k) * factorial(len(players) - k - 1) / factorial(len(players))
                value += weight * (contrast(after) - contrast(before))
        expected.append(value)
    weights, _ = explainer._coefficients(report["focus"])
    other, _ = explainer._coefficients(report["rival"])
    np.testing.assert_allclose(expected, ((weights - other) * (x - baseline))[players], atol=1e-12)
    reliability = explainer.reliability(text, report)
    assert all(row["prediction_same"] and row["term_jaccard"] == 1 for row in reliability["stability"])
    assert reliability["deletion"] and reliability["external_requests"] == 0


def test_quotes_contradictions_negation_and_unsupported_claims(settings):
    text = "No hay malware. Un correo falso menciona al servidor y un impacto limitado."
    prediction = {"tipo": "malware", "severidad": "media", "activo_afectado": "servidor", "confianza": .82}
    report = extract_evidence(text, prediction, settings.explainability)
    assert all(text[row["start"]:row["end"]] == row["quote"] for row in report["claims"])
    assert report["validation"]["status"] == "requiere_revision"
    assert "tipo" in report["unsupported_fields"]
    report["original_quotes"] = [{"claim": 0, "exists": False}]
    summary = aggregate([{"evidence": report, "correct": None}])
    assert summary["inconsistencies"]["cita_sin_coincidencia_literal_original"] == 1
    base = {"field": "tipo", "value": "phishing", "start": 0, "end": 2, "quote": "No"}
    checked = validate_claims(text, prediction, [base, {**base, "quote": "inventado"}, {**base, "field": "causa"}], settings.explainability)
    assert {row["code"] for row in checked["issues"]} >= {
        "cita_ausente", "contradice_clasificacion", "afirmacion_no_admitida", "afirmacion_sin_criterio_observable"}
    claim = {**base, "value": "malware", "start": 7, "end": 14, "quote": "malware", "negated": False}
    assert "evidencia_negada" in {row["code"] for row in validate_claims(text, prediction, [claim], settings.explainability)["issues"]}


def test_map_escapes_html_and_human_overlap_requires_valid_references(settings):
    text = '<script>alert("personal")</script> malware visible'
    prediction = {"tipo": "malware", "severidad": "media", "activo_afectado": None, "confianza": .8}
    evidence = extract_evidence(text, prediction, settings.explainability)
    html, guide = term_html({"text": text, "evidence": evidence}, settings.figures)
    assert "<script>" not in html and "&lt;script&gt;" in html and guide.finding
    assert overlap(text, [], None)["applicable"] is False
    start = text.index("malware")
    human = {"input_sha256": text_hash(text), "run_id": "human-proof", "independence": "controlada_en_prueba",
             "spans": [{"start": start, "end": start + 7}]}
    result = overlap(text, [{"start": start, "end": len(text)}], human)
    assert result["recall"] == 1 and result["precision"] == pytest.approx(7 / 14)
    assert result["iou"] == result["precision"]
    with pytest.raises(AnalyticsError, match="otra versión"):
        overlap(text + "cambio", [], human)
    for invalid in ([], [{"start": True, "end": 2}], [{"start": -1, "end": 3}],
                    [{"start": 0, "end": 5}, {"start": 4, "end": 6}]):
        with pytest.raises(AnalyticsError):
            validate_spans(text, invalid, 20)
