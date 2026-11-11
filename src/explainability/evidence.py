"""Observable, extractive evidence and bounded validation of cited claims."""
from __future__ import annotations

from hashlib import sha256
import re

from backend.classifier import Classification
from src.data.models import content_hash
from src.explainability.settings import ExplainabilitySettings
from src.utils.errors import AnalyticsError


def text_hash(text: str) -> str:
    """Fingerprint exact UTF-8 characters, including spacing and accents."""
    return sha256(text.encode("utf-8")).hexdigest()


def extract_evidence(text: str, prediction: dict, policy: ExplainabilitySettings) -> dict:
    """Link lexical matches to configured criteria without asserting semantic truth."""
    result = Classification.model_validate(prediction).model_dump()
    claims = []
    for criterion in policy.criteria:
        if result[criterion.field] != criterion.value:
            continue
        for phrase in criterion.phrases:
            for match in re.finditer(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text, flags=re.I):
                prefix = text[max(0, match.start() - 70):match.start()].casefold()
                negated = any(prefix.rstrip().endswith(item.casefold()) for item in policy.negation_prefixes)
                claims.append({"field": criterion.field, "value": criterion.value, "start": match.start(), "end": match.end(),
                               "quote": match.group(), "criterion": criterion.description, "negated": negated})
    asset = result["activo_afectado"]
    if asset:
        for match in re.finditer(re.escape(asset), text, flags=re.I):
            claims.append({"field": "activo_afectado", "value": asset, "start": match.start(), "end": match.end(),
                           "quote": match.group(), "criterion": "El nombre del activo aparece en la entrada.", "negated": False})
    unique = {(item["field"], item["start"], item["end"]): item for item in claims}
    claims = sorted(unique.values(), key=lambda item: (item["start"], item["end"], item["field"]))[:policy.max_spans]
    checked = validate_claims(text, result, claims, policy)
    supported = {item["field"] for item in claims if not item["negated"]}
    absent = [field for field in ("tipo", "severidad", "activo_afectado") if result[field] is not None and field not in supported]
    fragments = [item["quote"] for item in claims if not item["negated"]]
    summary = ("Coincidencias textuales observables. " + ", ".join(dict.fromkeys(fragments))) if fragments else "Sin fragmentos de apoyo identificados por los criterios configurados."
    return {"method": "justificacion_extractiva_local", "criteria_version": policy.criteria_version,
            "criteria_sha256": content_hash([item.model_dump() for item in policy.criteria]),
            "input_sha256": text_hash(text), "classification": result, "claims": claims, "validation": checked,
            "unsupported_fields": absent, "summary": summary,
            "limitation": "Las coincidencias léxicas requieren revisión semántica. La justificación describe evidencia observable y no revela el razonamiento interno del proveedor."}


def validate_claims(text: str, prediction: dict, claims: list[dict], policy: ExplainabilitySettings | None = None) -> dict:
    """Check literal spans, declared outputs, negation and unsupported claim types."""
    issues = []
    for i, claim in enumerate(claims):
        field = claim.get("field")
        start, end, quote = claim.get("start"), claim.get("end"), claim.get("quote")
        valid_span = (type(start) is int and type(end) is int and 0 <= start < end <= len(text)
                      and isinstance(quote, str) and text[start:end] == quote)
        if not valid_span:
            issues.append({"claim": i, "code": "cita_ausente"})
        if field not in ("tipo", "severidad", "activo_afectado"):
            issues.append({"claim": i, "code": "afirmacion_no_admitida"})
        elif claim.get("value") != prediction.get(field):
            issues.append({"claim": i, "code": "contradice_clasificacion"})
        negated = bool(claim.get("negated"))
        if valid_span and policy is not None:
            prefix = text[max(0, start - 70):start].casefold().rstrip()
            negated = negated or any(prefix.endswith(item.casefold()) for item in policy.negation_prefixes)
            if field in ("tipo", "severidad") and not any(
                criterion.field == field and criterion.value == claim.get("value") and
                any(re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", quote, re.I) for phrase in criterion.phrases)
                for criterion in policy.criteria
            ):
                issues.append({"claim": i, "code": "afirmacion_sin_criterio_observable"})
        if negated:
            issues.append({"claim": i, "code": "evidencia_negada"})
    invalid_citations = {item["claim"] for item in issues if item["code"] == "cita_ausente"}
    return {"claims": len(claims), "literal_quotes": len(claims) - len(invalid_citations), "issues": issues,
            "status": "sin_citas" if not claims else "requiere_revision" if issues else "citas_verificadas"}


def validate_spans(text: str, spans: list[dict], maximum: int) -> list[dict]:
    """Validate explicit human character intervals before registering a reference."""
    if not isinstance(spans, list) or not 1 <= len(spans) <= maximum:
        raise AnalyticsError("Registra al menos un intervalo humano dentro del límite configurado.")
    result = []
    for item in spans:
        if not isinstance(item, dict) or set(item) != {"start", "end"}:
            raise AnalyticsError("Cada intervalo requiere exclusivamente start y end.")
        start, end = item["start"], item["end"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text) or not text[start:end].strip():
            raise AnalyticsError("Los intervalos humanos deben apuntar a caracteres existentes y no vacíos.")
        result.append({"start": start, "end": end})
    result.sort(key=lambda item: item["start"])
    if any(a["end"] > b["start"] for a, b in zip(result, result[1:])):
        raise AnalyticsError("Los intervalos humanos se solapan.")
    return result


def overlap(text: str, predicted: list[dict], human: dict | None) -> dict:
    """Compare character sets only against a verified, nonempty human reference."""
    if human is None:
        return {"applicable": False, "reason": "Faltan anotaciones humanas de fragmentos para esta entrada."}
    if human.get("input_sha256") != text_hash(text):
        raise AnalyticsError("La anotación humana corresponde a otra versión del texto.")
    expected = validate_spans(text, human["spans"], len(human["spans"]))
    observed = validate_spans(text, predicted, max(1, len(predicted))) if predicted else []
    units = lambda spans: {i for span in spans for i in range(span["start"], span["end"]) if not text[i].isspace()}
    a, b = units(observed), units(expected)
    intersection = len(a & b)
    return {"applicable": True, "unit": "caracter_no_blanco", "human_characters": len(b), "explanation_characters": len(a),
            "iou": intersection / len(a | b), "precision": intersection / len(a) if a else 0.0,
            "recall": intersection / len(b), "annotation_id": human["run_id"], "independence": human["independence"]}
