"""Public server ceilings and UI defaults for the integrated Optuna module."""
from pydantic import Field, model_validator
from src.training.settings import SettingsModel
from .contracts import Distribution


class OptimizationSettings(SettingsModel):
    """Bounds are checked again by the Phase 2 runner before dispatch."""

    directory: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    default_trials: int = Field(ge=10, le=100)
    default_timeout_seconds: float = Field(ge=1, le=86400)
    max_timeout_seconds: float = Field(ge=1, le=86400)
    max_parallel_trials: int = Field(ge=1, le=4)
    max_total_cpu_threads: int = Field(ge=1, le=16)
    max_grid_points: int = Field(ge=10, le=10000)
    max_config_bytes: int = Field(ge=1024, le=262144)
    importance_min_trials: int = Field(ge=10, le=100)
    importance_trees: int = Field(ge=16, le=256)
    contour_min_points: int = Field(ge=6, le=100)
    max_plot_parameters: int = Field(ge=2, le=8)
    startup_trials: int = Field(ge=1, le=100)
    warmup_steps: int = Field(ge=0, le=2)
    local_space: dict[str, Distribution]

    @model_validator(mode="after")
    def consistent_defaults(self) -> "OptimizationSettings":
        """Fail configuration loading when the UI default exceeds its server ceiling."""
        if self.default_timeout_seconds > self.max_timeout_seconds:
            raise ValueError("El tiempo inicial no puede superar el máximo del servidor.")
        return self
