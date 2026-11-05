from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from inspect import getsource
from uuid import uuid4

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url

from .config import ROOT
from .backups import backup_database
from .context import identity


REPORTS = """
SELECT r.*, a.responsable, a.asignado_at, a.vence_respuesta_at,
       a.vence_resolucion_at, a.respondido_at, a.resuelto_at,
       n.ocurrido_at AS notificado_at
FROM reports r
LEFT JOIN assignments a ON a.report_id = r.id
LEFT JOIN bitacora n ON n.report_id = r.id AND n.accion = 'notificacion'
"""

REQUEST_PROGRESS = """
SELECT r.id, r.titulo, r.descripcion, r.recibido_at, a.responsable, a.asignado_at,
       a.vence_respuesta_at, a.vence_resolucion_at, a.respondido_at, a.resuelto_at
FROM report_requesters owner
JOIN reports r ON r.id = owner.report_id
LEFT JOIN assignments a ON a.report_id = r.id
WHERE owner.user_id = %s
"""


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def deadline(received, minutes):
    start = datetime.fromisoformat(received) if isinstance(received, str) else received
    return (start + timedelta(minutes=minutes)).astimezone(timezone.utc).isoformat(
        timespec="microseconds"
    )


class Database:
    def __init__(self, settings):
        self.url = settings.database_url
        self.path = settings.sqlite_path
        url = make_url(self.url).set(drivername="postgresql+psycopg") if self.url else f"sqlite:///{self.path}"
        args = {"connect_timeout": 5} if self.url else {"timeout": 10, "check_same_thread": False}
        self.engine = create_engine(url, connect_args=args, pool_pre_ping=True)
        if not self.url:
            @event.listens_for(self.engine, "connect")
            def sqlite_foreign_keys(connection, record):
                connection.execute("PRAGMA foreign_keys = ON")

    @contextmanager
    def session(self, *, write=False, schema_upgrade=False):
        with self.engine.connect() as connection:
            def execute(query, params=()):
                pieces = query.split("%s")
                statement = pieces[0] + "".join(f":p{i}" + part for i, part in enumerate(pieces[1:]))
                return connection.execute(text(statement), {f"p{i}": value for i, value in enumerate(params)}).mappings()

            sqlite_upgrade = schema_upgrade and not self.url
            if sqlite_upgrade:
                connection.exec_driver_sql("PRAGMA foreign_keys = OFF")
            try:
                if write and not self.url:
                    connection.exec_driver_sql("BEGIN IMMEDIATE")
                actor = identity.get() or {}
                if self.url:
                    execute("SELECT set_config('soc.user_id', %s, true), set_config('soc.role', %s, true), set_config('soc.ip', %s, true), set_config('soc.request_id', %s, true)",
                            (actor.get("id", "sistema"), actor.get("role", "sistema"), actor.get("ip", ""), actor.get("request_id") or ""))
                yield execute
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                if sqlite_upgrade:
                    connection.exec_driver_sql("PRAGMA foreign_keys = ON")

    def initialize(self):
        schema = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
        fingerprint = sha256((schema + getsource(self.upgrade_columns) + getsource(self.install_audit_triggers)).encode()).hexdigest()
        with self.session(write=True, schema_upgrade=True) as execute:
            if self.url:
                execute("SELECT pg_advisory_xact_lock(640256167)")
                tables = {row["table_name"] for row in execute("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_type='BASE TABLE'")}
            else:
                tables = {row["name"] for row in execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if "soc_schema_revision" in tables:
                revision = execute("SELECT fingerprint FROM soc_schema_revision WHERE id=1").fetchone()
                if revision and revision["fingerprint"] == fingerprint:
                    return
            if tables:
                backup_database(self)
            for statement in map(str.strip, schema.split(";")):
                if statement:
                    execute(statement)
            users_definition = next(s.strip() for s in schema.split(";") if s.strip().startswith("CREATE TABLE IF NOT EXISTS users ("))
            self.upgrade_columns(execute, users_definition)
            self.install_audit_triggers(execute)
            execute("CREATE TABLE IF NOT EXISTS soc_schema_revision (id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL)")
            execute("""INSERT INTO soc_schema_revision (id,fingerprint) VALUES (1,%s)
                ON CONFLICT (id) DO UPDATE SET fingerprint=excluded.fingerprint""", (fingerprint,))

    def upgrade_columns(self, execute, users_definition):
        def columns(table):
            if self.url:
                rows = execute("""SELECT column_name FROM information_schema.columns
                    WHERE table_schema=current_schema() AND table_name=%s""", (table,))
                return {row["column_name"] for row in rows}
            return {row["name"] for row in execute(f"PRAGMA table_info({table})")}

        if "samples_json" not in columns("triage_baselines"):
            execute("ALTER TABLE triage_baselines ADD COLUMN samples_json TEXT NOT NULL DEFAULT '[]'")
        audit_columns = columns("audit_log")
        if "request_id" not in audit_columns:
            execute("ALTER TABLE audit_log ADD COLUMN request_id TEXT")
        if "outcome" not in audit_columns:
            execute("ALTER TABLE audit_log ADD COLUMN outcome TEXT")
        execute("CREATE INDEX IF NOT EXISTS audit_request_idx ON audit_log (request_id)")
        if self.url:
            role_check = execute("""SELECT pg_get_constraintdef(oid) AS definition FROM pg_constraint
                WHERE conrelid='users'::regclass AND conname='users_role_check'""").fetchone()
            if not role_check or "'solicitante'" not in role_check["definition"]:
                execute("""ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check,
                    ADD CONSTRAINT users_role_check
                    CHECK (role IN ('administrador', 'analista', 'gestor', 'auditor', 'solicitante'))""")
        else:
            definition = execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()["sql"]
            if "'solicitante'" not in definition:
                execute(users_definition.replace("CREATE TABLE IF NOT EXISTS users (", "CREATE TABLE users_upgrade (", 1))
                fields = "id, username, password_hash, role, active, token_version, creado_at"
                execute(f"INSERT INTO users_upgrade ({fields}) SELECT {fields} FROM users")
                execute("DROP TABLE users")
                execute("ALTER TABLE users_upgrade RENAME TO users")
            if execute("PRAGMA foreign_key_check").first():
                raise RuntimeError("La migración SQLite dejó referencias inválidas.")

    def report(self, report_id):
        with self.session() as execute:
            row = execute(REPORTS + " WHERE r.id = %s", (report_id,)).fetchone()
            return dict(row) if row else None

    def reports(self):
        with self.session() as execute:
            return [
                dict(row) for row in execute(
                    REPORTS + " ORDER BY r.recibido_at DESC, r.id LIMIT 100"
                ).fetchall()
            ]

    def request_owner(self, report_id):
        with self.session() as execute:
            row = execute("SELECT user_id FROM report_requesters WHERE report_id = %s", (report_id,)).fetchone()
            return row["user_id"] if row else None

    def request_progress(self, user_id, report_id=None):
        with self.session() as execute:
            if report_id is not None:
                row = execute(REQUEST_PROGRESS + " AND r.id = %s", (user_id, report_id)).fetchone()
                return dict(row) if row else None
            rows = execute(REQUEST_PROGRESS + " ORDER BY r.recibido_at DESC, r.id", (user_id,)).fetchall()
            return [dict(row) for row in rows]

    def request_notifications(self, user_id, limit):
        with self.session() as execute:
            rows = execute("""SELECT b.report_id, r.titulo, a.responsable, b.accion, b.ocurrido_at, n.read_at
                FROM report_requesters owner
                JOIN reports r ON r.id = owner.report_id
                JOIN bitacora b ON b.report_id = owner.report_id
                LEFT JOIN assignments a ON a.report_id = owner.report_id
                LEFT JOIN request_notification_reads n ON n.user_id = owner.user_id
                    AND n.report_id = b.report_id AND n.accion = b.accion
                WHERE owner.user_id = %s AND b.accion IN ('asignado', 'responder', 'resolver')
                ORDER BY b.ocurrido_at DESC, b.report_id, b.accion LIMIT %s""", (user_id, limit))
            return [dict(row) for row in rows]

    def mark_request_notification_read(self, user_id, report_id, action):
        with self.session(write=True) as execute:
            exists = execute("""SELECT 1 FROM report_requesters owner
                JOIN bitacora b ON b.report_id = owner.report_id
                WHERE owner.user_id = %s AND owner.report_id = %s AND b.accion = %s""",
                (user_id, report_id, action)).first()
            if not exists:
                return False
            execute("""INSERT INTO request_notification_reads (user_id, report_id, accion, read_at)
                VALUES (%s, %s, %s, %s) ON CONFLICT (user_id, report_id, accion) DO NOTHING""",
                (user_id, report_id, action, utc_now()))
            return True

    def audit(self, report_id):
        with self.session() as execute:
            return [
                dict(row) for row in execute(
                    """SELECT accion, actor, ocurrido_at, detalle FROM bitacora
                       WHERE report_id = %s
                       ORDER BY ocurrido_at, CASE accion
                           WHEN 'recibido' THEN 1
                           WHEN 'clasificado' THEN 2
                           WHEN 'enrutamiento_pendiente' THEN 3
                           WHEN 'asignado' THEN 4
                           WHEN 'notificacion' THEN 5
                           WHEN 'responder' THEN 6
                           WHEN 'resolver' THEN 7
                       END, accion""", (report_id,)
                ).fetchall()
            ]

    @staticmethod
    def event(execute, report_id, action, actor, details):
        execute(
            """INSERT INTO bitacora (report_id, accion, actor, ocurrido_at, detalle)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (report_id, accion) DO NOTHING""",
            (report_id, action, actor, utc_now(), details),
        )

    def save_report(self, report_id, payload, result, origin, reason, received_at, version_id=None, requester_id=None):
        with self.session(write=True) as execute:
            row = execute(
                """INSERT INTO reports (
                    id, titulo, descripcion, tipo, severidad, activo_afectado, confianza,
                    origen, motivo_revision, recibido_at, clasificado_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING RETURNING id""",
                (report_id, payload.titulo, payload.descripcion, result.tipo, result.severidad,
                 result.activo_afectado, result.confianza, origin, reason, received_at, utc_now()),
            ).fetchone()
            if row:
                if requester_id:
                    execute("INSERT INTO report_requesters (report_id,user_id) VALUES (%s,%s)", (report_id, requester_id))
                if version_id:
                    execute("INSERT INTO report_routing_versions (report_id,version_id) VALUES (%s,%s)", (report_id, version_id))
                self.event(execute, report_id, "recibido", "formulario", "Reporte registrado.")
                detail = f"{result.tipo} / {result.severidad}"
                if reason:
                    detail += f" / {reason}"
                if result.provider:
                    detail += f" / proveedor={result.provider}"
                self.event(execute, report_id, "clasificado", origin, detail)
            return row is not None

    def assign(self, report, rule, actor):
        report_id = report["id"]
        with self.session(write=True) as execute:
            row = execute(
                """INSERT INTO assignments (report_id, responsable, asignado_at,
                       vence_respuesta_at, vence_resolucion_at)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (report_id) DO NOTHING RETURNING report_id""",
                (report_id, rule["responsable"], utc_now(),
                 deadline(report["recibido_at"], rule["respuesta_min"]),
                 deadline(report["recibido_at"], rule["resolucion_min"])),
            ).fetchone()
            if row:
                self.event(execute, report_id, "asignado", actor, rule["responsable"])

    def notify(self, report, actor):
        with self.session(write=True) as execute:
            self.event(
                execute, report["id"], "notificacion", actor,
                f"Nuevo reporte para {report['responsable']}.",
            )

    def advance(self, report_id, action):
        with self.session(write=True) as execute:
            query = "SELECT respondido_at, resuelto_at FROM assignments WHERE report_id = %s"
            row = execute(query + (" FOR UPDATE" if self.url else ""), (report_id,)).fetchone()
            if row is None:
                return False
            if action == "resolver" and row["respondido_at"] is None:
                return False
            column = "respondido_at" if action == "responder" else "resuelto_at"
            if row[column] is None:
                execute(
                    f"UPDATE assignments SET {column} = %s WHERE report_id = %s",
                    (utc_now(), report_id),
                )
                self.event(execute, report_id, action, "operador", "Hito confirmado.")
            return True

    def metrics(self):
        now = utc_now()
        with self.session() as execute:
            return dict(execute(
                """SELECT COUNT(*) AS total,
                       COUNT(a.report_id) AS asignados,
                       COUNT(r.motivo_revision) AS requieren_revision,
                       COUNT(CASE WHEN a.respondido_at <= a.vence_respuesta_at THEN 1 END)
                           AS respuesta_a_tiempo,
                       COUNT(CASE WHEN a.resuelto_at <= a.vence_resolucion_at THEN 1 END)
                           AS resolucion_a_tiempo,
                       COUNT(CASE WHEN a.respondido_at IS NOT NULL
                                       OR a.vence_respuesta_at < %s THEN 1 END)
                           AS respuesta_evaluable,
                       COUNT(CASE WHEN a.resuelto_at IS NOT NULL
                                       OR a.vence_resolucion_at < %s THEN 1 END)
                           AS resolucion_evaluable
                   FROM reports r LEFT JOIN assignments a ON a.report_id = r.id""",
                (now, now),
            ).fetchone())

    def install_audit_triggers(self, execute):
        if self.url:
            execute("""
                CREATE OR REPLACE FUNCTION soc_audit_immutable() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'audit_log es inmutable';
                END $$""")
            execute("""
                CREATE OR REPLACE FUNCTION soc_audit_change() RETURNS trigger
                LANGUAGE plpgsql AS $$
                DECLARE entity text;
                BEGIN
                    entity := COALESCE(to_jsonb(NEW)->>'id',to_jsonb(NEW)->>'report_id',to_jsonb(NEW)->>'period',
                                       to_jsonb(OLD)->>'id',to_jsonb(OLD)->>'report_id',to_jsonb(OLD)->>'period',
                                       to_jsonb(NEW)->>'nombre',to_jsonb(OLD)->>'nombre');
                    INSERT INTO audit_log (id,user_id,role,action,module,ip,occurred_at,phase,outcome,entity_id,request_id)
                    VALUES (gen_random_uuid()::text,
                        COALESCE(NULLIF(current_setting('soc.user_id',true),''),'sistema'),
                        COALESCE(NULLIF(current_setting('soc.role',true),''),'sistema'),
                        TG_OP,TG_TABLE_NAME,
                        COALESCE(current_setting('soc.ip',true),''),
                        clock_timestamp(),'change','registrado',entity,NULLIF(current_setting('soc.request_id',true),''));
                    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                    RETURN NEW;
                END $$""")
            for operation in ("UPDATE", "DELETE", "TRUNCATE"):
                name = f"audit_no_{operation.lower()}"
                execute(f"DROP TRIGGER IF EXISTS {name} ON audit_log")
                execute(f"CREATE TRIGGER {name} BEFORE {operation} ON audit_log FOR EACH STATEMENT EXECUTE FUNCTION soc_audit_immutable()")
            for table in (
                "reports", "assignments", "users", "bitacora", "triage_baselines", "triage_measurements",
                "demo_impact_history", "routing_versions", "report_reviews", "assets",
                "team_directory", "report_comments", "report_attachments", "notification_reads",
                "impact_studies", "impact_observations", "report_requesters",
            ):
                execute(f"DROP TRIGGER IF EXISTS soc_change ON {table}")
                execute(f"CREATE TRIGGER soc_change AFTER INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION soc_audit_change()")
        else:
            for operation in ("UPDATE", "DELETE"):
                execute(f"""CREATE TRIGGER IF NOT EXISTS audit_no_{operation.lower()}
                    BEFORE {operation} ON audit_log BEGIN
                    SELECT RAISE(ABORT, 'audit_log es inmutable'); END""")

    def log_access(self, actor, action, module, phase, status=None, entity=None):
        with self.session(write=True) as execute:
            self.access_event(execute, actor, action, module, phase, status, entity)

    @staticmethod
    def access_event(execute, actor, action, module, phase, status=None, entity=None, *, outcome=None):
        actor = actor or {}
        if outcome is None:
            if phase == "entry":
                outcome = "iniciado"
            elif phase == "rejected" or status in (401, 403):
                outcome = "rechazado"
            elif status is not None:
                outcome = "error" if status >= 400 else "completado"
            else:
                outcome = "registrado"
        execute("""INSERT INTO audit_log
            (id,user_id,role,action,module,ip,occurred_at,phase,outcome,status_code,entity_id,request_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (str(uuid4()), actor.get("id", "anonimo"), actor.get("role", "publico"), action, module,
             actor.get("ip", ""), utc_now(), phase, outcome, status, entity, actor.get("request_id")))

    def audit_records(self, limit=200, before=None, *, clauses=(), values=()):
        with self.session() as execute:
            conditions, params = list(clauses), list(values)
            if before:
                row = execute("SELECT occurred_at FROM audit_log WHERE id=%s", (before,)).fetchone()
                if not row:
                    return []
                conditions.append("(occurred_at < %s OR (occurred_at = %s AND id < %s))")
                params.extend((row["occurred_at"], row["occurred_at"], before))
            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            return [dict(item) for item in execute(
                "SELECT * FROM audit_log" + where + " ORDER BY occurred_at DESC,id DESC LIMIT %s", (*params, limit)
            ).fetchall()]

    def all_reports(self):
        with self.session() as execute:
            return [dict(row) for row in execute(REPORTS + " ORDER BY r.recibido_at DESC,r.id").fetchall()]

    def measure_triage(self, report):
        if not report["notificado_at"]:
            return
        def timestamp(value):
            return datetime.fromisoformat(value) if isinstance(value, str) else value
        seconds = max(0, (timestamp(report["notificado_at"]) - timestamp(report["recibido_at"])).total_seconds())
        with self.session(write=True) as execute:
            baseline = execute("SELECT id FROM triage_baselines ORDER BY created_at DESC,id DESC LIMIT 1").fetchone()
            execute("""INSERT INTO triage_measurements
                (report_id,elapsed_seconds,review_seconds,baseline_id,measured_at)
                VALUES (%s,%s,%s,%s,%s) ON CONFLICT (report_id) DO NOTHING""",
                (report["id"], seconds, None if report["motivo_revision"] else 0,
                 baseline["id"] if baseline else None, utc_now()))

    def triage_metrics(self):
        with self.session() as execute:
            baseline = execute("SELECT * FROM triage_baselines ORDER BY created_at DESC,id DESC LIMIT 1").fetchone()
            rows = execute("""SELECT m.*,b.average_seconds,b.is_demo FROM triage_measurements m
                LEFT JOIN triage_baselines b ON b.id=m.baseline_id""").fetchall()
        comparable = [row for row in rows if row["average_seconds"] is not None and row["review_seconds"] is not None]
        seconds_saved = sum(row["average_seconds"] - row["elapsed_seconds"] - row["review_seconds"] for row in comparable)
        return {
            "baseline": dict(baseline) if baseline else None,
            "measured_reports": len(rows), "comparable_reports": len(comparable),
            "pending_review_measurements": sum(row["review_seconds"] is None for row in rows),
            "average_cycle_seconds": sum(row["elapsed_seconds"] for row in rows) / len(rows) if rows else None,
            "estimated_hours_saved": seconds_saved / 3600 if comparable else None,
            "demo_comparisons": sum(bool(row["is_demo"]) for row in comparable),
        }

    def impact_history(self):
        with self.session() as execute:
            rows = [dict(row) for row in execute(
                "SELECT * FROM demo_impact_history ORDER BY period"
            ).fetchall()]
            measured_baselines = execute(
                "SELECT COUNT(*) AS total FROM triage_baselines WHERE is_demo=0"
            ).fetchone()["total"]
        periods = []
        for row in rows:
            count = row["report_count"]
            periods.append({
                "period": row["period"], "source": "demo", "report_count": count,
                "response_on_time": row["response_on_time"],
                "resolution_on_time": row["resolution_on_time"],
                "response_pct": 100 * row["response_on_time"] / count,
                "resolution_pct": 100 * row["resolution_on_time"] / count,
                "manual_seconds_per_case": row["manual_seconds"],
                "automated_seconds_per_case": row["automated_seconds"],
                "review_seconds_per_case": row["review_seconds"],
                "estimated_hours_saved": count * (
                    row["manual_seconds"] - row["automated_seconds"] - row["review_seconds"]
                ) / 3600,
            })
        return {
            "source": "demo", "is_demo": True, "sla_target_pct": 90,
            "periods": periods, "measured_baselines": measured_baselines,
        }
