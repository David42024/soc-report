"""Authorized individual classification through the existing operational API."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from uuid import UUID

from pydantic import SecretStr, ValidationError

from backend.config import Settings
from backend.report_input import ReportInput
from src.data.manifest import ManifestStore
from src.data.models import content_hash
from src.data.revisions import operation_identity
from src.evaluation.store import EvaluationStore
from src.explainability.evidence import extract_evidence
from src.inference.robustness import archived_metric_rows, lexical_coverage, statistical_applicability
from src.inference.services import SocApi
from src.utils.config import AnalyticsSettings
from src.utils.errors import AnalyticsError, ServiceError
from src.utils.privacy import PrivacyError, protect_text
from src.utils.reproducibility import software_versions

LOGGER = logging.getLogger("soc_analytics.inference")


class InferenceWorkspace:
    """Share token-free resources while keeping report data in private session state."""

    def __init__(self, settings: AnalyticsSettings, api: SocApi) -> None:
        self.settings, self.api = settings, api
        self.evaluations = EvaluationStore(settings)
        self.directory = settings.path(Path(settings.runs_dir) / settings.inference.directory)

    def _actor(self, token: SecretStr) -> None:
        if not self.api.me(token).can("review"):
            raise ServiceError("Tu rol no permite consultar inferencias individuales.", 403)

    def catalog(self, token: SecretStr) -> list[dict]:
        """List minimal existing report identifiers, without original texts."""
        self._actor(token)
        self.api.audit_event(token, "consultar_inferencia")
        return [{key: row.get(key) for key in ("id", "tipo", "severidad", "recibido_at")} for row in self.api.reports(token)]

    def prepare(self, title: str, description: str, token: SecretStr) -> dict:
        """Validate the operational schema and preview only its minimized copy."""
        self._actor(token)
        try:
            request = ReportInput(titulo=title, descripcion=description)
            protected = protect_text(f"Título: {request.titulo}\n{request.descripcion}",
                                     known_secrets=Settings.from_env().privacy_secrets())
        except ValidationError:
            raise AnalyticsError("Revisa los campos obligatorios, sus longitudes y los caracteres permitidos.") from None
        except PrivacyError:
            raise AnalyticsError("La política de privacidad no está disponible. No se envió el reporte.") from None
        from backend.classifier import SUSPICIOUS
        return {"input_sha256": content_hash(request.model_dump()), "protected_text": protected.text,
                "privacy": protected.evidence, "potential_injection": bool(SUSPICIOUS.search(request.descripcion + "\n" + request.titulo))}

    def submit(self, title: str, description: str, identifier: str, token: SecretStr) -> dict:
        """Send once using the original webhook and preserve its idempotency identifier."""
        self._actor(token)
        self.prepare(title, description, token)
        request = ReportInput(titulo=title, descripcion=description)
        operation, _ = operation_identity()
        self.api.audit_event(token, "autorizar_inferencia", run_id=operation, outcome="iniciado")
        started = monotonic()
        try:
            receipt = self.api.submit_report(request.model_dump(), identifier, token, self.settings.inference.request_timeout_seconds)
        except ServiceError as error:
            LOGGER.warning("Envío de inferencia sin recibo confirmado; se conserva su identificador")
            raise ServiceError("El envío no tiene un recibo confirmado. Consulta el identificador guardado antes de crear otro reporte.",
                               error.status_code) from None
        duration = max(0.0, monotonic() - started)
        return self.observe(receipt["id"], token, submission={"request_id": identifier, "audit_operation": operation,
                                                            "http_roundtrip_seconds": duration})

    def observe(self, identifier: str, token: SecretStr, *, submission: dict | None = None) -> dict:
        """Read an existing protected prediction and freeze its supporting evidence."""
        self._actor(token)
        try:
            UUID(identifier)
        except ValueError:
            raise AnalyticsError("Selecciona un identificador de reporte válido.") from None
        operation, date = operation_identity()
        self.api.audit_event(token, "consultar_inferencia", run_id=operation)
        observed = self.api.explanation_input(identifier, token)
        text = observed["input"]["text"]
        try:
            if protect_text(text, known_secrets=Settings.from_env().privacy_secrets()).text != text:
                raise AnalyticsError("La política actual requiere revisar la protección de la entrada guardada.")
        except PrivacyError:
            raise AnalyticsError("No se pudo comprobar la protección del reporte.") from None
        evidence = extract_evidence(text, observed["classification"], self.settings.explainability)
        archived = [self.evaluations.result(row["run_id"]) for row in self.evaluations.list() if row["status"] == "completa"]
        context, guide = statistical_applicability(observed, archived)
        reference_rows, reference_guide = archived_metric_rows(observed, archived)
        result = {"schema_version": 1, "phase": 6, "run_id": operation, "created_at_utc": date,
                  "report": observed, "evidence": evidence, "lexical": lexical_coverage(text, self.settings),
                  "statistical_rows": context, "statistical_guide": guide.__dict__,
                  "reference_rows": reference_rows, "reference_guide": reference_guide.__dict__,
                  "seed": self.settings.seed, "software": software_versions(self.settings.software),
                  "config_sha256": content_hash(self.settings.inference.model_dump()),
                  "criteria_sha256": evidence["criteria_sha256"]}
        if submission:
            result["submission"] = submission
        payload = {**result, "content_sha256": content_hash(result)}
        raw = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
        if len(raw) > self.settings.data.max_csv_bytes:
            raise AnalyticsError("El registro de inferencia supera el límite configurado.")
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            destination = self.directory / operation
            with TemporaryDirectory(prefix=".inferencia-", dir=self.directory) as temporary:
                staging = Path(temporary)
                ManifestStore._publish(staging, "result.json", raw)
                self._actor(token)
                staging.rename(destination)
                try:
                    self.api.audit_event(token, "registrar_inferencia", run_id=operation)
                except AnalyticsError:
                    destination.rename(staging)
                    raise
        except OSError:
            raise AnalyticsError("No se pudo registrar la evidencia de inferencia en runs/.") from None
        LOGGER.info("Se registró una observación de inferencia protegida")
        return payload

    def metrics(self, token: SecretStr) -> dict:
        """Read current aggregate observations with their applicability limits."""
        self._actor(token)
        return self.api.inference_metrics(token)
