"""Validated analytical settings; the operational .env remains authoritative."""
from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from dotenv import dotenv_values

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from src.evaluation.settings import EvaluationSettings
from src.explainability.settings import ExplainabilitySettings
from src.training.settings import TrainingSettings
from src.inference.settings import InferenceSettings
from src.optimization.settings import OptimizationSettings

from .errors import ConfigurationError

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Model(BaseModel):
    """Reject accidental configuration keys and avoid input in validation errors."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


def project_path(root: Path, value: str | Path) -> Path:
    """Resolve a path inside the project, including checking symlink targets."""
    candidate = (root / value).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ConfigurationError("La ruta configurada debe permanecer dentro del proyecto.")
    return candidate


class Endpoints(Model):
    health: str
    login: str
    me: str
    logout: str
    reports: str
    report_collaboration: str
    analytical_audit: str
    report_explainability: str
    dashboard: str
    inference_metrics: str

    @field_validator("*")
    @classmethod
    def relative_endpoint(cls, value: str) -> str:
        """Disallow credentials and off-origin absolute URLs in endpoint paths."""
        if not value.startswith("/") or value.startswith("//") or any(c in value for c in ("?", "#", "\\")):
            raise ValueError("El endpoint debe ser una ruta relativa al backend.")
        return value


class ApiSettings(Model):
    base_url: str
    timeout_seconds: float = Field(gt=0, le=120)
    connect_timeout_seconds: float = Field(gt=0, le=30)
    max_response_bytes: int = Field(gt=0)
    endpoints: Endpoints

    @field_validator("base_url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        """Allow HTTPS or loopback HTTP, without URL-embedded credentials."""
        try:
            url = urlsplit(value)
            valid_port = url.port
        except ValueError:
            raise ValueError("URL de FastAPI inválida.") from None
        if (url.scheme not in ("http", "https") or not url.hostname or url.username or url.password
                or url.query or url.fragment or (url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1", "::1"))):
            raise ValueError("Usa HTTPS o HTTP local, sin credenciales en la URL de FastAPI.")
        return value.rstrip("/")


class PageSettings(Model):
    path: str
    title: str


class UiSettings(Model):
    title: str
    host: Literal["127.0.0.1", "localhost", "::1"]
    port: int = Field(ge=1024, le=65535)
    entrypoint: str
    cache_seconds: int = Field(ge=1)
    cache_entries: int = Field(ge=1)
    session_check_seconds: int = Field(ge=1, le=60)
    poll_seconds: float = Field(gt=0)
    workers: int = Field(ge=1, le=16)
    preview_rows: int = Field(ge=1, le=20)
    max_json_bytes: int = Field(gt=0)
    max_zip_member_bytes: int = Field(gt=0)
    preview_characters: int = Field(ge=1)
    pages: tuple[PageSettings, ...] = Field(min_length=1)


class LogSettings(Model):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
    max_bytes: int = Field(gt=0)
    backups: int = Field(ge=1)


class FlowValidationSettings(Model):
    """Conformance references; these do not select production providers."""

    export_file: str
    component_file: str
    prompt_file: str
    flow_path: str
    variables_path: str
    run_path: str
    expected_groq_model: str
    expected_gemini_model: str
    groq_variable: str
    gemini_variable: str
    probe_source_id: str
    probe_case_index: int = Field(ge=0)
    invalid_primary_model: str
    result_file: str

    @field_validator("flow_path", "variables_path", "run_path")
    @classmethod
    def local_endpoint(cls, value: str) -> str:
        """Keep the LangFlow API key on the configured server origin."""
        return Endpoints.relative_endpoint(value)


class FigureSettings(Model):
    dpi: int = Field(ge=600)
    font_family: str
    font_size: int = Field(ge=10)
    palette: tuple[str, ...] = Field(min_length=2)

    @field_validator("palette")
    @classmethod
    def valid_colors(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Validate explicit RGB colors without executing style expressions."""
        import re
        if not all(re.fullmatch(r"#[0-9a-fA-F]{6}", value) for value in values):
            raise ValueError("La paleta debe contener colores RGB hexadecimales.")
        return values


class ReportingSettings(Model):
    """Bounds and physical dimensions for scientific report exports."""

    directory: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    max_selections: int = Field(ge=2, le=10)
    figure_width_inches: float = Field(ge=4, le=10)
    figure_height_inches: float = Field(ge=2.5, le=8)


