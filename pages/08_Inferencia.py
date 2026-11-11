"""Individual SOC inference controls, using the operational webhook and audit services."""
from __future__ import annotations

import json
from uuid import uuid4

import streamlit as st

from src.reports.figures import export_png
from src.reports.inference_presentation import (
    attempts_table, event_table, evidence_table, human_review_table, latency_figure, metrics_table, prediction_table, routing_table,
)
from src.reports.presentation import TableGuide
from src.utils.streamlit_runtime import get_runtime, poll_task, render_guide, render_table, require_session, start_task

runtime = get_runtime()
st.title("Inferencia individual de reportes SOC")
session = require_session(runtime, "review")
if session is None:
    st.stop()
workspace = runtime.inference
if workspace is None:
    st.error("El módulo de inferencia no está disponible.")
    st.stop()

mode = st.radio("Reporte", ("Nuevo reporte", "Reporte existente"), horizontal=True, key="inf_mode")
if mode == "Nuevo reporte":
    st.caption("La clasificación registra un reporte y activa su recorrido operativo. FastAPI aplica el contrato y la política de revisión.")
    with st.form("inf_form"):
        title = st.text_input("Título del reporte", key="inf_title")
        description = st.text_area("Descripción del incidente", key="inf_description", height=170)
        validate = st.form_submit_button("Validar y proteger entrada", key="inf_validate_button",
                                         disabled="inf_submit" in st.session_state or "inf_prepare" in st.session_state)
    if validate:
        st.session_state["inf_payload"] = (title, description)
        start_task(runtime, "inf_prepare", workspace.prepare, title, description, session.token)
    poll_task(runtime, "inf_prepare", "Validando el reporte y su protección de datos…")
    prepared = st.session_state.get("inf_prepare_result")
    if prepared and "inf_prepare" not in st.session_state:
        st.subheader("Entrada protegida que se enviará a la IA")
        st.text(prepared["protected_text"])
        st.caption("Protección aplicada · " + prepared["privacy"]["status"])
        if prepared["potential_injection"]:
            st.warning("Se detectaron indicios de inyección. La política del backend deriva estos casos a revisión humana.")
        if st.session_state.get("inf_request_hash") != prepared["input_sha256"]:
            st.session_state["inf_request_id"] = str(uuid4())
            st.session_state["inf_request_hash"] = prepared["input_sha256"]
        identifier = st.session_state["inf_request_id"]
        st.caption("Identificador idempotente del envío")
        st.code(identifier)
        if st.button("Clasificar y registrar reporte", key="inf_create", disabled="inf_submit" in st.session_state):
            original_title, original_description = st.session_state["inf_payload"]
            start_task(runtime, "inf_submit", workspace.submit, original_title, original_description, identifier, session.token)
        if st.button("Consultar estado del envío", key="inf_reconcile", disabled="inf_observe" in st.session_state):
            start_task(runtime, "inf_observe", workspace.observe, identifier, session.token)
else:
    if "inf_catalog_result" not in st.session_state:
        start_task(runtime, "inf_catalog", workspace.catalog, session.token)
    if st.button("Actualizar reportes", key="inf_refresh"):
        st.session_state.pop("inf_catalog_result", None)
        start_task(runtime, "inf_catalog", workspace.catalog, session.token)
    poll_task(runtime, "inf_catalog", "Consultando los reportes existentes…")
    records = st.session_state.get("inf_catalog_result", [])
    if records:
        options = {row["id"]: row for row in records}
        identifier = st.selectbox("Reporte registrado", tuple(options),
            format_func=lambda key: f"{key} · {options[key]['tipo']} · {options[key]['severidad']}", key="inf_existing")
        st.caption("La consulta muestra la predicción guardada y sus correcciones humanas.")
        if st.button("Consultar inferencia guardada", key="inf_existing_read", disabled="inf_observe" in st.session_state):
            start_task(runtime, "inf_observe", workspace.observe, identifier, session.token)
    elif "inf_catalog_result" in st.session_state:
        st.info("No hay reportes existentes para mostrar.")

