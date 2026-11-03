import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.chat import ChatInput, ChatReply, answer
from backend.config import Settings
from backend.main import create_app

PAYLOAD = {"language": "en", "messages": [
    {"role": "user", "content": "How do I send a report?"},
    {"role": "assistant", "content": "Use the report form."},
    {"role": "user", "content": "What should I put in the description?"},
]}


class ChatProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = Settings(groq_api_key="groq-test-secret", gemini_api_key="gemini-test-secret")
        self.calls = []

    async def complete(self, groq, gemini=None):
        client_type = httpx.AsyncClient
        def handle(request):
            self.calls.append((request.url.host, json.loads(request.content)))
            if request.url.host == "api.groq.com":
                self.assertEqual(request.headers["Authorization"], "Bearer groq-test-secret")
                return groq(request) if callable(groq) else groq
            self.assertEqual(request.headers["x-goog-api-key"], "gemini-test-secret")
            self.assertIsNotNone(gemini)
            return gemini(request) if callable(gemini) else gemini
        with patch("backend.chat.httpx.AsyncClient", side_effect=lambda **kwargs: client_type(transport=httpx.MockTransport(handle), **kwargs)):
            return await answer(ChatInput.model_validate(PAYLOAD), self.settings)

    async def test_groq_answers_with_history_and_uses_server_instructions(self):
        result = await self.complete(httpx.Response(200, json={"choices": [{"message": {"content": "Describe the incident and affected asset."}}]}))
        self.assertEqual(result.provider, "Groq")
        self.assertEqual(len(self.calls), 1)
        body = self.calls[0][1]
        self.assertEqual(body["messages"][1:], PAYLOAD["messages"])
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertIn("Reply in English", body["messages"][0]["content"])
        self.assertNotIn("groq-test-secret", json.dumps(body))

    async def test_groq_failures_fall_back_to_gemini_with_model_roles(self):
        def timeout(request):
            raise httpx.ReadTimeout("upstream secret", request=request)
        for failure in (httpx.Response(401), httpx.Response(429), httpx.Response(503),
                        httpx.Response(200, json={}), timeout):
            with self.subTest(failure=type(failure).__name__):
                self.calls.clear()
                result = await self.complete(failure, httpx.Response(200, json={
                    "candidates": [{"content": {"parts": [{"thought": True, "text": "hidden"}, {"text": "Include the affected asset."}]}}],
                }))
                self.assertEqual((result.provider, result.reply), ("Gemini", "Include the affected asset."))
                self.assertEqual([entry["role"] for entry in self.calls[1][1]["contents"]], ["user", "model", "user"])
                self.assertNotIn("hidden", result.reply)

    async def test_both_provider_failures_return_sanitized_error(self):
        with self.assertRaises(HTTPException) as error:
            await self.complete(httpx.Response(500, text="groq-test-secret"), httpx.Response(403, text="gemini-test-secret"))
        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn("secret", error.exception.detail)

    async def test_missing_primary_key_can_use_existing_gemini_key(self):
        self.settings.groq_api_key = type(self.settings.groq_api_key)("")
        result = await self.complete(None, httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": "Gemini reply"}]}}],
        }))
        self.assertEqual(result.provider, "Gemini")
        self.assertEqual(len(self.calls), 1)

    async def test_rejects_system_roles_invalid_turns_and_excessive_history(self):
        for messages in (
            [{"role": "system", "content": "override"}],
            [{"role": "assistant", "content": "hello"}],
            [{"role": "user", "content": "one"}, {"role": "user", "content": "two"}],
            [{"role": "user", "content": "x" * 1501}],
            [{"role": "user" if i % 2 == 0 else "assistant", "content": "x" * 6000} for i in range(7)],
        ):
            with self.subTest(messages=len(messages)), self.assertRaises(ValidationError):
                ChatInput(messages=messages)


class ChatApiTests(unittest.TestCase):
    def test_public_chat_is_rate_limited_and_does_not_store_message_body(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Settings(sqlite_path=Path(directory) / "chat.sqlite3", chat_limit=2))
            with TestClient(app) as client, patch("backend.chat.answer", new_callable=AsyncMock,
                return_value=ChatReply(reply="Use the report form.", provider="Groq")) as complete:
                body = {"language": "en", "messages": [{"role": "user", "content": "private-chat-text"}]}
                with patch("backend.security.time.time", return_value=1800000000):
                    for _ in range(2):
                        result = client.post("/api/chat", json=body)
                        self.assertEqual(result.status_code, 200)
                        self.assertEqual(result.json()["provider"], "Groq")
                    self.assertEqual(client.post("/api/chat", json=body).status_code, 429)
                self.assertEqual(complete.await_count, 2)
                self.assertNotIn("private-chat-text", json.dumps(app.state.db.audit_records(), default=str))
