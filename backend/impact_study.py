"""Predeclared comparisons of operational SLA and active human triage time."""
from datetime import date, datetime, timedelta, timezone
import json
from typing import Literal
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import IntegrityError

from .classifier import Severidad, Tipo
from .db import utc_now
from .insights import LIMA, timestamp


class Study(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    nombre: str = Field(min_length=5, max_length=100)
    muestreo: str = Field(min_length=15, max_length=500)
    tipo: Tipo
    severidad: Severidad
    manual_desde: date
    manual_hasta: date
    asistido_desde: date
    asistido_hasta: date
    minimo_por_grupo: int = Field(ge=3, le=10000)
    respuesta_min: int = Field(ge=1, le=525600)
    resolucion_min: int = Field(ge=1, le=525600)
    meta_mejora_pp: float = Field(ge=0, le=100, allow_inf_nan=False)

    @model_validator(mode="after")
    def comparable(self):
        if not self.manual_desde <= self.manual_hasta < self.asistido_desde <= self.asistido_hasta:
            raise ValueError("Los periodos deben estar en orden y ser independientes.")
        if self.respuesta_min > self.resolucion_min:
            raise ValueError("El plazo de respuesta debe preceder al de resolución.")
        return self


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    modalidad: Literal["manual", "asistido"]
    segundos_activos: float = Field(gt=0, le=86400, allow_inf_nan=False)
    caso_real: Literal[True]
    referencia: str | None = Field(default=None, min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    reporte_id: UUID | None = None
    recibido_at: AwareDatetime | None = None
    respondido_at: AwareDatetime | None = None
    resuelto_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def cohort_fields(self):
        if self.modalidad == "manual":
            if not self.referencia or not self.recibido_at or self.reporte_id:
                raise ValueError("Indica una referencia externa y la fecha de recepción del caso manual.")
            if self.referencia.upper().startswith("DEMO"):
                raise ValueError("La referencia debe corresponder a un caso operativo real.")
            if (self.respondido_at and self.respondido_at < self.recibido_at
                    or self.resuelto_at and (not self.respondido_at or self.resuelto_at < self.respondido_at)):
                raise ValueError("Los hitos deben estar en orden cronológico.")
        elif not self.reporte_id or any((self.referencia, self.recibido_at, self.respondido_at, self.resuelto_at)):
            raise ValueError("Indica el ID de un reporte operativo para recuperar sus hitos.")
        return self


def study_row(execute, study_id):
    row = execute("SELECT * FROM impact_studies WHERE id=%s", (study_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Estudio no encontrado.")
    return row


def summarize_study(config, rows, now):
    groups = {}
    for cohort in ("manual", "asistido"):
        matching = [row for row in rows if row["cohort"] == cohort]
        count = len(matching)
        seconds = sum(row["active_seconds"] for row in matching)
        metrics = {"muestra": count, "segundos_activos_total": seconds, "segundos_activos_media": seconds / count if count else None}
        for milestone, field, minutes in (("respuesta", "answered_at", config.respuesta_min),
                                          ("resolucion", "resolved_at", config.resolucion_min)):
            good = eligible = 0
            for row in matching:
                due = timestamp(row["received_at"]) + timedelta(minutes=minutes)
                finished = timestamp(row[field])
                if finished or due < now:
                    eligible += 1
                    good += int(bool(finished and finished <= due))
            metrics[milestone] = {"a_tiempo": good, "evaluables": eligible, "porcentaje": 100 * good / eligible if eligible else None}
        groups[cohort] = metrics
    manual, assisted = groups["manual"], groups["asistido"]
    ended = now.astimezone(LIMA).date() > config.asistido_hasta
    time_ready = ended and min(manual["muestra"], assisted["muestra"]) >= config.minimo_por_grupo
    sla_ready = ended and all(group[key]["evaluables"] >= config.minimo_por_grupo
                              for group in groups.values() for key in ("respuesta", "resolucion"))
    difference = {key: assisted[key]["porcentaje"] - manual[key]["porcentaje"] for key in ("respuesta", "resolucion")} if sla_ready else None
    saved = ((manual["segundos_activos_media"] - assisted["segundos_activos_media"]) * assisted["muestra"] / 3600
             if time_ready else None)
    return {"grupos": groups, "periodo_completo": ended, "sla_comparable": sla_ready, "tiempo_comparable": time_ready,
            "mejora_sla_pp": difference, "meta_sla_cumplida": all(delta >= config.meta_mejora_pp for delta in difference.values()) if difference else None,
            "ahorro_estimado_horas_muestras_reales": saved}


def demo_sla_comparison():
    """Run the operational SLA calculator on a separate, fixed synthetic fixture."""
    config = Study(nombre="Comparación DEMO de SLA", muestreo="40 casos simulados comparables por grupo.",
                   tipo="phishing", severidad="media", manual_desde=date(2026, 9, 1), manual_hasta=date(2026, 9, 30),
                   asistido_desde=date(2026, 10, 1), asistido_hasta=date(2026, 10, 31), minimo_por_grupo=40,
                   respuesta_min=240, resolucion_min=1440, meta_mejora_pp=15)
    cases = []
    for cohort, month, responses, resolutions, active in (("manual", 9, 26, 24, 900), ("asistido", 10, 38, 36, 240)):
        for index in range(40):
            received = datetime(2026, month, 1 + index // 2, 9 + index % 2, tzinfo=LIMA)
            cases.append({"cohort": cohort, "received_at": received, "active_seconds": active,
                          "answered_at": received + timedelta(hours=2 if index < responses else 6),
                          "resolved_at": received + timedelta(hours=16 if index < resolutions else 32)})
    stats = summarize_study(config, cases, datetime(2026, 11, 2, tzinfo=LIMA))
    return {"source": "demo", "tipo": config.tipo, "severidad": config.severidad,
            "respuesta_min": config.respuesta_min, "resolucion_min": config.resolucion_min,
            "meta_mejora_pp": config.meta_mejora_pp, "meta_cumplida": stats["meta_sla_cumplida"],
            "mejora_pp": stats["mejora_sla_pp"], "grupos": {
                cohort: {"desde": getattr(config, cohort + "_desde"), "hasta": getattr(config, cohort + "_hasta"),
                         **{key: group[key] for key in ("respuesta", "resolucion")}}
                for cohort, group in stats["grupos"].items()
            }}


def install_impact_study(app, db, security):
    read = Depends(security.require("read"))

    @app.get("/api/estudios-impacto", dependencies=[read])
    def list_studies():
        with db.session() as execute:
            return [{"id": row["id"], **json.loads(row["configuration"])} for row in execute(
                "SELECT id,configuration FROM impact_studies ORDER BY created_at DESC,id DESC")]

    @app.post("/api/estudios-impacto", status_code=201)
    def create_study(payload: Study, principal=Depends(security.require("baseline"))):
        study_id = str(uuid4())
        with db.session(write=True) as execute:
            execute("INSERT INTO impact_studies (id,configuration,created_by,created_at) VALUES (%s,%s,%s,%s)",
                    (study_id, payload.model_dump_json(), principal["id"], utc_now()))
            db.access_event(execute, principal, "estudio_creado", "impact", "operation", 201, study_id)
        return {"id": study_id}

    @app.get("/api/estudios-impacto/{study_id}", dependencies=[read])
    def study_detail(study_id: UUID):
        with db.session() as execute:
            row = study_row(execute, str(study_id))
            config = Study.model_validate_json(row["configuration"])
            observations = list(execute("""SELECT o.id,o.cohort,o.reference,o.report_id,o.active_seconds,o.received_at,
                CASE WHEN o.cohort='asistido' THEN a.respondido_at ELSE o.answered_at END AS answered_at,
                CASE WHEN o.cohort='asistido' THEN a.resuelto_at ELSE o.resolved_at END AS resolved_at
                FROM impact_observations o LEFT JOIN assignments a ON a.report_id=o.report_id WHERE o.study_id=%s
                ORDER BY o.received_at,o.id""", (str(study_id),)))
        created = timestamp(row["created_at"])
        return {"id": str(study_id), "criterios": config, "observaciones": observations,
                "criterios_registrados_at": created, "criterios_previos_al_periodo_asistido": created.astimezone(LIMA).date() < config.asistido_desde,
                **summarize_study(config, observations, datetime.now(timezone.utc))}

    @app.post("/api/estudios-impacto/{study_id}/observaciones", status_code=201)
    def record_observation(study_id: UUID, payload: Observation, principal=Depends(security.require("read"))):
        row_id = str(uuid4())
        try:
            with db.session(write=True) as execute:
                config = Study.model_validate_json(study_row(execute, str(study_id))["configuration"])
                report_id = str(payload.reporte_id) if payload.reporte_id else None
                reference, received = payload.referencia, payload.recibido_at
                if report_id:
                    report = execute("SELECT titulo,tipo,severidad,origen,recibido_at FROM reports WHERE id=%s", (report_id,)).fetchone()
                    if not report:
                        raise HTTPException(404, "Reporte no encontrado.")
                    if report["origen"] == "demo" or report["titulo"].upper().startswith("[DEMO]"):
                        raise HTTPException(422, "Los casos DEMO se excluyen de los estudios operativos.")
                    if (report["tipo"], report["severidad"]) != (config.tipo, config.severidad):
                        raise HTTPException(422, "El tipo y la severidad deben coincidir con el estudio.")
                    reference, received = report_id, timestamp(report["recibido_at"])
                start = getattr(config, payload.modalidad + "_desde")
                end = getattr(config, payload.modalidad + "_hasta")
                now = datetime.now(timezone.utc)
                if not start <= received.astimezone(LIMA).date() <= end:
                    raise HTTPException(422, "La recepción está fuera del periodo del grupo.")
                if any(value and value > now for value in (received, payload.respondido_at, payload.resuelto_at)):
                    raise HTTPException(422, "Las observaciones reales no admiten fechas futuras.")
                if payload.modalidad == "manual" and any(
                    not milestone and received + timedelta(minutes=minutes) >= now
                    for milestone, minutes in ((payload.respondido_at, config.respuesta_min), (payload.resuelto_at, config.resolucion_min))
                ):
                    raise HTTPException(409, "Registra el caso manual cuando sus hitos estén documentados o sus plazos hayan vencido.")
                execute("""INSERT INTO impact_observations (id,study_id,cohort,reference,report_id,active_seconds,
                    received_at,answered_at,resolved_at,recorded_by,recorded_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (row_id, str(study_id), payload.modalidad, reference, report_id, payload.segundos_activos,
                     received.astimezone(timezone.utc).isoformat(),
                     payload.respondido_at.astimezone(timezone.utc).isoformat() if payload.respondido_at else None,
                     payload.resuelto_at.astimezone(timezone.utc).isoformat() if payload.resuelto_at else None, principal["id"], utc_now()))
                db.access_event(execute, principal, "observacion_registrada", "impact", "operation", 201, row_id)
        except IntegrityError:
            raise HTTPException(409, "Este caso ya está incluido en el grupo del estudio.") from None
        return {"id": row_id}
