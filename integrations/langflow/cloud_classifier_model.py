from urllib.parse import quote
from hashlib import sha256
import json
import re
from time import monotonic

import httpx
from lfx.custom.custom_component.component import Component
from lfx.io import MessageInput, Output, SecretStrInput, StrInput
from lfx.schema.message import Message
from lfx.utils.secrets import secret_value_to_str

from src.utils.privacy import protect_messages
from src.inference.telemetry import CloudTrace, ProviderAttempt


class ProviderPolicyError(ValueError):
    """An explicit safety refusal must terminate cross-provider failover."""


class SocCloudModel(Component):
    display_name = "Groq con respaldo Gemini"
    description = "Clasifica con Groq y usa Gemini si el proveedor falla."
    icon = "brain-circuit"
    name = "SocCloudModel"

    inputs = [
        MessageInput(name="input_value", display_name="Reporte", required=True),
        MessageInput(name="system_message", display_name="Instrucciones", required=True),
        SecretStrInput(name="groq_api_key", display_name="Clave Groq", required=True),
        SecretStrInput(name="gemini_api_key", display_name="Clave Gemini", required=True),
        StrInput(name="groq_model", display_name="Modelo Groq", value="openai/gpt-oss-20b", advanced=True),
        StrInput(name="gemini_model", display_name="Modelo Gemini", value="gemini-3-flash-preview", advanced=True),
    ]
    outputs = [Output(name="text_output", display_name="Clasificación", method="classify")]

    async def classify(self) -> Message:
        # One protected copy is shared by both providers and every retry. This
        # also protects direct LangFlow runs that did not pass through FastAPI.
        # Protection happens before entering the provider fallback block.
        messages, privacy = protect_messages([
            {"role": "system", "content": getattr(self.system_message, "text", self.system_message)},
            {"role": "user", "content": getattr(self.input_value, "text", self.input_value)},
        ], known_secrets=(secret_value_to_str(self.groq_api_key), secret_value_to_str(self.gemini_api_key)))
        attempts = []
        async with httpx.AsyncClient(timeout=25, trust_env=False) as client:
            try:
                result = await self._attempt(client, "groq", messages, attempts)
            except ProviderPolicyError:
                return self._protected_response(messages, privacy, attempts, "rechazo_politica_proveedor")
            except (httpx.HTTPError, ValueError):
                pass
            else:
                self.status = "Groq"
                return self._response(result, "groq", self.groq_model, messages, privacy, attempts)

            for attempt in range(2):
                try:
                    result = await self._attempt(client, "gemini", messages, attempts)
                    break
                except ProviderPolicyError:
                    return self._protected_response(messages, privacy, attempts, "rechazo_politica_proveedor")
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    if attempt or (status != 408 and status < 500):
                        return self._protected_response(messages, privacy, attempts, "proveedores_no_disponibles")
                except httpx.RequestError:
                    if attempt:
                        return self._protected_response(messages, privacy, attempts, "proveedores_no_disponibles")
                except ValueError:
                    return self._protected_response(messages, privacy, attempts, "proveedores_no_disponibles")
        self.status = "Gemini"
        return self._response(result, "gemini", self.gemini_model, messages, privacy, attempts)

    async def _attempt(self, client: httpx.AsyncClient, provider: str, messages: list[dict],
                       attempts: list[ProviderAttempt]) -> dict:
        """Time each actual HTTP attempt and retain only bounded, non-sensitive fields."""
        started = monotonic()
        outcome, status, response_model = "ok", None, None
        model = self.groq_model if provider == "groq" else self.gemini_model
        try:
            if provider == "groq":
                reply = await self._complete(client, "https://api.groq.com/openai/v1/chat/completions",
                    self.groq_api_key, model, messages, max_completion_tokens=1536)
            else:
                reply = await self._gemini(client, messages)
            response_model = reply["response_model"]
            return reply
        except ProviderPolicyError:
            outcome = "policy_rejected"
            raise
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            try:
                code = error.response.json()["error"].get("code")
            except (ValueError, TypeError, KeyError, AttributeError):
                code = None
            if code in ("content_policy_violation", "content_filter", "safety"):
                outcome = "policy_rejected"
                raise ProviderPolicyError("El proveedor rechazó la solicitud por política.") from None
            outcome = "http_error"
            raise
        except httpx.RequestError:
            outcome = "transport_error"
            raise
        except ValueError:
            outcome = "invalid_response"
            raise
        finally:
            attempts.append(ProviderAttempt(provider=provider, model=model, outcome=outcome,
                                            seconds=max(0.0, monotonic() - started), http_status=status,
                                            response_model=response_model))

    def _response(self, reply: dict, provider: str | None, model: str | None, messages: list[dict],
                  privacy: dict, attempts: list[ProviderAttempt], reason: str | None = None) -> Message:
        """Attach protected observable context outside the classification JSON."""
        user = messages[1]["content"]
        trace = CloudTrace(outcome="protective" if reason else "classified", attempts=attempts,
                           technical_fallback=any(item.provider == "gemini" for item in attempts), review_reason=reason)
        return Message(text=reply["text"], session_metadata={
            "soc_provider": provider, "soc_model": reply["response_model"] or model, "soc_privacy": privacy,
            "soc_model_scope": "response" if reply["response_model"] else "requested",
            "soc_prompt_sha256": sha256(messages[0]["content"].encode("utf-8")).hexdigest(),
            "soc_input_sha256": sha256(user.encode("utf-8")).hexdigest(), "soc_input_text": user,
            "soc_trace": trace.model_dump(),
            "soc_provider_seconds": attempts[-1].seconds if provider else None,
        })

    def _protected_response(self, messages: list[dict], privacy: dict, attempts: list[ProviderAttempt], reason: str) -> Message:
        """Return the operational safe result with its observable technical trace."""
        self.status = "Revisión humana"
        safe = {"tipo": "otro", "severidad": "media", "activo_afectado": None, "confianza": 0.0}
        return self._response({"text": json.dumps(safe), "response_model": None}, None, None, messages, privacy, attempts, reason)

    def _schema(self) -> dict:
        properties = {
            "tipo": {"type": "string"},
            "severidad": {"type": "string"},
            "activo_afectado": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "confianza": {"type": "number"},
        }
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }

    async def _complete(self, client, url, key, model, messages, **generation) -> dict:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {secret_value_to_str(key)}"},
            json={
                "model": model,
                "messages": messages,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "soc_classification",
                        "strict": True,
                        "schema": self._schema(),
                    },
                },
                "reasoning_effort": "low",
                **generation,
            },
        )
        response.raise_for_status()
        try:
            payload = response.json()
            choice = payload["choices"][0]
            message = choice["message"]
            if message.get("refusal") or choice.get("finish_reason") == "content_filter":
                raise ProviderPolicyError("Groq rechazó la solicitud por política.")
            text = message["content"]
        except ProviderPolicyError:
            raise
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise ValueError("El proveedor devolvió una respuesta inválida.") from None
        if not isinstance(text, str) or not text.strip():
            raise ValueError("El proveedor devolvió una respuesta vacía.")
        return {"text": text, "response_model": self._model_version(payload.get("model"))}

    async def _gemini(self, client, messages) -> dict:
        model = quote(self.gemini_model, safe="")
        generation = {
            "responseMimeType": "application/json",
            "responseJsonSchema": self._schema(),
            "maxOutputTokens": 1536,
        }
        if self.gemini_model == "gemini-3-flash-preview":
            generation["thinkingConfig"] = {"thinkingLevel": "low"}
        response = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": secret_value_to_str(self.gemini_api_key)},
            json={
                "systemInstruction": {"parts": [{"text": messages[0]["content"]}]},
                "contents": [{"role": "user", "parts": [{"text": messages[1]["content"]}]}],
                "generationConfig": generation,
            },
        )
        response.raise_for_status()
        try:
            payload = response.json()
            blocked = payload.get("promptFeedback", {}).get("blockReason")
            if blocked and blocked != "BLOCK_REASON_UNSPECIFIED":
                raise ProviderPolicyError("Gemini rechazó la solicitud por política.")
            candidate = payload["candidates"][0]
            if candidate.get("finishReason") in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"):
                raise ProviderPolicyError("Gemini rechazó la solicitud por política.")
            parts = candidate["content"]["parts"]
            result = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        except ProviderPolicyError:
            raise
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise ValueError("Gemini devolvió una respuesta inválida.") from None
        if not result.strip():
            raise ValueError("Gemini devolvió una respuesta vacía.")
        return {"text": result, "response_model": self._model_version(payload.get("modelVersion"))}

    @staticmethod
    def _model_version(value: object) -> str | None:
        """Keep only a provider-reported version with a safe identifier format."""
        return value if isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9._:/-]{1,160}", value) else None
