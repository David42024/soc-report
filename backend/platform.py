"""Role-restricted administration, compliance audit, baselines and exports."""
from datetime import datetime, timezone
from typing import Annotated, Literal
import json
import time
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError

from .context import identity
from .db import utc_now
from .exports import export_report
from .insights import TITLES, DateRange, ReportFilters, ReportKind, report_rows, report_table, summarize
from .security import LoginChallenge, LoginInput, PERMISSIONS, hash_password, verify_password
from .navigation import observe
from .impact_study import demo_sla_comparison

Role = Literal["administrador", "analista", "gestor", "auditor"]
Format = Literal["pdf", "docx", "xlsx"]
Module = Literal["intake", "inbox", "dashboard", "impact", "audit", "users", "profile", "chat",
                 "activos", "equipos", "revision", "notificaciones", "reglas", "salud", "login"]
MODULE_PERMISSIONS = {
    **dict.fromkeys(("inbox", "dashboard", "impact", "activos", "equipos", "notificaciones", "salud"), "read"),
    "audit": "audit", "users": "manage", "revision": "review", "reglas": "rules_edit",
}
AUDIT_FIELDS = [
    ("occurred_at", "Fecha"), ("user_id", "Usuario"), ("role", "Rol"), ("module", "Módulo"),
    ("action", "Acción"), ("phase", "Fase"), ("outcome", "Resultado"), ("status_code", "HTTP"), ("ip", "IP"),
    ("request_id", "Solicitud"), ("entity_id", "Entidad"),
]


class AuditFilters(DateRange):
    usuario: str | None = Field(default=None, max_length=80)
    rol: str | None = Field(default=None, max_length=32)
    modulo: str | None = Field(default=None, max_length=200)
    accion: str | None = Field(default=None, max_length=40)
    resultado: int | None = Field(default=None, ge=100, le=599)
    desenlace: Literal["iniciado", "registrado", "completado", "rechazado", "error", "expirado"] | None = None

    def query(self):
        clauses, values = self.conditions("occurred_at")
        if self.usuario:
            clauses.append("(user_id = %s OR user_id IN (SELECT id FROM users WHERE username = %s))")
            values.extend((self.usuario, self.usuario.lower()))
        for column, value in (("role", self.rol), ("module", self.modulo), ("action", self.accion),
                              ("status_code", self.resultado), ("outcome", self.desenlace)):
            if value is not None:
                clauses.append(f"{column} = %s")
                values.append(value)
        return {"clauses": clauses, "values": values}


class AuditPage(AuditFilters):
    limit: int = Field(default=100, ge=1, le=500)
    before: UUID | None = None


class Navigation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    anterior: Module | None = None
    siguiente: Module | None = None


class Visit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    secuencia: int = Field(ge=1, le=2**53-1)
    modulo: Module | None


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actual: str = Field(min_length=1, max_length=128)
    nueva: str = Field(min_length=12, max_length=128)


class FactorPassword(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=128)


class FactorConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^[0-9]{6}$")


class FactorDisable(FactorPassword):
    code: str = Field(min_length=6, max_length=48)


def download(rows, metrics, format_name, filename, **options):
    content, media = export_report(rows, metrics, format_name, **options)
    return Response(content, media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}.{format_name}"', "Cache-Control": "no-store"})


class UserInput(LoginInput):
    password: str = Field(min_length=12, max_length=128)
    role: Role


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role
    active: bool
    password: str | None = Field(default=None, min_length=12, max_length=128)


class BaselineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=5, max_length=150)
    seconds: list[float] = Field(min_length=3, max_length=1000)
    is_demo: bool = False

    @field_validator("seconds")
    @classmethod
    def positive_samples(cls, values):
        import math
        if any(not math.isfinite(value) or value <= 0 or value > 86400 for value in values):
            raise ValueError("Cada muestra debe estar entre 0 y 86400 segundos.")
        return values


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seconds: float = Field(ge=0, le=86400, allow_inf_nan=False)


