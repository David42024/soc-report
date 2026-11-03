"""Opt-in checks for the public chat and a real Gemini fallback."""
import unittest
from unittest.mock import patch

import httpx
from backend.chat import ChatInput, answer
from backend.config import Settings

class LiveChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_chat_returns_a_real_provider_reply(self):
        async with httpx.AsyncClient(timeout=65,trust_env=False) as api:
            response=await api.post("http://127.0.0.1:8000/api/chat",json={
                "language":"es",
                "messages":[{"role":"user","content":"En una frase breve, ¿cómo registro la primera respuesta en SOC Report Router?"}],
            })
            response.raise_for_status()
            value=response.json()
            self.assertIn(value["provider"],("Groq","Gemini"))
            self.assertGreater(len(value["reply"]),15)
            print(" Chat API provider:",value["provider"])

    async def test_gemini_replies_when_groq_transport_is_forced_to_fail(self):
        settings=Settings.from_env()
        payload=ChatInput(language="en",messages=[
            {"role":"user","content":"What is an SLA?"},
            {"role":"assistant","content":"It is a response or resolution deadline."},
            {"role":"user","content":"In one brief sentence, how do I view these deadlines in this app?"},
        ])
        with patch("backend.chat.groq_reply",side_effect=httpx.ReadTimeout("controlled Groq failure")):
            reply=await answer(payload,settings)
        self.assertEqual(reply.provider,"Gemini")
        self.assertGreater(len(reply.reply),15)
        print(" Chat fallback provider:",reply.provider,"(Groq failure injected)")
