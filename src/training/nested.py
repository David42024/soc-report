"""Run the fixed 5×3 protocol using a model-family or inference adapter."""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from pathlib import Path
from statistics import mean
from time import monotonic, thread_time
from typing import Protocol

import optuna

from src.data.models import content_hash
from src.training.metrics import outer_summary
from src.training.partition import Case, Fold, Partition, Split, split_identity
from src.training.settings import TrainingSettings
from src.utils.errors import AnalyticsError, DatasetError
from src.optimization.contracts import SearchOptions


class CancelledRun(AnalyticsError):
    """Cooperative cancellation at an execution boundary."""


class InvalidTrial(Exception):
    """Parameters could not fit on an inner training subset."""


class Search(Protocol):
    name: str

    def sampler(self, fold: int) -> optuna.samplers.BaseSampler: ...
    def suggest(self, trial: optuna.Trial) -> dict: ...
    def evaluate(self, train: tuple[Case, ...], validation: tuple[Case, ...], parameters: dict,
                 scope: str, check_cancel: Callable[[], None]) -> dict: ...
    def publish(self, train: tuple[Case, ...], parameters: dict, directory: Path) -> dict: ...


def _take(cases: tuple[Case, ...], indices: tuple[int, ...]) -> tuple[Case, ...]:
    return tuple(cases[index] for index in indices)


def _evidence(cases: tuple[Case, ...], split: Split, allowed: set[int]) -> dict:
    train, val = set(split.train), set(split.validation)
    if len(train) != len(split.train) or len(val) != len(split.validation) or train & val or train | val != allowed:
        raise DatasetError("Un fold usa registros fuera de su partición permitida.")
    left, right = _take(cases, split.train), _take(cases, split.validation)
    labels = {cases[index].label for index in allowed}
    if {case.label for case in left} != labels or {case.label for case in right} != labels:
        raise DatasetError("Un fold carece de una de las clases requeridas.")
    if {case.group for case in left} & {case.group for case in right}:
        raise DatasetError("Un fold comparte grupos de entrenamiento y validación.")
    return {"train": split_identity(left), "validation": split_identity(right), "groups_disjoint": True}


def fold_evidence(cases: tuple[Case, ...], folds: tuple[Fold, ...], policy: TrainingSettings) -> list[dict]:
    """Require complete outer and inner coverage before running a single trial."""
    if len(folds) != policy.outer_folds:
        raise DatasetError("La validación requiere cinco folds externos.")
    allowed = set(range(len(cases)))
    seen = Counter()
    evidence = []
    for fold in folds:
        outer = _evidence(cases, fold.outer, allowed)
        seen.update(fold.outer.validation)
        inner_allowed = set(fold.outer.train)
        if len(fold.inner) != policy.inner_folds or Counter(i for split in fold.inner for i in split.validation) != dict.fromkeys(inner_allowed, 1):
            raise DatasetError("La validación interna debe cubrir outer_train exactamente una vez en tres folds.")
        evidence.append({"outer": outer, "inner": [_evidence(cases, split, inner_allowed) for split in fold.inner]})
    if seen != dict.fromkeys(allowed, 1):
        raise DatasetError("La validación externa debe cubrir Desarrollo exactamente una vez.")
    return evidence


def maximum_flow_calls(partition: Partition, folds: tuple[Fold, ...], trials: int) -> int:
    """Upper bound before any cache hits or protected reviews."""
    return (sum(len(fold.outer.train) * trials + len(fold.outer.validation) for fold in folds)
            + len(folds) * len(partition.validation))


