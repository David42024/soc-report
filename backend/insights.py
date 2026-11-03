"""Filtered reporting data shared by dashboards and downloads."""
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator

from .classifier import Severidad, Tipo

LIMA = ZoneInfo("America/Lima")
ReportKind = Literal["cola", "sla", "pendientes", "mensual", "tendencia", "clasificador", "equipos"]
TITLES = {
    "cola": "Cola operativa", "sla": "SLA próximos o vencidos", "pendientes": "Asignaciones pendientes",
    "mensual": "Cumplimiento mensual", "tendencia": "Tendencia de incidentes",
    "clasificador": "Desempeño del clasificador", "equipos": "Carga por equipo",
}


class DateRange(BaseModel):
    desde: date | None = None
    hasta: date | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.desde and self.hasta and self.desde > self.hasta:
            raise ValueError("La fecha inicial debe preceder a la final.")
        return self

    def conditions(self, column):
        clauses, values = [], []
        if self.desde:
            clauses.append(f"{column} >= %s")
            values.append(datetime.combine(self.desde, time.min, LIMA).astimezone(timezone.utc).isoformat())
        if self.hasta:
            clauses.append(f"{column} <= %s")
            values.append(datetime.combine(self.hasta, time.max, LIMA).astimezone(timezone.utc).isoformat())
        return clauses, values


class ReportFilters(DateRange):
    tipo: Tipo | None = None
    severidad: Severidad | None = None
    equipo: str | None = Field(default=None, max_length=120)


def report_rows(db, filters):
    clauses, values = filters.conditions("r.recibido_at")
    for column, value in (("r.tipo", filters.tipo), ("r.severidad", filters.severidad), ("a.responsable", filters.equipo)):
        if value:
            clauses.append(f"{column} = %s")
            values.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with db.session() as execute:
        return [dict(row) for row in execute("""SELECT r.id,r.titulo,r.tipo,r.severidad,r.activo_afectado,
            r.origen,r.recibido_at,r.clasificado_at,r.motivo_revision,a.responsable,a.vence_respuesta_at,
            a.vence_resolucion_at,a.respondido_at,a.resuelto_at,
            v.report_id AS revisado,v.tipo AS tipo_revisado,v.severidad AS severidad_revisada,
            v.activo_afectado AS activo_revisado
            FROM reports r LEFT JOIN assignments a ON a.report_id=r.id
            LEFT JOIN report_reviews v ON v.report_id=r.id""" + where + " ORDER BY r.recibido_at DESC, r.id", values)]


def timestamp(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def pending_sla(report, now):
    deadlines = (("respuesta", "respondido_at"), ("resolucion", "resuelto_at"))
    for milestone, completed in deadlines:
        deadline = timestamp(report["vence_" + milestone + "_at"])
        if deadline and not report[completed] and deadline <= now + timedelta(hours=4):
            yield milestone, deadline, "Vencido" if deadline < now else "Por vencer"


def summarize(reports, now):
    states, types, severities = Counter(), Counter(), Counter()
    teams = defaultdict(lambda: {"total": 0, "abiertos": 0})
    months = defaultdict(Counter)
    timings = defaultdict(list)
    origins = defaultdict(lambda: {"total": 0, "revision": 0, "validados": 0, "aciertos": 0})
    sla = Counter()
    for report in reports:
        started = timestamp(report["recibido_at"])
        month = months[started.astimezone(LIMA).strftime("%Y-%m")]
        month["total"] += 1
        state = ("sin_asignar" if not report["responsable"] else "resuelto" if report["resuelto_at"]
                 else "en_atencion" if report["respondido_at"] else "por_atender")
        states[state] += 1
        types[report["tipo"]] += 1
        severities[report["severidad"]] += 1
        if report["responsable"]:
            team = teams[report["responsable"]]
            team["total"] += 1
            team["abiertos"] += int(state != "resuelto")
        demo = report["origen"] == "demo" or report["titulo"].startswith("[DEMO]")
        origin = origins[(report["origen"], demo)]
        origin["total"] += 1
        origin["revision"] += int(bool(report["motivo_revision"]))
        if report["revisado"]:
            origin["validados"] += 1
            origin["aciertos"] += int(
                report["tipo"] == report["tipo_revisado"] and report["severidad"] == report["severidad_revisada"]
                and report["activo_afectado"] == report["activo_revisado"]
            )
        for name, column in (("clasificacion", "clasificado_at"), ("respuesta", "respondido_at"), ("resolucion", "resuelto_at")):
            finished = timestamp(report[column])
            if finished:
                timings[name].append((finished - started).total_seconds())
            if name == "clasificacion":
                continue
            due = timestamp(report[f"vence_{name}_at"])
            if due and (finished or due < now):
                for counts in (month, sla):
                    counts[f"{name}_evaluable"] += 1
                    counts[f"{name}_a_tiempo"] += int(bool(finished and finished <= due))
    return {
        "total": len(reports),
        "demo": sum(counts["total"] for (_, demo), counts in origins.items() if demo),
        "estados": dict(states), "tipos": dict(types), "severidades": dict(severities),
        "equipos": [{"nombre": name, **counts} for name, counts in sorted(teams.items())],
        "mensual": [{"mes": month, **counts} for month, counts in sorted(months.items())],
        "sla": dict(sla),
        "tiempos": {name: {"segundos": sum(values) / len(values), "muestra": len(values)} for name, values in timings.items()},
        "clasificador": [{"origen": name, "demo": demo, **counts,
                         "precision": counts["aciertos"] / counts["validados"] if counts["validados"] else None}
                        for (name, demo), counts in sorted(origins.items())],
    }


def report_table(kind, reports, stats, now):
    if kind in ("cola", "pendientes", "sla"):
        rows = []
        for row in reports:
            if kind == "sla":
                rows.extend({**row, "hito": name, "vence_at": due, "situacion": status}
                            for name, due, status in pending_sla(row, now))
            elif kind == "cola" and not row["resuelto_at"] or kind == "pendientes" and not row["responsable"]:
                rows.append(row)
        fields = [("id", "ID"), ("titulo", "Título"), ("severidad", "Severidad"), ("responsable", "Equipo")]
        fields += ([("hito", "Hito"), ("vence_at", "Vencimiento"), ("situacion", "Estado SLA")] if kind == "sla"
                   else [("tipo", "Tipo"), ("recibido_at", "Recepción"), ("vence_respuesta_at", "Plazo respuesta"), ("vence_resolucion_at", "Plazo resolución")])
        return rows, fields
    if kind in ("mensual", "tendencia"):
        fields = [("mes", "Mes"), ("total", "Reportes")]
        if kind == "mensual":
            fields += [(f"{milestone}_{key}", f"{label} {milestone}") for milestone in ("respuesta", "resolucion")
                       for key, label in (("a_tiempo", "A tiempo"), ("evaluable", "Evaluables"))]
            return [{**dict.fromkeys((key for key, _ in fields[2:]), 0), **row} for row in stats["mensual"]], fields
        return stats["mensual"], fields
    if kind == "equipos":
        return stats["equipos"], [("nombre", "Equipo"), ("total", "Reportes"), ("abiertos", "Abiertos")]
    rows = [{**row, "demo": "DEMO" if row["demo"] else "Sin marca DEMO",
             "precision": f"{row['precision']:.1%}" if row["precision"] is not None else "Sin validaciones"}
            for row in stats["clasificador"]]
    return rows, [("origen", "Origen"), ("demo", "Conjunto"), ("total", "Reportes"), ("revision", "A revisión"),
                  ("validados", "Validados"), ("aciertos", "Coincidencias"), ("precision", "Precisión")]
