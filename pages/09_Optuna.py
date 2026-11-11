"""Optuna controls and visualization; execution remains in the Phase 2 manager."""
from __future__ import annotations

from decimal import Decimal
from functools import partial
import json

import streamlit as st

from src.data.models import LABEL_NAMES, TARGETS, content_hash
from src.inference.experimental import CloudParameters
from src.optimization.contracts import METRICS, SearchOptions
from src.optimization.workspace import build_request, default_options, parse_space
from src.reports.figures import export_png
from src.reports.optimization_presentation import (
    contour_plot, distribution_plot, history_plot, importance_plot, live_table, parallel_plot, slice_plot,
    space_table, stability_plot, stability_table, trials_table, winners_table,
)
from src.reports.training_presentation import log_table, partition_table, readiness_table
from src.reports.presentation import TableGuide
from src.training.local import FAMILY_NAMES
from src.training.runs import JobSpec
from src.utils.errors import AnalyticsError
from src.utils.streamlit_runtime import get_runtime, poll_task, render_guide, render_table, require_session, start_task

runtime = get_runtime()
st.title("Optimización de experimentos SOC con Optuna")
session = require_session(runtime)
if session is None:
    st.stop()
workspace, manager = runtime.optimization, runtime.experiments
if workspace is None or manager is None:
    st.error("El módulo de optimización no está disponible.")
    st.stop()
policy, token = runtime.settings.optimization, session.token

for key in ("opt_catalog", "opt_preview", "opt_start", "opt_control", "opt_inspect", "opt_save", "opt_load", "opt_import", "opt_candidate", "opt_authorize", "opt_readiness"):
    poll_task(runtime, key, "Consultando o preparando el experimento autorizado…")
    if st.session_state.get(key + "_error"):
        st.error(st.session_state[key + "_error"])
for key in ("opt_load_result", "opt_import_result"):
    if key in st.session_state:
        st.session_state["opt_loaded_spec"] = st.session_state.pop(key)
        st.session_state.pop("opt_request", None)
if "opt_start_result" in st.session_state:
    st.session_state["opt_latest_run"] = st.session_state.pop("opt_start_result")
    st.session_state.pop("opt_catalog_result", None)
if "opt_save_result" in st.session_state:
    saved = st.session_state["opt_save_result"]
    st.success("Configuración guardada · " + saved["version"])
if "opt_catalog_result" not in st.session_state and "opt_catalog" not in st.session_state and "opt_catalog_error" not in st.session_state:
    start_task(runtime, "opt_catalog", workspace.list, token)
if st.button("Actualizar estudios y configuraciones", key="opt_reload"):
    start_task(runtime, "opt_catalog", workspace.list, token)
catalog = st.session_state.get("opt_catalog_result", {"runs": [], "manifests": [], "configurations": [], "candidates": []})


def chart(visual, key: str) -> None:
    figure, guide = visual
    if figure is not None:
        st.pyplot(figure)
        st.download_button("Descargar PNG a 600 DPI", partial(export_png, figure, runtime.settings.figures),
                           file_name=key + ".png", mime="image/png", key="opt_png_" + key, on_click="ignore")
    render_guide(guide)


