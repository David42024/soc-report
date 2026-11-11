"""Configuration contracts for the experimental protocol."""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class LocalParameters(SettingsModel):
    """The shared text features and classifier parameters exposed in Streamlit."""

    ngram_min: int = Field(ge=1, le=3)
    ngram_max: int = Field(ge=1, le=3)
    min_df: int = Field(ge=1, le=100)
    max_df: float = Field(gt=0, le=1)
    max_features: int = Field(ge=10, le=100000)
    sublinear_tf: bool
    smooth_idf: bool
    c: float = Field(gt=0, le=1000)
    balanced: bool
    solver: Literal["lbfgs", "saga"]
    max_iter: int = Field(ge=100, le=10000)

    @model_validator(mode="after")
    def ngram_order(self) -> LocalParameters:
        if self.ngram_min > self.ngram_max:
            raise ValueError("El mínimo de n-gramas no puede exceder el máximo.")
        return self


class CloudSettings(SettingsModel):
    """Server ceilings and the versioned prompt allowlist for LangFlow."""

    prompts: dict[str, str | None] = Field(min_length=1, max_length=12)
    thresholds: tuple[float, ...] = Field(min_length=1)
    default_threshold: float = Field(ge=0, le=1)
    max_flow_calls: int = Field(ge=0, le=100000)
    seconds_between_calls: float = Field(ge=1)
    attempts_per_flow: Literal[3]
    max_consecutive_errors: int = Field(ge=1, le=10)
    approved_component_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_prompt_chars: int = Field(ge=500, le=20000)
    max_case_chars: int = Field(ge=100, le=5000)
    max_cost_per_flow_usd: Decimal = Field(ge=0, le=100)
    max_run_budget_usd: Decimal = Field(ge=0, le=10000)

    @model_validator(mode="after")
    def valid_choices(self) -> CloudSettings:
        if len(set(self.thresholds)) != len(self.thresholds) or any(not 0 <= value <= 1 for value in self.thresholds):
            raise ValueError("Usa umbrales únicos entre cero y uno.")
        if self.default_threshold not in self.thresholds:
            raise ValueError("El umbral inicial debe estar en la lista de umbrales.")
        if None not in self.prompts.values():
            raise ValueError("Incluye el prompt operativo entre las versiones.")
        return self


class TrainingSettings(SettingsModel):
    """Fixed folds and controlled local execution limits."""

    directory: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    outer_folds: Literal[5]
    inner_folds: Literal[3]
    ratios: tuple[float, float, float]
    fold_seed_attempts: int = Field(ge=1, le=100)
    partition_timeout_seconds: int = Field(ge=1, le=120)
    default_trials_per_fold: int = Field(ge=1)
    max_trials_per_fold: int = Field(ge=1, le=100)
    c_search_factor: float = Field(gt=1, le=100)
    cpu_threads: int = Field(ge=1, le=8)
    max_jobs: int = Field(ge=1, le=4)
    recent_events: int = Field(ge=10, le=500)
    demo_groups_per_class: int = Field(ge=20, le=100)
    local: LocalParameters
    cloud: CloudSettings

    @model_validator(mode="after")
    def valid_trials(self) -> TrainingSettings:
        if self.default_trials_per_fold > self.max_trials_per_fold:
            raise ValueError("Los trials iniciales exceden el máximo por fold.")
        if self.ratios != (0.70, 0.15, 0.15):
            raise ValueError("El protocolo requiere Desarrollo 70 %, Validación 15 % y Prueba 15 %.")
        return self
