"""Streamlit views for grouped training and budgeted inference experiments."""
from __future__ import annotations

from decimal import Decimal
from functools import partial
import json
from typing import Callable

from matplotlib.figure import Figure
import streamlit as st

from src.data.models import LABEL_NAMES, TARGETS, content_hash
from src.inference.experimental import CloudParameters
from src.reports.figures import export_png
from src.reports.presentation import TableGuide
from src.reports.training_presentation import (
    external_table, fold_plot, log_table, partition_table, readiness_table, stability_plot, summary_table, trial_plot, validation_table,
)
from src.training.local import FAMILY_NAMES
from src.training.runs import JobSpec
from src.training.settings import LocalParameters
from src.utils.errors import AnalyticsError
from src.utils.streamlit_runtime import get_runtime, poll_task, render_guide, render_table, require_session, start_task

runtime = get_runtime()
st.title("Experimentación SOC")
session = require_session(runtime)
if session is None:
    st.stop()

manager = runtime.experiments
if manager is None:
    st.error("El entorno de experimentación no está disponible.")
    st.stop()
policy = runtime.settings.training
token = session.token


def candidate_panel() -> None:
    """Consume a versioned candidate while keeping the existing preparation/start path."""
    version = st.session_state.get("exp_candidate_version")
    if not version or runtime.optimization is None or not session.user.can("write"):
        return
    st.subheader("Configuración candidata transferida desde Optuna")
    if st.session_state.get("exp_candidate_scope") != version and "exp_candidate_load" not in st.session_state:
        st.session_state["exp_candidate_scope"] = version
        start_task(runtime, "exp_candidate_load", runtime.optimization.load_candidate, version, token)
    poll_task(runtime, "exp_candidate_load", "Verificando candidata y procedencia…")
    if st.session_state.get("exp_candidate_load_error"):
        st.error(st.session_state["exp_candidate_load_error"])
    candidate = st.session_state.get("exp_candidate_load_result")
    if not candidate or candidate["version"] != version:
        return
    from src.reports.optimization_presentation import space_table
    spec = JobSpec.model_validate(candidate["request"])
    render_table(*space_table(spec.optimization))
    st.caption("Versión · " + version + " · Origen de selección · " + candidate["selection"])
    st.caption("La corrida candidata mantiene los parámetros fijados. Su validación reutiliza el protocolo experimental y no constituye una evaluación independiente de Prueba.")
    if st.button("Preparar corrida con candidata", key="exp_candidate_prepare"):
        start_task(runtime, "exp_candidate_preview", manager.preview, spec, token)
    poll_task(runtime, "exp_candidate_preview", "Preparando candidata con el motor existente…")
    if st.session_state.get("exp_candidate_preview_error"):
        st.error(st.session_state["exp_candidate_preview_error"])
    preview = st.session_state.get("exp_candidate_preview_result")
    if preview and preview["request_sha256"] == content_hash(spec.model_dump(mode="json")):
        render_table(*partition_table(preview["partition"]))
        if spec.cloud:
            st.info("La autorización y el presupuesto cloud se restablecieron. Usa los controles LangFlow para autorizar una búsqueda nueva con estos prompts y umbrales.")
        elif st.button("Iniciar corrida candidata", key="exp_candidate_start"):
            start_task(runtime, "exp_start", manager.start, spec, token, preview["plan_sha256"])


candidate_panel()


def launch(key: str, function: Callable, *args: object) -> None:
    start_task(runtime, key, function, *args)
    st.rerun()


def chart(visual: tuple[Figure, TableGuide], key: str) -> None:
    figure, guide = visual
    st.pyplot(figure, width="stretch")
    render_guide(guide)
    st.download_button("Descargar PNG a 600 DPI", partial(export_png, figure, runtime.settings.figures),
                       file_name=key + ".png", mime="image/png", key="exp_png_" + key, on_click="ignore")


