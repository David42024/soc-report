"""Prepare local container settings without printing credentials."""
import json
import secrets
import shutil
from pathlib import Path
from urllib.parse import urlsplit, unquote, quote

from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[1]
runtime = ROOT / ".venv/soc-runtime"
config = dotenv_values(ROOT / ".env")
backup = runtime / "env-before-platform.backup"
if not backup.exists():
    shutil.copy2(ROOT / ".env", backup)
url = urlsplit(config["DATABASE_URL"])
compose = runtime / "compose.env"
existing = dotenv_values(compose) if compose.exists() else {}
redis_password = existing.get("SOC_REDIS_PASSWORD") or secrets.token_urlsafe(32)
compose.touch(exist_ok=True)
for name, value in {
    "SOC_PG_USER": unquote(url.username),
    "SOC_PG_PASSWORD": unquote(url.password),
    "SOC_PG_DATABASE": url.path.strip("/"),
    "SOC_REDIS_PASSWORD": redis_password,
}.items():
    set_key(compose, name, value)
destination = runtime / "n8n-docker"
if not destination.exists():
    shutil.copytree(runtime / ".n8n", destination)
set_key(ROOT / ".env", "REDIS_URL", f"redis://:{quote(redis_password, safe='')}@127.0.0.1:6380/0")
set_key(ROOT / ".env", "LEGACY_OPERATOR_ENABLED", "false")
webhook = urlsplit(config["N8N_WEBHOOK_URL"])
set_key(ROOT / ".env", "N8N_WEBHOOK_URL", webhook._replace(netloc="127.0.0.1:5680").geturl())
if not config.get("JWT_SECRET"):
    set_key(ROOT / ".env", "JWT_SECRET", secrets.token_urlsafe(48))
# Adjust only the project workflow's callback host in the copied database.
import sqlite3
db = sqlite3.connect(destination / "database.sqlite")
row = db.execute("SELECT id,nodes FROM workflow_entity WHERE name LIKE '%Asignar reporte%'").fetchone()
if row:
    nodes = json.loads(row[1])
    for node in nodes:
        parameters = node.get("parameters", {})
        if "url" in parameters:
            parameters["url"] = parameters["url"].replace("http://127.0.0.1:8000/", "http://host.docker.internal:8000/")
    db.execute("UPDATE workflow_entity SET nodes=? WHERE id=?", (json.dumps(nodes), row[0]))
    db.commit()
    print("Workflow SOC preparado para callbacks desde Docker.")
db.close()
print("Configuración de contenedores lista. Credenciales conservadas localmente.")