class DataSettings(Model):
    """Bounds and criteria for the data inventory and quality checks."""

    directory: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    sealed_holdout_file: str
    prior_pilot_exclusions_file: str
    page_sizes: tuple[int, ...] = Field(min_length=1)
    max_source_rows: int = Field(ge=1, le=50000)
    max_csv_bytes: int = Field(ge=1, le=134217728)
    max_text_characters: int = Field(ge=4000, le=20000)
    max_history_entries: int = Field(ge=1, le=500)
    similarity_threshold: float = Field(gt=0, le=1)
    similarity_min_words: int = Field(ge=2)
    similarity_batch_size: int = Field(ge=1, le=128)
    similarity_features: int = Field(ge=1024, le=262144)
    similarity_aliases: dict[str, str] = Field(max_length=100)
    imbalance_ratio: float = Field(gt=1)
    max_examples: int = Field(ge=1, le=100)
    chart_categories: int = Field(ge=2, le=25)
    histogram_bins: int = Field(ge=2, le=50)
    vocabulary: tuple[str, ...] = Field(min_length=1, max_length=250)

    @field_validator("page_sizes")
    @classmethod
    def valid_page_sizes(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if any(not 1 <= value <= 100 for value in values) or len(set(values)) != len(values):
            raise ValueError("Los tamaños de página deben ser únicos y estar entre 1 y 100.")
        return values


class AnalyticsSettings(Model):
    version: Literal[1]
    seed: int = Field(ge=0, le=2**32 - 1)
    registry_file: str
    runs_dir: str
    api: ApiSettings
    flow_validation: FlowValidationSettings
    ui: UiSettings
    logging: LogSettings
    figures: FigureSettings
    data: DataSettings
    training: TrainingSettings
    evaluation: EvaluationSettings
    explainability: ExplainabilitySettings
    reporting: ReportingSettings
    inference: InferenceSettings
    optimization: OptimizationSettings
    software: tuple[str, ...]
    root: Path = Field(exclude=True, repr=False)
    source_file: Path = Field(exclude=True, repr=False)

    def path(self, value: str | Path) -> Path:
        """Resolve one configured project path."""
        return project_path(self.root, value)


def read_yaml(path: Path) -> dict:
    """Read a YAML mapping without allowing Python objects or unsafe loaders."""
    try:
        content = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise ConfigurationError("No se pudo leer el archivo YAML de configuración.") from None
    if not isinstance(content, dict):
        raise ConfigurationError("El archivo de configuración debe contener un objeto YAML.")
    return content


def load_config(root: Path = PROJECT_ROOT, *, environment: Mapping[str, str] | None = None) -> AnalyticsSettings:
    """Merge public settings with existing .env and process overrides, never credentials."""
    root = root.resolve()
    env = {**dotenv_values(root / ".env"), **(os.environ if environment is None else environment)}
    source = project_path(root, env.get("SOC_ANALYTICS_CONFIG") or "config/analytics.yaml")
    payload = read_yaml(source)
    try:
        payload["api"] = dict(payload["api"])
        payload["ui"] = dict(payload["ui"])
        payload["logging"] = dict(payload["logging"])
        payload["training"] = dict(payload["training"])
        payload["training"]["cloud"] = dict(payload["training"]["cloud"])
        if env.get("SOC_API_URL"):
            payload["api"]["base_url"] = env["SOC_API_URL"]
        for variable, name in (("SOC_ANALYTICS_PORT", "port"), ("SOC_ANALYTICS_HOST", "host")):
            if env.get(variable):
                payload["ui"][name] = env[variable]
        if env.get("SOC_ANALYTICS_LOG_LEVEL"):
            payload["logging"]["level"] = env["SOC_ANALYTICS_LOG_LEVEL"]
        for variable, name in (("SOC_EXPERIMENT_MAX_COST_PER_FLOW_USD", "max_cost_per_flow_usd"),
                               ("SOC_EXPERIMENT_MAX_RUN_BUDGET_USD", "max_run_budget_usd")):
            if env.get(variable):
                payload["training"]["cloud"][name] = env[variable]
        settings = AnalyticsSettings(**payload, root=root, source_file=source)
        for item in (settings.registry_file, settings.runs_dir, settings.ui.entrypoint,
                     settings.data.sealed_holdout_file, settings.data.prior_pilot_exclusions_file):
            settings.path(item)
        for page in settings.ui.pages:
            settings.path(page.path)
        for prompt in settings.training.cloud.prompts.values():
            if prompt is not None:
                settings.path(prompt)
        for item in (settings.flow_validation.export_file, settings.flow_validation.component_file,
                     settings.flow_validation.prompt_file, settings.flow_validation.result_file):
            settings.path(item)
        return settings
    except (ValidationError, KeyError, TypeError, ValueError):
        raise ConfigurationError("Configuración analítica inválida. Revisa config/analytics.yaml y las variables SOC_ANALYTICS_*.") from None
