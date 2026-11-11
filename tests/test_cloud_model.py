import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import httpx
from pydantic import SecretStr


def load_cloud_component():
    # The app's venv does not include Langflow. Stub only its component and UI types.
    modules = {}
    for path, attributes in {
        "lfx.custom.custom_component.component": {"Component": SimpleNamespace},
        "lfx.io": dict.fromkeys(("MessageInput", "Output", "SecretStrInput", "StrInput"), SimpleNamespace),
        "lfx.schema.message": {"Message": SimpleNamespace},
        "lfx.utils.secrets": {"secret_value_to_str": lambda key: key.get_secret_value()},
    }.items():
        modules[path] = ModuleType(path)
        vars(modules[path]).update(attributes)
    source = Path(__file__).resolve().parents[1] / "integrations/langflow/cloud_classifier_model.py"
    spec = importlib.util.spec_from_file_location("soc_cloud_test_module", source)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module.SocCloudModel


class CloudModelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.model = load_cloud_component()(
            system_message=SimpleNamespace(text="Instrucciones de clasificación."),
            input_value=SimpleNamespace(text="Reporte ficticio."),
            groq_model="openai/gpt-oss-20b",
            gemini_model="gemini-3-flash-preview",
            groq_api_key=SecretStr("test-groq"),
            gemini_api_key=SecretStr("test-gemini"),
        )
        self.hosts = []

    async def run_model(self, groq, gemini=None):
        client_type = httpx.AsyncClient

        def handle(request):
            host = request.url.host
            self.hosts.append(host)
            body = json.loads(request.content)
            if host == "api.groq.com":
                self.assertEqual(request.url.path, "/openai/v1/chat/completions")
                self.assertEqual(request.headers["Authorization"], "Bearer test-groq")
                self.assertEqual(body["model"], self.model.groq_model)
                self.assertEqual(body["messages"], [
                    {"role": "system", "content": "Instrucciones de clasificación."},
                    {"role": "user", "content": "Reporte ficticio."},
                ])
                self.assertTrue(body["response_format"]["json_schema"]["strict"])
                return groq(request) if callable(groq) else groq
            self.assertEqual(host, "generativelanguage.googleapis.com")
            self.assertEqual(request.url.path, f"/v1beta/models/{self.model.gemini_model}:generateContent")
            self.assertEqual(request.headers["x-goog-api-key"], "test-gemini")
            self.assertEqual(body["contents"][0]["parts"][0]["text"], "Reporte ficticio.")
            self.assertEqual(body["systemInstruction"]["parts"][0]["text"], "Instrucciones de clasificación.")
            self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
            self.assertFalse(body["generationConfig"]["responseJsonSchema"]["additionalProperties"])
            self.assertEqual(body["generationConfig"]["thinkingConfig"], {"thinkingLevel": "low"})
            self.assertIsNotNone(gemini, "Gemini no debía recibir esta solicitud")
            return gemini(request) if callable(gemini) else gemini

        with patch.object(httpx, "AsyncClient", side_effect=lambda **kwargs: client_type(
            transport=httpx.MockTransport(handle), **kwargs
        )):
            return await self.model.classify()

    async def test_primary_success_does_not_send_the_report_to_gemini(self):
        result = await self.run_model(httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]}))
        self.assertEqual((result.text, self.model.status, self.hosts), ("{}", "Groq", ["api.groq.com"]))
        self.assertEqual(result.session_metadata["soc_provider"], "groq")
        self.assertEqual(result.session_metadata["soc_privacy"]["status"], "protected")

    async def test_transient_errors_use_gemini_and_ignore_thought_parts(self):
        def timed_out(request):
            raise httpx.ReadTimeout("simulated", request=request)

        for failure in (httpx.Response(408), httpx.Response(429), httpx.Response(500), httpx.Response(503), timed_out):
            with self.subTest(failure=failure):
                self.hosts.clear()
                gemini = httpx.Response(200, json={"candidates": [{"content": {"parts": [
                    {"thought": True, "text": "internal"}, {"text": "{"}, {"text": "}"},
                ]}}]})
                result = await self.run_model(failure, gemini)
                self.assertEqual((result.text, self.model.status), ("{}", "Gemini"))
                self.assertEqual(result.session_metadata["soc_provider"], "gemini")
                self.assertEqual(result.session_metadata["soc_privacy"]["status"], "protected")
                self.assertEqual(self.hosts, ["api.groq.com", "generativelanguage.googleapis.com"])

    async def test_permanent_provider_errors_and_bad_responses_use_gemini(self):
        failures = [httpx.Response(status) for status in (400, 401, 403, 404)]
        failures.extend(httpx.Response(200, json=payload) for payload in ({}, {"choices": []}, {"choices": [{"message": {"content": " "}}]}))
        gemini = httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})
        for failure in failures:
            with self.subTest(failure=failure):
                self.hosts.clear()
                self.assertEqual((await self.run_model(failure, gemini)).text, "{}")
                self.assertEqual(self.hosts, ["api.groq.com", "generativelanguage.googleapis.com"])

    async def test_content_policy_rejection_does_not_try_the_other_provider(self):
        result = await self.run_model(httpx.Response(400, json={"error": {"code": "content_policy_violation"}}))
        self.assertEqual(json.loads(result.text)["confianza"], 0.0)
        self.assertIsNone(result.session_metadata["soc_provider"])
        self.assertEqual(result.session_metadata["soc_trace"]["review_reason"], "rechazo_politica_proveedor")
        self.assertFalse(result.session_metadata["soc_trace"]["technical_fallback"])
        self.assertEqual(self.hosts, ["api.groq.com"])

    async def test_gemini_failure_is_sanitized(self):
        def offline(request):
            raise httpx.ConnectError("synthetic secret in upstream error", request=request)

        for response, attempts in (
            (httpx.Response(503, text="upstream payload"), 3),
            (offline, 3),
            (httpx.Response(200, json={"candidates": []}), 2),
            (httpx.Response(200, json={"candidates": [{"content": {"parts": []}}]}), 2),
        ):
            with self.subTest(response=response):
                self.hosts.clear()
                result = await self.run_model(httpx.Response(429), response)
                metadata = result.session_metadata
                self.assertEqual(json.loads(result.text), {"tipo": "otro", "severidad": "media", "activo_afectado": None, "confianza": 0.0})
                self.assertIsNone(metadata["soc_provider"])
                self.assertEqual(metadata["soc_trace"]["review_reason"], "proveedores_no_disponibles")
                self.assertEqual(len(metadata["soc_trace"]["attempts"]), attempts)
                self.assertEqual(len(self.hosts), attempts)
                self.assertNotIn("synthetic secret", json.dumps(metadata))
                self.assertNotIn("upstream payload", json.dumps(metadata))

    async def test_gemini_retries_a_single_transient_failure(self):
        def gemini(request):
            if self.hosts.count("generativelanguage.googleapis.com") == 1:
                raise httpx.ReadTimeout("simulated", request=request)
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})

        self.assertEqual((await self.run_model(httpx.Response(400), gemini)).text, "{}")
        self.assertEqual(self.hosts, ["api.groq.com", "generativelanguage.googleapis.com", "generativelanguage.googleapis.com"])
