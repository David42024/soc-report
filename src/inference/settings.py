"""Public, bounded settings for individual SOC inference and its diagnostics."""
from pydantic import BaseModel, ConfigDict, Field


class InferenceSettings(BaseModel):
    """Experimental observations and latency objectives, without provider credentials."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    directory: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    request_timeout_seconds: float = Field(ge=90, le=240)
    max_metric_records: int = Field(ge=1, le=10000)
    latency_min_observations: int = Field(ge=20, le=1000)
    target_p95_seconds: float = Field(gt=0)
    lexical_min_terms: int = Field(ge=1, le=10)
