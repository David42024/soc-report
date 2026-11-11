"""Read-only analysis of original decisions with authenticated XAI artifacts."""
from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import Literal
import logging
import json

from pydantic import SecretStr

from backend.config import Settings
from src.data.models import content_hash
from src.evaluation.contracts import EvaluationSet
from src.evaluation.dataset import final_selection
from src.evaluation.predictors import local_model
from src.explainability.analysis import aggregate
from src.explainability.evidence import extract_evidence, overlap, text_hash, validate_spans
from src.explainability.linear import LinearTextExplainer
from src.explainability.store import ExplanationStore
from src.inference.services import SocApi, User
from src.training.runs import RunStore
from src.utils.config import AnalyticsSettings
from src.utils.errors import AnalyticsError
from src.utils.privacy import PrivacyError, protect_text
from src.utils.reproducibility import software_versions

LOGGER = logging.getLogger("soc_analytics.explainability")


class ExplanationWorkspace:
    """Use the existing backend identity and separate explanation artifacts."""

    def __init__(self, settings: AnalyticsSettings, api: SocApi, training: RunStore | None = None) -> None:
        self.settings, self.api = settings, api
        self.training = training or RunStore(settings)
        self.store = ExplanationStore(settings)

    def _actor(self, token: SecretStr, permission: str = "review") -> User:
        actor = self.api.me(token)
        if not actor.can(permission):
            raise AnalyticsError("Tu rol no permite consultar textos o registrar explicaciones.")
        return actor

    def catalog(self, token: SecretStr) -> dict:
        """Return final local models and aggregate report metadata."""
        self._actor(token, "read")
        self.api.audit_event(token, "consultar_explicabilidad")
        selections = []
        for row in self.training.versions():
            if row["status"] != "completo" or row["mode"] != "academico":
                continue
            try:
                result = self.training.verified(row["run_id"], "result.json")
                for family in result["families"]:
                    final_selection(self.training, row["run_id"], family)
                    selections.append({**row, "family": family})
            except AnalyticsError:
                LOGGER.warning("Se omitió un artefacto local sin selección final verificable.")
        reports = [{key: report[key] for key in ("run_id", "created_at_utc", "mode", "source", "summary")}
                   for report in self.store.records()]
        return {"selections": selections, "reports": reports}

    def operational_reports(self, token: SecretStr) -> list[dict]:
        """List minimal identifiers without putting originals in shared state."""
        self._actor(token)
        self.api.audit_event(token, "consultar_explicabilidad")
        return [{field: row.get(field) for field in ("id", "tipo", "severidad", "origen")} for row in self.api.reports(token)]

    def _publish(self, data: dict, authorize: Callable[[str], None]) -> dict:
        sources = sorted(Path(__file__).parent.glob("*.py"))
        metadata = {"seed": self.settings.seed, "software": software_versions(self.settings.software),
                    "policy": self.settings.explainability.model_dump(mode="json"),
                    "current_prompt_reference_sha256": sha256(self.settings.path(self.settings.flow_validation.prompt_file).read_bytes()).hexdigest(),
                    "implementation_sha256": content_hash({path.name: sha256(path.read_bytes()).hexdigest() for path in sources})}
        return self.store.append("explicacion", {**data, **metadata, "summary": aggregate(data["cases"])}, authorize)

    @staticmethod
    def _check_protection(text: str, secrets: tuple[str, ...]) -> None:
        """Fail closed if the recorded text needs a new privacy transformation."""
        try:
            if protect_text(text, known_secrets=secrets).text != text:
                raise AnalyticsError("La política actual cambia el texto registrado. Revisa su protección antes de explicar el artefacto.")
        except PrivacyError:
            raise AnalyticsError("La política de privacidad no está disponible para consultar explicaciones.") from None

    def _local(self, phase2: str, family: str, partition: Literal["development", "validation"],
               authorize: Callable[[str], None]) -> dict:
        if partition not in ("development", "validation"):
            raise AnalyticsError("Las perturbaciones XAI requieren Desarrollo o Validación.")
        selected, record, spec, plan = final_selection(self.training, phase2, family)
        if spec.cloud:
            raise AnalyticsError("Los coeficientes requieren un modelo académico local publicado.")
        source = plan.development if partition == "development" else plan.validation
        if not source or len(source) > self.settings.explainability.max_cases:
            raise AnalyticsError("El subconjunto vacío o su tamaño excede el límite configurado de explicabilidad.")
        dataset = EvaluationSet(source, spec.target, spec.source, plan.test.sha256, plan.source_sha256,
                                spec.manifest_version, plan.labels)
        model = local_model(selected, dataset, self.settings)
        if record["environment"]["software"].get("scikit-learn") != software_versions(("scikit-learn",))["scikit-learn"]:
            raise AnalyticsError("La versión de scikit-learn difiere de la del modelo publicado.")
        secrets = Settings.from_env().privacy_secrets()
        for case in (*plan.development, *plan.validation):
            self._check_protection(case.text, secrets)
        explainer = LinearTextExplainer(model, [case.text for case in plan.development], self.settings.explainability)
        cases = []
        for row in source:
            explained = explainer.explain(row.text)
            cases.append({"key": row.key, "group": row.group, "text": row.text, "input_sha256": text_hash(row.text),
                          "truth": row.label, "target": spec.target, "correct": row.label == explained["predicted"],
                          "linear": explained, "reliability": explainer.reliability(row.text, explained)})
        return self._publish({"mode": "local", "source": spec.source, "phase2_run_id": phase2,
            "family": family, "partition": partition, "model_sha256": selected.artifact["sha256"],
            "configuration": selected.configuration, "phase2_result_sha256": selected.source_result_sha256,
            "dataset_sha256": content_hash([(row.key, text_hash(row.text), row.label) for row in source]),
            "background_sha256": content_hash([(row.key, text_hash(row.text)) for row in plan.development]),
            "test_inferences": 0, "external_requests": 0, "cases": cases}, authorize)

    def local(self, phase2: str, family: str, partition: str, token: SecretStr) -> dict:
        """Explain the final model on accessible partitions and archive the analysis."""
        self._actor(token)
        self.api.audit_event(token, "consultar_explicabilidad", run_id=phase2)
        result = self._local(phase2, family, partition, lambda identifier: self.api.audit_event(
            token, "autorizar_explicabilidad", run_id=identifier, outcome="iniciado"))
        return {"run_id": result["run_id"]}

    def operational(self, report_id: str, token: SecretStr) -> dict:
        """Explain observable evidence without generating a new provider decision."""
        self._actor(token)
        observed = self.api.explanation_input(report_id, token, original=True)
        original = observed.pop("original", None)
        source = observed["input"]
        text = source["text"]
        if not isinstance(text, str) or len(text) > self.settings.explainability.max_text_characters or text_hash(text) != source["input_sha256"]:
            raise AnalyticsError("La entrada minimizada está incompleta o su huella cambió.")
        self._check_protection(text, Settings.from_env().privacy_secrets())
        explanation = extract_evidence(text, observed["classification"], self.settings.explainability)
        if original:
            original_text = f"Título: {original['title']}\n{original['description']}"
            explanation["original_sha256"] = text_hash(original_text)
            explanation["original_quotes"] = [{"claim": i, "exists": row["quote"] in original_text}
                                               for i, row in enumerate(explanation["claims"])]
        else:
            explanation["original_quotes"] = None
        reviewed = observed.get("human_review")
        correct = reviewed["tipo"] == observed["classification"]["tipo"] if reviewed else None
        case = {"key": report_id, "text": text, "input_sha256": text_hash(text), "evidence": explanation,
                "correct": correct, "target": "tipo", "truth": reviewed["tipo"] if reviewed else None,
                "original_available": bool(original), "operational": observed}
        demo = observed["origin"] == "demo" or (original and original["title"].startswith("[DEMO]"))
        result = self._publish({"mode": "llm", "source": "demo" if demo else "operacional",
                                "external_requests": 0, "cases": [case]}, lambda identifier: self.api.audit_event(
                                    token, "autorizar_explicabilidad", run_id=identifier, outcome="iniciado"))
        return {"run_id": result["run_id"]}

    def original(self, report_id: str, token: SecretStr) -> dict:
        """Return the original only on explicit authorized inspection."""
        self._actor(token)
        result = self.api.explanation_input(report_id, token, original=True)
        if "original" not in result:
            raise AnalyticsError("El backend no proporcionó el texto original autorizado.")
        return result["original"]

    def summary(self, identifier: str, token: SecretStr) -> dict:
        """Allow dashboard roles to access only aggregated findings."""
        self._actor(token, "read")
        self.api.audit_event(token, "consultar_explicabilidad", run_id=identifier)
        report = self.store.read(identifier)
        return {key: value for key, value in report.items() if key != "cases"}

    def detail(self, identifier: str, token: SecretStr) -> dict:
        """Audit per-case masked text and explainability artifacts."""
        self._actor(token)
        self.api.audit_event(token, "inspeccionar_explicabilidad", run_id=identifier)
        return self.store.read(identifier)

    def annotate(self, identifier: str, case_key: str, spans: list[dict], token: SecretStr) -> dict:
        """Append an identified retrospective human reference without changing labels."""
        actor = self._actor(token)
        report = self.detail(identifier, token)
        case = next((row for row in report["cases"] if row["key"] == case_key), None)
        if case is None:
            raise AnalyticsError("El caso no pertenece a la explicación seleccionada.")
        checked = validate_spans(case["text"], spans, self.settings.explainability.max_spans)
        result = self.store.append("anotacion", {"explanation_id": identifier, "case_key": case_key,
            "input_sha256": case["input_sha256"], "spans": checked, "annotator_id": actor.id,
            "independence": "retrospectiva_explicacion_visible"}, lambda key: self.api.audit_event(
                token, "autorizar_anotacion_xai", run_id=key, outcome="iniciado"))
        return {"run_id": result["run_id"]}

    def annotate_json(self, identifier: str, case_key: str, payload: str, token: SecretStr) -> dict:
        """Parse a bounded human annotation without echoing supplied text on errors."""
        if len(payload) > self.settings.ui.max_json_bytes:
            raise AnalyticsError("La anotación supera el tamaño permitido.")
        try:
            spans = json.loads(payload)
        except (ValueError, TypeError):
            raise AnalyticsError("La anotación debe ser una lista JSON de intervalos start y end.") from None
        return self.annotate(identifier, case_key, spans, token)

    def alignment(self, identifier: str, case_key: str, token: SecretStr) -> dict:
        """Measure spatial overlap only with a registered matching human reference."""
        report = self.detail(identifier, token)
        case = next((row for row in report["cases"] if row["key"] == case_key), None)
        if case is None:
            raise AnalyticsError("El caso no pertenece a la explicación seleccionada.")
        reference = next((row for row in self.store.records("anotacion")
                          if row["explanation_id"] == identifier and row["case_key"] == case_key), None)
        if "linear" in case:
            tokens = case["linear"]["tokens"]
            predicted = [{"start": row["start"], "end": row["end"]} for row in tokens if row["weight"] > 0]
        else:
            raw = sorted((row["start"], row["end"]) for row in case["evidence"]["claims"] if not row["negated"])
            merged = []
            for start, end in raw:
                if merged and start <= merged[-1]["end"]:
                    merged[-1]["end"] = max(end, merged[-1]["end"])
                else:
                    merged.append({"start": start, "end": end})
            predicted = merged
        return overlap(case["text"], predicted, reference)
