"""Phase-0 landing page; service results come from the operational API."""
import streamlit as st

from src.inference.services import health_rows
from src.reports.presentation import service_guide
from src.utils.reproducibility import software_versions
from src.utils.streamlit_runtime import get_runtime, poll_task, render_table, start_task

runtime = get_runtime()
st.title(runtime.settings.ui.title)
st.write("Entorno analítico del sistema de clasificación y gestión de reportes de seguridad.")
st.caption("Datos, experimentación y evaluación del SOC")
st.write("FastAPI conserva la clasificación en LangFlow con Groq y respaldo Gemini, la persistencia en PostgreSQL, las reglas de SLA y la automatización n8n.")
st.caption(f"Semilla analítica: {runtime.settings.seed}. La reproducibilidad numérica no garantiza respuestas idénticas de proveedores cloud.")

if st.button("Comprobar servicios", key="health_check", disabled="health_task" in st.session_state):
    start_task(runtime, "health_task", runtime.api.health)
poll_task(runtime, "health_task", "Consultando la salud del sistema sin ejecutar clasificaciones…")
snapshot = st.session_state.get("health_task_result")
error = st.session_state.get("health_task_error")
if error:
    st.warning(error)
rows = health_rows(snapshot, unavailable=bool(error))
render_table(rows, service_guide(rows))
if snapshot:
    st.caption("Modo observado: base=" + str(snapshot.get("base", "sin informar")) +
               "; clasificador=" + str(snapshot.get("clasificador", "sin informar")) +
               "; enrutador=" + str(snapshot.get("enrutador", "sin informar")))
    with st.expander("Diagnóstico de los proveedores"):
        st.write("El botón de salud reutiliza GET /health. Los diagnósticos cloud se ejecutan desde Operaciones → Salud en el sistema SOC y se consultan aquí cuando el backend los informa.")
        for name in ("groq", "gemini"):
            provider = snapshot.get("proveedores", {}).get(name, {})
            st.write(f"{name.capitalize()}: {provider.get('estado', 'sin comprobar')}; diagnóstico vigente: {'sí' if provider.get('vigente') else 'no'}.")

st.subheader("Accesos disponibles")
for page in runtime.settings.ui.pages[1:]:
    st.page_link(str(runtime.settings.path(page.path)), label=page.title)
st.link_button("Abrir el sistema operativo SOC", runtime.settings.api.base_url)
with st.expander("Módulos previstos en las siguientes fases"):
    st.write("Reportes científicos, inferencia y optimización.")
    st.caption("Su implementación se habilita únicamente al solicitar la fase correspondiente.")
with st.expander("Versiones del entorno"):
    for package, version in software_versions(runtime.settings.software).items():
        st.text(f"{package} · {version}")
