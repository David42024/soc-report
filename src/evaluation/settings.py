"""Prespecified reporting and eligibility rules for the sealed evaluation."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvaluationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    directory: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    min_real_groups_per_class: int = Field(ge=2)
    min_ci_groups: int = Field(ge=5)
    min_ci_groups_per_class: int = Field(ge=2)
    min_test_groups: int = Field(ge=5)
    min_discordant: int = Field(ge=1)
    bootstrap_replicates: int = Field(ge=100, le=10000)
    bootstrap_min_fraction: float = Field(gt=0, le=1)
    alpha: Literal[0.05]
    practical_accuracy_delta: float = Field(gt=0, le=1)
    max_artifact_bytes: int = Field(gt=0)
    inspection_characters: int = Field(ge=80, le=4000)
