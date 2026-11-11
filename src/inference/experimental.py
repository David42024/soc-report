"""Budgeted inference experiments against the unchanged LangFlow classifier."""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from html import escape
from itertools import product
from math import isfinite
from pathlib import Path
import re
from time import monotonic, sleep
from uuid import uuid4

import optuna
from pydantic import Field, ValidationError

from backend.classifier import Classification, SUSPICIOUS
from backend.config import Settings
from src.data.models import LabelField
from src.training.metrics import REVIEW, macro_f1, objective_metrics
from src.training.partition import Case
from src.training.settings import CloudSettings, SettingsModel
from src.utils.config import AnalyticsSettings
from src.utils.errors import AnalyticsError, ServiceError
from src.utils.langflow import LangflowConformance, graph_contract, graph_digest
from src.utils.privacy import PrivacyError, protect_text
from src.inference.telemetry import valid_trace


class CloudParameters(SettingsModel):
    """Explicit selections and a one-run authorization from the operator."""

    prompts: tuple[str, ...] = Field(min_length=1)
    thresholds: tuple[float, ...] = Field(min_length=1)
    budget_usd: Decimal = Field(ge=0, le=10000)
    approve: bool


@dataclass(frozen=True, slots=True)
class PromptVersion:
    id: str
    text: str
    sha256: str


def prompt_versions(settings: AnalyticsSettings) -> dict[str, PromptVersion]:
    """Resolve local versioned templates only, without consulting any provider."""
    try:
        base = settings.path(settings.flow_validation.prompt_file).read_text(encoding="utf-8").strip()
        versions = {}
        for name, path in settings.training.cloud.prompts.items():
            if not name or len(name) > 80:
                raise ValueError
            template = base + ("\n" + settings.path(path).read_text(encoding="utf-8").strip() if path else "")
            if len(template) > settings.training.cloud.max_prompt_chars:
                raise ValueError
            versions[name] = PromptVersion(name, template, sha256(template.encode()).hexdigest())
        return versions
    except (OSError, ValueError):
        raise AnalyticsError("Revisa los archivos y límites de las versiones de prompt configuradas.") from None


def cloud_choices(parameters: CloudParameters, policy: CloudSettings) -> tuple[tuple[str, float], ...]:
    prompts, thresholds = sorted(set(parameters.prompts)), sorted(set(parameters.thresholds))
    if not set(prompts) <= policy.prompts.keys() or not set(thresholds) <= set(policy.thresholds):
        raise AnalyticsError("Selecciona versiones y umbrales registrados para este flujo.")
    return tuple(product(prompts, thresholds))


def budget_quote(parameters: CloudParameters, planned_calls: int, policy: CloudSettings) -> dict:
    """Reserve a conservative allowance including the configured fallback retries."""
    ceiling = policy.max_cost_per_flow_usd
    upper = ceiling * planned_calls
    return {
        "planned_flow_calls": planned_calls, "max_provider_attempts": planned_calls * policy.attempts_per_flow,
        "ceiling_per_flow_usd": str(ceiling), "reserved_usd": str(upper), "approved_usd": str(parameters.budget_usd),
        "authorized": bool(parameters.approve and 0 < planned_calls <= policy.max_flow_calls and
                           0 < upper <= parameters.budget_usd <= policy.max_run_budget_usd),
    }


def quote_with_prompts(quote: dict, parameters: CloudParameters, versions: dict[str, PromptVersion]) -> dict:
    """Bind the allowance to the selected template hashes."""
    return {**quote, "prompt_versions": {name: versions[name].sha256 for name in sorted(set(parameters.prompts))}}


@dataclass(frozen=True, slots=True)
class Prediction:
    label: str | None
    confidence: float | None
    provider: str | None = None
    review: str | None = None
    flow_seconds: float | None = None
    provider_seconds: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    technical_failure: bool = False
    format_error: bool = False
    taxonomy_error: bool = False
    model: str | None = None
    model_scope: str | None = None


