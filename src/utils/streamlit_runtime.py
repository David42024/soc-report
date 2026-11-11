"""UI-only resources, caching and private session state for Streamlit pages."""
from __future__ import annotations

import atexit
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Any, Callable

from pydantic import SecretStr
import streamlit as st

from src.data.catalog import DatasetCatalog
from src.inference.services import Session, SocApi
from src.reports.presentation import TableGuide
from src.training.experiments import RunRegistry
from src.utils.config import AnalyticsSettings, load_config
from src.utils.errors import AnalyticsError
from src.utils.logging import configure_logging
from src.utils.reproducibility import seed_everything
from src.utils.tasks import TaskRunner

LOGGER = logging.getLogger("soc_analytics.ui")

if TYPE_CHECKING:
    from src.explainability.workspace import ExplanationWorkspace
    from src.evaluation.workspace import EvaluationWorkspace
    from src.training.jobs import ExperimentManager
    from src.reports.workspace import ReportingWorkspace
    from src.inference.workspace import InferenceWorkspace
    from src.optimization.workspace import OptimizationWorkspace


def _inventory(config_json: str, root: str, source: str, fingerprint: tuple) -> list[dict]:
    """Cache only shared local metadata; tokens and private records never enter this cache."""
    settings = AnalyticsSettings(**json.loads(config_json), root=Path(root), source_file=Path(source))
    return DatasetCatalog(settings, SocApi(settings.api)).inspect_all()


@dataclass
class Runtime:
    """Token-free shared resources; actual user state belongs to session_state."""

    settings: AnalyticsSettings
    api: SocApi
    catalog: DatasetCatalog
    runs: RunRegistry
    tasks: TaskRunner
    inventory: Callable[..., list[dict]]
    experiments: ExperimentManager | None = None
    evaluations: EvaluationWorkspace | None = None
    explainability: ExplanationWorkspace | None = None
    reporting: ReportingWorkspace | None = None
    inference: InferenceWorkspace | None = None
    optimization: OptimizationWorkspace | None = None

    def profiles(self) -> list[dict]:
        """Get copies of metadata, invalidated by configuration or source changes."""
        return self.inventory(self.settings.model_dump_json(), str(self.settings.root),
                              str(self.settings.source_file), self.catalog.fingerprint())


@st.cache_resource(show_spinner=False)
def _resources(config_json: str, root: str, source: str, registry_stamp: int) -> Runtime:
    from src.optimization.workspace import OptimizationWorkspace
    from src.explainability.workspace import ExplanationWorkspace
    from src.evaluation.workspace import EvaluationWorkspace
    from src.training.jobs import ExperimentManager
    from src.reports.workspace import ReportingWorkspace
    from src.inference.workspace import InferenceWorkspace

    settings = AnalyticsSettings(**json.loads(config_json), root=Path(root), source_file=Path(source))
    configure_logging(settings)
    seed_everything(settings.seed)
    api = SocApi(settings.api)
    tasks = TaskRunner(settings.ui.workers)
    atexit.register(tasks.close)
    inventory = st.cache_data(ttl=settings.ui.cache_seconds, max_entries=settings.ui.cache_entries,
                              show_spinner=False)(_inventory)
    experiments = ExperimentManager(settings, api)
    atexit.register(experiments.close)
    evaluations = EvaluationWorkspace(settings, api, experiments.store)
    explanations = ExplanationWorkspace(settings, api, experiments.store)
    reporting = ReportingWorkspace(settings, api)
    inference = InferenceWorkspace(settings, api)
    optimization = OptimizationWorkspace(experiments)
    return Runtime(settings, api, DatasetCatalog(settings, api), RunRegistry(settings), tasks, inventory, experiments, evaluations, explanations, reporting, inference, optimization)


def get_runtime() -> Runtime:
    """Load only public settings and reuse token-free resources."""
    settings = load_config()
    try:
        stamp = settings.path(settings.registry_file).stat().st_mtime_ns
        return _resources(settings.model_dump_json(), str(settings.root), str(settings.source_file), stamp)
    except OSError:
        raise AnalyticsError("No se pudo preparar el entorno analítico. Revisa el catálogo y los permisos de runs/.") from None


def start_task(runtime: Runtime, key: str, function: Callable, *args: Any) -> None:
    """Start at most one pending operation for this key in the current session."""
    if key not in st.session_state:
        st.session_state.pop(key + "_error", None)
        st.session_state.pop(key + "_result", None)
        st.session_state[key] = runtime.tasks.submit(function, *args)