def academic_controls() -> tuple[tuple[str, ...], LocalParameters]:
    defaults = policy.local
    families = st.multiselect("Modelos académicos", ("tfidf_logreg", "tfidf_svm"),
        default=("tfidf_logreg", "tfidf_svm"), format_func=FAMILY_NAMES.get, key="exp_models")
    with st.expander("Hiperparámetros del pipeline"):
        first, second, third = st.columns(3)
        with first:
            lower = st.selectbox("N-grama mínimo", [1, 2, 3], index=defaults.ngram_min - 1, key="exp_ngram_min")
            uppers = list(range(lower, 4))
            upper = st.selectbox("N-grama máximo", uppers, index=uppers.index(max(lower, defaults.ngram_max)), key="exp_ngram_max")
            min_df = st.number_input("min_df (documentos)", 1, 100, defaults.min_df, key="exp_min_df")
            max_df = st.number_input("max_df (proporción)", .01, 1.0, defaults.max_df, step=.05, key="exp_max_df")
        with second:
            features = st.number_input("Límite de características", 10, 100000, defaults.max_features, key="exp_features")
            sublinear = st.checkbox("Escala sublineal del TF", defaults.sublinear_tf, key="exp_sublinear")
            smooth = st.checkbox("Suavizar el IDF", defaults.smooth_idf, key="exp_smooth")
        with third:
            c = st.number_input("Regularización C de referencia", .0001, 1000.0, defaults.c,
                                format="%.4f", key="exp_c")
            balanced = st.checkbox("Ponderación balanceada de clases", defaults.balanced, key="exp_balanced")
            solvers = ("lbfgs", "saga")
            solver = st.selectbox("Solver de regresión logística", solvers, index=solvers.index(defaults.solver),
                                  disabled="tfidf_logreg" not in families, key="exp_solver")
            max_iter = st.number_input("Iteraciones máximas", 100, 10000, defaults.max_iter, key="exp_max_iter")
        st.caption(f"Optuna busca C en escala logarítmica con factor {policy.c_search_factor:g} y ajusta el n-grama máximo. SVM lineal usa selección automática de formulación dual.")
    return tuple(families), LocalParameters(ngram_min=lower, ngram_max=upper, min_df=min_df, max_df=max_df,
        max_features=features, sublinear_tf=sublinear, smooth_idf=smooth, c=c, balanced=balanced, solver=solver, max_iter=max_iter)


def cloud_controls() -> CloudParameters | None:
    flow, cloud = runtime.settings.flow_validation, policy.cloud
    st.write(f"**Groq principal** · {flow.expected_groq_model}")
    st.write(f"**Gemini de respaldo técnico** · {flow.expected_gemini_model}")
    st.caption("El componente instalado usa esfuerzo de razonamiento bajo en Groq, thinking bajo en Gemini y un límite de salida de 1.536 tokens. Las variantes ajustan el prompt por petición y el umbral de revisión experimental.")
    prompts = st.multiselect("Versiones de prompt", list(cloud.prompts), default=list(cloud.prompts),
                             key="exp_prompts")
    thresholds = st.multiselect("Umbrales de revisión (puntaje 0–1)", list(cloud.thresholds),
                                default=[cloud.default_threshold], key="exp_thresholds")
    budget = st.number_input("Presupuesto solicitado (USD)", min_value=0.0, max_value=float(cloud.max_run_budget_usd),
                             value=0.0, format="%.4f", disabled=cloud.max_run_budget_usd == 0, key="exp_budget")
    if not cloud.max_run_budget_usd or not cloud.max_cost_per_flow_usd:
        st.info("Presupuesto del servidor en 0 USD. La modalidad permite consultar configuraciones y requisitos de datos.")
    st.caption(f"Intervalo mínimo entre solicitudes a LangFlow de {cloud.seconds_between_calls:g} s. Cada ejecución puede consumir hasta {cloud.attempts_per_flow} intentos de proveedor.")
    if not prompts or not thresholds:
        st.info("Selecciona al menos un prompt y un umbral.")
        return None
    return CloudParameters(prompts=tuple(prompts), thresholds=tuple(thresholds),
                           budget_usd=Decimal(str(budget)), approve=False)


def dataset_selection(mode: str, manifests: list[dict]) -> tuple[str, str, str | None, bool]:
    if mode == "academico":
        source = st.radio("Datos del experimento", ("sintetico", "real"), horizontal=True, key="exp_source",
            format_func=lambda value: "Prueba técnica sintética" if value == "sintetico" else "Referencias humanas")
    else:
        source = "real"
    if source == "sintetico":
        st.caption("La prueba técnica usa ejemplos sintéticos identificados y comprueba el protocolo para tipo.")
        return source, "tipo", None, True
    target = st.selectbox("Objetivo supervisado", TARGETS, format_func=LABEL_NAMES.get, key="exp_target")
    if not manifests:
        st.info("Publica un manifiesto desde Datos del SOC para consultar la disponibilidad de referencias.")
        return source, target, None, False
    version = st.selectbox("Versión del manifiesto", [row["Versión"] for row in manifests], key="exp_version")
    scope = version, target
    if st.session_state.get("exp_status_scope") != scope and "exp_status" not in st.session_state:
        st.session_state["exp_status_scope"] = scope
        launch("exp_status", manager.real_status, version, target, token)
    status = st.session_state.get("exp_status_result")
    if not status or (status["version"], status["target"]) != scope:
        return source, target, version, False
    render_table(*readiness_table(status))
    for reason in status["reasons"]:
        st.warning(reason)
    return source, target, version, status["ready"]