if session.user.can("write"):
    with st.expander("Guardar y cargar configuraciones experimentales"):
        if catalog["configurations"]:
            version = st.selectbox("Configuración guardada", catalog["configurations"], key="opt_saved_config")
            if st.button("Cargar configuración", key="opt_load_button"):
                start_task(runtime, "opt_load", workspace.load_configuration, version, token)
        uploaded = st.file_uploader("Configuración YAML o JSON de búsqueda", type=("yaml", "yml", "json"), key="opt_config_file")
        if uploaded and st.button("Importar configuración", key="opt_import_button"):
            start_task(runtime, "opt_import", workspace.parse, uploaded.getvalue(), token)
    loaded = st.session_state.get("opt_loaded_spec")
    suffix = "_" + content_hash(loaded.model_dump(mode="json"))[:12] if loaded else ""
    key = lambda name: "opt_" + name + suffix
    default_family = "langflow" if loaded and loaded.cloud else loaded.models[0] if loaded else "tfidf_logreg"
    families = tuple(FAMILY_NAMES)
    family = st.selectbox("Modelo o configuración experimental", families, index=families.index(default_family), format_func=FAMILY_NAMES.get, key=key("family"))
    cloud_mode = family == "langflow"
    source = "real" if cloud_mode else st.radio("Datos", ("sintetico", "real"), index=int(bool(loaded and loaded.source == "real")),
        format_func=lambda value: "Prueba técnica sintética" if value == "sintetico" else "Referencias humanas", horizontal=True, key=key("source"))
    version = None
    target = "tipo"
    if source == "real":
        target = st.selectbox("Objetivo supervisado", TARGETS, index=TARGETS.index(loaded.target) if loaded else 0, format_func=LABEL_NAMES.get, key=key("target"))
        versions = [row["Versión"] for row in catalog["manifests"]]
        if versions:
            version = st.selectbox("Manifiesto de datos", versions, index=versions.index(loaded.manifest_version) if loaded and loaded.manifest_version in versions else 0, key=key("manifest"))
            scope = version, target
            if st.session_state.get("opt_readiness_scope") != scope and "opt_readiness" not in st.session_state:
                st.session_state["opt_readiness_scope"] = scope
                start_task(runtime, "opt_readiness", manager.real_status, version, target, token)
            ready = st.session_state.get("opt_readiness_result")
            if ready and (ready["version"], ready["target"]) == scope:
                render_table(*readiness_table(ready))
                for reason in ready["reasons"]:
                    st.info(reason)
        else:
            st.info("Publica un manifiesto en Datos del SOC. Las búsquedas reales exigen referencias y un sello válido.")
    defaults = loaded.optimization if loaded and bool(loaded.cloud) == cloud_mode else default_options(runtime.settings, cloud=cloud_mode)
    with st.form("opt_search_form" + suffix):
        first, second, third = st.columns(3)
        with first:
            sampler = st.selectbox("Sampler", ("tpe", "random", "grid"), index=("tpe", "random", "grid").index(defaults.sampler), key=key("sampler"))
            pruner = st.selectbox("Pruner", ("none", "median", "halving"), index=("none", "median", "halving").index(defaults.pruner), key=key("pruner"))
            trials = st.number_input("Trials por fold externo", 1, runtime.settings.training.max_trials_per_fold,
                loaded.trials if loaded else policy.default_trials if not cloud_mode else min(policy.default_trials, len(runtime.settings.training.cloud.prompts) * len(runtime.settings.training.cloud.thresholds)), key=key("trials"))
            seconds = st.number_input("Tiempo máximo acumulado (s)", min_value=1.0, max_value=policy.max_timeout_seconds, value=defaults.timeout_seconds, key=key("timeout"))
        with second:
            metric = st.selectbox("Métrica objetivo", tuple(METRICS), index=tuple(METRICS).index(defaults.metric), format_func=METRICS.get, key=key("metric"))
            direction = st.selectbox("Dirección", ("maximize", "minimize"), index=int(defaults.direction == "minimize"), key=key("direction"))
            seed = st.number_input("Semilla", 0, 2**32 - 1, loaded.seed if loaded else runtime.settings.seed, key=key("seed"))
            parallel = st.number_input("Trials simultáneos", 1, policy.max_parallel_trials, defaults.parallel_trials, disabled=cloud_mode, key=key("parallel"))
            threads = st.number_input("Hilos numéricos por ajuste", 1, runtime.settings.training.cpu_threads, defaults.cpu_threads, key=key("cpu"))
        with third:
            startup = st.number_input("Trials iniciales de exploración / pruner", 1, runtime.settings.training.max_trials_per_fold, defaults.startup_trials, key=key("startup"))
            warmup = st.number_input("Pasos internos de espera del pruner", 0, 2, defaults.warmup_steps, key=key("warmup"))
            critical = st.number_input("Penalización de FNR crítica (λ)", 0.0, 1.0, defaults.critical_penalty, disabled=metric != "penalized_f1", key=key("critical_penalty"))
            review = st.number_input("Penalización de revisión (γ)", 0.0, 1.0, defaults.review_penalty, disabled=metric != "penalized_f1", key=key("review_penalty"))
            budget = st.number_input("Presupuesto cloud solicitado (USD)", 0.0, float(runtime.settings.training.cloud.max_run_budget_usd),
                0.0, disabled=not cloud_mode or runtime.settings.training.cloud.max_run_budget_usd == 0, key=key("budget"))
        text = st.text_area("Espacio de búsqueda (JSON editable)", json.dumps({name: value.model_dump(mode="json", exclude_defaults=True) for name, value in defaults.space.items()},
            ensure_ascii=False, indent=2), height=230, key=key("space"))
        st.caption('Tipos admitidos: float e int con low/high, step opcional y log; categorical con choices. Grid exige categorías finitas. F1 penalizado = F1 macro − λ·FNR crítica − γ·tasa de revisión.')
        validate = st.form_submit_button("Validar configuración", key="opt_validate")
    if parallel > 1:
        st.warning("Los trials concurrentes pueden completar en otro orden. TPE paralelo carece de reproducibilidad exacta de la secuencia.")
    if cloud_mode:
        st.info("Groq/Gemini, el JSON estructurado, los límites de generación y el fallback conservan su configuración. Solo se optimizan prompts y umbrales admitidos. El costo facturado carece de telemetría disponible.")
        st.caption("El presupuesto del servidor permanece en cero hasta habilitación y autorización explícitas. Las revisiones no equivalen a probabilidades calibradas.")
    if validate:
        try:
            space = parse_space(text, policy.max_config_bytes)
            cloud = CloudParameters(prompts=tuple(runtime.settings.training.cloud.prompts), thresholds=runtime.settings.training.cloud.thresholds,
                                    budget_usd=Decimal(str(budget)), approve=False) if cloud_mode else None
            raw = dict(source=source, target=target, seed=seed, trials=trials, manifest_version=version,
                models=() if cloud else (family,), local=None if cloud else (loaded.local if loaded and loaded.local else runtime.settings.training.local).model_dump(mode="json"),
                cloud=cloud.model_dump(mode="json") if cloud else None,
                optimization=dict(space=space, sampler=sampler, pruner=pruner, startup_trials=startup, warmup_steps=warmup, metric=metric,
                    direction=direction, timeout_seconds=seconds, parallel_trials=1 if cloud else parallel, cpu_threads=threads,
                    critical_penalty=critical if metric == "penalized_f1" else 0, review_penalty=review if metric == "penalized_f1" else 0))
            st.session_state["opt_request"] = build_request(raw, runtime.settings)
        except AnalyticsError as error:
            st.error(str(error))
    spec = st.session_state.get("opt_request")
    if spec:
        st.subheader("Búsqueda validada")
        st.caption(f"Modelo · {FAMILY_NAMES['langflow' if spec.cloud else spec.models[0]]} · Datos · {spec.source} · "
                   f"Objetivo · {METRICS[spec.optimization.metric]} · Trials por fold · {spec.trials} · Semilla · {spec.seed}")
        render_table(*space_table(spec.optimization))
        st.download_button("Descargar configuración YAML", workspace.serialize(spec), file_name="soc-optuna-search.yaml", mime="application/yaml", key="opt_download_configuration")
        if st.button("Guardar configuración versionada", key="opt_save_button", disabled="opt_save" in st.session_state):
            start_task(runtime, "opt_save", workspace.save_configuration, spec, token)
        if st.button("Preparar partición y presupuesto", key="opt_prepare", disabled="opt_preview" in st.session_state):
            start_task(runtime, "opt_preview", manager.preview, spec, token)
        preview = st.session_state.get("opt_preview_result")
        if preview and preview["request_sha256"] == content_hash(spec.model_dump(mode="json")):
            render_table(*partition_table(preview["partition"]))
            approved = not spec.cloud
            if spec.cloud:
                quote = preview["budget"]
                render_table([{"Solicitudes máximas (n)": quote["planned_flow_calls"], "Intentos máximos (n)": quote["max_provider_attempts"],
                               "Techo reservado (USD)": quote["reserved_usd"], "Presupuesto solicitado (USD)": quote["approved_usd"]}],
                    TableGuide("Reserva de consumo experimental", "Solicitudes e intentos en conteos; techo monetario en USD.",
                        "El techo incluye respaldo y reintentos; la caché puede reducir las llamadas.",
                        f"El plan reserva hasta {quote['planned_flow_calls']} solicitudes y USD {quote['reserved_usd']}.",
                        "Los importes son límites conservadores configurados, sin costo facturado observado. El servidor exige aprobación y topes positivos."))
                approved = st.checkbox("Autorizo esta corrida con reportes protegidos y el presupuesto indicado", key="opt_approve_" + preview["plan_sha256"],
                    disabled=not bool(preview["budget"]["reserved_usd"] != "0" and runtime.settings.training.cloud.max_run_budget_usd))
            if st.button("Iniciar estudio", type="primary", disabled=not approved or "opt_start" in st.session_state, key="opt_start_button"):
                effective = spec.model_copy(update={"cloud": spec.cloud.model_copy(update={"approve": True})}) if spec.cloud else spec
                start_task(runtime, "opt_start", manager.start, effective, token, preview["plan_sha256"])

