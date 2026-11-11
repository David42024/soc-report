"""Reference checks and controlled examples for the grouped evaluation."""
from dataclasses import replace

import numpy as np
import pytest
from scipy.stats import binomtest
from sklearn.metrics import (
    accuracy_score, average_precision_score, balanced_accuracy_score, cohen_kappa_score, confusion_matrix, f1_score,
    matthews_corrcoef, precision_recall_fscore_support, roc_auc_score,
)

from src.data.models import SEVERITIES
from src.evaluation.contracts import EvaluationSet, Observation, label_value
from src.evaluation.inference_stats import GroupBootstrap, compare, holm, uncertainty
from src.evaluation.metrics import curves, operations, report_metrics
from src.reports.evaluation_presentation import comparison_tables
from src.training.metrics import REVIEW
from src.utils.errors import DatasetError


def controlled_severity() -> tuple[tuple[Observation, ...], tuple[Observation, ...]]:
    """Construct discordant model outputs for testing formulas only."""
    rng = np.random.default_rng(847)
    models = [[], []]
    for label_index, label in enumerate(SEVERITIES):
        for group in range(8):
            for row in range(2):
                key = f"{label_index}-{group}-{row}"
                cluster = f"{label_index}-{group}"
                for i, buffer in enumerate(models):
                    mistakes = (group + row + label_index) % (4 - i)
                    pred = label if mistakes else SEVERITIES[(label_index + 1) % len(SEVERITIES)]
                    if i == 1 and group == 0 and row == 1:
                        pred = REVIEW
                    values = rng.normal(size=len(SEVERITIES))
                    values[label_index] += 2.8 - i * 1.2
                    buffer.append(Observation(key, cluster, label, pred, dict(zip(SEVERITIES, map(float, values)))))
    return tuple(models[0]), tuple(models[1])


def test_nominal_and_ordinal_metrics_match_sklearn_and_show_critical_errors():
    _, rows = controlled_severity()
    dataset = EvaluationSet((), "severidad", "sintetico", "seal", "data", None, SEVERITIES,
                            {"tipo": {row.key: "phishing" if i % 2 else "malware" for i, row in enumerate(rows)}})
    report = report_metrics(rows, dataset)
    values = report["overall"]
    truth, pred = [row.truth for row in rows], [row.predicted for row in rows]
    full = (*SEVERITIES, REVIEW)
    expected = confusion_matrix(truth, pred, labels=full)[:len(SEVERITIES)]
    np.testing.assert_array_equal(report["matrix"]["counts"], expected)
    np.testing.assert_allclose(np.array(report["matrix"]["normalized"]).sum(axis=1), 1)
    assert values["accuracy"] == pytest.approx(accuracy_score(truth, pred))
    assert values["balanced_accuracy"] == pytest.approx(balanced_accuracy_score(truth, pred))
    assert values["f1_macro"] == pytest.approx(f1_score(truth, pred, labels=SEVERITIES, average="macro"))
    assert values["f1_weighted"] == pytest.approx(f1_score(truth, pred, labels=SEVERITIES, average="weighted"))
    assert values["mcc"] == pytest.approx(matthews_corrcoef(truth, pred))
    assert values["kappa"] == pytest.approx(cohen_kappa_score(truth, pred, labels=full))
    valid = [row for row in rows if row.predicted != REVIEW]
    assert values["kappa_quadratic"] == pytest.approx(cohen_kappa_score(
        [row.truth for row in valid], [row.predicted for row in valid], labels=SEVERITIES, weights="quadratic"))
    assert report["ordinal"]["ordinal_pairs"] == len(valid)
    precision, recall, f1, _ = precision_recall_fscore_support(truth, pred, labels=SEVERITIES, zero_division=0)
    for i, label in enumerate(SEVERITIES):
        item = report["by_class"][i]
        assert item["precision"] == pytest.approx(precision[i])
        assert item["recall"] == pytest.approx(recall[i])
        assert item["f1"] == pytest.approx(f1[i])
        assert item["specificity"] == pytest.approx(item["tn"] / (item["tn"] + item["fp"]))
    assert report["critical"]["lower"] > 0 and report["critical"]["review"] == 1
    assert report["critical"]["fn"] == report["critical"]["lower"] + 1
    assert {row["field"] for row in report["strata"]} == {"tipo"}


def test_asset_normalization_and_curve_score_requirements():
    assert label_value("activo_afectado", "  SERVIDOR\u00a0Web  ") == "servidor web"
    assert label_value("activo_afectado", "servidor-web") != label_value("activo_afectado", "servidor web")
    assert label_value("tipo", "Phishing") == "Phishing"
    rows, _ = controlled_severity()
    assert curves(rows, SEVERITIES, None)["reason"]
    valid = curves(rows, SEVERITIES, "margin")["classes"]["critica"]
    truth = [row.truth == "critica" for row in rows]
    score = [row.scores["critica"] for row in rows]
    assert valid["roc_auc"] == pytest.approx(roc_auc_score(truth, score))
    assert valid["average_precision"] == pytest.approx(average_precision_score(truth, score))
    assert "reason" in curves(rows, SEVERITIES, "probability")["classes"]["critica"]
    assert "reason" in curves(tuple(replace(row, scores={"critica": 1.0}) for row in rows), SEVERITIES, "margin")["classes"]["critica"]