poll_task(runtime, "inf_submit", "Clasificando mediante FastAPI y LangFlow y verificando asignación y notificación…")
poll_task(runtime, "inf_observe", "Recuperando la entrada protegida y la clasificación guardada…")
for task in ("inf_prepare", "inf_submit", "inf_catalog", "inf_observe", "inf_metrics"):
    if st.session_state.get(task + "_error"):
        st.error(st.session_state[task + "_error"])

if "inf_observe_result" in st.session_state:
    st.session_state["inf_result"] = st.session_state.pop("inf_observe_result")
if "inf_submit_result" in st.session_state:
    st.session_state["inf_result"] = st.session_state.pop("inf_submit_result")
snapshot = st.session_state.get("inf_result")
if snapshot:
    report = snapshot["report"]
    if report["system"]["classifier"] != "langflow":
        st.warning("Esta observación pertenece al modo de demostración.")
    render_table(*prediction_table(snapshot))
    if report["human_review"]:
        render_table(*human_review_table(snapshot))
    st.subheader("Entrada protegida asociada al resultado")
    st.text(report["input"]["text"])
    st.subheader("Justificación textual verificable")
    st.write(snapshot["evidence"]["summary"])
    render_table(*evidence_table(snapshot))
    render_table(*routing_table(snapshot))
    render_table(*attempts_table(snapshot))
    render_table(*event_table(snapshot))
    lexical = snapshot["lexical"]
    if lexical["potential_ood"]:
        st.warning("La entrada tiene cobertura léxica SOC baja. Señal heurística de posible entrada fuera de distribución.")
    st.caption(f"Términos configurados observados · {lexical['matched_terms']}")
    st.caption(lexical["limitation"])
    render_table(snapshot["statistical_rows"], TableGuide(**snapshot["statistical_guide"]))
    render_table(snapshot["reference_rows"], TableGuide(**snapshot["reference_guide"]))
    st.caption("Versión de observación · " + snapshot["run_id"])
    st.download_button("Descargar evidencia protegida", json.dumps(snapshot, ensure_ascii=False, indent=2).encode(),
                       file_name="soc-inferencia-" + snapshot["run_id"] + ".json", mime="application/json", key="inf_download")
    st.page_link("pages/06_Explicabilidad.py", label="Revisar explicabilidad y originales autorizados")

st.header("Desempeño y robustez observados")
if st.button("Consultar indicadores de inferencia", key="inf_metrics_button", disabled="inf_metrics" in st.session_state):
    start_task(runtime, "inf_metrics", workspace.metrics, session.token)
poll_task(runtime, "inf_metrics", "Consultando telemetría agregada del backend…")
metrics = st.session_state.get("inf_metrics_result")
if metrics:
    render_table(*metrics_table(metrics))
    st.caption(f"Conmutaciones técnicas observadas · {metrics['technical_fallbacks']} · "
               f"Salidas protectoras · {metrics['safe_origin_fallbacks']} · "
               f"Reportes sin traza de intentos · {metrics['without_trace']}")
    st.caption(f"Errores de formato · {metrics['format_errors']} · Taxonomía · {metrics['taxonomy_errors']} · "
               f"Derivaciones a revisión · {metrics['review']}")
    repeat = metrics["repeatability"]
    if repeat["modal_agreement"] is None:
        st.info("La concordancia de predicciones repetidas está pendiente por ausencia de grupos con repeticiones comparables.")
    else:
        st.caption(f"Concordancia modal observada · {repeat['modal_agreement']:.2%} en {repeat['observations']} observaciones de {repeat['groups']} grupos.")
    if metrics["critical_reference"]:
        st.caption(f"Errores de severidad inferior · {metrics['critical_lower']} de {metrics['critical_classified']} críticos clasificados con revisión operativa. "
                   f"Salidas protectoras entre los críticos revisados · {metrics['critical_protective']}.")
    else:
        st.info("Los errores críticos están pendientes de referencias humanas de severidad crítica.")
    figure, guide = latency_figure(metrics, runtime.settings.figures, runtime.settings.reporting)
    if figure:
        st.pyplot(figure)
        render_guide(guide)
        st.download_button("Descargar figura PNG de 600 DPI", export_png(figure, runtime.settings.figures),
                           file_name="latencias-inferencia.png", mime="image/png", key="inf_figure_download")
