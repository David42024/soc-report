"""Local provisioning and demo data commands. Secrets are written to a private local file."""
import argparse
import base64
import json
import os
import secrets
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
from dotenv import dotenv_values, set_key

from .config import ROOT, Settings
from .context import identity
from .db import Database, utc_now
from .backups import backup_database
from .demo_cases import CASES
from .security import ROLES, hash_password

RUNTIME = ROOT / ".venv" / "soc-runtime"
LIMA = ZoneInfo("America/Lima")


def bootstrap():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    config = dotenv_values(ROOT / ".env")
    if not config.get("JWT_SECRET"):
        set_key(ROOT / ".env", "JWT_SECRET", secrets.token_urlsafe(48))
    if not config.get("TOTP_ENCRYPTION_KEY"):
        set_key(ROOT / ".env", "TOTP_ENCRYPTION_KEY", base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
    if not config.get("WEASYPRINT_DLL_DIRECTORIES"):
        set_key(ROOT / ".env", "WEASYPRINT_DLL_DIRECTORIES", "C:/Program Files/Tesseract-OCR")
    fontconfig = RUNTIME / "fonts.conf"
    fontconfig.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd"><fontconfig><dir>C:/Windows/Fonts</dir><cachedir>' + (RUNTIME / "font-cache").as_posix() + '</cachedir></fontconfig>', encoding="utf-8")
    set_key(ROOT / ".env", "FONTCONFIG_FILE", fontconfig.as_posix())
    settings = Settings.from_env()
    db = Database(settings)
    db.initialize()
    target = RUNTIME / ("access.json" if settings.database_url else "access-demo.json")
    accounts = json.loads(target.read_text(encoding="utf-8")) if target.exists() else []
    actor = identity.set({"id": "bootstrap", "role": "sistema", "ip": "127.0.0.1"})
    try:
        with db.session(write=True) as execute:
            for role in ROLES:
                if execute("SELECT id FROM users WHERE username=%s", (role,)).fetchone():
                    continue
                password = secrets.token_urlsafe(20)
                execute("INSERT INTO users (id,username,password_hash,role,creado_at) VALUES (%s,%s,%s,%s,%s)",
                        (str(uuid4()), role, hash_password(password), role, utc_now()))
                accounts.append({"username": role, "password": password, "role": role})
        target.write_text(json.dumps(accounts, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        identity.reset(actor)
        db.engine.dispose()
    print(f"Usuarios preparados. Credenciales locales en .venv/soc-runtime/{target.name}")


@contextmanager
def seed_lock():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with (RUNTIME / "seed.lock").open("a+b") as lock:
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("El seeder ya se está ejecutando.") from None
        yield


@contextmanager
def seed_session(api, account):
    auth = api.post("/api/auth/login", json={key: account[key] for key in ("username", "password")}).raise_for_status().json()
    headers = {"Authorization": "Bearer " + auth["access_token"]}
    try:
        yield headers
    finally:
        api.post("/api/auth/logout", headers=headers).raise_for_status()


def seed_case(api, case, requester, operator):
    report_id = str(uuid5(NAMESPACE_URL, f"soc-report-router/demo-curated/2026/{case.number}"))
    path = f"/api/reportes/{report_id}"
    payload = case.payload()
    response = api.post("/api/reportes", headers={**requester, "Idempotency-Key": report_id}, json=payload)
    report = response.raise_for_status().json()
    stage = "enrutamiento_pendiente"
    if report["notificado_at"]:
        if case.stage != "por_atender" and not report["respondido_at"]:
            report = api.post(path + "/responder", headers=operator).raise_for_status().json()
        if case.stage == "resuelto" and not report["resuelto_at"]:
            report = api.post(path + "/resolver", headers=operator).raise_for_status().json()
        stage = "por_atender"
        if report["resuelto_at"]:
            stage = "resuelto"
        elif report["respondido_at"]:
            stage = "en_atencion"

        collaboration = api.get(path + "/colaboracion", headers=operator).raise_for_status().json()
        if not any(item["contenido"] == case.note for item in collaboration["comentarios"]):
            api.post(path + "/comentarios", headers=operator, json={"contenido": case.note}).raise_for_status()
        if case.evidence:
            name, content = case.evidence
            if not any(item["nombre"] == name for item in collaboration["adjuntos"]):
                api.post(path + "/adjuntos", headers=operator, json={
                    "nombre": name, "base64": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                }).raise_for_status()
    return {
        "id": report_id, "titulo": payload["titulo"], "origen": report["origen"], "tipo": report["tipo"],
        "severidad": report["severidad"], "responsable": report["responsable"], "estado": stage,
        "notificado": bool(report["notificado_at"]), "creado": response.status_code == 201,
        **{field: datetime.fromisoformat(report[field]).astimezone(LIMA).isoformat() if report[field] else None
           for field in ("recibido_at", "respondido_at", "resuelto_at")},
    }


def reset_seed_data():
    """Back up and clear report/demo data while preserving accounts and audit history."""
    settings = Settings.from_env()
    db = Database(settings)
    db.initialize()
    try:
        backup = backup_database(db)
        marker = identity.set({"id": "seed-reset", "role": "sistema", "ip": "127.0.0.1"})
        try:
            with db.session(write=True) as execute:
                existing = execute("SELECT COUNT(*) AS total FROM reports").fetchone()["total"]
                for table in (
                    "impact_observations", "impact_studies", "triage_measurements",
                    "request_notification_reads", "report_comments", "report_attachments",
                    "notification_reads", "report_requesters", "report_routing_versions",
                    "report_reviews", "bitacora", "assignments", "reports",
                    "demo_impact_history", "triage_baselines",
                ):
                    execute(f"DELETE FROM {table}")
        finally:
            identity.reset(marker)
        print(f"Reseed: {existing} reportes eliminados. Copia previa: {backup.relative_to(ROOT)}", flush=True)
        print("Se conservaron usuarios, sesiones, configuración y audit_log inmutable.", flush=True)
    finally:
        db.engine.dispose()


def seed(count, *, reset=False):
    cases = CASES[:count]
    if count > len(cases):
        print(f"La muestra contiene {len(cases)} casos distintos. Se cargarán esos casos.", flush=True)
    with seed_lock():
        if reset:
            reset_seed_data()
            seed_history()
        seed_cases(cases)


def seed_cases(cases):
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=120, trust_env=False) as api:
        database = api.get("/health").raise_for_status().json()["base"]
        access = "access.json" if database == "postgresql" else "access-demo.json"
        accounts = {account["role"]: account for account in json.loads((RUNTIME / access).read_text(encoding="utf-8"))}
        requester_account = accounts["solicitante"]
        with seed_session(api, accounts["administrador"]) as operator, seed_session(api, requester_account) as requester:
            if api.get("/api/triage", headers=operator).raise_for_status().json()["baseline"] is None:
                api.post("/api/triage/baselines", headers=operator, json={
                    "label": "Demostración sintética de triaje manual", "seconds": [120, 150, 180, 135, 165], "is_demo": True,
                }).raise_for_status()
            results = []
            for case in cases:
                result = seed_case(api, case, requester, operator)
                result["solicitante"] = requester_account["username"]
                results.append(result)
                operation = "creado" if result["creado"] else "reutilizado"
                print(f"[{case.number}/{len(cases)}] {result['titulo']} | {result['estado']} | {operation}", flush=True)
        evidence = RUNTIME / ("seed-evidence.json" if database == "postgresql" else "seed-evidence-demo.json")
        staged = evidence.with_suffix(".tmp")
        staged.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        staged.replace(evidence)
        if any(not result["notificado"] for result in results):
            raise RuntimeError("Hay casos pendientes de enrutamiento. Revisa n8n y vuelve a ejecutar el seeder.")


def seed_history():
    """Historical demonstration aggregates, stored apart from case records."""
    settings = Settings.from_env()
    db = Database(settings)
    db.initialize()
    today = datetime.now(LIMA).date()
    current_month = today.year * 12 + today.month - 1
    scenarios = [
        (22, 20, 720, 90), (26, 25, 600, 80), (30, 29, 480, 70),
        (33, 32, 360, 60), (36, 35, 240, 45), (38, 37, 120, 30),
    ]
    marker = identity.set({"id": "seed-history-demo", "role": "sistema", "ip": "127.0.0.1"})
    try:
        with db.session(write=True) as execute:
            for offset, (response, resolution, cycle, review) in enumerate(scenarios):
                year, month = divmod(current_month - 6 + offset, 12)
                period = f"{year:04d}-{month+1:02d}"
                execute("""INSERT INTO demo_impact_history
                    (period,report_count,response_on_time,resolution_on_time,
                     manual_seconds,automated_seconds,review_seconds,created_at)
                    VALUES (%s,40,%s,%s,900,%s,%s,%s)
                    ON CONFLICT (period) DO NOTHING""",
                    (period, response, resolution, cycle, review, utc_now()))
    finally:
        identity.reset(marker)
        db.engine.dispose()
    print("Histórico DEMO preparado. Seis meses simulados en una tabla separada.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["bootstrap", "seed", "seed-history"])
    parser.add_argument("--count", type=int, choices=range(1, 31), default=len(CASES),
                        help="Número de casos. La muestra tiene seis casos distintos.")
    parser.add_argument("--reset", action="store_true",
                        help="Antes de sembrar, respalda y elimina reportes, actividad y métricas DEMO anteriores.")
    args = parser.parse_args()
    if args.command == "bootstrap":
        bootstrap()
    elif args.command == "seed-history":
        seed_history()
    else:
        seed(args.count, reset=args.reset)
