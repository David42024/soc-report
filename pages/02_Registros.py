"""Phase-0 environment evidence, without training or evaluation controls."""
import json

import streamlit as st

from src.reports.presentation import runs_guide
from src.utils.streamlit_runtime import get_runtime, render_table, require_session, start_task, poll_task

runtime = get_runtime()
st.title("Registros de validación")
session = require_session(runtime)
if session is None:
    st.stop()
if st.button("Actualizar registros", disabled="records_task" in st.session_state):
    st.session_state.pop("records_task_result", None)
    st.session_state.pop("records_task_error", None)
if "records_task_result" not in st.session_state and "records_task_error" not in st.session_state:
    start_task(runtime, "records_task", runtime.runs.authorized_records, runtime.api, session.token)
poll_task(runtime, "records_task", "Consultando y auditando el acceso a los informes…")
if st.session_state.get("records_task_error"):
    st.error(st.session_state["records_task_error"])
    st.stop()
if "records_task_result" not in st.session_state:
    st.stop()
records = st.session_state["records_task_result"]
rows = [{"Registro": item["run_id"], "Fecha (UTC)": item["created_at"], "Fuente": item["dataset"]["source_id"],
         "Semilla": item["seed"], "Tipo": "Validación de entorno", "Auditoría": item["audit_state"]} for item in records]
render_table(rows, runs_guide(records))
if records:
    record_id = st.selectbox("Registro de validación", [item["run_id"] for item in records])
    selected = next(item for item in records if item["run_id"] == record_id)
    st.download_button("Descargar metadatos de la verificación", json.dumps(selected, ensure_ascii=False, indent=2),
                       file_name=record_id + ".json", mime="application/json")
    st.caption("El registro contiene metadatos técnicos y huellas; los textos originales permanecen en sus fuentes.")
