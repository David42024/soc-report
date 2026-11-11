import json
import re
import unicodedata
from html import escape
from hashlib import sha256
from typing import Literal
from urllib.parse import quote
from uuid import uuid4
from time import monotonic

import httpx
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator

from src.utils.privacy import PrivacyError, ProtectedText, load_policy, protect_text
from src.inference.telemetry import valid_trace

Tipo = Literal[
    "phishing", "malware", "acceso_no_autorizado", "ddos", "fuga_datos",
    "vulnerabilidad", "uso_indebido", "incidente_fisico", "fraude", "otro",
]
Severidad = Literal["critica", "alta", "media", "baja"]

SUSPICIOUS = re.compile(
    r"(?:ignora|omite|ignore|disregard).{0,45}(?:instrucciones|instructions)"
    r"|(?:system|assistant)\s*:|<\|im_(?:start|end)\|>|</?reporte\s*>",
    re.IGNORECASE | re.DOTALL,
)


class Classification(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tipo: Tipo
    severidad: Severidad
    activo_afectado: str | None = Field(max_length=160)
    confianza: float = Field(ge=0, le=1, allow_inf_nan=False)
    _provider: Literal["groq", "gemini"] | None = PrivateAttr(default=None)
    _privacy: dict | None = PrivateAttr(default=None)
    _explanation_input: dict | None = PrivateAttr(default=None)
    _review_reason: str | None = PrivateAttr(default=None)

    @property
    def provider(self):
        return self._provider

    @property
    def privacy(self) -> dict | None:
        """Non-sensitive evidence of the local egress filter, outside the LLM contract."""
        return self._privacy

    @property
    def explanation_input(self) -> dict | None:
        """Protected request snapshot, stored separately from operational predictions."""
        return self._explanation_input

    @field_validator("activo_afectado")
    @classmethod
    def validate_asset(cls, value):
        if value is not None and (not value.strip() or "\x00" in value):
            raise ValueError("Activo inválido.")
        return value


def demo_classify(text: str) -> Classification:
    plain = "".join(
        c for c in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(c) != "Mn"
    )
    categories = (
        ("fuga_datos", ("fuga de datos", "exfiltracion", "datos filtrados")),
        ("malware", ("ransomware", "malware", "troyano", "archivos cifrados")),
        ("phishing", ("phishing", "correo falso", "enlace sospechoso", "suplantacion")),
        ("acceso_no_autorizado", ("acceso no autorizado", "inicio de sesion desconocido")),
        ("ddos", ("ddos", "denegacion de servicio")),
        ("vulnerabilidad", ("vulnerabilidad", "cve-")),
        ("uso_indebido", ("uso indebido",)),
        ("incidente_fisico", ("robo", "acceso fisico")),
        ("fraude", ("fraude", "estafa")),
    )
    category = next((key for key, words in categories if any(w in plain for w in words)), "otro")
    severity = "media"
    if any(word in plain for word in ("servicio caido", "ransomware", "exfiltracion confirmada")):
        severity = "critica"
    elif category in {"fuga_datos", "malware", "acceso_no_autorizado", "ddos"}:
        severity = "alta"
    match = re.search(r"^\s*activo\s*:\s*([^\n]+)", text, re.MULTILINE | re.IGNORECASE)
    return Classification(
        tipo=category, severidad=severity,
        activo_afectado=(match.group(1).strip()[:160] or None) if match else None,
        confianza=0.85 if category != "otro" else 0.35,
    )


def langflow_classify(text: str, settings) -> Classification:
    """Send a minimized report to the existing local graph and validate its response."""
    # Minimize before the local orchestration boundary too: LangFlow can retain
    # messages/traces, so it must never receive the original report body.
    protected = protect_text(text, known_secrets=settings.privacy_secrets())
    url = f"{settings.langflow_url.rstrip('/')}/api/v1/run/{quote(settings.langflow_flow_id, safe='')}"
    clean = protected.text
    with httpx.Client(timeout=settings.langflow_timeout_seconds, trust_env=False) as client:
        response = client.post(
            url,
            headers={"x-api-key": settings.langflow_api_key},
            json={
                "input_value": f"<reporte>\n{escape(clean, quote=False)}\n</reporte>",
                "input_type": "chat",
                "output_type": "chat",
                "session_id": str(uuid4()),
            },
        )
        response.raise_for_status()
    message = response.json()["outputs"][0]["outputs"][0]["results"]["message"]
    result = message["text"]
    metadata = message.get("session_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    trace = valid_trace(metadata)
    errors = {"format": False, "taxonomy": False}
    try:
        if not isinstance(result, str) or len(result) > 4096:
            raise ValueError
        classification = Classification.model_validate(json.loads(result))
    except ValueError as error:
        issues = error.errors(include_input=False, include_context=False) if hasattr(error, "errors") else []
        errors["taxonomy"] = any(issue["type"] == "literal_error" and issue["loc"] in (("tipo",), ("severidad",)) for issue in issues)
        errors["format"] = not issues or any(issue["type"] != "literal_error" for issue in issues)
        classification = _safe_classification("respuesta_langflow_invalida")
    if metadata.get("soc_trace") is not None and trace is None:
        classification = _safe_classification("respuesta_langflow_invalida")
        errors["format"] = True
        metadata = {}
    if trace:
        last = trace["attempts"][-1]
        if trace["outcome"] == "protective":
            classification = _safe_classification(trace["review_reason"])
        elif metadata.get("soc_provider") != last["provider"] or metadata.get("soc_model") != (last["response_model"] or last["model"]):
            classification = _safe_classification("respuesta_langflow_invalida")
            trace, errors["format"] = None, True
            metadata = {}
    _capture_input(classification, text, protected, metadata, trace, errors, settings.langflow_flow_id, settings.privacy_secrets())
    return classification


def _safe_classification(reason: str) -> Classification:
    """Use the operational safe taxonomy while preserving the reason for human review."""
    result = Classification(tipo="otro", severidad="media", activo_afectado=None, confianza=0.0)
    result._review_reason = reason
    return result


def _capture_input(classification: Classification, text: str, protected: ProtectedText, metadata: dict,
                   trace: dict | None, errors: dict, flow_id: str | None = None,
                   known_secrets: tuple[str, ...] = ()) -> None:
    """Capture a minimized, integrity-bound observation outside the LLM response contract."""
    classification._privacy = protected.evidence
    if metadata.get("soc_provider") in ("groq", "gemini"):
        classification._provider = metadata["soc_provider"]
    classification._explanation_input = {
        "schema_version": 1, "text": protected.text, "input_sha256": sha256(protected.text.encode("utf-8")).hexdigest(),
        "privacy": protected.evidence, "provider": classification.provider,
        "model": None, "prompt_sha256": None, "flow_id": flow_id,
        "model_scope": metadata.get("soc_model_scope") if metadata.get("soc_model_scope") in ("response", "requested") else "legacy",
        "scope": "entrada_fastapi_langflow" if flow_id else "entrada_fastapi",
        "original_sha256": sha256(text.encode("utf-8")).hexdigest(),
        "classification_sha256": sha256(json.dumps(classification.model_dump(), ensure_ascii=False, sort_keys=True,
                                                   separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest(),
        "trace": trace, "response_errors": errors,
    }
    model = metadata.get("soc_model")
    prompt_hash = metadata.get("soc_prompt_sha256")
    if isinstance(model, str) and re.fullmatch(r"[a-zA-Z0-9._:/-]{1,160}", model):
        classification._explanation_input["model"] = model
    if isinstance(prompt_hash, str) and re.fullmatch(r"[a-f0-9]{64}", prompt_hash):
        classification._explanation_input["prompt_sha256"] = prompt_hash
    provider_text, provider_hash = metadata.get("soc_input_text"), metadata.get("soc_input_sha256")
    if (isinstance(provider_text, str) and len(provider_text) <= load_policy().max_characters and
            sha256(provider_text.encode("utf-8")).hexdigest() == provider_hash):
        # Known server secrets were removed before the LangFlow boundary. Verify
        # the returned snapshot again with the same policy and secret inventory.
        reprotected = protect_text(provider_text, known_secrets=known_secrets)
        if reprotected.text == provider_text:
            classification._explanation_input.update(text=provider_text, input_sha256=provider_hash, scope="entrada_proveedor")


def classify(titulo, descripcion, settings, *, threshold=0.75):
    started = monotonic()
    text = f"Título: {titulo}\n{descripcion}"
    try:
        protected = protect_text(text, known_secrets=settings.privacy_secrets())
    except PrivacyError:
        fallback = _safe_classification("privacidad_no_disponible")
        fallback._privacy = {"status": "blocked", "reason": "policy_unavailable_or_invalid"}
        return fallback, "fallback", "privacidad_no_disponible"
    if SUSPICIOUS.search(text):
        reason = "posible_inyeccion"
    else:
        try:
            result = (
                langflow_classify(text, settings)
                if settings.classifier_mode == "langflow" else demo_classify(text)
            )
            reason = result._review_reason or ("confianza_baja" if result.confianza < threshold else None)
            if result.explanation_input is None:
                _capture_input(result, text, protected, {}, None, {"format": False, "taxonomy": False},
                               known_secrets=settings.privacy_secrets())
            result._explanation_input["classification_call_seconds"] = max(0.0, monotonic() - started)
            return result, "fallback" if result._review_reason else settings.classifier_mode, reason
        except PrivacyError:
            reason = "privacidad_no_disponible"
        except httpx.HTTPError:
            reason = "langflow_no_disponible"
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            reason = "respuesta_langflow_invalida"
    fallback = _safe_classification(reason)
    _capture_input(fallback, text, protected, {}, None, {"format": reason == "respuesta_langflow_invalida", "taxonomy": False},
                   settings.langflow_flow_id if settings.classifier_mode == "langflow" else None, settings.privacy_secrets())
    fallback._explanation_input["classification_call_seconds"] = max(0.0, monotonic() - started)
    return fallback, "fallback", reason
