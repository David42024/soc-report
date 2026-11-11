"""Versioned, allowlisted observables from cloud attempts and report timestamps."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from math import isfinite
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

Provider = Literal["groq", "gemini"]
AttemptOutcome = Literal["ok", "http_error", "transport_error", "invalid_response", "policy_rejected"]
ReviewReason = Literal["proveedores_no_disponibles", "rechazo_politica_proveedor"]


class ProviderAttempt(BaseModel):
    """A bounded transport observation which never contains an upstream body."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    provider: Provider
    model: str = Field(pattern=r"^[a-zA-Z0-9._:/-]{1,160}$")
    response_model: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9._:/-]{1,160}$")
    outcome: AttemptOutcome
    seconds: float = Field(ge=0, le=3600, allow_inf_nan=False)
    http_status: int | None = Field(default=None, ge=100, le=599)


class CloudTrace(BaseModel):
    """Provider provenance independent of the four-field classification contract."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal[1] = 1
    outcome: Literal["classified", "protective"]
    attempts: list[ProviderAttempt] = Field(min_length=1, max_length=3)
    technical_fallback: bool
    review_reason: ReviewReason | None = None

    @model_validator(mode="after")
    def valid_sequence(self) -> CloudTrace:
        providers = [attempt.provider for attempt in self.attempts]
        if providers[0] != "groq" or providers[1:] not in ([], ["gemini"], ["gemini", "gemini"]):
            raise ValueError("Secuencia de proveedores inválida.")
        if self.technical_fallback != ("gemini" in providers):
            raise ValueError("El indicador de conmutación no coincide con los intentos.")
        if len(self.attempts) > 1 and self.attempts[0].outcome in ("ok", "policy_rejected"):
            raise ValueError("Una respuesta correcta o un rechazo de política no activa Gemini.")
        if len(self.attempts) == 3:
            previous = self.attempts[1]
            if previous.outcome != "transport_error" and not (
                previous.outcome == "http_error" and previous.http_status is not None and
                (previous.http_status == 408 or previous.http_status >= 500)
            ):
                raise ValueError("El reintento de Gemini requiere un fallo transitorio.")
        if self.outcome == "classified" and (self.attempts[-1].outcome != "ok" or self.review_reason is not None):
            raise ValueError("Falta una respuesta de clasificación observable.")
        if self.outcome == "protective":
            last = self.attempts[-1].outcome
            expected = "rechazo_politica_proveedor" if last == "policy_rejected" else "proveedores_no_disponibles"
            if last == "ok" or self.review_reason != expected:
                raise ValueError("La salida protectora requiere un motivo coherente con el fallo.")
        return self


def valid_trace(metadata: dict) -> dict | None:
    """Discard absent/invalid telemetry without guessing a provider or a duration."""
    try:
        return CloudTrace.model_validate(metadata.get("soc_trace")).model_dump()
    except (ValidationError, TypeError):
        return None


def elapsed(start: object, end: object) -> float | None:
    """Compute an observed elapsed duration only from ordered, aware timestamps."""
    if not start or not end:
        return None
    try:
        first = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        last = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        seconds = (last - first).total_seconds()
        return seconds if first.tzinfo and last.tzinfo and isfinite(seconds) and seconds >= 0 else None
    except (ValueError, TypeError):
        return None


def percentiles(values: list[float]) -> dict:
    """Return descriptive sample quantiles, including the observed denominator."""
    return {"n": len(values), "p50_s": float(np.quantile(values, .5)) if values else None,
            "p95_s": float(np.quantile(values, .95)) if values else None}


def observed_metrics(rows: list[dict], minimum: int, objective: float) -> dict:
    """Summarize unique non-DEMO reports, keeping missing provenance observable."""
    eligible = [row for row in rows if not row["demo"]]
    responder, attempts, repeated = Counter(), [], defaultdict(list)
    traces, technical_fallbacks = 0, 0
    for row in eligible:
        captured = row.get("input") or {}
        trace = valid_trace({"soc_trace": captured.get("trace")})
        if captured.get("provider") in ("groq", "gemini"):
            responder[(captured["provider"], captured.get("model"))] += 1
        if trace:
            traces += 1
            technical_fallbacks += trace["technical_fallback"]
            attempts.extend(trace["attempts"])
        identity = tuple(captured.get(key) for key in ("input_sha256", "provider", "model", "prompt_sha256"))
        if all(identity) and row["origin"] != "fallback":
            repeated[identity].append((row["tipo"], row["severidad"], row.get("activo_afectado")))
    measured = {name: percentiles([value for row in eligible if (value := elapsed(row["received_at"], row.get(field))) is not None])
                for name, field in (("classification", "classified_at"), ("end_to_end", "notified_at"))}
    measured["providers"] = {name: percentiles([attempt["seconds"] for attempt in attempts if attempt["provider"] == name])
                             for name in ("groq", "gemini")}
    repeats = [predictions for predictions in repeated.values() if len(predictions) > 1]
    latest = measured["end_to_end"]
    comparison = ("sin_mediciones" if latest["p95_s"] is None else
                  "p95_observado_inferior_a_meta" if latest["p95_s"] < objective else "p95_observado_igual_o_superior_a_meta")
    critical = [row for row in eligible if row.get("human_severity") == "critica"]
    classified_critical = [row for row in critical if row["origin"] != "fallback"]
    lower = sum(row["severidad"] != "critica" for row in classified_critical)
    return {"rows": len(rows), "demo_excluded": len(rows) - len(eligible), "non_demo": len(eligible),
            "traces": traces, "without_trace": len(eligible) - traces,
            "responders": [{"provider": provider, "model": model, "n": n} for (provider, model), n in responder.items()],
            "attempts": len(attempts), "technical_failures": sum(a["outcome"] in ("http_error", "transport_error", "invalid_response") for a in attempts),
            "policy_rejections": sum(a["outcome"] == "policy_rejected" for a in attempts),
            "gemini_attempts": sum(a["provider"] == "gemini" for a in attempts),
            "technical_fallbacks": technical_fallbacks,
            "safe_origin_fallbacks": sum(row["origin"] == "fallback" for row in eligible),
            "review": sum(bool(row["review"]) for row in eligible),
            "format_errors": sum(bool((row.get("input") or {}).get("response_errors", {}).get("format")) for row in eligible),
            "taxonomy_errors": sum(bool((row.get("input") or {}).get("response_errors", {}).get("taxonomy")) for row in eligible),
            "human_reviewed": sum(row.get("human_severity") is not None for row in eligible),
            "critical_reference": len(critical),
            "critical_classified": len(classified_critical),
            "critical_protective": len(critical) - len(classified_critical),
            "critical_lower": lower,
            "critical_lower_rate": lower / len(classified_critical) if classified_critical else None,
            "latency": measured, "target_p95_seconds": objective, "sample_minimum": minimum,
            "sample_sufficient": latest["n"] >= minimum, "target_comparison": comparison,
            "compliance": "pendiente_de_evidencia_representativa",
            "repeatability": {"groups": len(repeats), "observations": sum(map(len, repeats)),
                              "modal_agreement": sum(Counter(values).most_common(1)[0][1] for values in repeats) /
                              sum(map(len, repeats)) if repeats else None},
            "limitations": "Percentiles descriptivos de reportes observados. La representatividad y la independencia entre campañas "
                            "están sin verificar. La concordancia repetida usa la misma entrada protegida, proveedor, modelo y prompt. "
                            "Compara tipo, severidad y activo; no incluye decisiones de umbral. Un identificador informado también puede ser un alias mutable. "
                            "Las revisiones operativas son retrospectivas y no constituyen un holdout independiente."}
