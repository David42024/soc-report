from unittest import TestCase
from uuid import uuid4

from scripts.vcdb import DATASET
from scripts.vcdb_review import Adjudication, ReviewForm, freeze, initialize, make_packet, review_template


class ReviewWorkflowTests(TestCase):
    def test_review_binds_both_label_sets_to_the_frozen_text(self):
        included, excluded = str(uuid4()), str(uuid4())
        url = "https://example.com/incident"
        queue = {"dataset": DATASET, "status": "draft_for_independent_review",
                 "sampling": "Muestra de prueba con campañas independientes.",
                 "cases": [{"source_id": included}, {"source_id": excluded}]}
        eligible = {included: {"suggested_partition": "holdout_candidate", "source_urls": [url]}}
        preparation = initialize(queue)
        with self.assertRaisesRegex(ValueError, "2 casos"):
            make_packet(queue, preparation, eligible)
        preparation["cases"][0].update(
            disposition="include", source_url=url, group="example-campaign",
            source_stage="initial_public_report", redaction_reviewed=True, titulo="Aviso falso",
            descripcion="El mensaje engañoso solicitaba confirmar la cuenta mediante un enlace.",
        )
        preparation["cases"][1].update(disposition="exclude", exclusion_reason="Duplicado de campaña.")
        packet = make_packet(queue, preparation, eligible)
        self.assertEqual(set(packet["excluded"]), {excluded})
        template = review_template(packet)
        self.assertEqual(template["cases"], [{"source_id": included, "tipo": None}])
        first = ReviewForm.model_validate({**template, "reviewer": "Analista A",
                                          "cases": [{"source_id": included, "tipo": "phishing"}]})
        second = ReviewForm.model_validate({**template, "reviewer": "Analista B",
                                           "cases": [{"source_id": included, "tipo": "fraude"}]})
        with self.assertRaisesRegex(ValueError, "dos revisores"):
            freeze(packet, first, first, {}, eligible)
        with self.assertRaisesRegex(ValueError, "discrepancias"):
            freeze(packet, first, second, {}, eligible)
        resolution = {included: Adjudication(tipo="phishing", reason="El enlace de captura prevalece en la adjudicación.")}
        sample, disputed = freeze(packet, first, second, resolution, eligible)
        self.assertEqual((sample.stage, disputed, sample.cases[0].tipo), ("holdout", 1, "phishing"))
        self.assertEqual([item.tipo for item in sample.cases[0].reviews], ["phishing", "fraude"])
        packet["cases"][included]["descripcion"] += " Cambiada después de la revisión."
        with self.assertRaisesRegex(ValueError, "paquete congelado"):
            freeze(packet, first, second, resolution, eligible)