def test_paired_group_bootstrap_signs_and_auc_check_support(settings):
    a, b = controlled_severity()
    policy = settings.evaluation.model_copy(update={"bootstrap_replicates": 150})
    sampled = GroupBootstrap(a, policy, settings.seed)
    assert sampled.stratified and not sampled.reason
    first = next(sampled.draws())
    for index in range(0, len(a), 2):
        assert sum(first == index) == sum(first == index + 1)
    estimates = uncertainty(a, SEVERITIES, "severidad", "margin", policy, settings.seed)
    assert estimates == uncertainty(a, SEVERITIES, "severidad", "margin", policy, settings.seed)
    assert estimates["metrics"]["critical_fnr"]["ci95"] and estimates["metrics"]["critica.roc_auc"]["ci95"]
    paired = compare({"A": (a, "margin"), "B": (b, "margin")}, SEVERITIES, "severidad", policy, settings.seed)[0]
    assert paired["correctness"]["test"] == "Signos exacto por grupo"
    assert paired["correctness"]["p_holm"] is not None
    assert paired["differences"]["f1_macro"]["ci95"]
    assert paired["auc"]["critica"]["p_holm"] is not None
    cohort = EvaluationSet((), "severidad", "sintetico", "seal", "data", None, SEVERITIES)
    models = [{"family": family, "run_id": name, "coverage": report["coverage"], "metrics": report["overall"]}
              for name, family, report in (("A", "tfidf_logreg", report_metrics(a, cohort)),
                                           ("B", "tfidf_svm", report_metrics(b, cohort)))]
    critical, guide = comparison_tables({"models": models, "target": "severidad", "comparisons": [paired],
                                        "policy": policy.model_dump()})[-1]
    assert guide.title == "Diferencias en errores críticos" and len(critical) == 2
    assert critical[1]["Δ (pp)"] == -12.5 and critical[1]["IC 95 % (pp)"] != "No aplicable"
    missing = compare({"A": (a, "margin"), "B": (b, None)}, SEVERITIES, "severidad", policy, settings.seed)[0]
    assert missing["auc"]["critica"]["p"] is None and missing["auc"]["critica"]["reason"]
    with pytest.raises(DatasetError, match="mismos registros"):
        compare({"A": (a, "margin"), "B": (b[::-1], "margin")}, SEVERITIES, "severidad", policy, settings.seed)


def test_exact_mcnemar_and_holm_with_small_sample_gates(settings):
    a, b = (tuple(replace(row, group=row.key) for row in model) for model in controlled_severity())
    policy = settings.evaluation.model_copy(update={"bootstrap_replicates": 100})
    result = compare({"A": (a, None), "B": (b, None)}, SEVERITIES, "severidad", policy, settings.seed)[0]
    stats = result["correctness"]
    discordant = stats["left_only_correct"] + stats["right_only_correct"]
    assert stats["test"] == "McNemar exacto"
    assert stats["p"] == pytest.approx(binomtest(stats["left_only_correct"], discordant, .5).pvalue)
    assert stats["p_holm"] == stats["p"]
    assert holm([.04, .01, .03]) == pytest.approx([.06, .03, .06])
    tiny = compare({"A": (a[:8], None), "B": (b[:8], None)}, SEVERITIES, "severidad", policy, settings.seed)[0]
    assert tiny["correctness"]["p"] is None and tiny["bootstrap_reason"]


def test_operational_provenance_latency_and_billing_are_separate():
    rows = (
        Observation("a", "1", "phishing", REVIEW, provider="groq", model="groq-configured",
                    review_reason="confianza_baja", flow_seconds=2, provider_seconds=.7, input_tokens=20, output_tokens=10),
        Observation("b", "2", "malware", "malware", provider="gemini", model="gemini-configured",
                    flow_seconds=4, input_tokens=11, output_tokens=5, cost_usd=.01),
        Observation("c", "3", "malware", REVIEW, flow_seconds=6, technical_failure=True, review_reason="langflow_no_disponible"),
        Observation("d", "4", "malware", "malware", flow_seconds=4),
    )
    result = operations(rows)
    assert result["gemini_observed"] == result["technical_failures"] == 1
    assert result["flow_latency"] == {"n": 4, "p50_s": 4, "p95_s": pytest.approx(5.7)}
    assert result["responses_without_provider"] == 1
    assert result["provider_latency"]["groq"]["p50_s"] == .7
    assert result["review"]["confianza_baja"] == 1
    assert result["usage_observed"] == 2 and result["cost_usd"] is None
