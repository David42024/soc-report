import json
from hashlib import file_digest
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from pydantic import ValidationError

from scripts.soc_dataset import check_prior_pilots, summarize
from scripts.vcdb import REVISION, ReviewedSet, index_archive, validate_sample


class DatasetTests(unittest.TestCase):
    def test_pinned_archive_excludes_duplicate_records_and_ambiguous_types(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "cases.zip"
            ids = [str(uuid4()) for _ in range(3)]
            with ZipFile(path, "w") as archive:
                for index, source_id in enumerate(ids):
                    incident = {
                        "incident_id": source_id, "security_incident": "Confirmed",
                        "summary": "A user followed a fake email link." if index < 2 else "Ransomware was installed through a deceptive link.",
                        "reference": "https://example.com/a,https://example.com/b?token=secret",
                        "action": {"social": {"variety": ["Phishing"]}},
                    }
                    if index == 2:
                        incident["action"]["malware"] = {"variety": ["Ransomware"]}
                    archive.writestr(f"VCDB/data/json/validated/{source_id}.json", json.dumps(incident))
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                index_archive(path)
            with path.open("rb") as stream:
                digest = file_digest(stream, "sha256").hexdigest()
            with patch("scripts.vcdb.ARCHIVE_HASH", digest):
                candidates, summary = index_archive(path)
            self.assertEqual(list(candidates), [ids[2]])
            self.assertEqual(candidates[ids[2]]["source_urls"], ["https://example.com/a"])
            self.assertEqual(summary["exclusions"]["identificador_o_resumen_duplicado"], 2)
            self.assertEqual(summary["multiple_suggested_types"], 1)
            self.assertEqual(summary["pilot_suggestions"], 0)

    def test_holdout_requires_independent_review_and_rejects_sensitive_text(self):
        source_id = str(uuid4())
        case = {"source_id": source_id, "source_url": "https://example.com/report", "group": "case-group",
                "source_stage": "initial_public_report", "redaction_reviewed": True, "tipo": "phishing",
                "titulo": "Correo sospechoso", "descripcion": "Un mensaje intenta que el usuario abra un enlace.",
                "reviews": [{"reviewer": "analista-uno", "tipo": "phishing"}]}
        doc = {"revision": REVISION, "stage": "holdout", "sampling": "Casos separados por campaña antes del ensayo.",
               "cases": [case]}
        index = {source_id: {"source_urls": [case["source_url"]], "suggested_partition": "holdout_candidate"}}
        with self.assertRaisesRegex(ValueError, "dos revisores"):
            validate_sample(ReviewedSet.model_validate(doc), index)
        case["reviews"].append({"reviewer": "analista-dos", "tipo": "phishing"})
        sample = ReviewedSet.model_validate(doc)
        validate_sample(sample, index)
        with TemporaryDirectory() as directory:
            pilot = Path(directory) / "pilot"
            pilot.mkdir()
            (pilot / "results.json").write_text(json.dumps({"inputs": {"stage": "pilot", "selection": {
                str(uuid4()): {"group": case["group"], "source_url": "https://example.com/earlier"},
            }}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "comparte incidentes o grupos"):
                check_prior_pilots(sample, Path(directory))
        case["descripcion"] = "La víctima dejó su correo cliente@example.com en el registro."
        with self.assertRaises(ValidationError):
            ReviewedSet.model_validate(doc)

    def test_failed_classification_remains_visible_without_polluting_accuracy(self):
        row = {"status": "routed", "classification_failure": False, "reference_type": "phishing",
               "prediction": "phishing", "baseline_prediction": "otro", "review_reason": None, "provider": "groq",
               "policy_ok": True, "classification_ms": 900, "notification_ms": 1200,
               "reference_severity": None, "reference_asset": None}
        failed = {**row, "classification_failure": True, "review_reason": "langflow_no_disponible",
                  "prediction": "otro", "provider": None}
        stats = summarize([row, failed, {"status": "routing_pending"}])
        self.assertEqual(stats["completed"], 2)
        self.assertEqual(stats["coverage"], {"accepted": 1, "denominator": 2})
        self.assertEqual(stats["classification_failures"], 1)
        self.assertEqual(stats["classifier"]["macro_f1"], 1)
        self.assertEqual(stats["same_text_demo_rules"]["macro_f1"], 0)