def run_nested(partition: Partition, folds: tuple[Fold, ...], policy: TrainingSettings, search: Search,
               trial_limit: int, directory: Path, checkpoint: dict, save: Callable[[dict], None],
               event: Callable[..., None], check_cancel: Callable[[], None], *,
               optimization: SearchOptions | None = None, seed: int = 0,
               remaining: Callable[[], float] | None = None) -> dict:
    """Evaluate each external fold once and use the independent 15% for selection."""
    cases = partition.development
    evidence = fold_evidence(cases, folds, policy)
    records = checkpoint.setdefault("families", {}).setdefault(search.name, {"folds": []})
    if "validation_selection" in records:
        return records
    if records.get("pending_outer") is not None:
        raise AnalyticsError("El último fold externo se interrumpió durante su medición. Crea una ejecución nueva para preservar la regla de una evaluación.")

    for i, fold in enumerate(folds, start=1):
        if i <= len(records["folds"]):
            continue
        check_cancel()
        started = monotonic()
        event("inicio_fold", model=search.name, fold=i)
        if optimization:
            from src.optimization.studies import open_study, recover_interrupted
            study = open_study(directory, f"{search.name}-outer-{i}", optimization, seed, i,
                {"partition": content_hash(partition.evidence()), "fold": evidence[i - 1],
                 "family": search.name, "search": optimization.model_dump(mode="json"), "seed": seed})
            recovered = recover_interrupted(study)
            event("estudio_recuperado", model=search.name, fold=i, trials=len(study.trials), interrupted=recovered)
        else:
            study = optuna.create_study(direction="maximize", sampler=search.sampler(i))

        def objective(trial: optuna.Trial) -> float:
            wall_started, cpu_started = monotonic(), thread_time()
            try:
                parameters = search.suggest(trial)
                trial.set_user_attr("configuration", parameters)
                scores = []
                event("inicio_trial", model=search.name, fold=i, trial=trial.number + 1, parameters=trial.params)
                for j, split in enumerate(fold.inner, start=1):
                    check_cancel()
                    try:
                        result = search.evaluate(_take(cases, split.train), _take(cases, split.validation),
                                                 parameters, f"inner-{i}", check_cancel)
                    except ValueError:
                        event("trial_invalido", model=search.name, fold=i, trial=trial.number + 1, inner=j)
                        raise InvalidTrial("Parámetros o métrica incompatibles con este subconjunto de entrenamiento.") from None
                    scores.append(result)
                    trial.set_user_attr("inner_metrics", scores)
                    measured = mean(row.get("objective", row["score"]) for row in scores)
                    event("inner_medido", model=search.name, fold=i, trial=trial.number + 1, inner=j,
                          score=result["score"], objective=measured, seconds=result["seconds"])
                    if optimization:
                        trial.report(measured, step=j - 1)
                        if trial.should_prune():
                            event("trial_podado", model=search.name, fold=i, trial=trial.number + 1, inner=j)
                            raise optuna.TrialPruned()
                return measured
            finally:
                if optimization:
                    trial.set_user_attr("elapsed_seconds", max(0.0, monotonic() - wall_started))
                    trial.set_user_attr("cpu_thread_seconds", max(0.0, thread_time() - cpu_started))

        def completed_trial(study, trial) -> None:
            event("fin_trial", model=search.name, fold=i, trial=trial.number + 1, state=trial.state.name,
                  objective=trial.value, best_provisional=study.best_value if any(t.state == optuna.trial.TrialState.COMPLETE for t in study.trials) else None)

        trials_left = max(0, trial_limit - len(study.trials)) if optimization else trial_limit
        study.optimize(objective, n_trials=trials_left, catch=(InvalidTrial,), show_progress_bar=False,
                       n_jobs=optimization.parallel_trials if optimization else 1,
                       timeout=max(.001, remaining()) if remaining else None,
                       callbacks=[completed_trial] if optimization else None)
        try:
            best = study.best_trial
        except ValueError:
            raise AnalyticsError(f"El fold externo {i} carece de trials internos válidos. Revisa min_df, max_df y los tamaños.") from None
        check_cancel()
        parameters = best.user_attrs["configuration"]
        records["pending_outer"] = i
        save(checkpoint)
        outer = search.evaluate(_take(cases, fold.outer.train), _take(cases, fold.outer.validation),
                                parameters, f"outer-{i}", check_cancel)
        completed = {
            "fold": i, **evidence[i - 1], "outer_evaluations": 1, "outer_score": outer["score"],
            "outer_metrics": outer, "seconds": monotonic() - started, "winner": parameters,
            "best_inner_score": mean(row["score"] for row in best.user_attrs["inner_metrics"]), "winner_trial": best.number + 1,
            "trials": [{"number": trial.number + 1, "state": trial.state.name, "score": trial.value,
                        "configuration": trial.user_attrs.get("configuration"),
                        "inner_metrics": trial.user_attrs.get("inner_metrics", [])} for trial in study.trials],
        }
        if optimization:
            from src.optimization.studies import trial_rows
            completed.update(study_name=study.study_name, best_inner_objective=best.value,
                             outer_objective=outer["objective"],
                             trials=[{**row, "objective": row["score"],
                                      "score": mean(item["score"] for item in row["inner_metrics"]) if row["inner_metrics"] else None}
                                     for row in trial_rows(study)])
        records["folds"].append(completed)
        records.pop("pending_outer")
        save(checkpoint)
        event("outer_medido", model=search.name, fold=i, score=outer["score"], seconds=outer["seconds"])

    selected = {content_hash(row["winner"]): row["winner"] for row in records["folds"]}
    compared = []
    for key, parameters in sorted(selected.items()):
        check_cancel()
        measure = search.evaluate(cases, partition.validation, parameters, "selection", check_cancel)
        compared.append({"sha256": key, "configuration": parameters, **measure})
        event("validacion_medida", model=search.name, score=measure["score"], seconds=measure["seconds"])
    winner = min(compared, key=lambda row: ((row["objective"] if optimization.direction == "minimize" else -row["objective"])
                                          if optimization else -row["score"], row["sha256"]))
    check_cancel()
    artifact = search.publish(cases, winner["configuration"], directory)
    records.update(summary=outer_summary(records["folds"]),
                   validation_selection={"winner": winner, "candidates": compared, "rows": len(partition.validation)},
                   artifact=artifact)
    if optimization:
        records["optimization"] = {"options": optimization.model_dump(mode="json"), "storage": "optuna.journal",
                                   "studies": [row["study_name"] for row in records["folds"]],
                                   "selection_uses": "Validación independiente de Desarrollo; Prueba no se consulta"}
    save(checkpoint)
    return records
