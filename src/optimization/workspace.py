"""Authorized UI operations over the same Phase 2 ExperimentManager and RunStore."""
from __future__ import annotations

from contextlib import contextmanager
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

import optuna
from pydantic import SecretStr, ValidationError
import yaml

from src.data.manifest import VERSION_ID
from src.data.models import content_hash
from src.data.revisions import operation_identity
from src.training.jobs import ExperimentManager, validate_limits
from src.training.runs import JobSpec
from src.utils.errors import AnalyticsError
from .contracts import SearchOptions
from .studies import storage, trial_rows

LOGGER = logging.getLogger("soc_analytics.optimization")
if TYPE_CHECKING:
    from src.utils.config import AnalyticsSettings


def build_request(raw: dict, settings: AnalyticsSettings) -> JobSpec:
    """Validate form data and server ceilings without running a fit or sending text."""
    try:
        spec = JobSpec.model_validate(raw)
        validate_limits(spec, settings)
        return spec
    except ValidationError as error:
        messages = error.errors(include_input=False, include_context=False, include_url=False)
        raise AnalyticsError("Configuración inválida. " + " ".join(item["msg"] for item in messages[:2])) from None


def parse_space(text: str, maximum: int) -> dict:
    """Bound the data-only space editor before invoking typed distribution validation."""
    if len(text.encode()) > maximum:
        raise AnalyticsError("El espacio excede el límite de configuración.")
    try:
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, TypeError, RecursionError):
        raise AnalyticsError("El espacio requiere un objeto JSON de parámetros y distribuciones.") from None


def default_options(settings: AnalyticsSettings, *, cloud: bool = False) -> SearchOptions:
    """All default spaces and execution ceilings come from the public YAML."""
    policy = settings.optimization
    space = ({"prompt": {"kind": "categorical", "choices": tuple(settings.training.cloud.prompts)},
              "threshold": {"kind": "categorical", "choices": settings.training.cloud.thresholds}} if cloud else
             {name: value.model_dump() for name, value in policy.local_space.items()})
    return SearchOptions(space=space, sampler="tpe", pruner="none", startup_trials=policy.startup_trials,
        warmup_steps=policy.warmup_steps, metric="f1_macro", direction="maximize", timeout_seconds=policy.default_timeout_seconds,
        parallel_trials=1, cpu_threads=settings.training.cpu_threads, critical_penalty=0, review_penalty=0)