def job_form(mode: str, manifests: list[dict]) -> None:
    source, target, version, ready = dataset_selection(mode, manifests)
    if mode == "academico":
        families, local = academic_controls()
        cloud = None
        choices = policy.max_trials_per_fold
        configured = bool(families)
    else:
        cloud = cloud_controls()
        families, local = (), None
        choices = min(policy.max_trials_per_fold, len(cloud.prompts) * len(cloud.thresholds)) if cloud else 1
        configured = cloud is not None
    first, second = st.columns(2)
    with first:
        seed = st.number_input("Semilla", 0, 2**32 - 1, runtime.settings.seed, key="exp_seed")
    with second:
        trials = st.number_input("Trials por fold externo", 1, choices,
                                 min(choices, policy.default_trials_per_fold), key="exp_trials_" + mode)
    if not configured or not ready:
        return
    spec = JobSpec(source=source, target=target, seed=seed, trials=trials,
                   manifest_version=version, models=families, local=local, cloud=cloud)
    if st.button("Preparar partición", key="exp_prepare", disabled="exp_preview" in st.session_state):
        launch("exp_preview", manager.preview, spec, token)
    preview = st.session_state.get("exp_preview_result")
    if not preview or preview["request_sha256"] != content_hash(spec.model_dump(mode="json")):
        return
    render_table(*partition_table(preview["partition"]))
    st.caption(f"Prueba sellada · SHA-256 {preview['partition']['test']['sha256']}")
    allow = session.user.can("write")
    if cloud and preview["budget"]:
        quote = preview["budget"]
        st.write(f"Máximo de {quote['planned_flow_calls']} solicitudes a LangFlow y {quote['max_provider_attempts']} intentos de proveedor.")
        st.write(f"Techo calculado con los límites configurados de USD {quote['reserved_usd']}. Presupuesto ingresado de USD {cloud.budget_usd}.")
        with st.expander("Huellas de los prompts seleccionados"):
            st.json(quote["prompt_versions"], expanded=False)
        within_ceiling = (0 < Decimal(quote["reserved_usd"]) <= cloud.budget_usd <= policy.cloud.max_run_budget_usd and
                          quote["planned_flow_calls"] <= policy.cloud.max_flow_calls)
        approved = st.checkbox("Autorizo el envío de los reportes protegidos y el presupuesto de esta ejecución",
                               disabled=not allow or not within_ceiling, key="exp_approve_" + preview["request_sha256"])
        spec = spec.model_copy(update={"cloud": cloud.model_copy(update={"approve": approved})})
        allow = allow and approved and within_ceiling
    if st.button("Iniciar ejecución", type="primary", key="exp_start_button",
                 disabled=not allow or "exp_start" in st.session_state):
        launch("exp_start", manager.start, spec, token, preview["plan_sha256"])


def results_view(result: dict) -> None:
    if result["partition"]["source"] == "sintetico":
        st.info("Resultados de una prueba técnica sintética de clasificación de tipo.")
    render_table(*summary_table(result))
    chart(fold_plot(result, runtime.settings.figures), "f1_externo")
    chart(fold_plot(result, runtime.settings.figures, seconds=True), "duracion_folds")
    names = list(result["families"])
    name = st.selectbox("Modelo para consultar sus folds", names, format_func=FAMILY_NAMES.get, key="exp_result_model")
    family = result["families"][name]
    render_table(*external_table(family))
    number = st.selectbox("Fold externo para consultar sus trials", [fold["fold"] for fold in family["folds"]], key="exp_result_fold")
    fold = next(fold for fold in family["folds"] if fold["fold"] == number)
    chart(trial_plot(fold, runtime.settings.figures), "trials")
    chart(stability_plot(family, runtime.settings.figures), "estabilidad")
    render_table(*validation_table(family))
    with st.expander("Configuración seleccionada y huellas"):
        st.json({"configuración": family["validation_selection"]["winner"]["configuration"],
                 "artefacto": family["artifact"], "partición_sha256": result["partition_sha256"],
                 "evaluaciones_de_prueba": result["test_evaluations"]}, expanded=False)
    st.download_button("Descargar informe de ejecución", json.dumps(result, ensure_ascii=False, indent=2).encode(),
                       file_name="experimento-" + result["run_id"] + ".json", mime="application/json",
                       key="exp_download", on_click="ignore")


