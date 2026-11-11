"""Bounded search descriptions; never accept executable objectives or provider overrides."""
from __future__ import annotations

from math import isclose, isfinite, prod
from typing import TYPE_CHECKING, Literal

from pydantic import Field, model_validator

from src.training.settings import LocalParameters, SettingsModel
if TYPE_CHECKING:
    from optuna import Trial

Metric = Literal["f1_macro", "balanced_accuracy", "critical_recall", "kappa_quadratic", "critical_fnr", "latency_seconds", "penalized_f1"]
METRICS = {"f1_macro": "F1 macro", "balanced_accuracy": "Balanced accuracy", "critical_recall": "Recall de severidad crítica",
           "kappa_quadratic": "Kappa cuadrático de severidad", "critical_fnr": "FNR crítica, incluida revisión",
           "latency_seconds": "Latencia media observada por reporte (s)", "penalized_f1": "F1 macro con penalizaciones predefinidas"}


class Distribution(SettingsModel):
    """A safe Optuna distribution with unambiguous numeric and categorical types."""

    kind: Literal["float", "int", "categorical"]
    low: float | int | None = None
    high: float | int | None = None
    step: float | int | None = None
    log: bool = False
    choices: tuple[float | int | str | bool, ...] = Field(default=(), max_length=50)

    @model_validator(mode="after")
    def coherent(self) -> Distribution:
        if self.kind == "categorical":
            if not self.choices or any(v is not None for v in (self.low, self.high, self.step)) or self.log:
                raise ValueError("Las categorías requieren choices y no usan rango, paso ni escala logarítmica.")
            if len({(type(v).__name__, str(v)) for v in self.choices}) != len(self.choices):
                raise ValueError("Las categorías deben ser únicas.")
            if any((isinstance(v, str) and not 0 < len(v) <= 80) or (type(v) is float and not isfinite(v)) for v in self.choices):
                raise ValueError("Usa categorías cortas y números finitos.")
        else:
            if self.choices or self.low is None or self.high is None:
                raise ValueError("Un rango numérico requiere low y high, sin choices.")
            values = [v for v in (self.low, self.high, self.step) if v is not None]
            if any(type(v) not in (int, float) or not isfinite(v) for v in values) or self.low > self.high:
                raise ValueError("El rango numérico debe ser finito y ordenado.")
            if self.kind == "int" and any(type(v) is not int for v in values):
                raise ValueError("Los límites y pasos enteros deben ser enteros.")
            if self.step is not None and self.step <= 0:
                raise ValueError("El paso debe ser positivo.")
            if self.step is not None and not isclose((self.high - self.low) / self.step, round((self.high - self.low) / self.step), rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError("El paso debe alcanzar exactamente el extremo del rango; evita ajustes silenciosos de Optuna.")
            if self.log and (self.low <= 0 or self.step is not None and (self.kind == "float" or self.step != 1)):
                raise ValueError("La escala logarítmica requiere límites positivos y un paso compatible.")
        return self

    def boundaries(self) -> tuple:
        """Values sufficient to validate static domain constraints before any fit."""
        return self.choices if self.kind == "categorical" else (self.low, self.high)

    def suggest(self, trial: Trial, name: str) -> float | int | str | bool:
        """Use only the public typed suggestion APIs of the installed Optuna."""
        if self.kind == "categorical":
            return trial.suggest_categorical(name, list(self.choices))
        if self.kind == "int":
            return trial.suggest_int(name, self.low, self.high, step=self.step or 1, log=self.log)
        return trial.suggest_float(name, self.low, self.high, step=self.step, log=self.log)


class SearchOptions(SettingsModel):
    """One scalar objective keeps pruning well-defined across the three inner folds."""

    space: dict[str, Distribution] = Field(min_length=1, max_length=12)
    sampler: Literal["tpe", "random", "grid"]
    pruner: Literal["none", "median", "halving"]
    startup_trials: int = Field(ge=1, le=100)
    warmup_steps: int = Field(ge=0, le=2)
    metric: Metric
    direction: Literal["maximize", "minimize"]
    timeout_seconds: float = Field(gt=0, le=86400, allow_inf_nan=False)
    parallel_trials: int = Field(ge=1, le=4)
    cpu_threads: int = Field(ge=1, le=8)
    critical_penalty: float = Field(ge=0, le=1, allow_inf_nan=False)
    review_penalty: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def compatible(self) -> SearchOptions:
        expected = "minimize" if self.metric in ("critical_fnr", "latency_seconds") else "maximize"
        if self.direction != expected:
            raise ValueError("La dirección no corresponde a la métrica: maximiza calidad y minimiza errores o latencia.")
        if self.sampler == "grid" and (self.parallel_trials != 1 or any(v.kind != "categorical" for v in self.space.values())):
            raise ValueError("Grid requiere categorías finitas explícitas y ejecución secuencial.")
        if self.metric != "penalized_f1" and (self.critical_penalty or self.review_penalty):
            raise ValueError("Los pesos de penalización solo se usan con penalized_f1.")
        return self

    @property
    def grid_size(self) -> int:
        """Finite cardinality only for the explicitly categorical grid."""
        return prod(len(value.choices) for value in self.space.values()) if self.sampler == "grid" else 0


def validate_space(options: SearchOptions, local: LocalParameters | None, cloud, models: tuple, target: str) -> None:
    """Reject ineffective fields, invalid model domains and unsupported LLM tweaks."""
    if options.metric in ("critical_recall", "critical_fnr", "kappa_quadratic", "penalized_f1") and target != "severidad":
        raise ValueError("La métrica solicitada requiere referencias de severidad.")
    if cloud:
        if options.parallel_trials != 1:
            raise ValueError("LangFlow requiere una solicitud experimental a la vez para respetar tasa y presupuesto.")
        domains = {"prompt": cloud.prompts, "threshold": cloud.thresholds}
        if not set(options.space) <= domains.keys():
            raise ValueError("Este flujo solo admite optimizar prompts y umbrales registrados; su contrato JSON y parámetros de generación permanecen fijos.")
        for name, distribution in options.space.items():
            if distribution.kind != "categorical" or not set(distribution.choices) <= set(domains[name]):
                raise ValueError("Las opciones LLM deben ser categorías incluidas en la selección autorizada.")
            if name == "threshold" and any(type(value) not in (int, float) for value in distribution.choices):
                raise ValueError("Los umbrales deben ser valores numéricos explícitos.")
        return
    if options.metric == "latency_seconds":
        raise ValueError("La latencia de proveedor requiere una configuración LangFlow.")
    if len(models) != 1 or local is None:
        raise ValueError("Cada estudio avanzado usa un modelo académico; crea estudios separados para comparar familias.")
    integers = {"ngram_min", "ngram_max", "min_df", "max_features", "max_iter"}
    booleans = {"sublinear_tf", "smooth_idf", "balanced"}
    for name, distribution in options.space.items():
        if name not in LocalParameters.model_fields or name == "solver" and models[0] != "tfidf_logreg":
            raise ValueError("El parámetro no pertenece al pipeline o no tiene efecto en ese modelo.")
        if name in integers and distribution.kind == "float":
            raise ValueError("Los conteos requieren una distribución int o categorías enteras.")
        for value in distribution.boundaries():
            if name in integers and type(value) is not int or name in booleans and type(value) is not bool:
                raise ValueError("El tipo de la distribución no coincide con el hiperparámetro.")
            if name in ("solver", *booleans) and distribution.kind != "categorical":
                raise ValueError("Solver y opciones booleanas requieren categorías explícitas.")
            if name in ("c", "max_df") and type(value) not in (int, float):
                raise ValueError("Los parámetros numéricos requieren números, sin coerción de texto o booleanos.")
            candidate = {**local.model_dump(), name: value}
            if name in ("ngram_min", "ngram_max"):
                candidate["ngram_max" if name == "ngram_min" else "ngram_min"] = value
            LocalParameters.model_validate(candidate)
    lower = max(options.space["ngram_min"].boundaries()) if "ngram_min" in options.space else local.ngram_min
    upper = min(options.space["ngram_max"].boundaries()) if "ngram_max" in options.space else local.ngram_max
    if lower > upper:
        raise ValueError("El espacio permite n-gramas mínimos mayores que los máximos.")
