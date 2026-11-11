"""Point estimates and curves computed from paired sealed-set observations."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import sqrt

import numpy as np
from sklearn.metrics import auc, average_precision_score, precision_recall_curve, roc_curve

from src.data.models import LabelField, SEVERITIES
from src.evaluation.contracts import EvaluationSet, Observation, ScoreKind
from src.training.metrics import REVIEW
from src.utils.errors import DatasetError


def ratio(numerator: int | float, denominator: int | float) -> float | None:
    return float(numerator / denominator) if denominator else None


@dataclass(frozen=True)
class Encoded:
    classes: tuple[str, ...]
    columns: tuple[str, ...]
    cells: np.ndarray
    groups: tuple[str, ...]
    target: LabelField

    def matrix(self, indices: np.ndarray | None = None) -> np.ndarray:
        size = len(self.columns)
        cells = self.cells if indices is None else self.cells[indices]
        return np.bincount(cells, minlength=size * size).reshape(size, size)


def encode(rows: tuple[Observation, ...], classes: tuple[str, ...], target: LabelField) -> Encoded:
    if not rows or len(set(classes)) != len(classes) or not {row.truth for row in rows} <= set(classes):
        raise DatasetError("Las observaciones y la taxonomía del objetivo difieren.")
    columns = (*classes, *sorted({row.predicted for row in rows} - set(classes)))
    code = {label: index for index, label in enumerate(columns)}
    cells = np.array([code[row.truth] * len(columns) + code[row.predicted] for row in rows], dtype=np.intp)
    return Encoded(classes, columns, cells, tuple(row.group for row in rows), target)


def _quadratic_kappa(matrix: np.ndarray, columns: tuple[str, ...]) -> dict:
    indices = [columns.index(label) for label in SEVERITIES if label in columns]
    positions = np.array([SEVERITIES.index(columns[i]) for i in indices])
    table = matrix[np.ix_(indices, indices)]
    n = int(table.sum())
    result = {"score": None, "ordinal_pairs": n, "coverage": ratio(n, int(matrix.sum()))}
    if n:
        weights = (positions[:, None] - positions[None, :]) ** 2
        expected = (weights * np.outer(table.sum(axis=1), table.sum(axis=0))).sum() / n
        if expected > 0:
            result["score"] = float(1 - (weights * table).sum() / expected)
    return result


def summarize(matrix: np.ndarray, classes: tuple[str, ...], columns: tuple[str, ...], target: LabelField) -> dict:
    """Use the same count denominators for point and bootstrap estimates."""
    n = int(matrix.sum())
    if not n:
        raise DatasetError("La medición requiere observaciones.")
    support, predicted = matrix.sum(axis=1), matrix.sum(axis=0)
    diagonal = matrix.diagonal()
    by_class = []
    for i, label in enumerate(classes):
        tp = int(diagonal[i])
        fp, fn = int(predicted[i]) - tp, int(support[i]) - tp
        tn = n - tp - fp - fn
        by_class.append({"label": label, "support": int(support[i]), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                         "precision": ratio(tp, tp + fp) if tp + fp else 0.0,
                         "recall": ratio(tp, tp + fn), "specificity": ratio(tn, tn + fp),
                         "f1": ratio(2 * tp, 2 * tp + fp + fn) or 0.0, "fnr": ratio(fn, tp + fn)})
    seen = [item for item in by_class if item["support"]]
    correct = int(diagonal.sum())
    expected = float(support @ predicted)
    left, right = float(n * n - support @ support), float(n * n - predicted @ predicted)
    metrics = {"accuracy": correct / n, "balanced_accuracy": float(np.mean([item["recall"] for item in seen])),
               "precision_macro": float(np.mean([item["precision"] for item in seen])),
               "recall_macro": float(np.mean([item["recall"] for item in seen])),
               "specificity_macro": (float(np.mean([item["specificity"] for item in seen]))
                                     if len(seen) >= 2 else None),
               "f1_macro": float(np.mean([item["f1"] for item in seen])),
               "f1_weighted": sum(item["support"] * item["f1"] for item in seen) / n,
               "mcc": (n * correct - expected) / sqrt(left * right) if left and right else 0.0,
               "kappa": ratio(n * correct - expected, n * n - expected)}
    ordinal = critical = None
    if target == "severidad":
        ordinal = _quadratic_kappa(matrix, columns)
        metrics["kappa_quadratic"] = ordinal["score"]
        if "critica" in classes:
            row = matrix[classes.index("critica")]
            support_critical = int(row.sum())
            lower = sum(int(row[i]) for i, label in enumerate(columns) if label in SEVERITIES[1:])
            referrals = int(row[columns.index(REVIEW)]) if REVIEW in columns else 0
            misses = support_critical - int(row[classes.index("critica")])
            critical = {"support": support_critical, "lower": lower, "review": referrals, "fn": misses,
                        "lower_rate": ratio(lower, support_critical), "fnr": ratio(misses, support_critical)}
            metrics.update(critical_lower_rate=critical["lower_rate"], critical_fnr=critical["fnr"])
    return {"rows": n, "overall": metrics, "by_class": by_class, "ordinal": ordinal, "critical": critical}


def report_metrics(rows: tuple[Observation, ...], dataset: EvaluationSet) -> dict:
    encoded = encode(rows, dataset.classes, dataset.target)
    matrix = encoded.matrix()
    reference = matrix[:len(encoded.classes)]
    normalized = np.divide(reference, reference.sum(axis=1, keepdims=True),
                           out=np.zeros_like(reference, dtype=float), where=reference.sum(axis=1, keepdims=True) > 0)
    report = summarize(matrix, encoded.classes, encoded.columns, dataset.target)
    report["matrix"] = {"reference": list(encoded.classes), "prediction": list(encoded.columns),
                        "counts": reference.tolist(), "normalized": normalized.tolist()}
    report["coverage"] = sum(not row.review for row in rows) / len(rows)
    strata = []
    for field, labels in dataset.strata.items():
        if field == dataset.target:
            continue
        blocks = defaultdict(list)
        for row in rows:
            if row.key in labels:
                blocks[labels[row.key]].append(row)
        for category, block in sorted(blocks.items()):
            subset = encode(tuple(block), dataset.classes, dataset.target)
            sub = summarize(subset.matrix(), subset.classes, subset.columns, dataset.target)
            observed = sum(item["support"] > 0 for item in sub["by_class"])
            strata.append({"field": field, "label": category, "n": len(block), "classes": observed,
                           "accuracy": sub["overall"]["accuracy"],
                           "f1_macro": sub["overall"]["f1_macro"] if observed >= 2 else None})
    report["strata"] = strata
    return report


def continuous_scores(rows: tuple[Observation, ...], label: str, kind: ScoreKind | None) -> np.ndarray | None:
    """Return complete class scores only from a declared continuous output."""
    if kind not in ("probability", "margin") or not all(row.scores is not None and label in row.scores for row in rows):
        return None
    values = np.array([row.scores[label] for row in rows], dtype=float)
    if not np.isfinite(values).all() or len(np.unique(values)) < 2 or (
        kind == "probability" and (np.any(values < 0) or np.any(values > 1))
    ):
        return None
    return values


def curves(rows: tuple[Observation, ...], classes: tuple[str, ...], kind: ScoreKind | None) -> dict:
    """Store ROC, trapezoidal PR-AUC and AP for each valid one-vs-rest class."""
    if kind is None:
        return {"kind": None, "reason": "La salida carece de un score continuo para cada clase. El puntaje operacional corresponde solo a la etiqueta elegida.", "classes": {}}
    result = {}
    for label in classes:
        truth = np.array([row.truth == label for row in rows], dtype=bool)
        scores = continuous_scores(rows, label, kind)
        if not truth.any() or truth.all() or scores is None:
            result[label] = {"reason": "Se requieren positivos, negativos y scores finitos y variables para todos los casos."}
            continue
        fpr, tpr, _ = roc_curve(truth, scores)
        precision, recall, _ = precision_recall_curve(truth, scores)
        result[label] = {"roc_auc": float(auc(fpr, tpr)), "pr_auc": float(auc(recall, precision)),
                         "average_precision": float(average_precision_score(truth, scores)),
                         "prevalence": float(truth.mean()), "positive": int(truth.sum()), "negative": int((~truth).sum()),
                         "fpr": fpr.tolist(), "tpr": tpr.tolist(), "precision": precision.tolist(), "recall": recall.tolist()}
    return {"kind": kind, "reason": None, "classes": result}


def operations(rows: tuple[Observation, ...], quote: dict | None = None) -> dict:
    """Separate observed response provenance, referrals and consumption."""
    def latency(values: list[float]) -> dict:
        return {"n": len(values), "p50_s": float(np.quantile(values, .50)) if values else None,
                "p95_s": float(np.quantile(values, .95)) if values else None}

    sent = [row for row in rows if row.flow_seconds is not None]
    usage = [row for row in sent if row.input_tokens is not None and row.output_tokens is not None]
    billed = [row for row in sent if row.cost_usd is not None]
    known = Counter((row.provider, row.model) for row in rows if row.provider)
    return {
        "requests": len(sent), "responses": [{"provider": name, "model": model, "n": count}
                                             for (name, model), count in sorted(known.items(), key=lambda item: (item[0][0], item[0][1] or ""))],
        "gemini_observed": sum(row.provider == "gemini" for row in rows),
        "technical_failures": sum(row.technical_failure for row in rows),
        "responses_without_provider": sum(row.provider is None and not row.technical_failure for row in sent),
        "review": dict(Counter(row.review_reason for row in rows if row.review_reason)),
        "format_errors": sum(row.format_error for row in rows), "taxonomy_errors": sum(row.taxonomy_error for row in rows),
        "flow_latency": latency([row.flow_seconds for row in sent]),
        "flow_latency_by_responder": {name: latency([row.flow_seconds for row in sent if row.provider == name])
                                      for name in ("groq", "gemini")},
        "provider_latency": {name: latency([row.provider_seconds for row in rows if row.provider == name and row.provider_seconds is not None])
                             for name in ("groq", "gemini")},
        "usage_observed": len(usage), "input_tokens_observed": sum(row.input_tokens for row in usage) if usage else None,
        "output_tokens_observed": sum(row.output_tokens for row in usage) if usage else None,
        "billed_observed": len(billed), "cost_usd": sum(row.cost_usd for row in billed) if billed and len(billed) == len(sent) else None,
        "budget": quote,
    }