st.header("Seguimiento de estudios")
available = [row["run_id"] for row in catalog["runs"]]
latest = st.session_state.get("opt_latest_run")
if latest and latest not in available:
    available.insert(0, latest)
if not available:
    st.info("Aún no hay estudios avanzados registrados. El modo básico de Fase 2 conserva sus ejecuciones.")
    st.stop()
run_id = st.selectbox("Ejecución de Fase 2", available, index=available.index(latest) if latest in available else 0, key="opt_run")
if st.session_state.get("opt_authorize_scope") != run_id:
    st.session_state["opt_authorize_scope"] = run_id
    start_task(runtime, "opt_authorize", manager.authorize_monitor, run_id, token)
if "opt_authorize_result" not in st.session_state or "opt_authorize" in st.session_state:
    st.stop()


@st.fragment(run_every=runtime.settings.ui.poll_seconds)
def monitor() -> None:
    if require_session(runtime) is None:
        return
    try:
        data = manager.monitor(run_id)
    except AnalyticsError as error:
        st.error(str(error))
        return
    status = data["state"]["status"] if data["active"] or data["state"]["status"] != "ejecutando" else "interrumpido"
    st.write(f"Estado · {status} · {data['state']['seconds']:.2f} s acumulados · solicitudes cloud {data['state']['flow_calls']}")
    render_table(*live_table(data))
    render_table(*log_table(data["events"]))
    if st.session_state["opt_authorize_result"]:
        if data["active"] and st.button("Solicitar cancelación segura", key="opt_cancel"):
            start_task(runtime, "opt_control", manager.manage, run_id, "cancelar", token)
        if not data["active"] and data["mode"] == "academico" and status != "completo" and st.button("Reanudar estudio", key="opt_resume"):
            start_task(runtime, "opt_control", manager.manage, run_id, "reanudar", token)


