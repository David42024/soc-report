"""On-demand cloud diagnostics with fixed synthetic input and a shared cooldown."""
import asyncio
import time

import httpx

from .chat import gemini_reply, groq_reply
from .db import utc_now

COOLDOWN_SECONDS = 300
PROBE_TIMEOUT_SECONDS = 25


class ProviderHealth:
    def __init__(self, settings):
        self.settings = settings
        self.providers = {
            "groq": (bool(settings.groq_api_key.get_secret_value()), groq_reply),
            "gemini": (bool(settings.gemini_api_key.get_secret_value()), gemini_reply),
        }
        self.lock = asyncio.Lock()
        self.checked_at = 0.0
        self.last_results = {name: {"estado": "pendiente" if configured else "sin_configurar", "verificado_at": None, "motivo": None}
                             for name, (configured, _) in self.providers.items()}

    def snapshot(self):
        stale = time.monotonic() - self.checked_at >= COOLDOWN_SECONDS
        return {name: {**value, "vigente": bool(value["verificado_at"] and not stale)}
                for name, value in self.last_results.items()}

    async def check(self):
        async with self.lock:
            if self.checked_at and time.monotonic() - self.checked_at < COOLDOWN_SECONDS:
                return self.snapshot()
            async with httpx.AsyncClient(timeout=httpx.Timeout(PROBE_TIMEOUT_SECONDS, connect=4), trust_env=False) as client:
                async def probe(name, configured, complete):
                    if not configured:
                        return name, self.last_results[name]
                    reason = None
                    options = {"token_limit": 384}
                    if name == "gemini" and self.settings.chat_gemini_model == "gemini-3-flash-preview":
                        options["thinking_level"] = "low"
                    try:
                        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
                            await complete(client, self.settings, "Responde únicamente OK.",
                                           [{"role": "user", "content": "Prueba sintética de disponibilidad."}], **options)
                    except httpx.HTTPStatusError as error:
                        reason = f"http_{error.response.status_code}"
                    except (httpx.RequestError, TimeoutError):
                        reason = "sin_respuesta"
                    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                        reason = "respuesta_invalida"
                    return name, {"estado": "error" if reason else "ok", "verificado_at": utc_now(), "motivo": reason}

                results = await asyncio.gather(*(probe(name, *config) for name, config in self.providers.items()))
            self.last_results = dict(results)
            self.checked_at = time.monotonic()
            return self.snapshot()