def poll_task(runtime: Runtime, key: str, label: str) -> None:
    """Poll background futures with a fragment; workers never call Streamlit."""
    @st.fragment(run_every=runtime.settings.ui.poll_seconds)
    def progress() -> None:
        future = st.session_state.get(key)
        if future is None:
            return
        if not future.done():
            st.info(label)
            return
        try:
            st.session_state[key + "_result"] = future.result()
            if key == "record_task":
                st.session_state.pop("records_task_result", None)
        except AnalyticsError as error:
            st.session_state[key + "_error"] = str(error)
        except Exception:
            LOGGER.error("Una tarea analítica no pudo completarse; detalles omitidos por privacidad")
            st.session_state[key + "_error"] = "No se pudo completar la tarea. Revisa la configuración y los servicios."
        finally:
            del st.session_state[key]
        st.rerun()

    progress()


def clear_private_state() -> None:
    """Remove tokens, previews and pending references on logout or expiry."""
    for key in list(st.session_state):
        if key.startswith(("auth_", "identity_", "preview_", "record_", "records_", "catalog_", "data_", "exp_", "eval_", "xai_", "informe_", "inf_", "opt_")):
            st.session_state.pop(key, None)


def render_account(runtime: Runtime) -> None:
    """Use the operational login and TOTP flow without saving passwords."""
    with st.sidebar:
        st.caption("Sesión del sistema SOC")
        if "auth_login_result" in st.session_state:
            st.session_state["auth_session"] = st.session_state.pop("auth_login_result")
        session = st.session_state.get("auth_session")
        if session:
            st.write(f"{session.user.username} · {session.user.role}")
            if st.button("Cerrar sesión", key="logout"):
                token = session.token
                clear_private_state()
                start_task(runtime, "logout_task", runtime.api.logout, token)
                st.rerun()
        else:
            st.caption("Accede con tu cuenta y permisos actuales.")
            with st.form("soc_login", clear_on_submit=True):
                username = st.text_input("Usuario", max_chars=80)
                password = st.text_input("Contraseña", type="password", max_chars=128)
                otp = st.text_input("Segundo factor, si está activo", type="password", max_chars=48)
                submitted = st.form_submit_button("Iniciar sesión", disabled="auth_login" in st.session_state)
            if submitted:
                if not username.strip() or not password:
                    st.warning("Introduce usuario y contraseña.")
                else:
                    start_task(runtime, "auth_login", runtime.api.login, username.strip(), SecretStr(password), SecretStr(otp))
            if st.session_state.get("auth_login_error"):
                st.error(st.session_state["auth_login_error"])
        poll_task(runtime, "auth_login", "Validando la sesión con FastAPI…")
        poll_task(runtime, "logout_task", "Cerrando la sesión en FastAPI…")
        if st.session_state.pop("logout_task_error", None):
            st.warning("La sesión local se cerró. No se pudo confirmar su revocación en FastAPI.")


def require_session(runtime: Runtime, permission: str = "read") -> Session | None:
    """Gate local views using backend identity, expiry and the shared RBAC matrix."""
    session = st.session_state.get("auth_session")
    if session is None:
        st.info("Inicia sesión en la barra lateral para consultar esta página.")
        return None
    if session.expires_at <= datetime.now(timezone.utc):
        clear_private_state()
        st.warning("La sesión expiró. Inicia sesión nuevamente.")
        return None
    if "identity_task_result" in st.session_state:
        session = session.model_copy(update={"user": st.session_state.pop("identity_task_result"), "checked_at": monotonic()})
        st.session_state["auth_session"] = session
    if st.session_state.get("identity_task_error"):
        clear_private_state()
        st.warning("No se pudo validar tu sesión. Inicia sesión nuevamente.")
        return None
    if monotonic() - session.checked_at >= runtime.settings.ui.session_check_seconds:
        start_task(runtime, "identity_task", runtime.api.me, session.token)
        poll_task(runtime, "identity_task", "Comprobando la vigencia de la sesión…")
        return None
    if not session.user.can(permission):
        st.warning("Tu rol no permite acceder a este módulo.")
        return None
    return session


def render_table(rows: list[dict], guide: TableGuide) -> None:
    """Render the complete interpretation contract for a table."""
    st.subheader(guide.title)
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.info("No hay registros para mostrar.")
    render_guide(guide)


def render_guide(guide: TableGuide) -> None:
    """Provide units, interpretation and limits for tables or figures."""
    st.caption(guide.legend)
    st.markdown("**Cómo leerlo**\n\n" + guide.how_to_read)
    st.markdown("**Hallazgo clave**\n\n" + guide.finding)
    st.caption("**Limitaciones**\n\n" + guide.limitations)
