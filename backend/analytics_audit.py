"""Audit the analytical client's local operations through existing JWT and RBAC."""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from fastapi import Depends, HTTPException, FastAPI
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .security import PERMISSIONS

if TYPE_CHECKING:
    from .db import Database
    from .security import PlatformSecurity

EXPERIMENT_ACTIONS = ("consultar_experimentos", "autorizar_experimento", "cancelar_experimento", "reanudar_experimento")
EVALUATION_ACTIONS = ("consultar_evaluaciones", "autorizar_evaluacion", "inspeccionar_evaluacion")
EXPLAINABILITY_ACTIONS = ("consultar_explicabilidad", "autorizar_explicabilidad", "inspeccionar_explicabilidad", "autorizar_anotacion_xai")
REPORT_ACTIONS = ("consultar_informes", "autorizar_informe", "generar_informe")
INFERENCE_ACTIONS = ("consultar_inferencia", "autorizar_inferencia", "registrar_inferencia")
OPTIMIZATION_ACTIONS = ("consultar_optimizacion", "guardar_configuracion_optuna", "exportar_candidato_optuna")


class AnalyticalEvent(BaseModel):
    """Only bounded identifiers and outcomes, never report texts or credentials."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    action: Literal["consultar_catalogo", "consultar_fuente", "registrar_verificacion", "consultar_registros",
                    "consultar_datos", "autorizar_revision_datos", "autorizar_manifiesto_datos",
                    "consultar_experimentos", "autorizar_experimento", "cancelar_experimento", "reanudar_experimento",
                    "consultar_evaluaciones", "autorizar_evaluacion", "inspeccionar_evaluacion",
                    "consultar_explicabilidad", "autorizar_explicabilidad", "inspeccionar_explicabilidad", "autorizar_anotacion_xai",
                    "consultar_informes", "autorizar_informe", "generar_informe",
                    "consultar_inferencia", "autorizar_inferencia", "registrar_inferencia",
                    "consultar_optimizacion", "guardar_configuracion_optuna", "exportar_candidato_optuna"]
    source_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,79}$")
    run_id: str | None = Field(default=None, pattern=r"^\d{8}T\d{12}Z_[0-9a-f]{12}$")
    outcome: Literal["iniciado", "completado", "error"] = "completado"

    @model_validator(mode="after")
    def identifiers(self) -> AnalyticalEvent:
        if self.action in ("consultar_fuente", "registrar_verificacion", "autorizar_revision_datos") and self.source_id is None:
            raise ValueError("La operación requiere un identificador de fuente.")
        if self.action == "registrar_verificacion" and self.outcome == "completado" and self.run_id is None:
            raise ValueError("La confirmación requiere un identificador de registro.")
        if self.action.startswith("autorizar_") and (self.run_id is None or self.outcome != "iniciado"):
            raise ValueError("La autorización requiere el identificador y el estado inicial de la operación.")
        if self.action in ("cancelar_experimento", "reanudar_experimento") and self.run_id is None:
            raise ValueError("La operación requiere el identificador del experimento.")
        if self.action in ("inspeccionar_evaluacion", "inspeccionar_explicabilidad") and self.run_id is None:
            raise ValueError("La inspección requiere el identificador de evaluación.")
        if self.action == "generar_informe" and (self.run_id is None or self.outcome == "iniciado"):
            raise ValueError("La generación requiere un identificador de informe y un resultado.")
        if self.action == "registrar_inferencia" and self.run_id is None:
            raise ValueError("El registro de inferencia requiere un identificador.")
        if self.action in ("guardar_configuracion_optuna", "exportar_candidato_optuna") and self.run_id is None:
            raise ValueError("La configuración requiere su identificador versionado.")
        return self


def install_analytical_audit(app: FastAPI, db: Database, security: PlatformSecurity) -> None:
    """Extend the existing API audit service without new tables or identities."""
    @app.post("/api/analitica/eventos", status_code=204)
    def analytical_event(payload: AnalyticalEvent, principal: dict = Depends(security.authenticate)) -> None:
        """Append the authorized actor's declared analytical operation to audit_log."""
        permissions = {"registrar_verificacion": "write", "autorizar_revision_datos": "review",
                       "autorizar_manifiesto_datos": "write", "autorizar_experimento": "write",
                       "cancelar_experimento": "write", "reanudar_experimento": "write",
                       "autorizar_evaluacion": "write", "inspeccionar_evaluacion": "review"}
        permissions.update(autorizar_explicabilidad="review", inspeccionar_explicabilidad="review", autorizar_anotacion_xai="review")
        permissions.update(dict.fromkeys(REPORT_ACTIONS, "report_export"))
        permissions.update(dict.fromkeys(INFERENCE_ACTIONS, "review"))
        permissions.update(guardar_configuracion_optuna="write", exportar_candidato_optuna="write")
        permission = permissions.get(payload.action, "read")
        analytical_actions = EXPERIMENT_ACTIONS + EVALUATION_ACTIONS + EXPLAINABILITY_ACTIONS + REPORT_ACTIONS + INFERENCE_ACTIONS + OPTIMIZATION_ACTIONS
        if (payload.action.endswith("_datos") or payload.action in analytical_actions) and not principal.get("jti"):
            raise HTTPException(401, "Se requiere una sesión JWT para esta operación analítica.")
        if principal["role"] not in PERMISSIONS[permission]:
            raise HTTPException(403, "El rol no permite esta operación analítica.")
        module = "analitica/fuentes" if payload.action in ("consultar_catalogo", "consultar_fuente") else "analitica/verificaciones"
        if payload.action.endswith("_datos"):
            module = "analitica/datos"
        if payload.action in EXPERIMENT_ACTIONS:
            module = "analitica/experimentos"
        if payload.action in EVALUATION_ACTIONS:
            module = "analitica/evaluacion"
        if payload.action in EXPLAINABILITY_ACTIONS:
            module = "analitica/explicabilidad"
        if payload.action in REPORT_ACTIONS:
            module = "analitica/informes"
        if payload.action in INFERENCE_ACTIONS:
            module = "analitica/inferencia"
        if payload.action in OPTIMIZATION_ACTIONS:
            module = "analitica/optimizacion"
        with db.session(write=True) as execute:
            db.access_event(execute, principal, payload.action, module, "operation", 204,
                            payload.run_id or payload.source_id, outcome=payload.outcome)
