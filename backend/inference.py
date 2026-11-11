"""Read-only operational inference telemetry under the existing JWT and permissions."""
from hashlib import sha256
import json

from fastapi import Depends, HTTPException

from src.inference.telemetry import observed_metrics
from src.utils.config import load_config
from src.utils.errors import AnalyticsError


def install_inference(app, db, security) -> None:
    """Aggregate the existing report/input/review records without new classifications."""
    @app.get("/api/analitica/inferencia/indicadores")
    def metrics(principal=Depends(security.require("read"))):
        if not principal.get("jti"):
            raise HTTPException(401, "Se requiere una sesión JWT para consultar telemetría.")
        try:
            policy = load_config().inference
        except AnalyticsError:
            raise HTTPException(503, "La configuración analítica de inferencia no está disponible.") from None
        with db.session() as execute:
            data = list(execute("""SELECT COUNT(*) OVER() AS total,r.id,r.tipo,r.severidad,r.activo_afectado,r.origen,r.titulo,
                r.motivo_revision,r.recibido_at,r.clasificado_at,n.ocurrido_at AS notificado_at,
                i.payload,i.sha256,v.severidad AS human_severity
                FROM reports r LEFT JOIN report_ai_inputs i ON i.report_id=r.id
                LEFT JOIN bitacora n ON n.report_id=r.id AND n.accion='notificacion'
                LEFT JOIN report_reviews v ON v.report_id=r.id
                ORDER BY r.recibido_at DESC,r.id DESC LIMIT %s""", (policy.max_metric_records,)))
        rows = []
        for record in data:
            captured = None
            if record["payload"]:
                try:
                    if sha256(record["payload"].encode()).hexdigest() != record["sha256"]:
                        raise ValueError
                    captured = json.loads(record["payload"])
                    if not isinstance(captured, dict):
                        raise ValueError
                except (TypeError, ValueError):
                    raise HTTPException(409, "La huella de una entrada registrada cambió.") from None
            rows.append({"id": record["id"], "tipo": record["tipo"], "severidad": record["severidad"],
                         "activo_afectado": record["activo_afectado"],
                         "origin": record["origen"], "review": record["motivo_revision"],
                         "demo": record["origen"] == "demo" or record["titulo"].startswith("[DEMO]"),
                         "input": captured, "human_severity": record["human_severity"],
                         "received_at": record["recibido_at"], "classified_at": record["clasificado_at"],
                         "notified_at": record["notificado_at"]})
        with db.session(write=True) as execute:
            db.access_event(execute, principal, "consultar_indicadores_inferencia", "analitica/inferencia", "operation", 200)
        total = data[0]["total"] if data else 0
        return {**observed_metrics(rows, policy.latency_min_observations, policy.target_p95_seconds),
                "total_registered": total, "bounded_to_latest": policy.max_metric_records,
                "truncated": total > len(rows)}
