"""Bounded experiment jobs, cooperative cancellation and audited access."""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from contextlib import nullcontext
from dataclasses import dataclass
from threading import RLock
from time import monotonic

import optuna
from pydantic import SecretStr
from threadpoolctl import threadpool_limits

from backend.config import Settings
from scripts.soc_dataset import run_lock
from src.data.manifest import ManifestStore
from src.data.models import LabelField, content_hash
from src.inference.experimental import CloudSearch, budget_quote, cloud_choices, prompt_versions, quote_with_prompts
from src.inference.services import SocApi, User
from src.training.dataset import read_manifest, readiness, real_partition
from src.training.demo import demo_partition
from src.training.local import LocalSearch
from src.training.nested import CancelledRun, maximum_flow_calls, run_nested
from src.training.partition import Fold, Partition, nested_folds
from src.training.runs import JobSpec, LOGGER, RunStore, fingerprint, utc
from src.utils.config import AnalyticsSettings
from src.utils.errors import AnalyticsError
from src.utils.langflow import LangflowConformance
from src.utils.tasks import TaskRunner


@dataclass(frozen=True, slots=True)
class Preparation:
    partition: Partition
    folds: tuple[Fold, ...]
    budget: dict | None = None
    request_sha256: str | None = None

    @property
    def sha256(self) -> str:
        # Approval is set after reading the estimate. The estimate itself remains bound.
        return content_hash({"partition": self.partition.evidence(),
                             "budget": {k: v for k, v in self.budget.items() if k != "authorized"} if self.budget else None,
                             **({"request_sha256": self.request_sha256} if self.request_sha256 else {})})


def validate_limits(spec: JobSpec, settings: AnalyticsSettings) -> None:
    """Check public ceilings without opening data or contacting a provider."""
    policy = settings.training
    if spec.trials > policy.max_trials_per_fold:
        raise AnalyticsError("El número de trials supera el límite configurado por fold.")
    if spec.optimization:
        options, cap = spec.optimization, settings.optimization
        if (options.timeout_seconds > cap.max_timeout_seconds or options.parallel_trials > cap.max_parallel_trials or
                options.cpu_threads > policy.cpu_threads or options.parallel_trials * options.cpu_threads > cap.max_total_cpu_threads):
            raise AnalyticsError("La búsqueda supera los límites de tiempo, paralelismo o CPU del servidor.")
        if options.sampler == "grid" and not spec.trials <= options.grid_size <= cap.max_grid_points:
            raise AnalyticsError("Grid requiere suficientes combinaciones para los trials y no puede superar el máximo configurado.")
    if spec.cloud and spec.trials > len(cloud_choices(spec.cloud, policy.cloud)):
        raise AnalyticsError("Los trials de LangFlow no pueden superar las combinaciones de prompt y umbral seleccionadas.")


def prepare(spec: JobSpec, settings: AnalyticsSettings) -> Preparation:
    """Check data, all folds and the upper bound for any possible cloud dispatch."""
    validate_limits(spec, settings)
    policy = settings.training
    if spec.source == "sintetico":
        partition = demo_partition(policy, spec.seed)
    else:
        manifests = ManifestStore(settings)
        envelope = read_manifest(manifests, spec.manifest_version)
        partition = real_partition(manifests, envelope, spec.target, policy, spec.seed)
        verify_seal_location(settings, envelope)
    folds = nested_folds(partition.development, policy, spec.seed)
    if spec.optimization and spec.optimization.metric in ("critical_recall", "critical_fnr", "penalized_f1") and "critica" not in partition.labels:
        raise AnalyticsError("La métrica requiere referencias humanas de severidad crítica en las particiones.")
    normalized = spec.model_dump(mode="json")
    if spec.cloud:
        normalized["cloud"]["approve"] = False
    request_digest = content_hash(normalized) if spec.optimization else None
    if spec.cloud:
        quote = budget_quote(spec.cloud, maximum_flow_calls(partition, folds, spec.trials), policy.cloud)
        return Preparation(partition, folds, quote_with_prompts(quote, spec.cloud, prompt_versions(settings)), request_digest)
    return Preparation(partition, folds, request_sha256=request_digest)


