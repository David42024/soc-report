"""Exploratory diagnostics over completed inner-CV trials, never outer/Test selection."""
from __future__ import annotations

from math import isfinite

import optuna
from optuna.importance import FanovaImportanceEvaluator, get_param_importances
from optuna.trial import TrialState


def importance(study: optuna.Study, policy, seed: int) -> dict:
    """Gate fANOVA on completed observations and actual objective variability."""
    trials = study.get_trials(deepcopy=False, states=(TrialState.COMPLETE,))
    if len(trials) < policy.importance_min_trials:
        return {"values": {}, "reason": f"Se requieren al menos {policy.importance_min_trials} trials completos de este fold."}
    if len({trial.value for trial in trials}) < 2:
        return {"values": {}, "reason": "El objetivo es constante; no permite estimar una importancia informativa."}
    try:
        values = get_param_importances(study, evaluator=FanovaImportanceEvaluator(n_trees=policy.importance_trees, seed=seed))
        if not values or any(not isfinite(value) for value in values.values()):
            raise ValueError
        return {"values": values, "reason": None,
                "method": "fANOVA sobre bosque aleatorio de trials internos completos", "n": len(trials)}
    except (ValueError, RuntimeError, ZeroDivisionError):
        return {"values": {}, "reason": "La variación y geometría observadas no permiten una estimación estable."}
