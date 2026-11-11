"""Opt-in Case 06 E2E check: approved existing case and isolated PostgreSQL/n8n."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import unittest
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from backend.routing import routing_policy
from scripts.soc_dataset import lifecycle
from scripts.soc_dataset_stack import stack
from scripts.vcdb import SENSITIVE
from src.data.catalog import DatasetCatalog
from src.inference.services import SocApi
from src.utils.config import load_config
from src.utils.langflow import LangflowConformance, graph_digest
from backend.config import Settings
from src.utils.privacy import load_policy


class Phase0LiveAlignment(unittest.TestCase):
    """One authorized integration observation; no holdout or predictive scoring."""

    def test_case06_pipeline_and_immutable_audit_on_isolated_postgres(self):
        settings = load_config()
        source = DatasetCatalog(settings, SocApi(settings.api)).source(settings.flow_validation.probe_source_id)
        case = json.loads(settings.path(source.path).read_text(encoding="utf-8-sig"))["cases"][settings.flow_validation.probe_case_index]
        text = f"Título: {case['titulo']}\n{case['descripcion']}"
        input_hash = sha256(text.encode()).hexdigest()
        if os.environ.get("SOC_PHASE0_APPROVED_INPUT_SHA256") != input_hash:
            self.skipTest("La prueba cloud requiere autorización explícita para la huella del caso concreto.")
        self.assertIs(case.get("redaction_reviewed"), True)
        self.assertIsNone(SENSITIVE.search(text))
        connection = LangflowConformance(settings, Settings.from_env())
        original_graph = graph_digest(connection.fetch())
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_e2e_" + uuid4().hex[:8]
        directory = settings.path(settings.runs_dir) / run_id
        directory.mkdir(parents=True)
        project = "soc-phase0-" + uuid4().hex[:12]
        result = {"kind": "phase0_case06_e2e", "run_id": run_id, "input_sha256": input_hash,
                  "source_id": source.id, "source_case_id": case["source_id"], "isolated_project": project,
                  "dataset_originals_read_only": True, "status": "running"}
        try:
            with stack(directory, project, "docker") as (api, db, services, metadata):
                with db.session() as execute:
                    database = execute("SELECT current_database() AS name").fetchone()["name"]
                self.assertEqual(database, "soc_evaluation", "Solo se permite actuar en la base aislada de evaluación.")
                policy = routing_policy(db)["configuration"]
                report_id = str(uuid4())
                payload = {name: case[name] for name in ("titulo", "descripcion")}
                response = api.post(settings.api.endpoints.reports, headers={"Idempotency-Key": report_id}, json=payload)
                self.assertEqual(response.status_code, 201)
                report = response.json()
                self.assertEqual(report["origen"], "langflow", "El proveedor debe producir una clasificación real, no el origen protector.")
                evidence = lifecycle(api, db, report, policy, "n8n")
                self.assertEqual(evidence["status"], "routed")
                self.assertIn(evidence["provider"], ("groq", "gemini"))
                classified = next(event for event in evidence["events"] if event["accion"] == "clasificado")
                privacy = json.loads(classified["detalle"].split(" / privacidad=", 1)[1].split(" / proveedor=", 1)[0])
                privacy_policy = load_policy()
                self.assertEqual(privacy["status"], "protected")
                self.assertEqual(privacy["policy_sha256"], privacy_policy.digest)
                self.assertEqual({key: db.report(report_id)[key] for key in payload}, payload)
                self.assertEqual([event["accion"] for event in evidence["events"]],
                                 ["recibido", "clasificado", "asignado", "notificacion"])
                duplicate = api.post(settings.api.endpoints.reports, headers={"Idempotency-Key": report_id}, json=payload)
                self.assertEqual(duplicate.status_code, 200)
                self.assertEqual(duplicate.json()["id"], report_id)
                blocked = {}
                for operation, statement in (("UPDATE", "UPDATE audit_log SET action='probe' WHERE 1=0"),
                                             ("DELETE", "DELETE FROM audit_log WHERE 1=0"),
                                             ("TRUNCATE", "TRUNCATE audit_log")):
                    rejected = False
                    try:
                        with db.session(write=True) as execute:
                            execute(statement)
                    except SQLAlchemyError as error:
                        rejected = "audit_log es inmutable" in str(error)
                    self.assertTrue(rejected, f"El trigger debe bloquear {operation} en la base aislada.")
                    blocked[operation] = rejected
                result.update(status="passed", runtime=metadata["mode"], postgres_version=metadata["postgresql_version"],
                    provider=evidence["provider"], model=metadata["langflow"]["models"][evidence["provider"] + "_model"],
                    report_id=report_id, counts=evidence["db_counts"], event_order=[event["accion"] for event in evidence["events"]],
                    deterministic_sla_valid=evidence["policy_ok"], idempotency_valid=True, immutable_audit=blocked,
                    privacy=privacy, original_report_preserved=True,
                    classification_ms_single_observation=evidence["classification_ms"],
                    notification_ms_single_observation=evidence["notification_ms"],
                    routing_rules_sha256=sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest())
            result["production_graph_unchanged"] = graph_digest(connection.fetch()) == original_graph
            self.assertTrue(result["production_graph_unchanged"])
        except Exception as error:
            result.update(status="failed", safe_error_type=type(error).__name__)
            raise
        finally:
            (directory / "e2e-result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main(verbosity=2)
