"""Selection and descriptive uncertainty for five external folds."""
from __future__ import annotations

from collections.abc import Sequence
from math import sqrt
from statistics import mean, stdev

from scipy.stats import t
from sklearn.metrics import f1_score

REVIEW = "__revision__"


def macro_f1(truth: Sequence[str], predicted: Sequence[str], labels: tuple[str, ...]) -> float:
    """Use the full class list and count referrals as missed classifications."""
    return float(f1_score(truth, predicted, labels=list(labels), average="macro", zero_division=0))


def objective_metrics(truth: Sequence[str], predicted: Sequence[str], labels: tuple[str, ...], target: str) -> dict:
    """Reuse Phase 3 count metrics on inner/outer validation without opening sealed Test."""
    import numpy as np
    from src.evaluation.metrics import summarize

    columns = (*labels, *sorted(set(predicted) - set(labels)))
    codes = {label: index for index, label in enumerate(columns)}
    matrix = np.zeros((len(columns), len(columns)), dtype=np.int64)
    for actual, inferred in zip(truth, predicted, strict=True):
        matrix[codes[actual], codes[inferred]] += 1
    report = summarize(matrix, labels, columns, target)
    critical = next((item for item in report["by_class"] if item["label"] == "critica"), None) if target == "severidad" else None
    coverage = sum(value in labels for value in predicted) / len(predicted)
    values = {**report["overall"], "critical_recall": critical["recall"] if critical else None,
              "review_rate": 1 - coverage, "coverage": coverage}
    if coverage != 1:
        # Conditional kappa over accepted rows is not a comparable search objective.
        values["kappa_quadratic"] = None
    return values


def outer_summary(rows: list[dict]) -> dict:
    """Report an approximate corrected t interval for overlapping train sets."""
    scores = [row["outer_score"] for row in rows]
    n = len(scores)
    center, deviation = mean(scores), stdev(scores)
    ratio = mean(row["outer"]["validation"]["rows"] / row["outer"]["train"]["rows"] for row in rows)
    radius = float(t.ppf(.975, n - 1)) * deviation * sqrt(1 / n + ratio)
    return {"folds": n, "mean": center, "sample_sd": deviation, "ci95": [max(0.0, center - radius), min(1.0, center + radius)],
            "validation_train_ratio": ratio, "method": "intervalo t aproximado con corrección por solapamiento"}
