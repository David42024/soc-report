"""Phase-0 conformance of the existing cloud graph, references and safe export."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import json
from time import monotonic
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx
from dotenv import dotenv_values

from backend.classifier import Classification
from backend.config import Settings
from scripts.vcdb import SENSITIVE
from src.data.catalog import DatasetCatalog
from src.inference.services import SocApi
from src.utils.config import AnalyticsSettings, ApiSettings
from src.utils.errors import AnalyticsError, ServiceError
from src.utils.security import SENSITIVE_KEY


def graph_digest(graph: dict) -> str:
    """Canonical fingerprint, including variable names but never secret values."""
    return sha256(json.dumps(graph, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def cloud_node(graph: dict) -> dict:
    """Identify one pure classifier with the original input, prompt and output."""
    nodes = graph.get("nodes", [])
    types = [node.get("data", {}).get("type") for node in nodes]
    if sorted(types) != sorted(["ChatInput", "Prompt", "SocCloudModel", "ChatOutput"]):
        raise AnalyticsError("El flujo debe contener entrada, prompt, SocCloudModel y salida, sin sustituir el clasificador cloud.")
    node = next(node for node in nodes if node["data"]["type"] == "SocCloudModel")
    edges = graph.get("edges", [])
    by_type = {item["data"]["type"]: item["id"] for item in nodes}
    expected = {(by_type["ChatInput"], node["id"]), (by_type["Prompt"], node["id"]), (node["id"], by_type["ChatOutput"])}
    if {(edge.get("source"), edge.get("target")) for edge in edges} != expected:
        raise AnalyticsError("Las conexiones del flujo no corresponden al clasificador puro existente.")
    return node


def graph_contract(graph: dict, settings: AnalyticsSettings, *, require_bindings: bool = True) -> dict:
    """Compare production component, prompt, configured models and credential names."""
    node = cloud_node(graph)
    template = node["data"]["node"]["template"]
    expected = settings.flow_validation
    if template["code"]["value"].strip() != settings.path(expected.component_file).read_text(encoding="utf-8").strip():
        raise AnalyticsError("El código del componente persistido difiere de su fuente versionada. No se reemplazó automáticamente.")
    prompt = next(item for item in graph["nodes"] if item["data"]["type"] == "Prompt")["data"]["node"]["template"]["template"]["value"]
    if prompt.strip() != settings.path(expected.prompt_file).read_text(encoding="utf-8").strip():
        raise AnalyticsError("El prompt persistido y prompt.txt no coinciden. Se requiere resolver esa diferencia explícitamente.")
    models = {name: template[name]["value"] for name in ("groq_model", "gemini_model")}
    if models != {"groq_model": expected.expected_groq_model, "gemini_model": expected.expected_gemini_model}:
        raise AnalyticsError("Los modelos persistidos no coinciden con las referencias del SPEC. No se modificaron.")
    variables = {"groq_api_key": expected.groq_variable, "gemini_api_key": expected.gemini_variable}
    bound = all(template[name].get("load_from_db") is True and template[name].get("value") == variable
                for name, variable in variables.items())
    if require_bindings and not bound:
        raise AnalyticsError("El componente no está enlazado a las dos credenciales globales existentes.")
    return {"models": models, "credential_references_valid": bound,
            "component_sha256": sha256(template["code"]["value"].encode()).hexdigest(),
            "prompt_sha256": sha256(prompt.encode()).hexdigest()}


def without_bindings(graph: dict) -> dict:
    """Protect every other graph value while correcting reference bindings."""
    result = deepcopy(graph)
    template = cloud_node(result)["data"]["node"]["template"]
    for field in ("groq_api_key", "gemini_api_key"):
        template[field].pop("value", None)
        template[field].pop("load_from_db", None)
    return result


class LangflowConformance:
    """Use the configured LangFlow API; never create or replace provider keys."""

    def __init__(self, settings: AnalyticsSettings, operational: Settings,
                 *, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self.operational = operational
        self.base_url = ApiSettings.safe_url(operational.langflow_url)
        self.transport = transport

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.operational.langflow_timeout_seconds,
                              trust_env=False, follow_redirects=False, transport=self.transport) as client:
                response = client.request(method, path, headers={"x-api-key": self.operational.langflow_api_key}, **kwargs)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            raise ServiceError(f"LangFlow rechazó la solicitud (HTTP {status}).", status) from None
        except (httpx.HTTPError, ValueError):
            raise ServiceError("No se pudo comprobar LangFlow con su API y credencial actuales.") from None

    def _path(self, template: str) -> str:
        return template.format(flow_id=quote(self.operational.langflow_flow_id, safe=""))

    def fetch(self) -> dict:
        """Read only the configured graph, without automatic login or a new flow."""
        return self._request("GET", self._path(self.settings.flow_validation.flow_path))["data"]

    def run_once(self, payload: dict) -> dict:
        """Invoke the existing graph once with an authorized, protected payload."""
        return self._request("POST", self._path(self.settings.flow_validation.run_path), json=payload)

    def check(self) -> dict:
        """Distinguish runtime contract, credential linkage and export equivalence."""
        graph = self.fetch()
        details = graph_contract(graph, self.settings, require_bindings=False)
        matches = False
        try:
            exported = json.loads(self.settings.path(self.settings.flow_validation.export_file).read_text(encoding="utf-8-sig"))
            graph_contract(exported["data"], self.settings)
            matches = graph_digest(exported["data"]) == graph_digest(graph)
        except (OSError, ValueError, KeyError, TypeError, AnalyticsError):
            pass
        return {**details, "export_matches_runtime": matches, "graph_sha256": graph_digest(graph)}

    def synchronize(self) -> dict:
        """Fix variable references only, then export the same graph without keys."""
        before = self.fetch()
        graph_contract(before, self.settings, require_bindings=False)
        settings = self.settings.flow_validation
        existing = self._request("GET", settings.variables_path)
        names = {row.get("name") for row in existing if row.get("type") == "Credential"}
        if not {settings.groq_variable, settings.gemini_variable}.issubset(names):
            raise AnalyticsError("Faltan credenciales globales existentes. No se crearon claves ni se copiaron valores al flujo.")
        graph = deepcopy(before)
        template = cloud_node(graph)["data"]["node"]["template"]
        for field, name in (("groq_api_key", settings.groq_variable), ("gemini_api_key", settings.gemini_variable)):
            template[field].update(value=name, load_from_db=True)
        changed = graph_digest(graph) != graph_digest(before)
        if changed:
            self._request("PATCH", self._path(settings.flow_path), json={"data": graph})
        try:
            current = self.fetch()
            graph_contract(current, self.settings)
            if graph_digest(without_bindings(current)) != graph_digest(without_bindings(before)):
                raise AnalyticsError("La corrección cambió valores ajenos a los enlaces de credenciales.")
            serialized = json.dumps({"name": "SOC Report Router | Groq + Gemini", "is_component": False, "data": current},
                                    indent=2, ensure_ascii=False) + "\n"
            if any(word in serialized.lower() for word in ("ollama", "qwen")):
                raise AnalyticsError("El export aún contiene referencias heredadas a proveedores locales.")
            secrets = dotenv_values(self.settings.root / ".env")
            if any(value and len(value) >= 8 and SENSITIVE_KEY.search(key) and value in serialized
                   for key, value in secrets.items()):
                raise AnalyticsError("El export contiene un valor sensible; no se escribió.")
            destination = self.settings.path(settings.export_file)
            temporary = destination.with_suffix(".json.tmp")
            temporary.write_text(serialized, encoding="utf-8")
            temporary.replace(destination)
        except Exception:
            if changed:
                self._request("PATCH", self._path(settings.flow_path), json={"data": before})
            raise
        return {**self.check(), "credential_bindings_corrected": changed}

    def probe(self, *, force_fallback: bool = False) -> dict:
        """Probe one existing redacted pilot case; never mutate the stored graph."""
        settings = self.settings.flow_validation
        before = self.fetch()
        graph_contract(before, self.settings)
        source = DatasetCatalog(self.settings, SocApi(self.settings.api)).source(settings.probe_source_id)
        if source.kind != "json_cases" or source.path is None:
            raise AnalyticsError("La comprobación requiere un manifiesto original de casos JSON.")
        data = json.loads(self.settings.path(source.path).read_text(encoding="utf-8-sig"))
        case = data["cases"][settings.probe_case_index]
        text = f"Título: {case['titulo']}\n{case['descripcion']}"
        if case.get("redaction_reviewed") is not True or SENSITIVE.search(text):
            raise AnalyticsError("La prueba requiere un caso original con revisión de redacción y sin indicadores sensibles.")
        payload = {"input_value": f"<reporte>\n{escape(text, quote=False)}\n</reporte>",
                   "input_type": "chat", "output_type": "chat", "session_id": str(uuid4())}
        if force_fallback:
            payload["tweaks"] = {cloud_node(before)["id"]: {"groq_model": settings.invalid_primary_model}}
        started = monotonic()
        result = self._request("POST", self._path(settings.run_path), json=payload)
        try:
            message = result["outputs"][0]["outputs"][0]["results"]["message"]
            classification = Classification.model_validate_json(message["text"])
            provider = message.get("session_metadata", {}).get("soc_provider")
            if provider != ("gemini" if force_fallback else "groq"):
                raise AnalyticsError("El proveedor observado no coincide con el objetivo de esta comprobación.")
            if graph_digest(self.fetch()) != graph_digest(before):
                raise AnalyticsError("El grafo persistido cambió durante la prueba; la comprobación no es conforme.")
        except (ValueError, KeyError, IndexError, TypeError):
            raise AnalyticsError("La prueba no produjo una clasificación válida con proveedor auditable.") from None
        return {"provider": provider, "model": settings.expected_gemini_model if force_fallback else settings.expected_groq_model,
                "classification_contract_valid": True, "fields": sorted(type(classification).model_fields),
                "seconds_single_observation": round(monotonic() - started, 3), "source_id": settings.probe_source_id,
                "input_sha256": sha256(text.encode()).hexdigest(), "runtime_graph_unchanged": True,
                "technical_failure_injected": "modelo Groq inexistente por tweak solo en esta petición" if force_fallback else None}


def write_conformance_report(settings: AnalyticsSettings, result: dict) -> None:
    """Keep technical evidence in ignored runs/, with no prompts or secrets."""
    path = settings.path(settings.flow_validation.result_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = {"at_utc": datetime.now(timezone.utc).isoformat(), **result}
    path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
