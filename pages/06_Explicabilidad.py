"""Authorized Streamlit views of observable text explanations."""
from collections.abc import Callable
from functools import partial
import json
from typing import Any

from matplotlib.figure import Figure
import streamlit as st

from src.reports.figures import export_png
from src.reports.presentation import TableGuide
from src.reports.xai_presentation import case_tables, contribution_figure, summary_tables, term_html, terms_figure
from src.training.local import FAMILY_NAMES
from src.utils.streamlit_runtime import get_runtime, poll_task, render_guide, render_table, require_session, start_task

runtime = get_runtime()
st.title("Explicabilidad textual del SOC")
session = require_session(runtime)
if session is None:
    st.stop()
workspace = runtime.explainability
if workspace is None:
    st.error("El entorno de explicabilidad no está disponible.")
    st.stop()
token = session.token


def launch(key: str, function: Callable, *args: Any) -> None:
    """Dispatch a bounded worker and refresh the private session view."""
    start_task(runtime, key, function, *args)
    st.rerun()


def plot(figure: Figure, guide: TableGuide, key: str) -> None:
    """Display the figure and its complete interpretation contract."""
    st.pyplot(figure, width="stretch", clear_figure=False)
    render_guide(guide)
    st.download_button("Descargar PNG a 600 DPI", partial(export_png, figure, runtime.settings.figures),
                       file_name=key + ".png", mime="image/png", key=key, on_click="ignore")


for key in ("xai_catalog", "xai_reports", "xai_execute", "xai_detail", "xai_original", "xai_annotation", "xai_alignment"):
    poll_task(runtime, key, "Consultando o analizando la evidencia autorizada…")
    if error := st.session_state.get(key + "_error"):
        st.error(error)
if executed := st.session_state.pop("xai_execute_result", None):
    st.session_state["xai_new_id"] = executed["run_id"]
    st.session_state.pop("xai_catalog_result", None)
if not any(key in st.session_state for key in ("xai_catalog", "xai_catalog_result", "xai_catalog_error")):
    launch("xai_catalog", workspace.catalog, token)
if st.button("Actualizar registros", key="xai_reload"):
    launch("xai_catalog", workspace.catalog, token)
catalog = st.session_state.get("xai_catalog_result")
if catalog is None:
    st.stop()

if session.user.can("review"):
    mode = st.radio("Origen de la explicación", ("local", "operacional"), horizontal=True, key="xai_mode",
                    format_func=lambda value: "Modelo académico" if value == "local" else "Reporte operativo")
    if mode == "local":
        options = {row["run_id"] + "|" + row["family"]: row for row in catalog["selections"]}
        if options:
            selected = st.selectbox("Modelo final de Fase 2", list(options), key="xai_selection",
                format_func=lambda key: FAMILY_NAMES[options[key]["family"]] + " · " + options[key]["source"] + " · " + options[key]["run_id"])
            partition = st.radio("Subconjunto experimental", ("validation", "development"), horizontal=True,
                                 format_func=lambda value: "Validación" if value == "validation" else "Desarrollo", key="xai_partition")
            if st.button("Analizar explicaciones", key="xai_run", type="primary", disabled="xai_execute" in st.session_state):
                row = options[selected]
                launch("xai_execute", workspace.local, row["run_id"], row["family"], partition, token)
        else:
            st.info("Falta un modelo local completo y verificable de Fase 2.")
    else:
        if st.button("Consultar reportes", key="xai_load_reports"):
            launch("xai_reports", workspace.operational_reports, token)
        choices = {row["id"]: row for row in st.session_state.get("xai_reports_result", [])}
        if choices:
            selected = st.selectbox("Reporte autorizado", list(choices), key="xai_report_id",
                                    format_func=lambda key: key + " · " + str(choices[key]["tipo"]))
            if st.button("Comprobar evidencia del reporte", key="xai_operational_run", disabled="xai_execute" in st.session_state):
                launch("xai_execute", workspace.operational, selected, token)

reports = {row["run_id"]: row for row in catalog["reports"]}
if not reports:
    st.info("Aún no hay informes de explicabilidad registrados.")
    st.stop()
if st.session_state.get("xai_new_id") in reports:
    st.session_state["xai_pick"] = st.session_state.pop("xai_new_id")
identifier = st.selectbox("Informe versionado", list(reports), key="xai_pick",
    format_func=lambda key: reports[key]["mode"] + " · " + reports[key]["source"] + " · " + key)
