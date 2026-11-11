"""Prediction adapters for verified final estimators and the existing LangFlow graph."""
from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from hashlib import sha256
from io import BytesIO

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

from backend.config import Settings
from src.evaluation.contracts import EvaluationSet, Observation, ScoreKind, label_value
from src.evaluation.dataset import FinalSelection
from src.inference.experimental import CloudParameters, CloudSearch, budget_quote
from src.training.metrics import REVIEW
from src.training.partition import Case
from src.utils.config import AnalyticsSettings
from src.utils.errors import AnalyticsError, DatasetError
from src.utils.langflow import LangflowConformance


def local_model(selection: FinalSelection, dataset: EvaluationSet, settings: AnalyticsSettings) -> Pipeline:
    """Verify the bounded Phase 2 artifact before loading its trusted local pickle."""
    try:
        if selection.model_path is None:
            raise ValueError
        with selection.model_path.open("rb") as handle:
            payload = handle.read(settings.evaluation.max_artifact_bytes + 1)
        if len(payload) > settings.evaluation.max_artifact_bytes or sha256(payload).hexdigest() != selection.artifact["sha256"]:
            raise ValueError
        model = joblib.load(BytesIO(payload))
        expected = LogisticRegression if selection.family == "tfidf_logreg" else LinearSVC
        if (type(model) is not Pipeline or type(model.named_steps["tfidf"]) is not TfidfVectorizer or
                type(model.named_steps["classifier"]) is not expected or len(model.steps) != 2 or
                {label_value(dataset.target, label) for label in model.classes_} != set(dataset.classes) or
                len(model.classes_) != len(dataset.classes)):
            raise ValueError
        return model
    except (OSError, EOFError, ImportError, TypeError, ValueError, KeyError, AttributeError):
        raise DatasetError("El modelo local no coincide con la huella, el pipeline o las clases finales de Fase 2.") from None


def local_predictions(model: Pipeline, dataset: EvaluationSet, family: str) -> tuple[tuple[Observation, ...], ScoreKind]:
    """Classify by the final estimator's continuous output, without refitting."""
    inputs = [case.text for case in dataset.cases]
    classes = [label_value(dataset.target, label) for label in model.classes_]
    kind: ScoreKind = "probability" if family == "tfidf_logreg" else "margin"
    values = np.asarray(model.predict_proba(inputs) if kind == "probability" else model.decision_function(inputs))
    if kind == "margin" and values.ndim == 1 and len(classes) == 2:
        values = np.column_stack((-values, values))
    if values.shape != (len(inputs), len(classes)) or not np.isfinite(values).all() or (
        kind == "probability" and (np.any(values < 0) or np.any(values > 1) or not np.allclose(values.sum(axis=1), 1))
    ):
        raise DatasetError("El modelo devolvió scores incompatibles con su taxonomía.")
    observations = tuple(Observation(case.key, case.group, case.label, classes[int(scores.argmax())],
                                     dict(zip(classes, map(float, scores))))
                         for case, scores in zip(dataset.cases, values))
    return observations, kind


def cloud_options(selection: FinalSelection, settings: AnalyticsSettings, count: int,
                  amount: Decimal, approved: bool) -> tuple[CloudParameters, dict]:
    params = selection.configuration
    selected = CloudParameters(prompts=(params["prompt"],), thresholds=(params["threshold"],),
                               budget_usd=amount, approve=approved)
    return selected, budget_quote(selected, count, settings.training.cloud)


class CloudEvaluation:
    """Run the final LangFlow selection with its existing technical fallback."""

    def __init__(self, selection: FinalSelection, dataset: EvaluationSet, settings: AnalyticsSettings,
                 params: CloudParameters, verify_actor: Callable[[], None], event: Callable[..., None],
                 client: LangflowConformance | None = None) -> None:
        operational = Settings.from_env()
        flow = client or LangflowConformance(settings, operational)
        self.dataset, self.selection = dataset, selection
        self.models = {"groq": settings.flow_validation.expected_groq_model, "gemini": settings.flow_validation.expected_gemini_model}
        if self.models != selection.artifact["configured_models"]:
            raise AnalyticsError("Los modelos de LangFlow difieren de la selección de Fase 2.")
        self.search = CloudSearch(settings, params, dataset.target, dataset.classes, settings.seed, len(dataset.cases),
                                  operational, flow, verify_actor, event)
        self.version = self.search.prepare_final(selection.configuration, selection.artifact["graph_sha256"])

    def predict(self, case: Case) -> Observation:
        result = self.search.predict_final(case, self.version, lambda: None)
        label = label_value(self.dataset.target, result.label)
        reason = result.review
        if reason is None:
            if result.confidence is None or result.confidence < self.selection.configuration["threshold"]:
                reason = "confianza_baja"
            elif label not in self.dataset.classes:
                reason = "valor_sin_referencia"
        return Observation(case.key, case.group, case.label, REVIEW if reason else label,
                           review_reason=reason, provider=result.provider, model=result.model,
                           flow_seconds=result.flow_seconds, provider_seconds=result.provider_seconds,
                           technical_failure=result.technical_failure, format_error=result.format_error,
                           taxonomy_error=result.taxonomy_error, input_tokens=result.input_tokens,
                           output_tokens=result.output_tokens, cost_usd=result.cost_usd)

    def finish(self) -> None:
        self.search.verify_final()
