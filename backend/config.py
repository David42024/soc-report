import os
from base64 import b64decode
from binascii import Error as Base64Error
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


class Settings(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    database_url: str = ""
    sqlite_path: Path = ROOT / "soc.sqlite3"
    classifier_mode: Literal["demo", "langflow"] = "demo"
    router_mode: Literal["local", "n8n"] = "local"
    operator_token: str = "demo-operador"
    internal_token: str = ""
    langflow_url: str = "http://127.0.0.1:7860"
    langflow_flow_id: str = ""
    langflow_api_key: str = ""
    langflow_timeout_seconds: float = Field(default=90, gt=0)
    n8n_webhook_url: str = "http://127.0.0.1:5678/webhook/soc-assign-report"
    n8n_webhook_token: str = ""
    jwt_secret: str = ""
    totp_encryption_key: SecretStr = SecretStr("")
    jwt_minutes: int = Field(default=60, ge=5, le=480)
    redis_url: str = ""
    login_limit: int = Field(default=10, ge=1)
    report_limit: int = Field(default=60, ge=1)
    legacy_operator_enabled: bool = True
    groq_api_key: SecretStr = SecretStr("")
    gemini_api_key: SecretStr = SecretStr("")
    chat_groq_model: str = "openai/gpt-oss-20b"
    chat_gemini_model: str = "gemini-3-flash-preview"
    chat_timeout_seconds: float = Field(default=25, gt=0, le=60)
    chat_limit: int = Field(default=20, ge=1)

    @model_validator(mode="after")
    def validate_credentials(self):
        key = self.totp_encryption_key.get_secret_value()
        if key:
            try:
                valid = len(b64decode(key, altchars=b"-_", validate=True)) == 32
            except (Base64Error, ValueError):
                valid = False
            if not valid or key == self.jwt_secret:
                raise ValueError("La clave de cifrado TOTP debe ser independiente y contener 32 bytes codificados en Base64.")
        if not self.operator_token.strip():
            raise ValueError("Configura OPERATOR_TOKEN.")
        if not self.legacy_operator_enabled and len(self.jwt_secret) < 32:
            raise ValueError("Configura JWT_SECRET con al menos 32 caracteres.")
        if self.classifier_mode == "langflow" and not (
            self.langflow_flow_id.strip() and self.langflow_api_key.strip()
        ):
            raise ValueError("Configura LANGFLOW_FLOW_ID y LANGFLOW_API_KEY.")
        if self.router_mode == "n8n" and not (
            self.n8n_webhook_token.strip() and self.internal_token.strip()
        ):
            raise ValueError("Configura N8N_WEBHOOK_TOKEN e INTERNAL_TOKEN.")
        if (self.classifier_mode == "langflow" or self.router_mode == "n8n") and (
            self.operator_token == "demo-operador"
        ):
            raise ValueError("Cambia OPERATOR_TOKEN al conectar servicios externos.")
        return self

    @classmethod
    def from_env(cls):
        values = {
            name: os.environ[name.upper()]
            for name in cls.model_fields if name.upper() in os.environ
        }
        if "sqlite_path" in values:
            values["sqlite_path"] = ROOT / values["sqlite_path"]
        return cls(**values)