monitor()
if st.button("Actualizar trials y gráficos", key="opt_inspect_button", disabled="opt_inspect" in st.session_state):
    start_task(runtime, "opt_inspect", workspace.inspect, run_id, token)
snapshot = st.session_state.get("opt_inspect_result")
if snapshot and snapshot["run_id"] == run_id and snapshot["studies"]:
    options = SearchOptions.model_validate(snapshot["request"]["optimization"])
    if snapshot["request"]["source"] == "sintetico":
        st.info("Prueba técnica sintética. Las métricas mostradas no acreditan calidad predictiva sobre reportes reales.")
    render_table(*space_table(options))
    names = [study["name"] for study in snapshot["studies"]]
    name = st.selectbox("Estudio interno de un fold externo", names, key="opt_study")
    study = next(study for study in snapshot["studies"] if study["name"] == name)
    render_table(*trials_table(study, options.metric))
    for function in (history_plot, importance_plot, parallel_plot, slice_plot, contour_plot, distribution_plot):
        chart(function(study, options, runtime.settings), function.__name__)
    data = manager.monitor(run_id)
    if data["result"]:
        family = next(iter(data["result"]["families"].values()))
        render_table(*winners_table(family))
        render_table(*stability_table(family, options))
        chart(stability_plot(family, options, runtime.settings, source=snapshot["request"]["source"]), "parameter_stability")
        if session.user.can("write") and st.button("Exportar configuración candidata", key="opt_candidate_button", disabled="opt_candidate" in st.session_state):
            start_task(runtime, "opt_candidate", workspace.candidate, run_id, token)
candidate = st.session_state.get("opt_candidate_result")
if candidate and candidate["source_phase2_run"] == run_id and session.user.can("write"):
    st.success("Configuración candidata versionada. Procede de Validación y requiere una decisión explícita de uso experimental.")
    st.caption("Versión · " + candidate["version"])
    st.download_button("Descargar candidata JSON", json.dumps(candidate, ensure_ascii=False, indent=2).encode(),
        file_name="soc-candidate-" + candidate["version"] + ".json", mime="application/json", key="opt_candidate_download")
    if st.button("Transferir candidata a Experimentación", key="opt_transfer"):
        st.session_state["exp_candidate_version"] = candidate["version"]
    st.page_link("pages/04_Experimentacion.py", label="Abrir Experimentación con la candidata")
