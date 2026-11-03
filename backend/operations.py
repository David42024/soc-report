"""Operational modules layered on the existing reports and assignments."""
import base64
import binascii
import json
from typing import Annotated
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .classifier import Classification
from .db import utc_now
from .routing import DEFAULT_RULES, Name, PolicyUpdate, policy_record, routing_policy

MAX_ATTACHMENT = 2 * 1024 * 1024
BodyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AssetInput(Input):
    nombre: Name
    descripcion: str = Field(default="", max_length=500)
    activo: bool = True


class TeamInput(Input):
    nombre: Name
    contacto: str = Field(default="", max_length=120)
    disponible: bool = True


class Review(Input):
    tipo: str
    severidad: str
    activo_afectado: str | None = None
    seconds: float | None = Field(default=None, ge=0, le=86400, allow_inf_nan=False)


class Comment(Input):
    contenido: BodyText


class Attachment(Input):
    nombre: Name
    base64: str = Field(min_length=4, max_length=4 * ((MAX_ATTACHMENT + 2) // 3))


def install_operations(app, db, security, get_report):
    read = Depends(security.require("read"))
    assets_edit = Depends(security.require("assets_edit"))
    teams_edit = Depends(security.require("teams_edit"))
    rules_edit = Depends(security.require("rules_edit"))

    @app.get("/api/activos", dependencies=[read])
    def assets():
        with db.session() as execute:
            return [dict(row) for row in execute("SELECT * FROM assets ORDER BY nombre,id")]

    @app.put("/api/activos/{asset_id}", dependencies=[assets_edit])
    def save_asset(asset_id: UUID, payload: AssetInput):
        with db.session(write=True) as execute:
            execute("""INSERT INTO assets (id,nombre,descripcion,activo,updated_at) VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO UPDATE SET nombre=excluded.nombre,descripcion=excluded.descripcion,
                activo=excluded.activo,updated_at=excluded.updated_at""",
                (str(asset_id), payload.nombre, payload.descripcion, int(payload.activo), utc_now()))
        return {"id": str(asset_id)}

    @app.get("/api/equipos", dependencies=[read])
    def teams():
        configuration = routing_policy(db)["configuration"]
        names = set(configuration["equipos"].values()) | {configuration["equipo_revision"]}
        with db.session() as execute:
            directory = {row["nombre"]: dict(row) for row in execute("SELECT * FROM team_directory")}
            load = {row["responsable"]: row["abiertos"] for row in execute("""SELECT responsable,
                COUNT(CASE WHEN resuelto_at IS NULL THEN 1 END) AS abiertos FROM assignments GROUP BY responsable""")}
        return [{"nombre": name, "contacto": "", "disponible": None, **directory.get(name, {}),
                 "abiertos": load.get(name, 0)} for name in sorted(names | directory.keys() | load.keys())]

    @app.put("/api/equipos", dependencies=[teams_edit])
    def save_team(payload: TeamInput):
        with db.session(write=True) as execute:
            execute("""INSERT INTO team_directory (nombre,contacto,disponible,updated_at) VALUES (%s,%s,%s,%s)
                ON CONFLICT (nombre) DO UPDATE SET contacto=excluded.contacto,disponible=excluded.disponible,
                updated_at=excluded.updated_at""", (payload.nombre, payload.contacto, int(payload.disponible), utc_now()))
        return {"nombre": payload.nombre}

    @app.get("/api/reglas", dependencies=[rules_edit])
    def rules():
        with db.session() as execute:
            current = policy_record(execute)
            history = [dict(row) for row in execute(
                "SELECT id,created_by,created_at FROM routing_versions ORDER BY created_at DESC,id DESC LIMIT 50")]
        return {"actual": current, "versiones": history}

    @app.get("/api/reglas/{version_id}", dependencies=[rules_edit])
    def rule_version(version_id: UUID):
        with db.session() as execute:
            row = execute("SELECT * FROM routing_versions WHERE id=%s", (str(version_id),)).fetchone()
        if not row:
            raise HTTPException(404, "Versión de reglas no encontrada.")
        return {**row, "configuration": json.loads(row["configuration"])}

    @app.post("/api/reglas", status_code=201)
    def save_rules(payload: PolicyUpdate, principal=Depends(security.require("rules_edit"))):
        version_id = str(uuid4())
        with db.session(write=True) as execute:
            if db.url:
                execute("LOCK TABLE routing_versions IN SHARE ROW EXCLUSIVE MODE")
            if policy_record(execute)["id"] != payload.version_anterior:
                raise HTTPException(409, "Otra persona publicó reglas. Recarga antes de editar.")
            names = {row["nombre"] for row in execute("SELECT nombre FROM team_directory")}
            names.update(DEFAULT_RULES["equipos"].values())
            names.add(DEFAULT_RULES["equipo_revision"])
            if (set(payload.equipos.values()) | {payload.equipo_revision}) - names:
                raise HTTPException(422, "Registra los equipos nuevos en el directorio antes de publicar.")
            execute("INSERT INTO routing_versions (id,configuration,created_by,created_at) VALUES (%s,%s,%s,%s)",
                    (version_id, payload.model_dump_json(exclude={"version_anterior"}), principal["id"], utc_now()))
            db.access_event(execute, principal, "publicar", "reglas", "operation", 201, version_id)
        return {"id": version_id}

    @app.get("/api/revision", dependencies=[Depends(security.require("review"))])
    def review_queue(limit: int = Query(100, ge=1, le=500)):
        with db.session() as execute:
            current_team = policy_record(execute)["configuration"]["equipo_revision"]
            return [dict(row) for row in execute("""SELECT r.id,r.titulo,r.descripcion,r.tipo,r.severidad,r.activo_afectado,
                r.confianza,r.motivo_revision,a.responsable
                FROM reports r LEFT JOIN assignments a ON a.report_id=r.id
                LEFT JOIN report_reviews v ON v.report_id=r.id
                WHERE v.report_id IS NULL AND (r.motivo_revision IS NOT NULL OR a.responsable IN (%s,%s))
                ORDER BY r.recibido_at,r.id LIMIT %s""", (DEFAULT_RULES["equipo_revision"], current_team, limit))]

    @app.put("/api/reportes/{report_id}/revision")
    def review(report_id: UUID, payload: Review, principal=Depends(security.require("review"))):
        report = get_report(report_id)
        try:
            result = Classification.model_validate({**payload.model_dump(exclude={"seconds"}), "confianza": 1.0})
        except ValueError:
            raise HTTPException(422, "Selecciona un tipo, una severidad y un activo válidos.") from None
        with db.session(write=True) as execute:
            execute("""INSERT INTO report_reviews (report_id,tipo,severidad,activo_afectado,reviewed_by,reviewed_at)
                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (report_id) DO UPDATE SET
                tipo=excluded.tipo,severidad=excluded.severidad,activo_afectado=excluded.activo_afectado,
                reviewed_by=excluded.reviewed_by,reviewed_at=excluded.reviewed_at""",
                (str(report_id), result.tipo, result.severidad, result.activo_afectado, principal["id"], utc_now()))
            if payload.seconds is not None:
                row = execute("UPDATE triage_measurements SET review_seconds=%s WHERE report_id=%s RETURNING report_id",
                              (payload.seconds, str(report_id))).fetchone()
                if not row:
                    raise HTTPException(409, "El caso debe estar notificado para medir el tiempo de revisión.")
            action = "confirmado" if all(report[field] == getattr(result, field) for field in ("tipo", "severidad", "activo_afectado")) else "corregido"
            db.access_event(execute, principal, action, "revision", "operation", 200, str(report_id))
        return {"resultado": action}

    @app.get("/api/reportes/{report_id}/colaboracion", dependencies=[read])
    def collaboration(report_id: UUID):
        get_report(report_id)
        with db.session() as execute:
            args = (str(report_id),)
            comments = execute("SELECT id,contenido,author,created_at FROM report_comments WHERE report_id=%s ORDER BY created_at,id", args)
            attachments = execute("SELECT id,nombre,tamano,author,created_at FROM report_attachments WHERE report_id=%s ORDER BY created_at,id", args)
            reviewed = execute("SELECT * FROM report_reviews WHERE report_id=%s", args).fetchone()
            return {"comentarios": [dict(row) for row in comments], "adjuntos": [dict(row) for row in attachments],
                    "revision": dict(reviewed) if reviewed else None}

    @app.post("/api/reportes/{report_id}/comentarios", status_code=201)
    def comment(report_id: UUID, payload: Comment, principal=Depends(security.require("comment"))):
        get_report(report_id)
        item = str(uuid4())
        with db.session(write=True) as execute:
            execute("INSERT INTO report_comments (id,report_id,contenido,author,created_at) VALUES (%s,%s,%s,%s,%s)",
                    (item, str(report_id), payload.contenido, principal["username"], utc_now()))
        return {"id": item}

    @app.post("/api/reportes/{report_id}/adjuntos", status_code=201)
    def attach(report_id: UUID, payload: Attachment, principal=Depends(security.require("comment"))):
        if any(ord(character) < 32 or character in "/\\" for character in payload.nombre) or payload.nombre in (".", ".."):
            raise HTTPException(422, "Nombre de archivo inválido.")
        try:
            data = base64.b64decode(payload.base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, "El archivo no es válido.") from None
        if len(data) > MAX_ATTACHMENT:
            raise HTTPException(413, "Cada archivo admite hasta 2 MiB.")
        attachment_id = str(uuid4())
        with db.session(write=True) as execute:
            lock = " FOR UPDATE" if db.url else ""
            if not execute("SELECT id FROM reports WHERE id=%s" + lock, (str(report_id),)).fetchone():
                raise HTTPException(404, "Reporte no encontrado.")
            count = execute("SELECT count(*) AS total FROM report_attachments WHERE report_id=%s", (str(report_id),)).fetchone()
            if count["total"] >= 10:
                raise HTTPException(409, "Cada reporte admite hasta 10 adjuntos.")
            execute("""INSERT INTO report_attachments (id,report_id,nombre,contenido,tamano,author,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (attachment_id, str(report_id), payload.nombre, data, len(data), principal["username"], utc_now()))
        return {"id": attachment_id}

    @app.get("/api/reportes/{report_id}/adjuntos/{attachment_id}", dependencies=[read])
    def attachment(report_id: UUID, attachment_id: UUID):
        with db.session() as execute:
            row = execute("SELECT nombre,contenido FROM report_attachments WHERE report_id=%s AND id=%s",
                          (str(report_id), str(attachment_id))).fetchone()
        if not row:
            raise HTTPException(404, "Adjunto no encontrado.")
        return Response(bytes(row["contenido"]), media_type="application/octet-stream",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(row["nombre"], safe=""),
                                 "X-Content-Type-Options": "nosniff"})

    @app.get("/api/notificaciones")
    def notifications(limit: int = Query(100, ge=1, le=500), principal=Depends(security.require("read"))):
        with db.session() as execute:
            return [dict(row) for row in execute("""SELECT b.report_id,b.ocurrido_at,r.titulo,a.responsable,n.read_at
                FROM bitacora b JOIN reports r ON r.id=b.report_id JOIN assignments a ON a.report_id=r.id
                LEFT JOIN notification_reads n ON n.report_id=b.report_id AND n.user_id=%s
                WHERE b.accion='notificacion' ORDER BY b.ocurrido_at DESC,b.report_id LIMIT %s""",
                (principal["id"], limit))]

    @app.put("/api/notificaciones/{report_id}/leida", status_code=204)
    def mark_read(report_id: UUID, principal=Depends(security.require("read"))):
        if not get_report(report_id)["notificado_at"]:
            raise HTTPException(404, "Notificación no encontrada.")
        with db.session(write=True) as execute:
            execute("""INSERT INTO notification_reads (report_id,user_id,read_at) VALUES (%s,%s,%s)
                ON CONFLICT (report_id,user_id) DO NOTHING""", (str(report_id), principal["id"], utc_now()))