def install_platform_routes(app, db, security):
    @app.post("/api/auth/login")
    def login(payload: LoginChallenge, request: Request):
        return security.login(payload, request)

    @app.get("/api/auth/me")
    def me(principal=Depends(security.authenticate)):
        return security.public_user(principal)

    @app.get("/api/auth/totp")
    def factor_status(principal=Depends(security.authenticate)):
        if not principal.get("jti"):
            raise HTTPException(403, "Inicia sesión con tu cuenta.")
        with db.session() as execute:
            record = security.totp.state(execute, principal["id"])
        return {"activo": bool(record and record["secret"]), "disponible": security.totp.key is not None}

    @app.post("/api/auth/totp/preparar")
    def factor_setup(payload: FactorPassword, request: Request, principal=Depends(security.authenticate)):
        security.rate_limit("totp", request.client.host, security.settings.login_limit)
        with db.session(write=True) as execute:
            user = security.totp.account(execute, principal, db.url)
            if not verify_password(payload.password, user["password_hash"]):
                raise HTTPException(403, "La contraseña actual es incorrecta.")
            record = security.totp.state(execute, principal["id"])
            if record and record["secret"]:
                raise HTTPException(409, "El segundo factor ya está activo.")
            result = security.totp.prepare(execute, principal)
            db.access_event(execute, principal, "totp_preparado", "auth", "operation", 200)
            return result

    def revoke_factor_sessions(execute, principal, action):
        execute("UPDATE users SET token_version=token_version+1 WHERE id=%s", (principal["id"],))
        execute("DELETE FROM auth_sessions WHERE user_id=%s", (principal["id"],))
        db.access_event(execute, principal, action, "auth", "operation", 200)

    @app.post("/api/auth/totp/activar")
    def factor_activate(payload: FactorConfirmation, request: Request, principal=Depends(security.authenticate)):
        security.rate_limit("totp", request.client.host, security.settings.login_limit)
        with db.session(write=True) as execute:
            security.totp.account(execute, principal, db.url)
            codes = security.totp.activate(execute, principal, payload.code)
            revoke_factor_sessions(execute, principal, "totp_activado")
            return {"codigos_recuperacion": codes}

    @app.post("/api/auth/totp/desactivar", status_code=204)
    def factor_disable(payload: FactorDisable, request: Request, principal=Depends(security.authenticate)):
        security.rate_limit("totp", request.client.host, security.settings.login_limit)
        with db.session(write=True) as execute:
            user = security.totp.account(execute, principal, db.url)
            if not verify_password(payload.password, user["password_hash"]):
                raise HTTPException(403, "La contraseña actual es incorrecta.")
            record = security.totp.state(execute, principal["id"])
            if not record or not record["secret"]:
                raise HTTPException(409, "El segundo factor ya está desactivado.")
            if not security.totp.consume(execute, principal["id"], record, payload.code.strip(), int(time.time())):
                raise HTTPException(401, "Código de verificación inválido.")
            execute("DELETE FROM user_totp WHERE user_id=%s", (principal["id"],))
            revoke_factor_sessions(execute, principal, "totp_desactivado")

    @app.post("/api/auth/password", status_code=204)
    def change_password(payload: PasswordChange, request: Request, principal=Depends(security.authenticate)):
        if not principal.get("jti"):
            raise HTTPException(403, "Inicia sesión con tu cuenta.")
        security.rate_limit("password", request.client.host, security.settings.login_limit)
        user = security.user(user_id=principal["id"])
        if not user or not verify_password(payload.actual, user["password_hash"]):
            raise HTTPException(403, "La contraseña actual es incorrecta.")
        if payload.actual == payload.nueva:
            raise HTTPException(422, "La nueva contraseña debe ser distinta.")
        new_hash = hash_password(payload.nueva)
        with db.session(write=True) as execute:
            changed = execute("""UPDATE users SET password_hash=%s,token_version=token_version+1
                WHERE id=%s AND active=1 AND token_version=%s RETURNING id""",
                (new_hash, user["id"], user["token_version"])).fetchone()
            if not changed:
                raise HTTPException(409, "La cuenta cambió. Inicia sesión otra vez.")
            execute("DELETE FROM auth_sessions WHERE user_id=%s", (user["id"],))
            execute("DELETE FROM login_failures WHERE user_id=%s", (user["id"],))

    @app.post("/api/auth/logout", status_code=204)
    def logout(principal=Depends(security.authenticate)):
        security.logout(principal)

    @app.get("/api/users", dependencies=[Depends(security.require("manage"))])
    def users():
        with db.session() as execute:
            return [dict(row) for row in execute("SELECT id,username,role,active,creado_at FROM users ORDER BY username").fetchall()]

    @app.post("/api/users", status_code=201, dependencies=[Depends(security.require("manage"))])
    def create_user(payload: UserInput):
        user_id = str(uuid4())
        try:
            with db.session(write=True) as execute:
                execute("""INSERT INTO users (id,username,password_hash,role,creado_at)
                    VALUES (%s,%s,%s,%s,%s)""",
                    (user_id, payload.username.lower(), hash_password(payload.password), payload.role, utc_now()))
        except IntegrityError:
            raise HTTPException(409, "El usuario ya existe.") from None
        return security.public_user(security.user(user_id=user_id))

    @app.put("/api/users/{user_id}", dependencies=[Depends(security.require("manage"))])
    def update_user(user_id: UUID, payload: UserUpdate):
        with db.session(write=True) as execute:
            if db.url:
                execute("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE")
            admins = execute("SELECT id FROM users WHERE role='administrador' AND active=1" + (" FOR UPDATE" if db.url else "")).fetchall()
            row = execute("SELECT * FROM users WHERE id=%s", (str(user_id),)).fetchone()
            if not row:
                raise HTTPException(404, "Usuario no encontrado.")
            if row["role"] == "administrador" and row["active"] and len(admins) == 1 and (not payload.active or payload.role != "administrador"):
                raise HTTPException(409, "Debe permanecer al menos un administrador activo.")
            password = hash_password(payload.password) if payload.password else row["password_hash"]
            execute("""UPDATE users SET role=%s,active=%s,password_hash=%s,token_version=token_version+1
                WHERE id=%s""", (payload.role, int(payload.active), password, str(user_id)))
            if payload.password:
                execute("DELETE FROM login_failures WHERE user_id=%s", (str(user_id),))
        return security.public_user(security.user(user_id=str(user_id)))

    @app.get("/api/audit", dependencies=[Depends(security.require("audit"))])
    def audit_log(filters: Annotated[AuditPage, Query()]):
        return db.audit_records(filters.limit, str(filters.before) if filters.before else None, **filters.query())

    @app.get("/api/audit/exportar/{format_name}", dependencies=[Depends(security.require("audit"))])
    def audit_export(format_name: Format, filters: Annotated[AuditFilters, Query()]):
        return download(db.audit_records(10001, **filters.query()), {}, format_name, "soc-auditoria",
                        fields=AUDIT_FIELDS, title="Auditoría SOC")

    @app.post("/api/audit/navegacion", status_code=204)
    def audit_navigation(payload: Navigation, principal=Depends(security.authenticate)):
        if payload.anterior == payload.siguiente:
            raise HTTPException(422, "Se requiere un cambio de módulo.")
        with db.session(write=True) as execute:
            for module, action in ((payload.anterior, "module_exit"), (payload.siguiente, "module_enter")):
                if module is None:
                    continue
                permission = MODULE_PERMISSIONS.get(module)
                if permission and principal["role"] not in PERMISSIONS[permission]:
                    raise HTTPException(403, "El rol carece de acceso a este módulo.")
                db.access_event(execute, principal, action, module, "navigation")

    @app.post("/api/audit/visitas", status_code=204)
    def audit_visit(payload: Visit, request: Request):
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            raise HTTPException(403, "La navegación debe originarse en la aplicación.")
        actor = identity.get()
        if actor["role"] == "publico":
            if payload.modulo not in (None, "intake", "login", "chat"):
                raise HTTPException(401, "Inicia sesión para continuar.")
            security.rate_limit("navigation", actor["ip"], 120)
        permission = MODULE_PERMISSIONS.get(payload.modulo)
        if permission and actor["role"] not in PERMISSIONS[permission]:
            raise HTTPException(403, "El rol carece de acceso a este módulo.")
        observe(db, str(payload.id), payload.secuencia, payload.modulo, actor)

    @app.get("/api/triage", dependencies=[Depends(security.require("read"))])
    def triage():
        return db.triage_metrics()

    @app.get("/api/impacto", dependencies=[Depends(security.require("read"))])
    def impact():
        return {**db.impact_history(), "sla_demo": demo_sla_comparison()}

    @app.get("/api/dashboard", dependencies=[Depends(security.require("read"))])
    def dashboard(filters: Annotated[ReportFilters, Query()]):
        return summarize(report_rows(db, filters), datetime.now(timezone.utc))

    @app.get("/api/informes/{kind}/{format_name}", dependencies=[Depends(security.require("report_export"))])
    def filtered_export(kind: ReportKind, format_name: Format, filters: Annotated[ReportFilters, Query()]):
        now = datetime.now(timezone.utc)
        reports = report_rows(db, filters)
        stats = summarize(reports, now) if kind not in ("cola", "sla", "pendientes") else {}
        rows, fields = report_table(kind, reports, stats, now)
        return download(rows, {}, format_name, f"soc-{kind}", fields=fields, title=TITLES[kind])

    @app.post("/api/triage/baselines", status_code=201)
    def baseline(payload: BaselineInput, principal=Depends(security.require("baseline"))):
        baseline_id = str(uuid4())
        with db.session(write=True) as execute:
            execute("""INSERT INTO triage_baselines
                (id,label,sample_count,average_seconds,is_demo,created_by,created_at,samples_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (baseline_id, payload.label, len(payload.seconds), sum(payload.seconds) / len(payload.seconds),
                 int(payload.is_demo), principal["id"], utc_now(), json.dumps(payload.seconds)))
        return {"id": baseline_id}

    @app.post("/api/reportes/{report_id}/triaje", dependencies=[Depends(security.require("write"))])
    def review_time(report_id: UUID, payload: ReviewInput):
        with db.session(write=True) as execute:
            saved = execute("""UPDATE triage_measurements SET review_seconds=%s WHERE report_id=%s
                AND EXISTS (SELECT 1 FROM reports WHERE id=%s AND motivo_revision IS NOT NULL)
                RETURNING report_id""", (payload.seconds, str(report_id), str(report_id))).fetchone()
        if not saved:
            raise HTTPException(409, "El reporte debe estar notificado y requerir revisión.")
        return {"report_id": str(report_id), "review_seconds": payload.seconds}

    @app.get("/api/exportar/{format_name}", dependencies=[Depends(security.require("report_export"))])
    def export(format_name: Format):
        return download(db.all_reports(), db.metrics(), format_name, "soc-reportes")