class OptimizationWorkspace:
    """Never owns a second executor, fitting loop, classifier client or production setter."""

    def __init__(self, manager: ExperimentManager) -> None:
        self.manager, self.settings, self.api = manager, manager.settings, manager.api
        self.directory = self.settings.path(Path(self.settings.runs_dir) / self.settings.optimization.directory)

    def _actor(self, token: SecretStr, permission: str = "read"):
        actor = self.api.me(token)
        if not actor.can(permission):
            raise AnalyticsError("Tu rol no permite esta operación de optimización.")
        return actor

    def list(self, token: SecretStr) -> dict:
        """Show advanced Phase 2 jobs alongside safe versioned configurations."""
        data = self.manager.list(token)
        self.api.audit_event(token, "consultar_optimizacion")
        return {**data, "runs": [row for row in data["runs"] if row.get("optimization")],
                "configurations": self._versions("configurations"), "candidates": self._versions("candidates")}

    def _versions(self, kind: str) -> list[str]:
        return [p.name for p in sorted((self.directory / kind).glob("*"), reverse=True)
                if VERSION_ID.fullmatch(p.name) and p.is_dir()][:self.settings.data.max_history_entries]

    def _canonical_spec(self, spec: JobSpec) -> JobSpec:
        if spec.optimization is None:
            raise AnalyticsError("La configuración debe incluir el espacio avanzado Optuna.")
        if spec.cloud:
            spec = spec.model_copy(update={"cloud": spec.cloud.model_copy(update={"approve": False})})
        validated = JobSpec.model_validate(spec.model_dump(mode="json"))
        validate_limits(validated, self.settings)
        return validated

    def serialize(self, spec: JobSpec) -> bytes:
        """Export data-only YAML, with API approval reset rather than inherited."""
        payload = {"schema_version": 1, "kind": "soc_optuna_search", "request": self._canonical_spec(spec).model_dump(mode="json")}
        return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False).encode()

    def parse(self, raw: bytes, token: SecretStr) -> JobSpec:
        """Load a bounded safe mapping; no Python objects, pickle, model bytes or paths."""
        self._actor(token, "write")
        if len(raw) > self.settings.optimization.max_config_bytes:
            raise AnalyticsError("El archivo de configuración supera el límite permitido.")
        try:
            payload = yaml.safe_load(raw)
            if not isinstance(payload, dict) or set(payload) != {"schema_version", "kind", "request"} or payload["schema_version"] != 1 or payload["kind"] != "soc_optuna_search":
                raise ValueError
            return self._canonical_spec(JobSpec.model_validate(payload["request"]))
        except (yaml.YAMLError, UnicodeError, ValueError, TypeError, RecursionError):
            raise AnalyticsError("El archivo no cumple el contrato de configuración Optuna. Revisa tipos, rangos y campos admitidos.") from None

    @contextmanager
    def _publication(self, kind: str, identifier: str):
        parent = self.directory / kind
        parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".optuna-", dir=parent) as temporary:
            yield Path(temporary), parent / identifier

    def _publish(self, kind: str, payload: dict, token: SecretStr, action: str) -> dict:
        self._actor(token, "write")
        result = {**payload, "content_sha256": content_hash(payload)}
        try:
            with self._publication(kind, payload["version"]) as (staging, destination):
                (staging / "record.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
                self._actor(token, "write")
                staging.rename(destination)
                try:
                    self.api.audit_event(token, action, run_id=payload["version"])
                except AnalyticsError:
                    destination.rename(staging)
                    raise
        except OSError:
            raise AnalyticsError("No se pudo publicar la configuración. Revisa el directorio de ejecuciones.") from None
        return result

    def save_configuration(self, spec: JobSpec, token: SecretStr) -> dict:
        """Version a reproducible search, never production credentials or originals."""
        actor = self._actor(token, "write")
        spec = self._canonical_spec(spec)
        validate_limits(spec, self.settings)
        identifier, date = operation_identity()
        return self._publish("configurations", {"schema_version": 1, "kind": "soc_optuna_configuration", "version": identifier,
            "created_at_utc": date, "owner": actor.id, "request": spec.model_dump(mode="json")}, token, "guardar_configuracion_optuna")

    def _read(self, kind: str, version: str) -> dict:
        if not VERSION_ID.fullmatch(version):
            raise AnalyticsError("Selecciona una versión registrada.")
        path = self.settings.path(self.directory / kind / version / "record.json")
        try:
            if path.stat().st_size > self.settings.optimization.max_config_bytes:
                raise ValueError
            value = json.loads(path.read_bytes())
            if value["version"] != version or value["content_sha256"] != content_hash({k: v for k, v in value.items() if k != "content_sha256"}):
                raise ValueError
            return value
        except (OSError, ValueError, TypeError, KeyError):
            raise AnalyticsError("La configuración guardada falta o cambió de huella.") from None

    def load_configuration(self, version: str, token: SecretStr) -> JobSpec:
        """Recheck identity and artifact integrity before populating a form."""
        self._actor(token, "write")
        self.api.audit_event(token, "consultar_optimizacion", run_id=version)
        return self._canonical_spec(JobSpec.model_validate(self._read("configurations", version)["request"]))

    def inspect(self, run_id: str, token: SecretStr) -> dict:
        """Load standard Optuna trials in a background task; expose metrics-only projections."""
        self._actor(token)
        self.manager.authorize_monitor(run_id, token)
        record = self.manager.store.verified(run_id, "run.json")
        spec = JobSpec.model_validate(record["request"])
        if not spec.optimization:
            raise AnalyticsError("Este registro corresponde al modo básico de Fase 2.")
        directory = self.manager.store.path(run_id)
        studies = []
        if (directory / "optuna.journal").is_file():
            journal = storage(directory)
            for summary in optuna.study.get_all_study_summaries(journal):
                study = optuna.load_study(study_name=summary.study_name, storage=journal)
                identity = study.user_attrs.get("identity", {})
                if (identity.get("partition") != record["partition_sha256"] or identity.get("search") != spec.optimization.model_dump(mode="json") or
                        identity.get("seed") != spec.seed or study.user_attrs.get("identity_sha256") != content_hash(identity)):
                    raise AnalyticsError("Los metadatos del estudio y de la ejecución difieren.")
                studies.append({"name": study.study_name, "direction": spec.optimization.direction,
                                "trials": trial_rows(study), "identity_sha256": study.user_attrs["identity_sha256"], "source": spec.source})
                from .analysis import importance
                studies[-1]["importance"] = importance(study, self.settings.optimization, spec.seed)
        return {"run_id": run_id, "request": spec.model_dump(mode="json"), "partition_sha256": record["partition_sha256"], "studies": studies}

    def candidate(self, run_id: str, token: SecretStr) -> dict:
        """Transfer the Phase 2 Validation winner, never the most favorable outer score."""
        actor = self._actor(token, "write")
        record = self.manager.store.verified(run_id, "run.json")
        report = self.manager.store.verified(run_id, "result.json")
        spec = JobSpec.model_validate(record["request"])
        if not spec.optimization:
            raise AnalyticsError("La corrida no tiene una búsqueda avanzada registrada.")
        family = next(iter(report["families"]))
        selected = report["families"][family]["validation_selection"]["winner"]
        parameters = selected["configuration"]
        options = SearchOptions.model_validate({**spec.optimization.model_dump(mode="json"),
            "space": {name: {"kind": "categorical", "choices": [parameters[name]]} for name in spec.optimization.space},
            "sampler": "random", "pruner": "none", "parallel_trials": 1})
        request = spec.model_dump(mode="json")
        request.update(trials=1, optimization=options.model_dump(mode="json"))
        if spec.cloud:
            request["cloud"].update(prompts=[parameters["prompt"]], thresholds=[parameters["threshold"]], approve=False, budget_usd="0")
        else:
            request["local"] = parameters
        # model_copy cannot validate nested dictionaries; validate again at this boundary.
        request = JobSpec.model_validate(request).model_dump(mode="json")
        identifier, date = operation_identity()
        return self._publish("candidates", {"schema_version": 1, "kind": "soc_optuna_candidate", "version": identifier,
            "created_at_utc": date, "owner": actor.id, "source_phase2_run": run_id,
            "source_result_sha256": report["content_sha256"], "partition_sha256": report["partition_sha256"],
            "dataset_sha256": report["partition"]["source_sha256"], "source": spec.source,
            "family": family, "selection": "15 % Validación; sin escoger por resultados externos",
            "selected_objective": selected["objective"], "objective": spec.optimization.metric,
            "selected_parameters": parameters, "artifact_reference": report["families"][family]["artifact"],
            "observed_models": selected.get("observed_models", []), "environment": report["environment"],
            "request": request, "production_deployment": False}, token, "exportar_candidato_optuna")

    def load_candidate(self, version: str, token: SecretStr) -> dict:
        """Reconcile a candidate with its immutable source and the user's current permission."""
        self._actor(token, "write")
        candidate = self._read("candidates", version)
        source = self.manager.store.verified(candidate["source_phase2_run"], "result.json")
        if source["content_sha256"] != candidate["source_result_sha256"]:
            raise AnalyticsError("La corrida de origen del candidato cambió.")
        JobSpec.model_validate(candidate["request"])
        self.api.audit_event(token, "consultar_optimizacion", run_id=version)
        return candidate
