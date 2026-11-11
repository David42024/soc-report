"""Small immutable objects shared by dataset, inference and metric code."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
import unicodedata

from src.data.models import LabelField, SEVERITIES, TYPES
from src.training.metrics import REVIEW
from src.training.partition import Case

ScoreKind = Literal["probability", "margin"]


def label_value(target: LabelField, value: str | None) -> str | None:
    """Keep SOC enums exact and normalize asset spelling without alias inference."""
    if value is None:
        return None
    if target == "activo_afectado":
        return " ".join(unicodedata.normalize("NFKC", value).casefold().split()) or None
    return value


def class_order(target: LabelField, observed: set[str]) -> tuple[str, ...]:
    domain = TYPES if target == "tipo" else SEVERITIES if target == "severidad" else tuple(sorted(observed))
    return tuple(label for label in domain if label in observed)


@dataclass(frozen=True, slots=True)
class EvaluationSet:
    """Cases with independently verified references or identified test fixtures."""

    cases: tuple[Case, ...]
    target: LabelField
    source: Literal["real", "sintetico"]
    seal_sha256: str
    dataset_sha256: str
    manifest_version: str | None
    classes: tuple[str, ...]
    strata: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Observation:
    """Persist prediction fields and telemetry without report or response bodies."""

    key: str
    group: str
    truth: str
    predicted: str
    scores: dict[str, float] | None = None
    review_reason: str | None = None
    provider: Literal["groq", "gemini"] | None = None
    model: str | None = None
    flow_seconds: float | None = None
    technical_failure: bool = False
    format_error: bool = False
    taxonomy_error: bool = False
    provider_seconds: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None

    @property
    def correct(self) -> bool:
        return self.truth == self.predicted

    @property
    def review(self) -> bool:
        return self.predicted == REVIEW