def verify_seal_location(settings: AnalyticsSettings, envelope: dict) -> None:
    """Verify the stamped location without opening the reserved artifact."""
    path = settings.path(settings.data.sealed_holdout_file)
    content = envelope["content"]
    try:
        stamp = path.stat()
        if (content["config"]["sealed_holdout_file"] != settings.data.sealed_holdout_file or
                content["holdout"]["artifact_stat"] != {"mtime_ns": stamp.st_mtime_ns, "bytes": stamp.st_size}):
            raise ValueError
    except (OSError, KeyError, TypeError, ValueError):
        raise AnalyticsError("Cambió la ubicación o la marca del sello de Prueba. Publica un manifiesto actualizado desde Datos del SOC.") from None


def _execute(store: RunStore, run_id: str, verify_actor: Callable[[], None] | None = None) -> dict | None:
    directory = store.path(run_id)
    with run_lock(directory):
        policy = store.settings.training
        state = store.state(run_id)
        if state["status"] == "completo":
            return store.verified(run_id, "result.json")
        started = monotonic()
        prior_time = state["seconds"]
        event_lock = RLock()
        optimization = None

        def event(name: str, **values) -> None:
            with event_lock:
                elapsed = monotonic() - started + prior_time
                row = {"at_utc": utc(), "elapsed_seconds": elapsed, "event": name, **values}
                store.append_event(run_id, row)
                state.update(seconds=elapsed, events=state["events"] + 1, updated_at=row["at_utc"], last_event=row)
                if "requests" in values:
                    state["flow_calls"] = values["requests"]
                if optimization and "trial" in values:
                    key = f"{values['model']}:{values['fold']}:{values['trial']}"
                    trial = state.setdefault("trials", {}).setdefault(key, {"model": values["model"], "fold": values["fold"],
                        "number": values["trial"], "state": "RUNNING", "seconds": 0.0})
                    if name == "inicio_trial":
                        trial["parameters"] = values["parameters"]
                    if name == "inner_medido":
                        trial.update(objective=values["objective"], inner=values["inner"])
                        trial["seconds"] += values["seconds"]
                    if name in ("trial_invalido", "trial_podado"):
                        trial["state"] = "FAIL" if name == "trial_invalido" else "PRUNED"
                    if name == "fin_trial":
                        trial.update(state=values["state"], objective=values["objective"])
                        state.setdefault("best_provisional", {})[f"{values['model']}:{values['fold']}"] = values["best_provisional"]
                store.save_state(run_id, state)

        def cancel_check() -> None:
            if (directory / "cancel.requested").is_file():
                raise CancelledRun("Cancelación solicitada.")
            if optimization and monotonic() - started + prior_time >= optimization.timeout_seconds:
                raise CancelledRun("Se agotó el tiempo autorizado. Se conserva lo completado; un presupuesto temporal nuevo requiere una configuración nueva.")

        def save(payload: dict) -> None:
            store.save_checkpoint(run_id, payload)

        try:
            state["status"] = "ejecutando"
            state.pop("message", None)
            event("inicio_ejecucion")
            record, spec, partition = store.inputs(run_id)
            optimization = spec.optimization
            checkpoint = store.checkpoint(run_id)
            environment = fingerprint(store.settings, store.software)
            changed = [name for name, value in environment.items() if record["environment"].get(name) != value]
            if record["policy"] != policy.model_dump(mode="json"):
                changed.append("policy")
            if changed:
                raise AnalyticsError("Cambió la configuración del trabajo en " + ", ".join(changed) +
                                     ". Crea una ejecución nueva.")
            folds = nested_folds(partition.development, policy, spec.seed)
            optuna.logging.set_verbosity(optuna.logging.ERROR)
            cancel_check()
            if spec.cloud:
                if verify_actor is None or state["flow_calls"]:
                    raise AnalyticsError("El trabajo cloud requiere autorización de sesión y una reserva nueva.")
                verify_actor()
                operational = Settings.from_env()
                client = LangflowConformance(store.settings, operational)
                searches = (CloudSearch(store.settings, spec.cloud, spec.target, partition.labels, spec.seed,
                    maximum_flow_calls(partition, folds, spec.trials), operational, client, verify_actor, event),)
                if searches[0].quote != record["budget"]:
                    raise AnalyticsError("Cambió la previsión de consumo desde la autorización.")
                cloud_directory = store.directory / ".cloud"
                cloud_directory.mkdir(exist_ok=True)
                execution_lock = run_lock(cloud_directory)
            else:
                searches = tuple(LocalSearch(name, spec.local, policy, spec.seed, partition.labels, target=spec.target) for name in spec.models)
                execution_lock = nullcontext()
            if optimization:
                from src.optimization.search import ConfiguredSearch
                searches = tuple(ConfiguredSearch(search, optimization) for search in searches)
            with execution_lock, threadpool_limits(limits=optimization.cpu_threads if optimization else policy.cpu_threads):
                results = {
                    search.name: run_nested(partition, folds, policy, search, spec.trials, directory, checkpoint, save, event, cancel_check,
                        optimization=optimization, seed=spec.seed,
                        remaining=(lambda: optimization.timeout_seconds - (monotonic() - started + prior_time)) if optimization else None)
                    for search in searches
                }
            report = {
                **{key: record[key] for key in ("phase", "schema_version", "run_id", "created_at", "mode", "request", "policy", "environment", "budget", "partition_sha256")},
                "completed_at": utc(), "partition": partition.evidence(), "families": results,
                "elapsed_seconds": monotonic() - started + prior_time, "flow_calls": state["flow_calls"],
                "test_evaluations": 0,
            }
            report["content_sha256"] = content_hash(report)
            store.write(run_id, "result.json", report)
            state["status"] = "completo"
            event("ejecucion_completa")
            return report
        except CancelledRun as error:
            for trial in state.get("trials", {}).values():
                if trial["state"] == "RUNNING":
                    trial.update(state="FAIL", interrupted=True)
            state.update(status="cancelado", message=str(error))
            event("ejecucion_cancelada")
        except AnalyticsError as error:
            state.update(status="error", message=str(error))
            event("ejecucion_con_error")
            LOGGER.warning("Experimento %s terminó con error controlado (%s)", run_id, type(error).__name__)
        except Exception as error:
            state.update(status="error", message="Falló el trabajo. Revisa la configuración, el espacio local y los puntos de control.")
            event("ejecucion_con_error")
            LOGGER.error("Experimento %s falló (%s)", run_id, type(error).__name__)
    return None


