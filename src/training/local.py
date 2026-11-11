"""Fit local sparse text pipelines independently within each training fold."""
from __future__ import annotations

from hashlib import file_digest
from pathlib import Path
from time import monotonic
from typing import Literal

import joblib
import optuna
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

from src.training.metrics import macro_f1, objective_metrics
from src.training.partition import Case
from src.training.settings import LocalParameters, TrainingSettings

Family = Literal["tfidf_logreg", "tfidf_svm"]
FAMILY_NAMES = {"tfidf_logreg": "TF-IDF + regresión logística", "tfidf_svm": "TF-IDF + SVM lineal",
                "langflow": "LangFlow · Groq con respaldo Gemini"}


def pipeline(family: Family, parameters: LocalParameters, seed: int) -> Pipeline:
    """Construct an unfitted vectorizer and classifier for this fit only."""
    vectorizer = TfidfVectorizer(ngram_range=(parameters.ngram_min, parameters.ngram_max),
        min_df=parameters.min_df, max_df=parameters.max_df, max_features=parameters.max_features,
        sublinear_tf=parameters.sublinear_tf, smooth_idf=parameters.smooth_idf)
    options = dict(C=parameters.c, max_iter=parameters.max_iter,
                   class_weight="balanced" if parameters.balanced else None, random_state=seed)
    classifier = (LogisticRegression(solver=parameters.solver, **options) if family == "tfidf_logreg"
                  else LinearSVC(dual="auto", **options))
    return Pipeline([("tfidf", vectorizer), ("classifier", classifier)])


class LocalSearch:
    """Expose the same fitting contract for either academic family."""

    def __init__(self, family: Family, parameters: LocalParameters, policy: TrainingSettings, seed: int,
                 labels: tuple[str, ...], *, target: str = "tipo") -> None:
        self.name = family
        self.parameters = parameters
        self.policy = policy
        self.seed = seed
        self.labels = labels
        self.target = target

    def sampler(self, fold: int) -> optuna.samplers.BaseSampler:
        return optuna.samplers.TPESampler(seed=(self.seed + fold) % (2**32))

    def suggest(self, trial: optuna.Trial) -> dict:
        base = self.parameters
        return base.model_copy(update={
            "c": trial.suggest_float("C", base.c / self.policy.c_search_factor,
                                     min(1000.0, base.c * self.policy.c_search_factor), log=True),
            "ngram_max": trial.suggest_int("ngram_max", base.ngram_min, base.ngram_max),
        }).model_dump(mode="json")

    def _fit(self, train: tuple[Case, ...], parameters: dict) -> Pipeline:
        estimator = pipeline(self.name, LocalParameters.model_validate(parameters), self.seed)
        estimator.fit([case.text for case in train], [case.label for case in train])
        return estimator

    def evaluate(self, train: tuple[Case, ...], validation: tuple[Case, ...], parameters: dict,
                 scope: str, check_cancel) -> dict:
        started = monotonic()
        estimator = self._fit(train, parameters)
        fit_seconds = monotonic() - started
        predicted = estimator.predict([case.text for case in validation])
        return {"score": macro_f1([case.label for case in validation], predicted.tolist(), self.labels),
                "metrics": objective_metrics([case.label for case in validation], predicted.tolist(), self.labels, self.target),
                "seconds": monotonic() - started, "fit_seconds": fit_seconds,
                "features": len(estimator.named_steps["tfidf"].vocabulary_)}

    def publish(self, train: tuple[Case, ...], parameters: dict, directory: Path) -> dict:
        """Write only the selected local model fitted to Development."""
        file = directory / (self.name + ".joblib")
        temporary = file.with_suffix(".tmp")
        try:
            joblib.dump(self._fit(train, parameters), temporary, compress=3)
            temporary.replace(file)
        finally:
            temporary.unlink(missing_ok=True)
        with file.open("rb") as handle:
            digest = file_digest(handle, "sha256").hexdigest()
        return {"file": file.name, "sha256": digest, "fit_partition": "Desarrollo"}
