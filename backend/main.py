import asyncio
import logging
from contextlib import asynccontextmanager
from secrets import compare_digest
from typing import Literal
from uuid import UUID, uuid4
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool
from sqlalchemy.exc import SQLAlchemyError
from redis.exceptions import RedisError

from .classifier import classify
from .config import ROOT, Settings
from .db import Database, utc_now
from .context import identity
from .security import PlatformSecurity
from .runtime import RuntimeServices
from .platform import install_platform_routes
from .chat import install_chat_route
from .routing import routing_policy, assignment_for
from .operations import install_operations
from .navigation import expire_visits
from .provider_health import ProviderHealth
from .impact_study import install_impact_study
from .report_input import ReportInput
from .analytics_audit import install_analytical_audit
from .explainability import install_explainability
from .inference import install_inference


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    responsable: str
    respuesta_min: int
    resolucion_min: int


def create_app(settings=None):
    settings = settings or Settings.from_env()
    db = Database(settings)
    security = PlatformSecurity(settings, db)
    runtime = RuntimeServices(db, security)
    providers = ProviderHealth(settings)

    async def routing_worker():
        while True:
            try:
                await run_in_threadpool(runtime.tick, dispatch)
            except Exception:
                logging.getLogger(__name__).warning("No se pudo procesar la cola de enrutamiento.")
            await asyncio.sleep(5)

    async def navigation_worker():
        while True:
            await asyncio.sleep(30)
            try:
                await run_in_threadpool(expire_visits, db)
            except Exception:
                logging.getLogger(__name__).warning("No se pudo expirar las visitas de auditoría.")

    @asynccontextmanager
    async def lifespan(app):
        db.initialize()
        workers = [asyncio.create_task(navigation_worker())]
        if settings.redis_url:
            workers.append(asyncio.create_task(routing_worker()))
        try:
            yield
        finally:
            for worker in workers:
                worker.cancel()
            for worker in workers:
                try:
                    await worker
                except asyncio.CancelledError:
                    pass
            db.engine.dispose()

    app = FastAPI(title="SOC Report Router", version="0.1.0", lifespan=lifespan)
    app.state.db = db
    app.state.security = security
    install_chat_route(app, security, settings)
    install_analytical_audit(app, db, security)
    install_explainability(app, db, security, settings)
    install_inference(app, db, security)
    app.mount("/static", StaticFiles(directory=ROOT / "frontend" / "dist"), name="static")

    @app.exception_handler(RequestValidationError)
    async def safe_validation(request, error):
        details = [{key: entry[key] for key in ("loc", "msg", "type")} for entry in error.errors()]
        return JSONResponse({"detail": details}, status_code=422)

    @app.middleware("http")
    async def audit_requests(request, call_next):
        if not request.url.path.startswith(("/api/", "/internal/")):
            return await call_next(request)
        request.state.request_id = str(uuid4())
        anonymous = {
            "id": "anonimo", "role": "publico", "ip": request.client.host,
            "request_id": request.state.request_id,
        }
        marker = identity.set(anonymous)
        entry_written = False
        result = None
        try:
            authentication_error = None
            try:
                if request.headers.get("Authorization") or request.headers.get("X-Operator-Token"):
                    principal = await run_in_threadpool(security.authenticate, request)
                    identity.set(principal)
                elif request.url.path.startswith("/internal/") and settings.internal_token and compare_digest(
                    request.headers.get("X-Internal-Token", "").encode(), settings.internal_token.encode()
                ):
                    principal = {**anonymous, "id": "n8n", "role": "servicio"}
                    identity.set(principal)
                    request.state.principal = principal
            except HTTPException as error:
                authentication_error = error

            await run_in_threadpool(db.log_access, identity.get(), request.method, request.url.path, "entry")
            entry_written = True
            if authentication_error:
                result = JSONResponse(
                    {"detail": authentication_error.detail}, status_code=authentication_error.status_code,
                    headers=authentication_error.headers,
                )
            else:
                result = await call_next(request)
            if result.status_code in (401, 403):
                await run_in_threadpool(
                    db.log_access, getattr(request.state, "principal", anonymous),
                    request.method, request.url.path, "rejected", result.status_code,
                )
        except Exception:
            result = JSONResponse(
                {"detail": "No se pudo completar la operación. Revisa los servicios locales."},
                status_code=503,
            )
        finally:
            try:
                if entry_written:
                    principal = getattr(request.state, "principal", anonymous)
                    await run_in_threadpool(
                        db.log_access, principal, request.method, request.url.path,
                        "exit", result.status_code if result else 503,
                    )
            except Exception:
                logging.getLogger(__name__).error("No se pudo escribir la salida de auditoría.")
                result = JSONResponse({"detail": "No se pudo completar la auditoría."}, status_code=503)
            finally:
                identity.reset(marker)
        result.headers["Cache-Control"] = "no-store"
        result.headers["X-Request-ID"] = request.state.request_id
        return result

    def authorize(received, expected):
        if not expected or not compare_digest(received.encode(), expected.encode()):
            raise HTTPException(401, "Token inválido.")

    operator = security.require("read")
    writer = security.require("write")

    def internal(x_internal_token: str = Header(default="")):
        authorize(x_internal_token, settings.internal_token)

    def get_report(report_id):
        row = db.report(str(report_id))
        if row is None:
            raise HTTPException(404, "Reporte no encontrado.")
        return row

    def route_for(report):
        rules = routing_policy(db, report["id"])["configuration"]
        return assignment_for(report, rules)

    def dispatch(report):
        if report["notificado_at"]:
            db.measure_triage(report)
            return report
        report_id = report["id"]
        if settings.router_mode == "local":
            db.assign(report, route_for(report), "local")
            db.notify(get_report(report_id), "local")
        else:
            try:
                with httpx.Client(timeout=12, trust_env=False) as client:
                    res = client.post(
                        settings.n8n_webhook_url,
                        headers={"X-Webhook-Token": settings.n8n_webhook_token},
                        json={"report_id": report_id},
                    )
                    res.raise_for_status()
                if not get_report(report_id)["notificado_at"]:
                    raise ValueError("El flujo no registró la notificación.")
            except (httpx.HTTPError, ValueError):
                with db.session(write=True) as execute:
                    db.event(
                        execute, report_id, "enrutamiento_pendiente", "fastapi",
                        "No se confirmó el flujo de n8n. Reintenta desde la bandeja.",
                    )
        result = get_report(report_id)
        db.measure_triage(result)
        if not result["notificado_at"]:
            runtime.enqueue(report_id)
        runtime.invalidate()
        return result

    def receipt(report):
        return {
            k: v for k, v in report.items() if k not in {"titulo", "descripcion"}
        }

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(ROOT / "frontend" / "dist" / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/health")
    def health(detalle: bool = False):
        status = {
            "estado": "ok", "base": "postgresql" if settings.database_url else "sqlite",
            "clasificador": settings.classifier_mode, "enrutador": settings.router_mode,
        }
        try:
            with db.session() as execute:
                execute("SELECT 1").fetchone()
            database = "ok"
        except SQLAlchemyError:
            database = "error"
        if not detalle:
            return status if database == "ok" else JSONResponse({**status, "estado": "error"}, status_code=503)
        services = {"fastapi": "ok", status["base"]: database, "redis": "local", "langflow": "local", "n8n": "local"}
        if security.redis:
            try:
                services["redis"] = "ok" if security.redis.ping() else "error"
            except RedisError:
                services["redis"] = "error"
        webhook = urlsplit(settings.n8n_webhook_url)
        with httpx.Client(timeout=3, trust_env=False) as client:
            for service, enabled, url in (
                ("langflow", settings.classifier_mode == "langflow", settings.langflow_url.rstrip("/") + "/health"),
                ("n8n", settings.router_mode == "n8n", f"{webhook.scheme}://{webhook.netloc}/healthz/readiness"),
            ):
                if enabled:
                    try:
                        services[service] = "ok" if client.get(url).is_success else "error"
                    except httpx.HTTPError:
                        services[service] = "error"
        return {**status, "estado": "degradado" if "error" in services.values() else "ok",
                "servicios": services, "proveedores": providers.snapshot()}

    @app.post("/api/salud/proveedores", dependencies=[Depends(security.require("manage"))])
    async def check_providers():
        return await providers.check()

    @app.post("/api/reportes", status_code=201)
    def submit(payload: ReportInput, response: Response, request: Request, idempotency_key: UUID | None = Header(None)):
        security.rate_limit("report", request.client.host, settings.report_limit)
        principal = getattr(request.state, "principal", {})
        requester_id = principal["id"] if principal.get("jti") else None
        report_id = str(idempotency_key or uuid4())
        row = db.report(report_id)
        if row is None:
            received_at = utc_now()
            policy = routing_policy(db)
            result, origin, reason = classify(payload.titulo, payload.descripcion, settings, threshold=policy["configuration"]["umbral"])
            created = db.save_report(report_id, payload, result, origin, reason, received_at, policy["id"], requester_id)
            row = get_report(report_id)
        else:
            created = False
        if not created:
            if db.request_owner(report_id) != requester_id or (row["titulo"], row["descripcion"]) != (payload.titulo, payload.descripcion):
                raise HTTPException(409, "La clave de envío ya corresponde a otro reporte.")
            response.status_code = 200
        return receipt(dispatch(row))

    @app.get("/api/mis-solicitudes")
    def my_requests(principal=Depends(security.authenticate)):
        return db.request_progress(principal["id"])

    @app.get("/api/mis-solicitudes/notificaciones")
    def my_notifications(limit: int = Query(100, ge=1, le=500), principal=Depends(security.authenticate)):
        return db.request_notifications(principal["id"], limit)

    @app.put("/api/mis-solicitudes/{report_id}/notificaciones/{accion}/leida", status_code=204)
    def mark_my_notification_read(report_id: UUID, accion: Literal["asignado", "responder", "resolver"],
                                  principal=Depends(security.authenticate)):
        if not db.mark_request_notification_read(principal["id"], str(report_id), accion):
            raise HTTPException(404, "Aviso de la solicitud no encontrado.")

    @app.get("/api/mis-solicitudes/{report_id}")
    def my_request(report_id: UUID, principal=Depends(security.authenticate)):
        row = db.request_progress(principal["id"], str(report_id))
        if row is None:
            raise HTTPException(404, "Solicitud no encontrada.")
        return row

    @app.get("/api/reportes", dependencies=[Depends(operator)])
    def list_reports():
        return db.reports()

    @app.get("/api/reportes/{report_id}", dependencies=[Depends(operator)])
    def report_detail(report_id: UUID):
        return get_report(report_id)

    @app.get("/api/metricas", dependencies=[Depends(operator)])
    def metrics():
        return runtime.metrics()

    @app.get("/api/reportes/{report_id}/bitacora", dependencies=[Depends(security.require("case_audit"))])
    def audit(report_id: UUID):
        get_report(report_id)
        return db.audit(str(report_id))

    install_platform_routes(app, db, security)
    install_impact_study(app, db, security)
    install_operations(app, db, security, get_report)

    @app.post("/api/reportes/{report_id}/reintentar", dependencies=[Depends(writer)])
    def retry(report_id: UUID):
        return dispatch(get_report(report_id))

    @app.post("/api/reportes/{report_id}/{accion}", dependencies=[Depends(writer)])
    def advance(report_id: UUID, accion: Literal["responder", "resolver"]):
        get_report(report_id)
        if not db.advance(str(report_id), accion):
            raise HTTPException(409, "Asigna el reporte y registra la primera respuesta antes de resolver.")
        runtime.invalidate()
        return get_report(report_id)

    @app.get("/internal/reportes/{report_id}/contexto", dependencies=[Depends(internal)])
    def context(report_id: UUID):
        report = get_report(report_id)
        return {
            "report_id": report["id"], "tipo": report["tipo"],
            "severidad": report["severidad"], "revision": bool(report["motivo_revision"]),
            "reglas": {key: value for key, value in routing_policy(db, report["id"])["configuration"].items() if key != "umbral"},
        }

    @app.post("/internal/reportes/{report_id}/asignacion", dependencies=[Depends(internal)])
    def assign(report_id: UUID, rule: Rule):
        report = get_report(report_id)
        if rule.model_dump() != route_for(report):
            raise HTTPException(422, "La asignación no coincide con las reglas vigentes.")
        db.assign(report, rule.model_dump(), "n8n")
        return {"report_id": report["id"]}

    @app.post("/internal/reportes/{report_id}/notificacion", dependencies=[Depends(internal)])
    def notify(report_id: UUID):
        report = get_report(report_id)
        if report["responsable"] is None:
            raise HTTPException(409, "El reporte requiere una asignación.")
        db.notify(report, "n8n")
        return {"report_id": report["id"], "notificado": True}

    return app


app = create_app()
