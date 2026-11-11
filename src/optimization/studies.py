"""Persistent Optuna studies used by the existing Phase 2 nested runner."""
from __future__ import annotations

from math import isfinite
from pathlib import Path

import optuna
from optuna.storages import JournalStorage
from optuna.storages.journal import JournalFileBackend, JournalFileOpenLock
from optuna.trial import TrialState

from src.data.models import content_hash
from src.utils.errors import AnalyticsError
from .contracts import SearchOptions


class TrialSeededSampler(optuna.samplers.BaseSampler):
    """Seed each trial from its immutable number so sequential recovery needs no pickle."""

    def __init__(self, options: SearchOptions, seed: int, fold: int) -> None:
        self.options, self.seed, self.fold = options, seed, fold
        self.delegates: dict[int, optuna.samplers.BaseSampler] = {}

    def _get(self, trial):
        if trial.number not in self.delegates:
            seed = int(content_hash([self.seed, self.fold, trial.number])[:8], 16)
            self.delegates[trial.number] = (optuna.samplers.TPESampler(seed=seed, n_startup_trials=self.options.startup_trials)
                if self.options.sampler == "tpe" else optuna.samplers.RandomSampler(seed=seed))
        return self.delegates[trial.number]

    def infer_relative_search_space(self, study, trial):
        return self._get(trial).infer_relative_search_space(study, trial)

    def sample_relative(self, study, trial, search_space):
        return self._get(trial).sample_relative(study, trial, search_space)

    def sample_independent(self, study, trial, param_name, param_distribution):
        return self._get(trial).sample_independent(study, trial, param_name, param_distribution)

    def before_trial(self, study, trial) -> None:
        self._get(trial).before_trial(study, trial)

    def after_trial(self, study, trial, state, values) -> None:
        self._get(trial).after_trial(study, trial, state, values)
        self.delegates.pop(trial.number, None)


def sampler(options: SearchOptions, seed: int, fold: int) -> optuna.samplers.BaseSampler:
    """Use finite Grid or trial-indexed TPE/Random through public Optuna APIs."""
    if options.sampler == "grid":
        return optuna.samplers.GridSampler({name: list(value.choices) for name, value in options.space.items()}, seed=(seed + fold) % 2**32)
    return TrialSeededSampler(options, seed, fold)


def pruner(options: SearchOptions) -> optuna.pruners.BasePruner:
    """Prune only from accumulated inner-validation metrics, never an outer score."""
    if options.pruner == "median":
        return optuna.pruners.MedianPruner(n_startup_trials=options.startup_trials, n_warmup_steps=options.warmup_steps)
    if options.pruner == "halving":
        return optuna.pruners.SuccessiveHalvingPruner(min_resource=1, reduction_factor=2, min_early_stopping_rate=options.warmup_steps)
    return optuna.pruners.NopPruner()


def storage(directory: Path) -> JournalStorage:
    """Use Windows-compatible file locks, without touching the operational database."""
    path = directory / "optuna.journal"
    return JournalStorage(JournalFileBackend(str(path), lock_obj=JournalFileOpenLock(str(path))))


def open_study(directory: Path, name: str, options: SearchOptions, seed: int, fold: int, identity: dict) -> optuna.Study:
    """Bind persisted trials to this run's data, fold, objective and search contract."""
    study = optuna.create_study(storage=storage(directory), study_name=name, direction=options.direction,
        sampler=sampler(options, seed, fold), pruner=pruner(options), load_if_exists=True)
    digest = content_hash(identity)
    previous = study.user_attrs.get("identity_sha256")
    if previous is not None and previous != digest:
        raise AnalyticsError("El estudio persistido no corresponde a los mismos datos, fold o espacio de búsqueda.")
    if previous is None:
        study.set_user_attr("identity_sha256", digest)
        study.set_user_attr("identity", identity)
    return study


def trial_rows(study: optuna.Study) -> list[dict]:
    """Produce a finite JSON projection without arbitrary exception messages or inputs."""
    return [{"number": trial.number + 1, "state": trial.state.name,
             "score": trial.value if trial.value is not None and isfinite(trial.value) else None,
             "parameters": trial.params, "configuration": trial.user_attrs.get("configuration"),
             "inner_metrics": trial.user_attrs.get("inner_metrics", []),
             "seconds": trial.user_attrs.get("elapsed_seconds", max(0.0, trial.duration.total_seconds()) if trial.duration else None),
             "cpu_thread_seconds": trial.user_attrs.get("cpu_thread_seconds"),
             "intermediate": {str(key): value for key, value in trial.intermediate_values.items() if isfinite(value)}}
            for trial in study.get_trials(deepcopy=False)]


def recover_interrupted(study: optuna.Study) -> int:
    """Keep interrupted trials as FAIL instead of discarding them or guessing results."""
    running = study.get_trials(deepcopy=False, states=(TrialState.RUNNING,))
    for trial in running:
        study.tell(trial.number, state=TrialState.FAIL)
    return len(running)
