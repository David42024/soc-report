"""Copy the original SOC tables to PostgreSQL 16, verify every row, then switch the URL."""
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import dotenv_values, set_key
import psycopg
from psycopg.rows import dict_row

from backend.config import ROOT, Settings
from backend.backups import backup_database
from backend.context import identity
from backend.db import Database

runtime = ROOT / ".venv/soc-runtime"
source_config = dotenv_values(runtime / "env-before-platform.backup")
source_url = source_config["DATABASE_URL"]
url = urlsplit(source_url)
destination_url = url._replace(netloc=f"{url.username}:{url.password}@127.0.0.1:5434").geturl()
tables = {}
with psycopg.connect(source_url, row_factory=dict_row, connect_timeout=5) as source:
    for table in ("reports", "assignments", "bitacora"):
        tables[table] = source.execute(f"SELECT * FROM {table}").fetchall()
snapshot = runtime / "postgres-before-platform.json"
if not snapshot.exists():
    snapshot.write_text(json.dumps(tables, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
target = Database(Settings(database_url=destination_url))
target.initialize()
backup_database(target)
marker = identity.set({"id": "migracion-pg16", "role": "sistema", "ip": "127.0.0.1"})
try:
    with target.session(write=True) as execute:
        for table, rows in tables.items():
            for row in rows:
                columns = list(row)
                names = ",".join(columns)
                placeholders = ",".join(["%s"] * len(columns))
                execute(f"INSERT INTO {table} ({names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING", tuple(row.values()))
            for row in rows:
                key_columns = ("report_id", "accion") if table == "bitacora" else ("report_id",) if table == "assignments" else ("id",)
                where = " AND ".join(f"{column}=%s" for column in key_columns)
                saved = execute(f"SELECT * FROM {table} WHERE {where}", tuple(row[column] for column in key_columns)).fetchone()
                if dict(saved) != row:
                    raise RuntimeError(f"La verificación de {table} no coincide. La configuración original sigue activa.")
            print(f"{table}: {len(rows)} filas verificadas")
finally:
    identity.reset(marker)
    target.engine.dispose()
set_key(ROOT / ".env", "DATABASE_URL", destination_url)
print("PostgreSQL 16 seleccionado en el puerto 5434. Origen y respaldo conservados.")
