"""Group-resampled uncertainty and prespecified paired comparisons."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from itertools import combinations
from typing import Any

import numpy as np
from scipy.stats import binomtest, rankdata

from src.data.models import LabelField
from src.evaluation.contracts import Observation, ScoreKind
from src.evaluation.metrics import continuous_scores, encode, summarize
from src.evaluation.settings import EvaluationSettings
from src.utils.errors import DatasetError


class GroupBootstrap:
    """Resample full independent groups, with stratification when homogeneous."""

    def __init__(self, rows: tuple[Observation, ...], settings: EvaluationSettings, seed: int) -> None:
        index = defaultdict(list)
        groups_by_label = defaultdict(set)
        for i, row in enumerate(rows):
            index[row.group].append(i)
            groups_by_label[row.truth].add(row.group)
        strata = defaultdict(list)
        truth = np.array([row.truth for row in rows])
        for group, indices in sorted(index.items()):
            labels = set(truth[indices])
            strata[next(iter(labels)) if len(labels) == 1 else None].append(np.array(indices, dtype=np.intp))
        self.stratified = None not in strata
        self.strata = tuple(strata.values()) if self.stratified else (sum(strata.values(), []),)
        self.truth = truth
        self.groups = len(index)
        self.groups_by_label = {label: len(support) for label, support in groups_by_label.items()}
        self.policy, self.seed = settings, seed

    @property
    def reason(self) -> str | None:
        if self.groups < self.policy.min_ci_groups:
            return f"Se observaron {self.groups} grupos. El protocolo requiere {self.policy.min_ci_groups} para intervalos."
        if min(self.groups_by_label.values(), default=0) < self.policy.min_ci_groups_per_class:
            return f"Se requieren {self.policy.min_ci_groups_per_class} grupos por clase para intervalos."
        return None

    def draws(self) -> Iterator[np.ndarray]:
        rng = np.random.default_rng(self.seed)
        for _ in range(self.policy.bootstrap_replicates):
            yield np.concatenate([stratum[i] for stratum in self.strata
                                  for i in rng.integers(len(stratum), size=len(stratum))])

    def interval(self, values: list[float]) -> dict:
        required = self.policy.bootstrap_min_fraction * self.policy.bootstrap_replicates
        if len(values) < required:
            return {"ci95": None, "valid": len(values), "reason": "Demasiadas réplicas perdieron soporte o produjeron una métrica indefinida."}
        if min(values) == max(values):
            return {"ci95": None, "valid": len(values), "reason": "Las réplicas no muestran variación para estimar incertidumbre."}
        return {"ci95": np.quantile(values, [self.policy.alpha / 2, 1 - self.policy.alpha / 2]).tolist(),
                "valid": len(values), "reason": None}


def _flatten(summary: dict) -> dict[str, float | None]:
    return {**summary["overall"], **{f"{item['label']}.{metric}": item[metric] for item in summary["by_class"]
                                   for metric in ("precision", "recall", "specificity", "f1", "fnr")}}


def _rank_auc(truth: np.ndarray, score: np.ndarray) -> float | None:
    positives = int(truth.sum())
    negatives = len(truth) - positives
    if not positives or not negatives:
        return None
    ranks = rankdata(score)
    return float((ranks[truth].sum() - positives * (positives + 1) / 2) / (positives * negatives))


def uncertainty(rows: tuple[Observation, ...], classes: tuple[str, ...], target: LabelField,
                kind: ScoreKind | None, settings: EvaluationSettings, seed: int) -> dict:
    bootstrap = GroupBootstrap(rows, settings, seed)
    result = {"groups": bootstrap.groups, "groups_by_class": bootstrap.groups_by_label,
              "replicates": settings.bootstrap_replicates, "stratified": bootstrap.stratified,
              "reason": bootstrap.reason, "metrics": {}}
    if bootstrap.reason:
        return result
    encoded = encode(rows, classes, target)
    continuous = {label: scores for label in classes if (scores := continuous_scores(rows, label, kind)) is not None}
    samples = defaultdict(list)
    for draw in bootstrap.draws():
        matrix = encoded.matrix(draw)
        if not np.all(matrix[:len(classes)].sum(axis=1)):
            continue
        values = _flatten(summarize(matrix, classes, encoded.columns, target))
        for label, scores in continuous.items():
            values[f"{label}.roc_auc"] = _rank_auc(bootstrap.truth[draw] == label, scores[draw])
        for metric, value in values.items():
            if value is not None:
                samples[metric].append(value)
    result["metrics"] = {name: bootstrap.interval(values) for name, values in samples.items()}
    return result


def holm(values: list[float]) -> list[float]:
    """Step-down familywise adjusted p-values in original order."""
    adjusted = [0.0] * len(values)
    largest = 0.0
    for index, item in enumerate(sorted(enumerate(values), key=lambda pair: pair[1])):
        pos, value = item
        largest = min(1.0, max(largest, (len(values) - index) * value))
        adjusted[pos] = largest
    return adjusted


def _correctness_test(left: tuple[Observation, ...], right: tuple[Observation, ...],
                      policy: EvaluationSettings) -> dict:
    b = sum(a.correct and not other.correct for a, other in zip(left, right))
    c = sum(other.correct and not a.correct for a, other in zip(left, right))
    grouped = defaultdict(int)
    for a, other in zip(left, right):
        grouped[a.group] += int(a.correct) - int(other.correct)
    iid = len(grouped) == len(left)
    win, loss = (b, c) if iid else (sum(x > 0 for x in grouped.values()), sum(x < 0 for x in grouped.values()))
    effect = (b - c) / len(left)
    result = {"test": "McNemar exacto" if iid else "Signos exacto por grupo",
              "groups": len(grouped), "left_only_correct": b, "right_only_correct": c,
              "positive_units": win, "negative_units": loss,
              "accuracy_delta": effect, "practical_magnitude": abs(effect) >= policy.practical_accuracy_delta,
              "discordant_odds_ratio": b / c if iid and c else None,
              "p": None, "reason": None}
    if len(grouped) < policy.min_test_groups:
        result["reason"] = f"El contraste requiere {policy.min_test_groups} grupos independientes."
    elif win + loss < policy.min_discordant:
        result["reason"] = f"El contraste requiere {policy.min_discordant} unidades discordantes o con diferencia."
    else:
        result["p"] = float(binomtest(win, win + loss, .5).pvalue)
    return result


def _paired(left: tuple[Observation, ...], right: tuple[Observation, ...], classes: tuple[str, ...], target: LabelField,
            kinds: tuple[ScoreKind | None, ScoreKind | None], policy: EvaluationSettings, seed: int) -> dict:
    if [(row.key, row.group, row.truth) for row in left] != [(row.key, row.group, row.truth) for row in right]:
        raise DatasetError("Las predicciones no corresponden a los mismos registros y referencias.")
    bootstrap = GroupBootstrap(left, policy, seed)
    test = _correctness_test(left, right, policy)
    enc_a, enc_b = encode(left, classes, target), encode(right, classes, target)
    score_a = summarize(enc_a.matrix(), classes, enc_a.columns, target)["overall"]
    score_b = summarize(enc_b.matrix(), classes, enc_b.columns, target)["overall"]
    metrics = {name: {"delta": score_a[name] - score_b[name], "ci95": None}
               for name in score_a if score_a[name] is not None and score_b[name] is not None}
    auc_inputs, auc = {}, {}
    for label in classes:
        a = continuous_scores(left, label, kinds[0])
        b = continuous_scores(right, label, kinds[1])
        truth = bootstrap.truth == label
        if a is None or b is None or not truth.any() or truth.all():
            auc[label] = {"delta": None, "ci95": None, "p": None,
                          "reason": "Se requieren scores válidos de ambos modelos para todos los casos."}
            continue
        delta = _rank_auc(truth, a) - _rank_auc(truth, b)
        auc_inputs[label] = truth, a, b
        auc[label] = {"delta": delta, "ci95": None, "p": None, "reason": bootstrap.reason}
    if bootstrap.reason:
        return {"correctness": test, "differences": metrics, "auc": auc, "bootstrap_reason": bootstrap.reason}
    samples, auc_samples = defaultdict(list), defaultdict(list)
    for draw in bootstrap.draws():
        left_matrix, right_matrix = enc_a.matrix(draw), enc_b.matrix(draw)
        if not np.all(left_matrix[:len(classes)].sum(axis=1)):
            continue
        vals_a = summarize(left_matrix, classes, enc_a.columns, target)["overall"]
        vals_b = summarize(right_matrix, classes, enc_b.columns, target)["overall"]
        for metric in metrics:
            if vals_a[metric] is not None and vals_b[metric] is not None:
                samples[metric].append(vals_a[metric] - vals_b[metric])
        for label, (truth, a, b) in auc_inputs.items():
            auc_samples[label].append(_rank_auc(truth[draw], a[draw]) - _rank_auc(truth[draw], b[draw]))
    for metric, result in metrics.items():
        result.update(bootstrap.interval(samples[metric]))
    for label in auc_inputs:
        result = auc[label]
        samples_for_label = auc_samples[label]
        result.update(bootstrap.interval(samples_for_label))
        if result["ci95"] is not None and bootstrap.groups >= policy.min_test_groups:
            center = result["delta"]
            # Center the paired bootstrap around the null. This is an approximate contrast.
            result["p"] = (1 + sum(abs(value - center) >= abs(center) for value in samples_for_label)) / (1 + len(samples_for_label))
        elif not result["reason"]:
            result["reason"] = f"El contraste de AUC requiere {policy.min_test_groups} grupos."
    return {"correctness": test, "differences": metrics, "auc": auc, "bootstrap_reason": None}


def compare(models: dict[str, tuple[tuple[Observation, ...], ScoreKind | None]], classes: tuple[str, ...],
            target: LabelField, policy: EvaluationSettings, seed: int) -> list[dict[str, Any]]:
    """Apply Holm jointly to eligible contrasts for the same target and sealed cohort."""
    comparisons, tested = [], []
    for left, right in combinations(sorted(models), 2):
        a, kind_a = models[left]
        b, kind_b = models[right]
        entry = {"left": left, "right": right, **_paired(a, b, classes, target, (kind_a, kind_b), policy, seed)}
        comparisons.append(entry)
        for measure in (entry["correctness"], *entry["auc"].values()):
            measure.update(p_holm=None, significant=None)
            if measure["p"] is not None:
                tested.append(measure)
    for measure, adjusted in zip(tested, holm([item["p"] for item in tested])):
        measure.update(p_holm=adjusted, significant=adjusted <= policy.alpha)
    return comparisons
