"""JWT-authorized sealed evaluation, model comparison and error inspection."""
from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import logging

from pydantic import SecretStr

from scripts.soc_dataset import run_lock
from src.data.manifest import ManifestStore
from src.data.models import content_hash
from src.evaluation.contracts import Observation
from src.evaluation.dataset import final_selection, load_test, readiness
from src.evaluation.inference_stats import compare, uncertainty
from src.evaluation.metrics import curves, operations, report_metrics
from src.evaluation.predictors import CloudEvaluation, cloud_options, local_model, local_predictions
from src.evaluation.store import EvaluationStore
from src.inference.services import SocApi
from src.training.dataset import read_manifest
from src.training.jobs import verify_seal_location
from src.training.runs import RunStore, utc
from src.utils.config import AnalyticsSettings
from src.utils.errors import AnalyticsError, DatasetError
from src.utils.reproducibility import software_versions

LOGGER = logging.getLogger("soc_analytics.evaluation")


class EvaluationWorkspace:
    def __init__(self, settings: AnalyticsSettings, api: SocApi, training: RunStore | None = None) -> None:
        self.settings, self.api = settings, api
        self.training = training or RunStore(settings)
        self.store = EvaluationStore(settings)

    def _actor(self, token: SecretStr, permission: str = "read") -> None:
        if not self.api.me(token).can(permission):
            raise AnalyticsError("Tu rol no permite esta operación de evaluación.")

    def catalog(self, token: SecretStr) -> dict:
        """List verified Phase 2 selections and readiness without opening test text."""
        self._actor(token)
        self.api.audit_event(token, "consultar_evaluaciones")
        records = self.training.versions()
        selections = []
        for row in records:
            if row["status"] != "completo":
                continue
            try:
                result = self.training.verified(row["run_id"], "result.json")
                selections.extend({**row, "family": family} for family in result["families"])
            except (AnalyticsError, KeyError, TypeError):
                LOGGER.warning("Se omitió una corrida de Fase 2 sin resultado verificable.")
        verified_runs = list({row["run_id"]: row for row in selections}.values())
        return {"selections": selections, "readiness": readiness(self.settings, verified_runs), "evaluations": self.store.list()}

    def preview(self, phase2: str, family: str, token: SecretStr) -> dict:
        """Show only the selected configuration and aggregate seal metadata."""
        self._actor(token)
        self.api.audit_event(token, "consultar_evaluaciones", run_id=phase2)
        selected, _, spec, partition = final_selection(self.training, phase2, family)
        if spec.source == "real":
            manifest = read_manifest(ManifestStore(self.settings), spec.manifest_version)
            if manifest["content_sha256"] != partition.source_sha256:
                raise DatasetError("El manifiesto de datos difiere de la corrida de Fase 2.")
            verify_seal_location(self.settings, manifest)
        n = sum(partition.test.counts.values())
        budget = cloud_options(selected, self.settings, n, Decimal(0), False)[1] if spec.cloud else None
        return {"phase2_run_id": phase2, "family": family, "source": spec.source, "target": spec.target,
                "manifest_version": spec.manifest_version, "rows": n, "seal": partition.test.sha256,
                "configuration": selected.configuration, "quote": budget}

    def evaluate(self, phase2: str, family: str, token: SecretStr, *, budget: str = "0", approved: bool = False) -> dict:
        """Authorize an evaluation or retrieve the ID of its existing result."""
        self._actor(token, "write")
        result = self._evaluate(phase2, family, lambda identifier: self.api.audit_event(
            token, "autorizar_evaluacion", run_id=identifier, outcome="iniciado"),
            verify_actor=lambda: self._actor(token, "write"), budget=budget, approved=approved)
        self.api.audit_event(token, "consultar_evaluaciones", run_id=result["run_id"])
        return {"run_id": result["run_id"]}

    def _evaluate(self, phase2: str, family: str, authorize: Callable[[str], None], *,
                  verify_actor: Callable[[], None] | None = None, budget: str = "0", approved: bool = False) -> dict:
        selected, record, spec, partition = final_selection(self.training, phase2, family)
        if verify_actor is None and spec.source != "sintetico":
            raise AnalyticsError("El comando técnico solo admite la prueba sintética.")
        dataset = load_test(self.settings, record, spec, partition)
        policy = self.settings.evaluation
        quote = cloud = None
        estimator = None
        events: list[dict] = []
        guard = nullcontext()
        software = software_versions(self.settings.software)
        if spec.cloud:
            try:
                amount = Decimal(budget)
                if not amount.is_finite() or not 0 <= amount <= 10000:
                    raise ValueError
                params, quote = cloud_options(selected, self.settings, len(dataset.cases), amount, approved)
            except (InvalidOperation, ValueError):
                raise AnalyticsError("Ingresa un presupuesto en USD válido.") from None
            if verify_actor is None or not quote["authorized"]:
                raise AnalyticsError("La evaluación cloud requiere un presupuesto nuevo autorizado para el conjunto sellado.")
            directory = self.training.directory / ".cloud"
            directory.mkdir(parents=True, exist_ok=True)
            guard = run_lock(directory)
        else:
            if record["environment"]["software"].get("scikit-learn") != software.get("scikit-learn"):
                raise AnalyticsError("La versión de scikit-learn difiere de la usada para publicar el modelo final.")
            estimator = local_model(selected, dataset, self.settings)
        meta = {"phase": 3, "schema_version": 1, "phase2_run_id": phase2, "family": family,
                "phase2_result_sha256": selected.source_result_sha256, "configuration_sha256": selected.identity(spec.target),
                "configuration": selected.configuration, "artifact": selected.artifact,
                "target": spec.target, "source": spec.source, "reference": "humana_independiente" if spec.source == "real" else "prueba_tecnica",
                "seal_sha256": dataset.seal_sha256, "dataset_sha256": dataset.dataset_sha256,
                "manifest_version": dataset.manifest_version, "classes": list(dataset.classes),
                "groups": len({row.group for row in dataset.cases}), "rows": len(dataset.cases),
                "seed": self.settings.seed, "policy": policy.model_dump(mode="json"),
                "software": software, "created_at_utc": utc()}
        try:
            with guard:
                if spec.cloud:
                    cloud = CloudEvaluation(selected, dataset, self.settings, params, verify_actor,
                                            lambda name, **values: events.append({"event": name, **values}))
                run_id, fresh = self.store.reserve(meta, authorize)
                if not fresh:
                    return self.store.result(run_id)
                observations: tuple[Observation, ...] = ()
                partial: list[Observation] = []
                try:
                    if cloud:
                        for row in dataset.cases:
                            partial.append(cloud.predict(row))
                        cloud.finish()
                        observations, kind = tuple(partial), None
                    else:
                        observations, kind = local_predictions(estimator, dataset, family)
                    report = {**meta, "status": "completa", "completed_at_utc": utc(), "score_kind": kind,
                              "metrics": report_metrics(observations, dataset), "curves": curves(observations, dataset.classes, kind),
                              "uncertainty": uncertainty(observations, dataset.classes, spec.target, kind, policy, self.settings.seed),
                              "operations": operations(observations, quote),
                              "predictions": [asdict(row) for row in observations]}
                    errors = {row.key for row in observations if not row.correct}
                    excerpts = {row.key: {"title": row.title[:policy.inspection_characters],
                                          "description": row.description[:policy.inspection_characters]}
                                for row in dataset.cases if row.key in errors}
                    return self.store.publish(run_id, report, excerpts)
                except Exception as error:
                    self.store.failure(run_id, {**meta, "status": "fallida", "error_type": type(error).__name__,
                                               "operations": operations(tuple(partial), quote), "events": events,
                                               "completed_at_utc": utc()})
                    LOGGER.warning("Evaluación %s detenida (%s)", run_id, type(error).__name__)
                    if isinstance(error, AnalyticsError):
                        raise
                    raise AnalyticsError("La evaluación se detuvo. La reserva se conserva para revisión del resultado.") from None
        except ValueError:
            raise AnalyticsError("Ya se está ejecutando un trabajo con LangFlow.") from None

    def result(self, run_id: str, token: SecretStr) -> dict:
        """Expose aggregate results to roles with read access."""
        self._actor(token)
        self.api.audit_event(token, "consultar_evaluaciones", run_id=run_id)
        report = self.store.result(run_id)
        # Detailed predictions and case keys are served only by the protected inspection path.
        return {key: value for key, value in report.items() if key != "predictions"}

    def report(self, run_id: str, token: SecretStr) -> dict:
        """Audit access to individual predictions in the full export."""
        self._actor(token, "review")
        self.api.audit_event(token, "inspeccionar_evaluacion", run_id=run_id)
        return self.store.result(run_id)

    def errors(self, run_id: str, token: SecretStr) -> list[dict]:
        """List misclassified or referred rows without the source texts."""
        report = self.report(run_id, token)
        return [{key: row[key] for key in ("key", "truth", "predicted", "provider", "review_reason")}
                for row in report.get("predictions", []) if row["truth"] != row["predicted"]]

    def inspect_error(self, run_id: str, key: str, token: SecretStr) -> dict:
        """Retrieve an audited masked excerpt under the review permission."""
        self._actor(token, "review")
        self.api.audit_event(token, "inspeccionar_evaluacion", run_id=run_id)
        return self.store.excerpt(run_id, key)

    def comparison(self, run_id: str, token: SecretStr) -> dict:
        """Compare archived predictions without requesting new classifications."""
        self._actor(token)
        self.api.audit_event(token, "consultar_evaluaciones", run_id=run_id)
        selected = self.store.result(run_id)
        return self._comparison(selected["dataset_sha256"], selected["target"], lambda identifier: self.api.audit_event(
            token, "consultar_evaluaciones", run_id=identifier))

    def _comparison(self, dataset: str, target: str, authorize: Callable[[str], None]) -> dict:
        reports = self.store.cohort(dataset, target)
        if len(reports) < 2:
            raise DatasetError("Se requieren al menos dos configuraciones evaluadas en la misma cohorte.")
        if len({(item["source"], tuple(item["classes"])) for item in reports}) != 1:
            raise DatasetError("Las evaluaciones no comparten la misma naturaleza y taxonomía.")
        classes = tuple(reports[0]["classes"])
        entries = {item["run_id"]: (tuple(Observation(**row) for row in item["predictions"]), item["score_kind"])
                   for item in reports}
        policy = self.settings.evaluation
        signature = content_hash({"results": [item["content_sha256"] for item in reports],
                                  "policy": policy.model_dump(mode="json"), "seed": self.settings.seed})
        summary = [{"run_id": item["run_id"], "family": item["family"], "phase2_run_id": item["phase2_run_id"],
                    "metrics": item["metrics"]["overall"], "groups": item["groups"], "coverage": item["metrics"]["coverage"]}
                   for item in reports]
        result = {"schema_version": 1, "phase": 3, "source": reports[0]["source"], "target": target,
                  "dataset_sha256": dataset, "policy": policy.model_dump(mode="json"), "seed": self.settings.seed,
                  "models": summary, "comparisons": compare(entries, classes, target, policy, self.settings.seed)}
        return self.store.comparison(signature, result, authorize)


def technical_evaluation(settings: AnalyticsSettings, phase2: str) -> tuple[list[dict], dict]:
    """Reproduce the synthetic path with the published Phase 2 model artifacts."""
    workspace = EvaluationWorkspace(settings, SocApi(settings.api))
    run = workspace.training.verified(phase2, "result.json")
    if run["partition"]["source"] != "sintetico":
        raise AnalyticsError("El comando técnico solo admite corridas sintéticas de Fase 2.")
    reports = [workspace._evaluate(phase2, family, lambda _identifier: None) for family in run["families"]]
    comparison = workspace._comparison(reports[0]["dataset_sha256"], reports[0]["target"], lambda _identifier: None)
    return reports, comparison
