import json
import re
import unicodedata
from html import escape
from typing import Literal
from urllib.parse import quote
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

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


def langflow_classify(text, settings) -> Classification:
    url = f"{settings.langflow_url.rstrip('/')}/api/v1/run/{quote(settings.langflow_flow_id, safe='')}"
    clean = "".join(c for c in text if c in "\n\t" or not unicodedata.category(c).startswith("C"))
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
    result = response.json()["outputs"][0]["outputs"][0]["results"]["message"]["text"]
    if not isinstance(result, str) or len(result) > 4096:
        raise ValueError("Salida del clasificador inválida.")
    return Classification.model_validate(json.loads(result))


def classify(titulo, descripcion, settings, *, threshold=0.75):
    text = f"Título: {titulo}\n{descripcion}"
    if SUSPICIOUS.search(text):
        reason = "posible_inyeccion"
    else:
        try:
            result = (
                langflow_classify(text, settings)
                if settings.classifier_mode == "langflow" else demo_classify(text)
            )
            reason = "confianza_baja" if result.confianza < threshold else None
            return result, settings.classifier_mode, reason
        except httpx.HTTPError:
            reason = "langflow_no_disponible"
        except (ValueError, KeyError, IndexError, TypeError):
            reason = "respuesta_langflow_invalida"
    fallback = Classification(tipo="otro", severidad="media", activo_afectado=None, confianza=0.0)
    return fallback, "fallback", reason