if st.session_state.get("xai_detail_scope") != identifier and "xai_detail" not in st.session_state:
    st.session_state["xai_detail_scope"] = identifier
    launch("xai_detail", workspace.detail if session.user.can("review") else workspace.summary, identifier, token)
report = st.session_state.get("xai_detail_result")
if not report or report["run_id"] != identifier:
    st.stop()
st.caption("Modalidad " + report["source"] + " · " + report["mode"])
for rows, guide in summary_tables(report):
    render_table(rows, guide)
plot(*terms_figure(report, runtime.settings.figures, runtime.settings.explainability.top_features), "xai_terms_png")
st.download_button("Descargar informe XAI", json.dumps(report, ensure_ascii=False, indent=2),
                   file_name="xai-" + identifier + ".json", mime="application/json", key="xai_download", on_click="ignore")
if not session.user.can("review"):
    st.stop()
cases = {row["key"]: row for row in report["cases"]}
chosen = st.selectbox("Caso para inspección", list(cases), key="xai_case",
                     format_func=lambda key: key[:16] + " · " + ("sin referencia" if cases[key]["correct"] is None else "acierto" if cases[key]["correct"] else "error"))
case = cases[chosen]
if st.session_state.get("xai_annotation_case") != (identifier, chosen):
    st.session_state["xai_annotation_case"] = identifier, chosen
    st.session_state["xai_human_spans"] = "[]"
    st.session_state["xai_annotation_confirmed"] = False
if "linear" in case:
    st.caption("Referencia del objetivo " + case["target"] + " · " + case["truth"])
    plot(*contribution_figure(case, runtime.settings.figures), "xai_contributions_png")
else:
    st.subheader("Justificación extractiva de la decisión guardada")
    st.write(case["evidence"]["summary"])
html, guide = term_html(case, runtime.settings.figures)
st.subheader(guide.title)
st.html(html)
render_guide(guide)
for rows, guide in case_tables(case):
    render_table(rows, guide)
if case.get("original_available"):
    if st.button("Ver texto original autorizado", key="xai_open_original", disabled="xai_original" in st.session_state):
        st.session_state["xai_original_scope"] = identifier, chosen
        launch("xai_original", workspace.original, chosen, token)
    if st.session_state.get("xai_original_scope") == (identifier, chosen) and (original := st.session_state.get("xai_original_result")):
        st.subheader("Texto original autorizado")
        st.text(original["title"])
        st.text(original["description"])
with st.expander("Comparar con fragmentos humanos"):
    st.caption("Los offsets empiezan en cero sobre la entrada protegida. Fin es exclusivo. La anotación se registra como retrospectiva con la explicación visible.")
    payload = st.text_area("Intervalos humanos en JSON", value=None, key="xai_human_spans")
    confirmed = st.checkbox("Confirmo que estos fragmentos provienen de mi revisión humana", key="xai_annotation_confirmed")
    if st.button("Registrar anotación", key="xai_annotate", disabled=not confirmed or "xai_annotation" in st.session_state):
        st.session_state["xai_annotation_scope"] = identifier, chosen
        launch("xai_annotation", workspace.annotate_json, identifier, chosen, payload, token)
    if st.session_state.get("xai_annotation_scope") == (identifier, chosen) and (annotation := st.session_state.get("xai_annotation_result")):
        st.success("Anotación humana registrada con ID " + annotation["run_id"])
    if st.button("Calcular coincidencia con referencia registrada", key="xai_overlap", disabled="xai_alignment" in st.session_state):
        st.session_state["xai_alignment_scope"] = identifier, chosen
        launch("xai_alignment", workspace.alignment, identifier, chosen, token)
    result = st.session_state.get("xai_alignment_result")
    if result and st.session_state.get("xai_alignment_scope") == (identifier, chosen):
        if result["applicable"]:
            render_table([result], TableGuide("Coincidencia con anotación humana registrada", "IoU, precisión y recall de caracteres no blancos, de 0 a 1.",
                "La comparación usa el mismo hash de entrada y los intervalos guardados por un revisor autenticado.",
                f"IoU observado de {result['iou']:.3f} con {result['human_characters']} caracteres humanos.",
                "La anotación retrospectiva puede estar influida por la explicación visible. La coincidencia carece de interpretación causal."))
        else:
            st.info("No aplicable. " + result["reason"])
