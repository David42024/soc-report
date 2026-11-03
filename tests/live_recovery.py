"""Controlled outage of only the project's n8n container, with unconditional restoration."""
import json
import subprocess
import time
import unittest
from uuid import uuid4
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values
from backend.config import ROOT


class LiveRecoveryTests(unittest.TestCase):
    def test_pending_report_is_preserved_and_retried_once(self):
        config = dotenv_values(ROOT / ".env")
        accounts = json.loads((ROOT / ".venv/soc-runtime/access.json").read_text(encoding="utf-8"))
        admin = next(account for account in accounts if account["role"] == "administrador")
        compose = ["docker", "compose", "--env-file", str(ROOT / ".venv/soc-runtime/compose.env")]
        with httpx.Client(base_url="http://127.0.0.1:8000", timeout=120, trust_env=False) as api:
            token = api.post("/api/auth/login", json={key: admin[key] for key in ("username", "password")}).raise_for_status().json()["access_token"]
            headers = {"Authorization": "Bearer " + token}
            report_id = str(uuid4())
            try:
                subprocess.run(compose + ["stop", "n8n"], cwd=ROOT, check=True, capture_output=True)
                health = api.get("/health?detalle=true").raise_for_status().json()
                self.assertEqual((health["estado"], health["servicios"]["n8n"]), ("degradado", "error"))
                result = api.post("/api/reportes", headers={"Idempotency-Key": report_id}, json={
                    "titulo": "[DEMO] Recuperación de enrutamiento",
                    "descripcion": "Recibí un correo falso con enlace sospechoso para renovar la clave. Activo: correo corporativo",
                }).raise_for_status().json()
                self.assertIsNone(result["notificado_at"])
                self.assertIn(report_id, [row["id"] for row in api.get("/api/reportes", headers=headers).raise_for_status().json()])
                log = api.get(f"/api/reportes/{report_id}/bitacora", headers=headers).raise_for_status().json()
                self.assertIn("enrutamiento_pendiente", [entry["accion"] for entry in log])
            finally:
                subprocess.run(compose + ["start", "n8n"], cwd=ROOT, check=True, capture_output=True)
            webhook = urlsplit(config["N8N_WEBHOOK_URL"])
            for attempt in range(60):
                try:
                    if api.get(f"{webhook.scheme}://{webhook.netloc}/healthz/readiness").is_success:
                        break
                except httpx.RequestError:
                    pass
                time.sleep(0.5)
            for attempt in range(30):
                recovered = api.post(f"/api/reportes/{report_id}/reintentar", headers=headers).raise_for_status().json()
                if recovered["notificado_at"]:
                    break
                time.sleep(1)
            self.assertTrue(recovered["notificado_at"])
            self.assertEqual(api.get("/health?detalle=true").raise_for_status().json()["servicios"]["n8n"], "ok")
            api.post(f"/api/reportes/{report_id}/reintentar", headers=headers).raise_for_status()
            log = api.get(f"/api/reportes/{report_id}/bitacora", headers=headers).raise_for_status().json()
            self.assertEqual(sum(entry["accion"] == "asignado" for entry in log), 1)
            self.assertEqual(sum(entry["accion"] == "notificacion" for entry in log), 1)
            self.assertEqual(next(entry["actor"] for entry in log if entry["accion"] == "asignado"), "n8n")
            api.post("/api/auth/logout", headers=headers).raise_for_status()
            evidence = {"report_id": report_id, "events": log}
            (ROOT / ".venv/soc-runtime/recovery-evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