def technical_run(settings: AnalyticsSettings, spec: JobSpec) -> tuple[str, dict | None]:
    """CLI entry point for the identified local synthetic test only."""
    if spec.source != "sintetico" or spec.cloud:
        raise AnalyticsError("La ejecución técnica por CLI admite únicamente la prueba sintética local.")
    planned = prepare(spec, settings)
    store = RunStore(settings)
    run_id = store.create(spec, planned.partition, "prueba_tecnica_cli", lambda _identifier: None)
    return run_id, _execute(store, run_id)


class ExperimentManager:
    """Own a finite queue of jobs whose workers never call Streamlit."""

    def __init__(self, settings: AnalyticsSettings, api: SocApi) -> None:
        self.settings, self.api = settings, api
        self.store = RunStore(settings)
        self.manifests = ManifestStore(settings)
        self._pool = TaskRunner(settings.training.max_jobs)
        self._lock = RLock()
        self._running: dict[str, Future] = {}

    def _actor(self, token: SecretStr, permission: str = "read") -> User:
        actor = self.api.me(token)
        if not actor.can(permission):
            raise AnalyticsError("Tu rol no permite esta operación experimental.")
        return actor

    def _space(self) -> None:
        self._running = {identifier: job for identifier, job in self._running.items() if not job.done()}
        if len(self._running) >= self.settings.training.max_jobs:
            raise AnalyticsError("Hay un trabajo en ejecución. Revisa su progreso o cancélalo antes de iniciar otro.")

    def list(self, token: SecretStr) -> dict:
        self._actor(token)
        self.api.audit_event(token, "consultar_experimentos")
        return {"runs": self.store.versions(), "manifests": self.manifests.list()}

    def real_status(self, version: str, target: LabelField, token: SecretStr) -> dict:
        self._actor(token)
        self.api.audit_event(token, "consultar_experimentos", run_id=version)
        return readiness(read_manifest(self.manifests, version), target, self.settings.training)

    def preview(self, spec: JobSpec, token: SecretStr) -> dict:
        self._actor(token)
        self.api.audit_event(token, "consultar_experimentos", run_id=spec.manifest_version)
        planned = prepare(spec, self.settings)
        return {"request_sha256": content_hash(spec.model_dump(mode="json")), "partition": planned.partition.evidence(),
                "budget": planned.budget, "plan_sha256": planned.sha256}

    def start(self, spec: JobSpec, token: SecretStr, expected_plan: str) -> str:
        actor = self._actor(token, "write")
        planned = prepare(spec, self.settings)
        if expected_plan != planned.sha256:
            raise AnalyticsError("Cambió la partición o la previsión. Vuelve a preparar el trabajo antes de autorizarlo.")
        if planned.budget is not None and not planned.budget["authorized"]:
            raise AnalyticsError("El techo de solicitudes y USD requiere aprobación explícita dentro del presupuesto configurado.")
        with self._lock:
            self._space()
            run_id = self.store.create(spec, planned.partition, actor.id, lambda identifier: self.api.audit_event(
                token, "autorizar_experimento", run_id=identifier, outcome="iniciado"), planned.budget)
            verify = (lambda: self._actor(token, "write")) if spec.cloud else None
            self._running[run_id] = self._pool.submit(_execute, self.store, run_id, verify)
        return run_id

    def authorize_monitor(self, run_id: str, token: SecretStr) -> bool:
        actor = self._actor(token)
        record = self.store.verified(run_id, "run.json")
        self.api.audit_event(token, "consultar_experimentos", run_id=run_id)
        return self._may_manage(actor, record)

    @staticmethod
    def _may_manage(actor: User, record: dict) -> bool:
        return actor.can("write") and (actor.id == record["owner"] or actor.role == "administrador")

    def monitor(self, run_id: str) -> dict:
        state = self.store.state(run_id)
        record = self.store.verified(run_id, "run.json")
        with self._lock:
            active = (future := self._running.get(run_id)) is not None and not future.done()
        checkpoint = self.store.checkpoint(run_id)
        return {"state": state, "active": active, "events": self.store.recent_events(run_id),
                "completed_folds": sum(len(family["folds"]) for family in checkpoint.get("families", {}).values()),
                "mode": record["mode"], "request": record["request"], "budget": record["budget"],
                "partition": self.store.read(run_id, "partition.json"),
                "result": self.store.verified(run_id, "result.json") if state["status"] == "completo" else None}

    def manage(self, run_id: str, operation: str, token: SecretStr) -> None:
        actor = self._actor(token, "write")
        record = self.store.verified(run_id, "run.json")
        if not self._may_manage(actor, record):
            raise AnalyticsError("La gestión corresponde al autor o a un administrador.")
        directory = self.store.path(run_id)
        state = self.store.state(run_id)
        if operation == "cancelar":
            if state["status"] not in ("pendiente", "ejecutando"):
                raise AnalyticsError("El trabajo ya alcanzó un estado final.")
            self.api.audit_event(token, "cancelar_experimento", run_id=run_id)
            (directory / "cancel.requested").touch()
            return
        if operation != "reanudar" or record["mode"] != "academico" or state["status"] == "completo":
            raise AnalyticsError("Este trabajo requiere una ejecución nueva.")
        with self._lock:
            self._space()
            try:
                with run_lock(directory):
                    checkpoint = self.store.checkpoint(run_id)
                    if any("pending_outer" in family for family in checkpoint.get("families", {}).values()):
                        raise AnalyticsError("El fold externo quedó interrumpido durante su medición. Inicia una corrida nueva.")
                    self.api.audit_event(token, "reanudar_experimento", run_id=run_id)
                    (directory / "cancel.requested").unlink(missing_ok=True)
            except ValueError:
                raise AnalyticsError("La ejecución sigue activa.") from None
            self._running[run_id] = self._pool.submit(_execute, self.store, run_id)

    def close(self) -> None:
        self._pool.close()
