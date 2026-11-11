"""Prespecified bounds and evidence criteria for text explainability."""
from pydantic import BaseModel, ConfigDict, Field


class Criterion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    field: str = Field(pattern=r"^(tipo|severidad)$")
    value: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=8, max_length=300)
    phrases: tuple[str, ...] = Field(min_length=1, max_length=20)


class ExplainabilitySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    directory: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    criteria_version: str = Field(min_length=1, max_length=64)
    top_features: int = Field(ge=2, le=30)
    max_cases: int = Field(ge=1, le=500)
    max_spans: int = Field(ge=1, le=30)
    max_text_characters: int = Field(ge=100, le=20000)
    tolerance: float = Field(gt=0, le=.01)
    negation_prefixes: tuple[str, ...]
    criteria: tuple[Criterion, ...]
