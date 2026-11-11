"""Phase-0 source inventory and authorized read-only metadata previews."""
from functools import partial

import streamlit as st

from src.reports.presentation import catalog_guide, preview_guide
from src.utils.errors import AnalyticsError
from src.utils.streamlit_runtime import get_runtime, poll_task, render_table, require_session, start_task

runtime = get_runtime()
st.title("Fuentes existentes")
session = require_session(runtime)
if session is None:
    st.stop()

if "catalog_access_result" not in st.session_state and "catalog_access_error" not in st.session_state:
    start_task(runtime, "catalog_access", partial(runtime.api.audit_event, session.token, "consultar_catalogo"))
poll_task(runtime, "catalog_access", "Autorizando y auditando la consulta del catálogo…")
if st.session_state.get("catalog_access_error"):
    st.error(st.session_state["catalog_access_error"])
    if st.button("Reintentar acceso al catálogo"):
        st.session_state.pop("catalog_access_error", None)
        st.rerun()
    st.stop()
if "catalog_access_result" not in st.session_state:
    st.stop()

try:
    profiles = runtime.profiles()
except AnalyticsError as error:
    st.error(str(error))
    st.stop()
rows = [{"Fuente": item["name"], "Formato": item["format"], "Estado": item["status"],
         "Filas (registros)": item["rows"], "Columnas (cantidad)": len(item["columns"]) if item["columns"] else None,
         "Naturaleza": "Sintética" if item["synthetic"] else "Fuente original", "Acceso": item["location"]} for item in profiles]
render_table(rows, catalog_guide(profiles))

source_id = st.selectbox("Fuente registrada", list(runtime.catalog.sources),
                         format_func=lambda key: runtime.catalog.source(key).name, key="preview_source")
source = runtime.catalog.source(source_id)
st.write(source.provenance)
st.caption("Campos de etiqueta declarados: " + (", ".join(source.labels) or "ninguno en este archivo"))
st.caption(source.limitation)
if st.button("Verificar acceso y huella", key="preview_check", disabled="preview_task" in st.session_state):
    start_task(runtime, "preview_task", partial(runtime.catalog.preview, source_id, token=session.token))
poll_task(runtime, "preview_task", "Verificando la sesión, leyendo el original y calculando su huella…")
if st.session_state.get("preview_task_error"):
    st.error(st.session_state["preview_task_error"])
preview = st.session_state.get("preview_task_result")
if preview and preview["source_id"] == source_id:
    render_table(preview["rows"], preview_guide(source.name, preview, source.limitation))
    st.code(preview["sha256"], language=None)
    st.caption("SHA-256 · " + preview["hash_scope"])
    if session.user.can("write") and st.button("Registrar esta verificación de entorno", key="record_check", disabled="record_task" in st.session_state):
        start_task(runtime, "record_task", runtime.runs.record_source_validation, runtime.catalog, preview, session.token)
poll_task(runtime, "record_task", "Guardando configuración, métricas técnicas, versiones y huella…")
if st.session_state.get("record_task_error"):
    st.error(st.session_state["record_task_error"])
if st.session_state.get("record_task_result"):
    st.success("Verificación registrada: " + st.session_state["record_task_result"]["run_id"])
