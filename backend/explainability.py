"""Restricted read-only evidence for the existing operational report pipeline."""
from hashlib import sha256
import json
import re
from uuid import UUID

from fastapi import Depends, HTTPException

from .classifier import Classification
from .routing import routing_policy
from .routing import assignment_for
from .db import deadline
from src.inference.telemetry import elapsed
from src.utils.privacy import protect_text


def install_explainability(app, db, security, settings) -> None:
    """Serve original text and minimized snapshots under existing review and JWT."""
    @app.get("/api/reportes/{report_id}/explicabilidad")
    def explanation_input(report_id: UUID, original: bool = False, principal=Depends(security.require("review"))):
        if not principal.get("jti"):
            raise HTTPException(401, "Se requiere una sesión JWT para consultar evidencia textual.")
        report = db.report(str(report_id))
        if report is None:
            raise HTTPException(404, "Reporte no encontrado.")
        with db.session(write=True) as execute:
            snapshot = execute("SELECT payload,sha256 FROM report_ai_inputs WHERE report_id=%s", (str(report_id),)).fetchone()
            reviewed = execute("SELECT * FROM report_reviews WHERE report_id=%s", (str(report_id),)).fetchone()
            db.access_event(execute, principal, "consultar_original" if original else "consultar_entrada_ia",
                            "analitica/explicabilidad", "operation", 200, str(report_id))
        if snapshot:
            if sha256(snapshot["payload"].encode("utf-8")).hexdigest() != snapshot["sha256"]:
                raise HTTPException(409, "La huella de la entrada registrada cambió.")
            observed = json.loads(snapshot["payload"])
            status = "capturada"
        else:
            protected = protect_text(f"Título: {report['titulo']}\n{report['descripcion']}", known_secrets=settings.privacy_secrets())
            observed = {"text": protected.text, "input_sha256": sha256(protected.text.encode()).hexdigest(),
                        "privacy": protected.evidence, "provider": None, "model": None, "prompt_sha256": None,
                        "scope": "reconstruccion_actual"}
            status = "reconstruida"
            if report["origen"] == "langflow":
                for event in db.audit(str(report_id)):
                    if event["accion"] == "clasificado" and event["actor"] == "langflow":
                        provider = re.search(r" / proveedor=(groq|gemini)(?: /|$)", event["detalle"])
                        if provider:
                            observed["provider"] = provider.group(1)
        prediction = Classification.model_validate({field: report[field] for field in Classification.model_fields}).model_dump()
        if snapshot:
            classification_hash = sha256(json.dumps(prediction, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                                     allow_nan=False).encode("utf-8")).hexdigest()
            original_hash = sha256(f"Título: {report['titulo']}\n{report['descripcion']}".encode("utf-8")).hexdigest()
            if observed.get("classification_sha256") != classification_hash or observed.get("original_sha256") != original_hash:
                raise HTTPException(409, "La entrada registrada corresponde a otra versión del reporte o de su predicción.")
        # Asset labels may also contain personal information. The original remains in reports.
        if prediction["activo_afectado"]:
            prediction["activo_afectado"] = protect_text(prediction["activo_afectado"], known_secrets=settings.privacy_secrets()).text
        policy = routing_policy(db, str(report_id))
        response = {"id": str(report_id), "input": observed, "input_status": status, "classification": prediction,
                    "origin": report["origen"], "review_reason": report["motivo_revision"],
                    "human_review": {field: reviewed[field] for field in ("tipo", "severidad", "activo_afectado")} if reviewed else None,
                    "routing": {"version": policy["id"], "configuration": policy["configuration"],
                                "assigned_team": report.get("responsable")}}
        expected = assignment_for(report, policy["configuration"])
        deadlines = {name: deadline(report["recibido_at"], expected[name + "_min"]) for name in ("respuesta", "resolucion")}
        verified = (report.get("responsable") == expected["responsable"] and all(
            elapsed(deadlines[name], report.get("vence_" + name + "_at")) == 0 for name in deadlines))
        response["routing"].update(
            expected=expected, verified=verified if report.get("responsable") else None,
            response_due_at=report.get("vence_respuesta_at"), resolution_due_at=report.get("vence_resolucion_at"))
        response["timestamps"] = {field: report.get(field) for field in
                                  ("recibido_at", "clasificado_at", "asignado_at", "notificado_at")}
        response["timing"] = {"classification_seconds": elapsed(report["recibido_at"], report["clasificado_at"]),
                              "end_to_end_seconds": elapsed(report["recibido_at"], report.get("notificado_at"))}
        response["events"] = [{key: event[key] for key in ("accion", "actor", "ocurrido_at")} for event in db.audit(str(report_id))]
        response["system"] = {"classifier": settings.classifier_mode, "router": settings.router_mode}
        if response["human_review"] and response["human_review"]["activo_afectado"]:
            response["human_review"]["activo_afectado"] = protect_text(response["human_review"]["activo_afectado"], known_secrets=settings.privacy_secrets()).text
        if original:
            response["original"] = {"title": report["titulo"], "description": report["descripcion"]}
        return response