def monitor_view(run_id: str, can_manage: bool) -> None:
    try:
        initial = manager.monitor(run_id)
    except AnalyticsError as error:
        st.error(str(error))
        return

    @st.fragment(run_every=runtime.settings.ui.poll_seconds if initial["active"] else None)
    def live_status() -> None:
        if require_session(runtime) is None:
            return
        try:
            data = manager.monitor(run_id)
        except AnalyticsError as error:
            st.error(str(error))
            return
        if initial["active"] and not data["active"]:
            st.rerun()
        state = data["state"]
        status = state["status"]
        if status == "ejecutando" and not data["active"]:
            status = "interrumpido"
        st.write(f"**Estado** · {status} · {state['seconds']:.2f} s acumulados")
        if state.get("message"):
            st.warning(state["message"])
        total = policy.outer_folds * (len(data["request"]["models"]) or 1)
        count = data["completed_folds"]
        st.progress(min(1.0, count / total), text=f"Mediciones externas completas {count}/{total}")
        if data["budget"]:
            st.caption(f"Solicitudes reservadas {state['flow_calls']} de {data['budget']['planned_flow_calls']}. El costo se presenta como techo declarado.")
        render_table(*log_table(data["events"]))
        if can_manage and data["active"] and st.button("Solicitar cancelación", key="exp_cancel"):
            launch("exp_control", manager.manage, run_id, "cancelar", token)
        if can_manage and not data["active"] and data["mode"] == "academico" and status != "completo":
            if st.button("Reanudar desde el punto de control", key="exp_resume"):
                launch("exp_control", manager.manage, run_id, "reanudar", token)

    live_status()
    render_table(*partition_table(initial["partition"]))
    if initial["result"]:
        results_view(initial["result"])


for key, message in (
    ("exp_list", "Consultando manifiestos y ejecuciones autorizadas…"),
    ("exp_status", "Comprobando referencias y el sello de Prueba…"),
    ("exp_preview", "Calculando cuotas y comprobando los 20 folds…"),
    ("exp_start", "Preparando y auditando el trabajo…"),
    ("exp_monitor", "Autorizando acceso al seguimiento…"),
    ("exp_control", "Registrando el control solicitado…"),
):
    poll_task(runtime, key, message)
    if error := st.session_state.get(key + "_error"):
        st.error(error)

if started := st.session_state.pop("exp_start_result", None):
    st.session_state["exp_started_id"] = started
    st.session_state.pop("exp_list_result", None)
if "exp_list_result" not in st.session_state and "exp_list" not in st.session_state and "exp_list_error" not in st.session_state:
    launch("exp_list", manager.list, token)
if st.button("Actualizar ejecuciones y manifiestos", key="exp_reload", disabled="exp_list" in st.session_state):
    st.session_state.pop("exp_status_scope", None)
    launch("exp_list", manager.list, token)
catalog = st.session_state.get("exp_list_result")
if catalog is None:
    st.stop()

mode = st.radio("Modalidad", ("academico", "langflow"), horizontal=True, key="exp_mode",
                format_func=lambda value: "Modelos académicos" if value == "academico" else "Inferencia experimental con LangFlow")
if session.user.can("write"):
    job_form(mode, catalog["manifests"])
else:
    st.caption("Tu rol permite consultar los experimentos registrados.")
st.subheader("Seguimiento y resultados")
available = [run["run_id"] for run in catalog["runs"] if run["mode"] == mode]
if available:
    last_started = st.session_state.get("exp_started_id")
    default = available.index(last_started) if last_started in available else 0
    selector = "exp_selection_" + mode
    if last_started in available:
        st.session_state[selector] = st.session_state.pop("exp_started_id")
    run_id = st.selectbox("Ejecución", available, index=default, key=selector)
    if st.session_state.get("exp_monitor_scope") != run_id and "exp_monitor" not in st.session_state:
        st.session_state["exp_monitor_scope"] = run_id
        launch("exp_monitor", manager.authorize_monitor, run_id, token)
    if st.session_state.get("exp_monitor_scope") == run_id and "exp_monitor_result" in st.session_state:
        monitor_view(run_id, st.session_state["exp_monitor_result"])
else:
    st.info("La modalidad elegida aún no tiene ejecuciones registradas.")