def _telemetry(metadata: dict) -> dict:
    """Allow only explicit numeric metadata. Current LangFlow may omit every field."""
    def number(value: object) -> float | None:
        return float(value) if type(value) in (int, float) and 0 <= value <= 1e12 and isfinite(value) else None

    usage = metadata.get("soc_usage")
    usage = usage if isinstance(usage, dict) else {}
    return {"provider_seconds": number(metadata.get("soc_provider_seconds")),
            "input_tokens": usage["input_tokens"] if type(usage.get("input_tokens")) is int and
            number(usage["input_tokens"]) is not None else None,
            "output_tokens": usage["output_tokens"] if type(usage.get("output_tokens")) is int and
            number(usage["output_tokens"]) is not None else None,
            "cost_usd": number(usage.get("cost_usd"))}


class CloudSearch:
    """Optimize prompts and review thresholds without fitting provider weights."""

    name = "langflow"

    def __init__(self, settings: AnalyticsSettings, parameters: CloudParameters, target: LabelField,
                 labels: tuple[str, ...], seed: int, planned_calls: int, operational: Settings,
                 client: LangflowConformance, verify_actor: Callable[[], None], event: Callable[..., None]) -> None:
        self.policy = settings.training.cloud
        self.quote = budget_quote(parameters, planned_calls, self.policy)
        if not self.quote["authorized"]:
            raise AnalyticsError("Autoriza un presupuesto que cubra el techo de llamadas y respete los límites del servidor.")
        self.settings, self.operational, self.client = settings, operational, client
        self.target, self.labels, self.seed = target, labels, seed
        self.options = cloud_choices(parameters, self.policy)
        self.prompts = prompt_versions(settings)
        self.quote = quote_with_prompts(self.quote, parameters, self.prompts)
        self.verify_actor, self.event = verify_actor, event
        self.calls, self.errors, self.next_call = 0, 0, 0.0
        self._scope = ""
        self._predictions: dict[tuple[str, str], Prediction] = {}
        self._graph: str | None = None
        self._prompt_node: str | None = None

    def sampler(self, fold: int) -> optuna.samplers.BaseSampler:
        return optuna.samplers.GridSampler({"opcion": list(range(len(self.options)))}, seed=(self.seed + fold) % (2**32))

    def suggest(self, trial: optuna.Trial) -> dict:
        prompt, threshold = self.options[trial.suggest_categorical("opcion", list(range(len(self.options))))]
        return {"prompt": prompt, "prompt_sha256": self.prompts[prompt].sha256, "threshold": threshold}

    def _verify_graph(self) -> None:
        try:
            graph = self.client.fetch()
            graph_contract(graph, self.settings)
            code = self.settings.path(self.settings.flow_validation.component_file).read_text(encoding="utf-8").strip()
            if sha256(code.encode()).hexdigest() != self.policy.approved_component_sha256:
                raise AnalyticsError("El componente cambió y requiere volver a verificar el límite de intentos.")
            for node in graph["nodes"]:
                if node["data"]["type"] in ("ChatInput", "ChatOutput"):
                    if node["data"]["node"]["template"]["should_store_message"]["value"] is not False:
                        raise AnalyticsError("El flujo debe mantener desactivado el guardado de mensajes experimentales.")
            node = next(item for item in graph["nodes"] if item["data"]["type"] == "Prompt")
            digest = graph_digest(graph)
            if self._graph is not None and self._graph != digest:
                raise AnalyticsError("Cambió el flujo durante el experimento. Se detuvo la ejecución.")
            self._graph, self._prompt_node = digest, node["id"]
        except (OSError, AttributeError, KeyError, TypeError, StopIteration, ValueError):
            raise AnalyticsError("El flujo operativo no cumple el contrato de experimentación.") from None

    def _predict(self, case: Case, version: PromptVersion, check_cancel: Callable[[], None]) -> Prediction:
        text = "Título: " + case.text
        if len(text) > self.policy.max_case_chars:
            return Prediction(None, None, review="texto_fuera_del_limite")
        if SUSPICIOUS.search(text):
            return Prediction(None, None, review="posible_inyeccion")
        try:
            protected = protect_text(text, known_secrets=self.operational.privacy_secrets()).text
        except PrivacyError:
            return Prediction(None, None, review="privacidad_no_disponible")
        while (delay := self.next_call - monotonic()) > 0:
            check_cancel()
            sleep(min(delay, .25))
        check_cancel()
        self.verify_actor()
        self._verify_graph()
        if self.calls >= self.quote["planned_flow_calls"]:
            raise AnalyticsError("Se alcanzó el límite autorizado de solicitudes.")
        self.calls += 1
        self.event("solicitud_cloud_reservada", requests=self.calls,
                   maximum_provider_attempts=self.calls * self.policy.attempts_per_flow,
                   cost_ceiling_usd=str(self.policy.max_cost_per_flow_usd * self.calls))
        payload = {"input_value": f"<reporte>\n{escape(protected, quote=False)}\n</reporte>",
                   "input_type": "chat", "output_type": "chat", "session_id": str(uuid4())}
        if self.policy.prompts[version.id] is not None:
            payload["tweaks"] = {self._prompt_node: {"template": version.text}}
        started = monotonic()
        self.next_call = started + self.policy.seconds_between_calls
        try:
            response = self.client.run_once(payload)
        except ServiceError as error:
            self.errors += 1
            elapsed = monotonic() - started
            self.event("fallo_tecnico_cloud", requests=self.calls, flow_seconds=elapsed, http_status=error.status_code)
            if error.status_code in (401, 403, 404, 429) or self.errors >= self.policy.max_consecutive_errors:
                raise AnalyticsError("LangFlow rechazó las solicitudes o alcanzó su límite. Se detuvo el consumo.") from None
            return Prediction(None, None, review="langflow_no_disponible", flow_seconds=elapsed, technical_failure=True)
        details = {"flow_seconds": monotonic() - started}
        try:
            message = response["outputs"][0]["outputs"][0]["results"]["message"]
            metadata = message.get("session_metadata", {})
            metadata = metadata if isinstance(metadata, dict) else {}
            provider = metadata.get("soc_provider")
            details.update(provider=provider if provider in ("groq", "gemini") else None, **_telemetry(metadata))
            model = metadata.get("soc_model")
            if isinstance(model, str) and re.fullmatch(r"[a-zA-Z0-9._:/-]{1,160}", model):
                details["model"] = model
                details["model_scope"] = metadata.get("soc_model_scope") if metadata.get("soc_model_scope") in ("response", "requested") else None
            trace = valid_trace(metadata)
            if metadata.get("soc_trace") is not None and trace is None:
                raise ValueError
            if trace and trace["outcome"] == "protective":
                details.update(provider=None, model=None, provider_seconds=None)
                self.errors += 1
                if self.errors >= self.policy.max_consecutive_errors:
                    raise AnalyticsError("Se alcanzó el límite de fallos consecutivos del proveedor.")
                return Prediction(None, None, review=trace["review_reason"],
                                  technical_failure=trace["review_reason"] == "proveedores_no_disponibles", **details)
            if trace:
                last = trace["attempts"][-1]
                if details.get("provider") != last["provider"] or details.get("model") != (last["response_model"] or last["model"]):
                    raise ValueError
            value = message["text"]
            if not isinstance(value, str) or len(value) > 4096:
                raise ValueError
            result = Classification.model_validate_json(value)
        except ValidationError as error:
            self.errors = 0
            issues = error.errors(include_url=False, include_context=False, include_input=False)
            taxonomy = sum(issue["type"] == "literal_error" and issue["loc"] in (("tipo",), ("severidad",))
                           for issue in issues)
            return Prediction(None, None, review="respuesta_langflow_invalida", taxonomy_error=bool(taxonomy),
                              format_error=taxonomy < len(issues), **details)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            self.errors = 0
            return Prediction(None, None, review="respuesta_langflow_invalida", format_error=True, **details)
        self.errors = 0
        return Prediction(getattr(result, self.target), result.confianza, **details)

    def prepare_final(self, parameters: dict, expected_graph: str) -> PromptVersion:
        """Bind a one-pass evaluation to its previously selected prompt and graph."""
        try:
            version = self.prompts[parameters["prompt"]]
            if version.sha256 != parameters["prompt_sha256"] or (version.id, parameters["threshold"]) not in self.options:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise AnalyticsError("La configuración de inferencia difiere de la versión final seleccionada.") from None
        self._graph = expected_graph
        self._verify_graph()
        return version

    def predict_final(self, case: Case, version: PromptVersion, guard: Callable[[], None]) -> Prediction:
        """Classify a held-out report once using the guarded flow."""
        return self._predict(case, version, guard)

    def verify_final(self) -> None:
        """Verify that the configured graph still matches the selected one."""
        self._verify_graph()

    def evaluate(self, train: tuple[Case, ...], validation: tuple[Case, ...], parameters: dict,
                 scope: str, check_cancel: Callable[[], None]) -> dict:
        if self._scope != scope:
            self._scope, self._predictions = scope, {}
        version = self.prompts[parameters["prompt"]]
        if version.sha256 != parameters["prompt_sha256"]:
            raise AnalyticsError("Cambió la huella del prompt seleccionado.")
        started = monotonic()
        labels, providers, reviews, observed, fresh = [], Counter(), Counter(), [], []
        prior_calls = self.calls
        for case in validation:
            check_cancel()
            key = version.id, case.key
            if key not in self._predictions:
                self._predictions[key] = self._predict(case, version, check_cancel)
                fresh.append(self._predictions[key])
            result = self._predictions[key]
            observed.append(result)
            if result.provider:
                providers[result.provider] += 1
            reason = result.review or ("confianza_baja" if result.confidence is not None and
                                        result.confidence < parameters["threshold"] else None)
            reason = reason or ("valor_sin_referencia" if result.label not in self.labels else None)
            if reason:
                reviews[reason] += 1
            labels.append(REVIEW if reason else result.label)
        metrics = objective_metrics([case.label for case in validation], labels, self.labels, self.target)
        metrics["latency_seconds"] = (sum(row.flow_seconds for row in observed) / len(observed)
                                       if all(row.flow_seconds is not None for row in observed) else None)
        models = Counter((row.provider, row.model, row.model_scope) for row in observed if row.provider)
        return {"score": macro_f1([case.label for case in validation], labels, self.labels), "metrics": metrics,
                "observed_models": [{"provider": provider, "model": model, "scope": scope, "rows": count}
                                    for (provider, model, scope), count in models.items()],
                "seconds": monotonic() - started, "flow_calls": self.calls - prior_calls,
                "consumption": {"rows_with_measured_latency": sum(row.flow_seconds is not None for row in observed),
                                "new_flow_calls": self.calls - prior_calls,
                                "new_observed_cost_usd": sum(row.cost_usd for row in fresh if row.flow_seconds is not None)
                                  if all(row.cost_usd is not None for row in fresh if row.flow_seconds is not None) else None},
                "observed_providers": dict(providers), "human_review": dict(reviews),
                "coverage": (len(validation) - sum(reviews.values())) / len(validation)}

    def publish(self, train: tuple[Case, ...], parameters: dict, directory: Path) -> dict:
        self._verify_graph()
        return {"graph_sha256": self._graph, "configuration": parameters, "flow_calls": self.calls,
                "configured_models": {"groq": self.settings.flow_validation.expected_groq_model,
                                      "gemini": self.settings.flow_validation.expected_gemini_model},
                "cost_ceiling_usd": str(self.policy.max_cost_per_flow_usd * self.calls), "actual_cost_usd": None}
