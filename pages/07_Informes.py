"""UI controls for authorized scientific and operational report snapshots."""
from __future__ import annotations

import streamlit as st
from pydantic import ValidationError

from src.reports.scientific import ReportRequest, SECTION_TITLES, TEMPLATES, display_cell
from src.utils.streamlit_runtime import get_runtime, poll_task, render_guide, require_session, start_task

runtime = get_runtime()
st.title("Reportes científicos y operacionales")
session = require_session(runtime, "report_export")
if session is None:
    st.stop()
workspace = runtime.reporting
if workspace is None:
    st.error("El módulo de informes no está disponible en este entorno.")
    st.stop()

if "informe_catalog_result" not in st.session_state:
    start_task(runtime, "informe_catalog", workspace.catalog, session.token)
if st.button("Actualizar evidencias", key="informe_refresh"):
    st.session_state.pop("informe_catalog_result", None)
    start_task(runtime, "informe_catalog", workspace.catalog, session.token)
poll_task(runtime, "informe_catalog", "Consultando versiones de las Fases 1 a 4…")
for task in ("informe_catalog", "informe_preview", "informe_figures", "informe_export"):
    if st.session_state.get(task + "_error"):
        st.error(st.session_state[task + "_error"])
catalog = st.session_state.get("informe_catalog_result")
if catalog is None:
    st.stop()

template = st.selectbox("Plantilla", tuple(TEMPLATES), format_func=lambda key: TEMPLATES[key].title, key="informe_template")
sections = st.multiselect("Secciones", tuple(SECTION_TITLES), default=TEMPLATES[template].sections,
                         format_func=SECTION_TITLES.get, key="informe_sections_" + template)
st.caption("El intervalo filtra la fecha de recepción operativa en hora de Lima. Las corridas conservan su cohorte original.")
with st.form("informe_selection"):
    left, right = st.columns(2)
    start = left.date_input("Desde", value=None, key="informe_since")
    end = right.date_input("Hasta", value=None, key="informe_until")
    manifest = st.selectbox("Manifiesto de datos", [None, *catalog["manifests"]],
                            format_func=lambda value: value or "Pendiente de selección", key="informe_manifest")
    st.caption(f"Máximo {runtime.settings.reporting.max_selections} versiones por categoría.")
    experiments = st.multiselect("Experimentos finales", [row["run_id"] for row in catalog["experiments"]], key="informe_experiments")
    evaluations = st.multiselect("Evaluaciones publicadas", [row["run_id"] for row in catalog["evaluations"]], key="informe_evaluations")
    explanations = st.multiselect("Resultados XAI", [row["run_id"] for row in catalog["explanations"]], key="informe_explanations")
    preview = st.form_submit_button("Previsualizar informe", key="informe_preview_button",
                                   disabled="informe_preview" in st.session_state or "informe_export" in st.session_state)
if preview:
    try:
        request = ReportRequest(template=template, sections=tuple(sections), desde=start, hasta=end, manifest=manifest,
                                experiments=tuple(experiments), evaluations=tuple(evaluations), explanations=tuple(explanations))
        st.session_state.pop("informe_export_result", None)
        st.session_state.pop("informe_preview_result", None)
        st.session_state.pop("informe_figures_result", None)
        start_task(runtime, "informe_preview", workspace.compose, request, session.token)
    except ValidationError:
        st.error("Selecciona al menos una sección y un intervalo de fechas válido.")
poll_task(runtime, "informe_preview", "Preparando una instantánea verificable del informe…")
snapshot = st.session_state.get("informe_preview_result")
if snapshot:
    if "informe_figures_result" not in st.session_state:
        start_task(runtime, "informe_figures", workspace.preview_figures, snapshot, session.token)
    poll_task(runtime, "informe_figures", "Preparando la previsualización de figuras…")
    figure_previews = iter(st.session_state.get("informe_figures_result", ()))
    st.header(snapshot.template.title)
    st.write(snapshot.template.context)
    st.caption(f"Versión {snapshot.run_id} · Generado UTC {snapshot.generated_at}")
    st.caption(snapshot.period)
    for section in snapshot.sections:
        st.header(section.title)
        for note in section.notes:
            st.write(note)
        for table in section.tables:
            st.subheader(table.guide.title)
            if table.rows:
                st.dataframe([{label: display_cell(value, table.style(index)) for index, (label, value) in enumerate(zip(table.columns, row))}
                              for row in table.rows], hide_index=True, width="stretch")
            render_guide(table.guide)
        for figure in section.figures:
            if preview_png := next(figure_previews, None):
                st.image(preview_png, caption=figure.guide.title)
            render_guide(figure.guide)
    st.header("Discusión, limitaciones y conclusiones")
    for note in snapshot.conclusions:
        st.write(note)
    with st.expander("Metadatos de reproducibilidad"):
        for label, value in snapshot.provenance:
            st.text(label + "\n" + value)
    if st.button("Generar PDF, Word y Excel", key="informe_generate",
                 disabled="informe_export" in st.session_state or "informe_export_result" in st.session_state):
        start_task(runtime, "informe_export", workspace.publish, snapshot, session.token)
poll_task(runtime, "informe_export", "Generando los tres formatos y las figuras de 600 DPI…")
exported = st.session_state.get("informe_export_result")
if exported:
    st.success("Informe versionado y auditoría de generación confirmada.")
    st.caption("SHA-256 del contenido · " + exported["content_sha256"])
    for index, output in enumerate(exported["outputs"]):
        st.download_button(output.filename, output.data, file_name=output.filename, mime=output.mime,
                           key=f"informe_download_{index}")
