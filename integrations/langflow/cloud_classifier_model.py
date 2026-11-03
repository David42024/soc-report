from urllib.parse import quote

import httpx
from lfx.custom.custom_component.component import Component
from lfx.io import MessageInput, Output, SecretStrInput, StrInput
from lfx.schema.message import Message
from lfx.utils.secrets import secret_value_to_str


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
        messages = [
            {"role": "system", "content": getattr(self.system_message, "text", self.system_message)},
            {"role": "user", "content": getattr(self.input_value, "text", self.input_value)},
        ]
        async with httpx.AsyncClient(timeout=25, trust_env=False) as client:
            try:
                result = await self._complete(
                    client, "https://api.groq.com/openai/v1/chat/completions",
                    self.groq_api_key, self.groq_model, messages, max_completion_tokens=1536,
                )
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                try:
                    code = exc.response.json()["error"].get("code")
                except (ValueError, TypeError, KeyError, AttributeError):
                    code = None
                if code in ("content_policy_violation", "content_filter", "safety"):
                    raise ValueError(f"Groq rechazó la solicitud (HTTP {status}).") from None
            except (httpx.RequestError, ValueError):
                pass
            else:
                self.status = "Groq"
                return Message(text=result)

            for attempt in range(2):
                try:
                    result = await self._gemini(client, messages)
                    break
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    if attempt or (status != 408 and status < 500):
                        raise ValueError(f"Gemini rechazó la solicitud (HTTP {status}).") from None
                except httpx.RequestError:
                    if attempt:
                        raise ValueError("Gemini no respondió a la solicitud.") from None
        self.status = "Gemini"
        return Message(text=result)

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

    async def _complete(self, client, url, key, model, messages, **generation) -> str:
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
            text = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise ValueError("El proveedor devolvió una respuesta inválida.") from None
        if not isinstance(text, str) or not text.strip():
            raise ValueError("El proveedor devolvió una respuesta vacía.")
        return text

    async def _gemini(self, client, messages) -> str:
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
            parts = response.json()["candidates"][0]["content"]["parts"]
            result = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise ValueError("Gemini devolvió una respuesta inválida.") from None
        if not result.strip():
            raise ValueError("Gemini devolvió una respuesta vacía.")
        return result
