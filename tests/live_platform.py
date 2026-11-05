"""Opt-in checks against the local production stack, using disposable test identities."""
import json
import unittest
from io import BytesIO
from uuid import uuid4

import httpx
import psycopg
from redis import Redis
from openpyxl import load_workbook
from docx import Document
from dotenv import dotenv_values

from backend.config import ROOT


class LivePlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = dotenv_values(ROOT / ".env")
        cls.accounts = json.loads((ROOT / ".venv/soc-runtime/access.json").read_text(encoding="utf-8"))
        cls.api = httpx.Client(base_url="http://127.0.0.1:8000", timeout=90, trust_env=False)
        cls.tokens = {}
        for account in cls.accounts:
            result = cls.api.post("/api/auth/login", json={key: account[key] for key in ("username", "password")}).raise_for_status().json()
            cls.tokens[account["role"]] = {"Authorization": "Bearer " + result["access_token"]}

    @classmethod
    def tearDownClass(cls):
        for headers in cls.tokens.values():
            cls.api.post("/api/auth/logout", headers=headers)
        cls.api.close()

    def test_database_version_redis_cache_and_session(self):
        with psycopg.connect(self.config["DATABASE_URL"], connect_timeout=5) as db:
            self.assertTrue(db.execute("SHOW server_version").fetchone()[0].startswith("16."))
        redis = Redis.from_url(self.config["REDIS_URL"])
        self.assertTrue(redis.ping())
        self.api.get("/api/metricas", headers=self.tokens["administrador"]).raise_for_status()
        self.assertTrue(redis.exists("soc:metrics"))
        self.assertTrue(list(redis.scan_iter("soc:session:*", count=100)))

    def test_cloud_health_requires_admin_and_reports_each_provider(self):
        path = "/api/salud/proveedores"
        self.assertEqual(self.api.post(path).status_code, 401)
        self.assertEqual(self.api.post(path, headers=self.tokens["gestor"]).status_code, 403)
        diagnostics = self.api.post(path, headers=self.tokens["administrador"]).raise_for_status().json()
        self.assertEqual({name: probe["estado"] for name, probe in diagnostics.items()}, {"groq": "ok", "gemini": "ok"})
        self.assertEqual(self.api.get("/health?detalle=true").raise_for_status().json()["proveedores"], diagnostics)

    def test_all_roles_and_three_real_exports(self):
        for role, headers in self.tokens.items():
            with self.subTest(role=role):
                self.assertEqual(self.api.get("/api/reportes", headers=headers).status_code,
                                 200 if role in ("administrador", "analista", "gestor") else 403)
                self.assertEqual(self.api.get("/api/audit", headers=headers).status_code, 200 if role in ("auditor", "administrador") else 403)
                self.assertEqual(self.api.get("/api/users", headers=headers).status_code, 200 if role == "administrador" else 403)
                for path in ("/api/exportar/xlsx", "/api/informes/cola/xlsx"):
                    self.assertEqual(self.api.get(path, headers=headers).status_code,
                                     200 if role in ("administrador", "gestor") else 403)
                self.assertEqual(self.api.get("/api/audit/exportar/xlsx?modulo=dashboard", headers=headers).status_code,
                                 200 if role in ("administrador", "auditor") else 403)
        manager = self.tokens["gestor"]
        pdf = self.api.get("/api/exportar/pdf", headers=manager).raise_for_status()
        self.assertTrue(pdf.content.startswith(b"%PDF-"))
        self.assertTrue(Document(BytesIO(self.api.get("/api/exportar/docx", headers=manager).raise_for_status().content)).paragraphs)
        workbook = load_workbook(BytesIO(self.api.get("/api/exportar/xlsx", headers=manager).raise_for_status().content))
        self.assertGreater(workbook["Reportes"].max_row, 1)

    def test_extended_permissions_and_filtered_exports_in_postgresql(self):
        for role, headers in self.tokens.items():
            with self.subTest(role=role):
                can_read = role in ("administrador", "analista", "gestor")
                for route, allowed in (
                    ("dashboard", can_read), ("activos", can_read),
                    ("equipos", can_read), ("notificaciones", can_read),
                    ("revision", role in ("administrador", "analista")), ("reglas", role == "administrador"),
                ):
                    self.assertEqual(self.api.get("/api/" + route, headers=headers).status_code, 200 if allowed else 403)
        manager = self.tokens["gestor"]
        nav = self.api.post("/api/audit/navegacion", headers=manager, json={"anterior": "inbox", "siguiente": "dashboard"})
        self.assertEqual(nav.status_code, 204)
        with psycopg.connect(self.config["DATABASE_URL"], connect_timeout=5) as db:
            self.assertEqual(db.execute("""SELECT action,module FROM audit_log WHERE request_id=%s AND phase='navigation'
                ORDER BY occurred_at""", (nav.headers["X-Request-ID"],)).fetchall(),
                [("module_exit", "inbox"), ("module_enter", "dashboard")])
        params = {"tipo": "phishing"}
        dashboard = self.api.get("/api/dashboard", params=params, headers=manager).raise_for_status().json()
        self.assertEqual(dashboard["tipos"], {"phishing": dashboard["total"]} if dashboard["total"] else {})
        data = {}
        for format_name in ("pdf", "docx", "xlsx"):
            data[format_name] = self.api.get("/api/informes/tendencia/" + format_name, params=params,
                                             headers=manager).raise_for_status().content
        self.assertTrue(data["pdf"].startswith(b"%PDF-") and data["pdf"].rstrip().endswith(b"%%EOF"))
        word = Document(BytesIO(data["docx"]))
        self.assertEqual(sum(int(row.cells[1].text) for row in word.tables[0].rows[1:]), dashboard["total"])
        sheet = load_workbook(BytesIO(data["xlsx"])).active
        self.assertEqual(sum(int(row[1]) for row in list(sheet.values)[1:]), dashboard["total"])

    def test_immutable_log_and_postgresql_change_triggers(self):
        admin = self.tokens["administrador"]
        username = "test_" + uuid4().hex[:12]
        user = self.api.post("/api/users", headers=admin, json={
            "username": username, "password": uuid4().hex + uuid4().hex, "role": "analista",
        }).raise_for_status().json()
        self.api.put(f"/api/users/{user['id']}", headers=admin, json={"role": "analista", "active": False}).raise_for_status()
        with psycopg.connect(self.config["DATABASE_URL"], connect_timeout=5) as db:
            rows = db.execute("SELECT action FROM audit_log WHERE entity_id=%s AND module='users'", (user["id"],)).fetchall()
            self.assertIn(("INSERT",), rows)
            self.assertIn(("UPDATE",), rows)
        for statement in ("UPDATE audit_log SET action='alterado'", "DELETE FROM audit_log", "TRUNCATE audit_log"):
            with psycopg.connect(self.config["DATABASE_URL"], connect_timeout=5) as db:
                with self.assertRaises(psycopg.Error):
                    db.execute(statement)
                db.rollback()

    def test_demo_baseline_is_identified(self):
        value = self.api.get("/api/triage", headers=self.tokens["gestor"]).raise_for_status().json()
        self.assertGreater(value["measured_reports"], 0)
        self.assertIsNotNone(value["baseline"])
        self.assertEqual(value["baseline"]["is_demo"], 1)
        self.assertGreater(value["demo_comparisons"], 0)
        self.assertEqual(len(json.loads(value["baseline"]["samples_json"])), 5)

    def test_rejected_requests_have_entry_and_exit_with_the_same_request_id(self):
        response = self.api.get("/api/auth/me", headers={"Authorization": "Bearer invalid-live-check"})
        self.assertEqual(response.status_code, 401)
        request_id = response.headers["X-Request-ID"]
        with psycopg.connect(self.config["DATABASE_URL"], connect_timeout=5) as db:
            rows = db.execute(
                "SELECT phase,status_code,outcome FROM audit_log WHERE request_id=%s ORDER BY occurred_at", (request_id,),
            ).fetchall()
        self.assertEqual([row[0] for row in rows], ["entry","rejected","exit"])
        self.assertEqual(rows[-1][1], 401)
        self.assertEqual([row[2] for row in rows], ["iniciado", "rechazado", "rechazado"])

    def test_browser_navigation_persists_observed_outcome(self):
        public = str(uuid4())
        private = str(uuid4())
        path = "/api/audit/visitas"
        manager = self.tokens["gestor"]
        for visit, headers, module in ((public, {}, "intake"), (private, manager, "dashboard")):
            self.assertEqual(self.api.post(path, headers=headers, json={"id":visit,"secuencia":1,"modulo":module}).status_code, 204)
            self.assertEqual(self.api.post(path, headers=headers, json={"id":visit,"secuencia":2,"modulo":None}).status_code, 204)
        with psycopg.connect(self.config["DATABASE_URL"], connect_timeout=5) as db:
            for visit, role, module in ((public, "publico", "intake"), (private, "gestor", "dashboard")):
                actual = db.execute("""SELECT action,module,role,outcome FROM audit_log WHERE entity_id=%s
                    AND phase='navigation' ORDER BY occurred_at""", (visit,)).fetchall()
                self.assertEqual(actual, [("module_enter", module, role, "registrado"), ("module_exit", module, role, "registrado")])

    def test_historical_demo_is_explicit_and_uses_separate_aggregate_data(self):
        headers = self.tokens["gestor"]
        before = self.api.get("/api/metricas", headers=headers).raise_for_status().json()["total"]
        value = self.api.get("/api/impacto", headers=headers).raise_for_status().json()
        self.assertTrue(value["is_demo"])
        self.assertEqual(value["source"], "demo")
        self.assertGreaterEqual(len(value["periods"]), 6)
        self.assertEqual([row["period"] for row in value["periods"]], sorted(row["period"] for row in value["periods"]))
        first,last = value["periods"][0],value["periods"][-1]
        self.assertEqual((first["response_pct"],last["response_pct"]),(55,95))
        self.assertAlmostEqual(last["estimated_hours_saved"],40*(900-120-30)/3600)
        self.assertEqual(self.api.get("/api/metricas", headers=headers).raise_for_status().json()["total"],before)
