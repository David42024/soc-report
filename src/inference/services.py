"""Authenticated adapter for existing FastAPI endpoints, never provider SDKs."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from time import monotonic
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from backend.security import PERMISSIONS, Role
from src.utils.config import ApiSettings
from src.utils.errors import ServiceError

LOGGER = logging.getLogger("soc_analytics.services")


class User(BaseModel):
    """Public identity returned and authorized by the existing backend."""

    model_config = ConfigDict(hide_input_in_errors=True)
    id: str
    username: str
    role: Role
    active: int

    def can(self, permission: str) -> bool:
        """Reuse the operational permission matrix for local analytical views."""
        return bool(self.active and self.role in PERMISSIONS.get(permission, ()))


class Session(BaseModel):
    """A token private to one browser session, excluded from representations."""

    token: SecretStr
    user: User
    expires_at: datetime
    checked_at: float


class SocApi:
    """A stateless, shareable client; tokens are supplied separately per request."""

    def __init__(self, settings: ApiSettings, *, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport

    def _request(self, method: str, endpoint: str, *, token: SecretStr | None = None,
                 payload: dict | None = None, params: dict | None = None,
                 request_headers: dict | None = None, request_timeout: float | None = None) -> Any:
        headers = {"Accept": "application/json"}
        headers.update(request_headers or {})
        if token is not None:
            if not token.get_secret_value():
                raise ServiceError("Inicia sesión para acceder a los datos.", 401)
            headers["Authorization"] = "Bearer " + token.get_secret_value()
        timeout = httpx.Timeout(request_timeout or self.settings.timeout_seconds, connect=self.settings.connect_timeout_seconds)
        try:
            with httpx.Client(base_url=self.settings.base_url, timeout=timeout, trust_env=False,
                              follow_redirects=False, transport=self._transport) as client:
                with client.stream(method, endpoint, headers=headers, json=payload, params=params) as response:
                    if response.status_code >= 300:
                        messages = {
                            401: "Sesión inválida o credenciales incorrectas. Inicia sesión nuevamente.",
                            403: "Tu rol no permite consultar este recurso.",
                            409: "El registro cambió. Actualiza los datos antes de continuar.",
                            428: "Se requiere el código de segundo factor o de recuperación.",
                            429: "Se alcanzó el límite del servicio. Espera antes de reintentar.",
                        }
                        LOGGER.warning("Endpoint SOC respondió HTTP %s", response.status_code)
                        raise ServiceError(messages.get(response.status_code, "El servicio SOC no pudo completar la consulta."), response.status_code)
                    if response.status_code == 204:
                        return None
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > self.settings.max_response_bytes:
                            raise ServiceError("La respuesta excede el límite configurado.")
                        chunks.append(chunk)
                    return json.loads(b"".join(chunks))
        except httpx.HTTPError:
            LOGGER.warning("No se pudo contactar el backend SOC")
            raise ServiceError("FastAPI no está disponible. Comprueba el arranque de los servicios SOC.") from None
        except (ValueError, TypeError):
            raise ServiceError("El servicio devolvió una respuesta que no cumple el contrato esperado.") from None

    def health(self) -> dict:
        """Read backend health, including its cached provider diagnostics."""
        value = self._request("GET", self.settings.endpoints.health, params={"detalle": "true"})
        if not isinstance(value, dict) or not isinstance(value.get("servicios"), dict):
            raise ServiceError("La respuesta de salud no cumple el contrato SOC.")
        return value

    def login(self, username: str, password: SecretStr, otp: SecretStr | None = None) -> Session:
        """Delegate passwords, TOTP, lockout and JWT issuance to FastAPI."""
        payload = {"username": username, "password": password.get_secret_value()}
        if otp and otp.get_secret_value():
            payload["otp"] = otp.get_secret_value()
        response = self._request("POST", self.settings.endpoints.login, payload=payload)
        try:
            token = response["access_token"]
            lifetime = response["expires_in"]
            if not isinstance(token, str) or not token or not isinstance(lifetime, int) or lifetime <= 0:
                raise ValueError
            return Session(token=SecretStr(token), user=User.model_validate(response["user"]),
                           expires_at=datetime.now(timezone.utc) + timedelta(seconds=lifetime), checked_at=monotonic())
        except (KeyError, TypeError, ValueError, ValidationError):
            raise ServiceError("La respuesta de autenticación no cumple el contrato SOC.") from None

    def me(self, token: SecretStr) -> User:
        """Validate the session against backend RBAC and revocation controls."""
        try:
            return User.model_validate(self._request("GET", self.settings.endpoints.me, token=token))
        except ValidationError:
            raise ServiceError("La identidad devuelta por el backend es inválida.") from None

    def logout(self, token: SecretStr) -> None:
        """Revoke the JWT through the existing session endpoint."""
        self._request("POST", self.settings.endpoints.logout, token=token)

    def reports(self, token: SecretStr) -> list[dict]:
        """Read the existing bounded operational view; no report is created."""
        value = self._request("GET", self.settings.endpoints.reports, token=token)
        if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
            raise ServiceError("La lista de reportes no cumple el contrato SOC.")
        return value

    def dashboard(self, token: SecretStr, start: date | None, end: date | None) -> dict:
        """Read the operational aggregate API for an inclusive Lima reception range."""
        params = {key: day.isoformat() for key, day in (("desde", start), ("hasta", end)) if day is not None}
        value = self._request("GET", self.settings.endpoints.dashboard, token=token, params=params)
        if not isinstance(value, dict):
            raise ServiceError("El tablero SOC devolvió un resumen inválido.")
        return value

    def audit_event(self, token: SecretStr, action: str, *, source_id: str | None = None,
                    run_id: str | None = None, outcome: str = "completado") -> None:
        """Require server-side authorization and append-only audit for local work."""
        self._request("POST", self.settings.endpoints.analytical_audit, token=token,
                      payload={"action": action, "source_id": source_id, "run_id": run_id, "outcome": outcome})

    def report_review(self, report_id: str, token: SecretStr) -> dict | None:
        """Reuse the collaboration contract and return only its review."""
        try:
            endpoint = self.settings.endpoints.report_collaboration.format(report_id=UUID(report_id))
        except (ValueError, KeyError, IndexError):
            raise ServiceError("El identificador de la revisión operativa no es válido.") from None
        value = self._request("GET", endpoint, token=token)
        if not isinstance(value, dict) or "revision" not in value:
            raise ServiceError("La revisión operativa no cumple el contrato esperado.")
        review = value["revision"]
        if review is not None and not isinstance(review, dict):
            raise ServiceError("La revisión operativa no cumple el contrato esperado.")
        return review

    def explanation_input(self, report_id: str, token: SecretStr, *, original: bool = False) -> dict:
        """Fetch the authorized operational snapshot through FastAPI."""
        try:
            endpoint = self.settings.endpoints.report_explainability.format(report_id=UUID(report_id))
        except (ValueError, KeyError, IndexError):
            raise ServiceError("El identificador del reporte es inválido.") from None
        response = self._request("GET", endpoint, token=token, params={"original": str(original).lower()})
        if not isinstance(response, dict) or not all(key in response for key in ("id", "input", "classification", "routing")):
            raise ServiceError("La evidencia del reporte no cumple el contrato de explicabilidad.")
        return response

    def submit_report(self, payload: dict, identifier: str, token: SecretStr, timeout: float) -> dict:
        """Send one explicit report through the operational webhook with stable idempotency."""
        try:
            key = UUID(identifier)
        except ValueError:
            raise ServiceError("La clave del envío es inválida.") from None
        response = self._request("POST", self.settings.endpoints.reports, token=token, payload=payload,
                                 request_headers={"Idempotency-Key": str(key)}, request_timeout=timeout)
        if not isinstance(response, dict) or response.get("id") != str(key):
            raise ServiceError("El recibo del envío no coincide con su identificador.")
        return response

    def inference_metrics(self, token: SecretStr) -> dict:
        """Read aggregate observed telemetry, without fetching report texts."""
        value = self._request("GET", self.settings.endpoints.inference_metrics, token=token)
        if not isinstance(value, dict) or not isinstance(value.get("latency"), dict):
            raise ServiceError("La telemetría de inferencia no cumple el contrato.")
        return value


def health_rows(snapshot: dict | None, *, unavailable: bool = False) -> list[dict[str, str]]:
    """Normalize only allowlisted public health fields for a table."""
    if not snapshot:
        return [{"Servicio": "FastAPI", "Estado": "no disponible" if unavailable else "sin comprobar"}]
    return [{"Servicio": str(name), "Estado": str(state)} for name, state in snapshot["servicios"].items()
            if name in ("fastapi", "postgresql", "sqlite", "redis", "langflow", "n8n")]
