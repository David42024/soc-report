"""Streamlit presentation for the authenticated data workspace."""
from __future__ import annotations

from collections import Counter
from functools import partial
import json
from typing import Callable

import streamlit as st

from src.data.manifest import holdout_status
from src.data.models import DataRecord, DataSource, LABEL_NAMES, PROVENANCE_NAMES, SEVERITIES, TARGETS, TYPES
from src.data.quality import quality_checks
from src.data.statistics import (
    NATURE_NAMES, NUMERIC_NAMES, RecordFilters, coverage, frequencies, label_fields, numeric_summary,
    numerical_values, page_slice, select_records, term_frequencies,
)
from src.data.workspace import DataView, DataWorkspace
from src.reports.data_presentation import (
    category_plot, coverage_comparison, coverage_plot, histogram, inventory_rows, length_comparison, missing_plot, record_rows, term_plot,
)
from src.reports.figures import export_png
from src.reports.presentation import TableGuide
from src.utils.streamlit_runtime import get_runtime, poll_task, render_guide, render_table, require_session, start_task

runtime = get_runtime()
st.title("Datos del SOC")
session = require_session(runtime)
if session is None:
    st.stop()

workspace = DataWorkspace(runtime.catalog)
config = runtime.settings.data
figures = runtime.settings.figures
token = session.token


def start(key: str, operation: Callable) -> None:
    start_task(runtime, key, operation)
    st.rerun()


def chart(figure_and_guide, key: str) -> None:
    figure, guide = figure_and_guide
    st.pyplot(figure, width="stretch", clear_figure=False)
    render_guide(guide)
    st.download_button("Descargar PNG a 600 DPI", data=partial(export_png, figure, figures),
                       file_name=key + ".png", mime="image/png", key="data_png_" + key, on_click="ignore")


def catalog_view(view: DataView) -> None:
    sources = view.inventory.sources
    rows = inventory_rows(sources)
    available = sum(source.sha256 is not None for source in sources)
    render_table(rows, TableGuide("Inventario de fuentes del SOC", "Filas y columnas se muestran como conteos.",
        "Compara formatos, revisiones y composición de las fuentes.",
        f"{available} de {len(sources)} fuentes tienen una huella y lectura observadas.",
        "Una representación original y un índice pueden contener el mismo incidente. FastAPI entrega hasta 100 reportes recientes."))
    objective = st.selectbox("Objetivo de la comparación", TARGETS, format_func=LABEL_NAMES.get, key="data_catalog_target")
    rows = coverage_comparison(sources, objective)
    total = sum(row["Total (registros)"] for row in rows)
    human = sum(row["Referencia humana (registros)"] for row in rows)
    render_table(rows, TableGuide("Etiquetas disponibles y referencias por fuente", "Cada porcentaje usa el total de la fuente.",
        "Lee por separado la cobertura observada y las etiquetas respaldadas por personas.",
        f"{human} de {total} filas del inventario aportan una referencia humana para el objetivo seleccionado.",
        "Los totales suman representaciones de incidentes. Una predicción, sugerencia o simulación conserva su propia procedencia."))
    if total:
        chart(coverage_plot(rows, objective, figures), "cobertura")
    series = [(source.name + (" · " + label if nature != "real" else ""), values)
              for source in sources for nature, label in NATURE_NAMES.items()
              if (values := numerical_values(tuple(record for record in source.records if record.nature == nature), "text_characters"))]
    if len(series) > 1:
        chart(length_comparison(series, figures), "longitud_por_fuente")
    with st.expander("Procedencia, esquema y huella"):
        by_id = {item.id: item for item in sources}
        source_id = st.selectbox("Detalle de la fuente", list(by_id), format_func=lambda key: by_id[key].name, key="data_catalog_detail")
        source = by_id[source_id]
        st.write(source.provenance)
        st.text(source.location)
        st.caption(source.limitation)
        if source.sha256:
            st.code(source.sha256, language=None)
            st.caption("SHA-256 · " + source.hash_scope)
        st.text(", ".join(source.columns))
        for note in source.notes:
            st.caption(note)


def optional_select(label: str, choices, key: str, format_value=str):
    return st.selectbox(label, [None, *choices], format_func=lambda value: "Todas" if value is None else format_value(value),
                        key=key)


def show_history(view: DataView, record: DataRecord) -> None:
    if st.button("Consultar historial", key="data_history_button", disabled="data_history" in st.session_state):
        st.session_state["data_history_key"] = record.key
        start("data_history", partial(workspace.history, view, record.key, token))
    if st.session_state.get("data_history_key") != record.key or "data_history_result" not in st.session_state:
        return
    history = st.session_state["data_history_result"]
    rows = [{"Versión": item.version, "Revisor": item.author, "Fecha (UTC)": item.created_at,
             "Campos": ", ".join(item.changes), "Huella": item.sha256, "Operación auditada": item.run_id}
            for item in history]
    render_table(rows, TableGuide("Historial de revisiones del registro", "Una fila por versión. Las fechas se expresan en UTC.",
        "Relaciona el identificador de la operación con la bitácora del SOC y consulta los campos guardados.",
        f"Se muestran {len(history)} revisiones. La versión aplicada al original consultado es {record.applied_version}.",
        f"La vista incluye hasta {config.max_history_entries} versiones recientes. Las correcciones guardan únicamente campos editados y protegidos."))
    if history:
        version = st.selectbox("Ver cambios de la versión", history, format_func=lambda item: str(item.version),
                               key="data_history_version_" + record.key)
        st.text(json.dumps(version.changes, ensure_ascii=False, indent=2))


def edit_record(view: DataView, record: DataRecord) -> None:
    if not session.user.can("review"):
        st.caption("Tu rol tiene acceso de lectura.")
        return
    def single(field: str):
        values = record.label(field).values
        return values[0] if len(values) == 1 else None
    defaults = {"titulo": record.title, "descripcion": record.description, "tipo": single("tipo"),
        "severidad": single("severidad"), "activo_afectado": single("activo_afectado"), "fuente": record.source_label,
        "origen": record.origin, "grupo": record.group, "observaciones": record.notes}
    with st.expander("Editar metadatos"):
        with st.form(f"data_edit_{record.key}_{record.version}"):
            title = st.text_input("Título", defaults["titulo"] or "", max_chars=500)
            description = st.text_area("Descripción protegida", defaults["descripcion"] or "",
                                       max_chars=config.max_text_characters, height=150)
            first, second, third = st.columns(3)
            with first:
                kind = st.selectbox("Tipo de incidente", (None, *TYPES), index=(None, *TYPES).index(defaults["tipo"]),
                                    format_func=lambda value: value or "Sin selección")
            with second:
                severity = st.selectbox("Severidad", (None, *SEVERITIES), index=(None, *SEVERITIES).index(defaults["severidad"]),
                                        format_func=lambda value: value or "Sin selección")
            with third:
                asset = st.text_input("Activo afectado", defaults["activo_afectado"] or "", max_chars=160)
            source = st.text_input("Fuente declarada", defaults["fuente"] or "", max_chars=160)
            origin = st.text_input("Origen declarado", defaults["origen"] or "", max_chars=160)
            group = st.text_input("Identificador de grupo", defaults["grupo"] or "", max_chars=100)
            state = st.selectbox("Estado de la revisión", (None, "pendiente", "revisado", "excluido"),
                                 format_func=lambda value: value or f"Sin cambios ({record.review_state})")
            reviewed = st.multiselect("Campos que confirmas al marcar Revisado", TARGETS, format_func=LABEL_NAMES.get)
            notes = st.text_area("Observaciones", defaults["observaciones"] or "", max_chars=1000)
            st.caption("La revisión conserva la fuente registrada y se atribuye a tu cuenta con la fecha del guardado.")
            confirmed = st.checkbox("Confirmo guardar esta revisión")
            submitted = st.form_submit_button("Guardar versión", type="primary", disabled="data_save" in st.session_state)
        if submitted:
            values = {"titulo": title, "descripcion": description, "tipo": kind, "severidad": severity,
                      "activo_afectado": asset, "fuente": source, "origen": origin, "grupo": group, "observaciones": notes}
            changes = {key: value or None for key, value in values.items() if (value or None) != defaults[key]}
            if state is not None or reviewed:
                changes.update(estado=state, campos_revisados=reviewed)
            if state == "excluido" and notes:
                changes["observaciones"] = notes
            start("data_save", partial(workspace.save_revision, view, record.key, changes, record.version, confirmed, token))


def detail(view: DataView, record: DataRecord) -> None:
    st.subheader("Detalle del registro")
    st.text(record.title or "Título ausente")
    if record.description:
        st.text(record.description)
    else:
        st.caption("Esta representación carece de una descripción protegida disponible.")
    group = view.groups.by_record[record.key]
    members = view.groups.members[group]
    render_table([{"Incidente": record.incident_id, "Fuente registrada": record.source_id, "Fuente declarada": record.source_label,
                   "Origen": record.origin, "Revisor": record.reviewer, "Fecha (UTC)": record.reviewed_at,
                   "Grupo calculado": group, "Clave del registro": record.key}], TableGuide(
        "Identidad y procedencia del registro", "La fecha de revisión se expresa en UTC cuando está registrada.",
        "Distingue la fuente registrada de la descripción editable de procedencia. La clave identifica esta representación.",
        f"El grupo contiene {len(members)} representaciones en el inventario. Se aplica la versión {record.applied_version}.",
        "Un vínculo por referencia o texto requiere revisión humana antes de asumir que dos registros describen el mismo evento."))
    labels = [{"Variable": LABEL_NAMES[field], "Valor": ", ".join(annotation.values),
               "Procedencia": PROVENANCE_NAMES[annotation.provenance], "Revisores (personas)": annotation.reviewers}
              for field, annotation in record.labels.items()]
    render_table(labels, TableGuide("Etiquetas del registro", "Revisores en personas asociadas a cada etiqueta.",
        "Consulta la procedencia por campo y el respaldo humano registrado.",
        f"{sum(label.human_reference for label in record.labels.values())} de {len(labels)} variables visibles tienen referencia humana.",
        "Una anotación analítica individual registra una confirmación. La prueba reservada exige el proceso de revisión independiente."))
    if record.predictions:
        original = [{"Variable": LABEL_NAMES[key], "Predicción guardada": ", ".join(value.values)}
                    for key, value in record.predictions.items()]
        render_table(original, TableGuide("Predicción operativa original", "Campos categóricos de la clasificación guardada.",
            "Contrasta el resultado original con la procedencia de las etiquetas que se muestran arriba.",
            f"Se observan {len(original)} campos de la predicción original.", "Los campos corresponden al reporte operativo consultado."))
    if record.notes:
        st.text(record.notes)
    edit_record(view, record)
    show_history(view, record)


def explorer(view: DataView, source: DataSource) -> tuple[DataRecord, ...]:
    first, second, third = st.columns(3)
    suffix = "_" + source.id
    with first:
        query = st.text_input("Buscar por texto protegido, incidente, clave o grupo", max_chars=200, key="data_search" + suffix)
        nature = optional_select("Naturaleza", sorted({r.nature for r in source.records}), "data_nature" + suffix, NATURE_NAMES.get)
    with second:
        state = optional_select("Estado de revisión", sorted({r.review_state for r in source.records}), "data_status" + suffix)
        partition = optional_select("Partición registrada", sorted({r.partition for r in source.records}), "data_partition" + suffix)
    with third:
        origins = sorted({label.provenance for r in source.records for label in r.labels.values()})
        provenance = optional_select("Procedencia de etiqueta", origins, "data_provenance" + suffix, PROVENANCE_NAMES.get)
    chosen = []
    fields = label_fields(source.records)
    if fields:
        columns = st.columns(min(3, len(fields)))
        for index, field in enumerate(fields):
            with columns[index % len(columns)]:
                options = sorted({value for record in source.records for value in record.label(field).values})
                value = optional_select(LABEL_NAMES[field], options, "data_filter_" + field + suffix)
                if value is not None:
                    chosen.append((field, value))
    return select_records(source.records, RecordFilters(search=query, nature=nature, review_state=state,
                           partition=partition, provenance=provenance, native_labels=tuple(chosen)), view.groups.by_record)


def explore_view(view: DataView, source: DataSource) -> None:
    records = explorer(view, source)
    first, second = st.columns(2)
    with first:
        size = st.selectbox("Registros por página", config.page_sizes, index=min(1, len(config.page_sizes) - 1), key="data_size")
    _, _, pages = page_slice(records, 1, size)
    with second:
        page = int(st.number_input("Página", min_value=1, max_value=pages, value=1, step=1, key="data_page_" + source.id))
    visible, current, pages = page_slice(records, page, size)
    render_table(record_rows(visible), TableGuide("Registros de la selección", f"Página {current} de {pages}. Una fila por registro.",
        "Combina los filtros. Elige una fila de esta página para consultar su detalle y sus revisiones.",
        f"{len(records)} de {len(source.records)} registros coinciden. Esta página muestra {len(visible)}.",
        "Los textos están protegidos. Las etiquetas pueden ser originales, sugeridas, revisadas, predichas o simuladas."))
    if visible:
        by_key = {record.key: record for record in visible}
        labels = {record.key: f"{record.incident_id} · {(record.title or '')[:70]} · {record.key[:8]}" for record in visible}
        key = st.selectbox("Registro para ver el detalle", (None, *by_key),
                           format_func=lambda item: labels.get(item, "Selecciona un registro"), key="data_detail_" + source.id)
        if key in by_key:
            detail(view, by_key[key])


def quality_view(view: DataView, source: DataSource | None) -> None:
    checks = quality_checks(view.inventory, view.groups, view.similarity, config, source.id if source else None)
    rows = [{"Criterio": item.name, "Estado": item.status, "Conteo": item.count, "Unidad": item.unit,
             "Regla de comprobación": item.criterion, "Acción recomendada": item.recommendation} for item in checks]
    states = Counter(item.status for item in checks)
    render_table(rows, TableGuide("Informe de calidad de los datos", "El conteo usa la unidad indicada en cada fila.",
        "Revisa las reglas de los criterios con Error o Advertencia y abre sus evidencias.",
        f"{states['Aprobado']} criterios aprobados, {states['Advertencia']} advertencias y {states['Error']} errores.",
        "Los vínculos y candidatos textuales describen las fuentes cargadas. La similitud requiere confirmación humana."))
    options = [item for item in checks if item.examples]
    if options:
        item = st.selectbox("Evidencia por criterio", options, format_func=lambda value: value.name, key="data_quality_evidence")
        render_table([{"Clave de registro o grupo": key} for key in item.examples], TableGuide(
            "Evidencia de la comprobación seleccionada", "Claves técnicas derivadas del inventario.",
            "Busca la clave del registro en el explorador o consulta la pertenencia del grupo en el manifiesto.",
            f"Se muestran {len(item.examples)} claves asociadas a la comprobación.",
            f"La muestra de evidencias está limitada a {config.max_examples} claves. El informe conserva el conteo completo."))
    pairs = view.similarity.examples
    if source:
        keys = {record.key for record in source.records}
        pairs = tuple(pair for pair in pairs if pair[1] in keys or pair[2] in keys)
    if pairs:
        render_table([{"Registro A": left, "Registro B": right, "Coseno (0–1)": score} for score, left, right in pairs],
                     TableGuide("Candidatos por similitud textual", "Puntaje coseno entre cero y uno.",
                         "Usa las claves para revisar el contexto de ambos registros.",
                         f"La similitud más alta mostrada es {pairs[0][0]:.3f} en {len(pairs)} parejas visibles.",
                         "Se muestran las parejas de mayor similitud. El puntaje depende del texto protegido y de los n-gramas."))


def statistics_view(view: DataView, source: DataSource) -> None:
    records = explorer(view, source)
    rows = coverage(records)
    render_table(rows, TableGuide("Cobertura de anotaciones en la selección", "Conteos en registros y porcentajes sobre la selección.",
        "Compara los campos ausentes, los valores disponibles y su respaldo humano.",
        f"{sum(row['Válidos (registros)'] > 0 for row in rows)} de {len(rows)} variables tienen al menos un valor en {len(records)} registros.",
        "Las referencias humanas se cuentan por campo. Las etiquetas de fuentes externas y simulaciones tienen su propia escala."))
    if records:
        chart(missing_plot(rows, figures), "faltantes")
    fields = {field: LABEL_NAMES[field] for field in label_fields(records)}
    fields.update({field: field.replace("_", " ").capitalize() for record in records for field in record.categories})
    if fields:
        field = st.selectbox("Variable categórica", list(fields), format_func=fields.get, key="data_categorical")
        rows = frequencies(records, field)
        render_table(rows, TableGuide(f"Frecuencias de {fields[field]}", "Conteo y porcentaje sobre registros válidos de cada estrato.",
            "Lee la naturaleza y procedencia para comparar etiquetas con el mismo significado.",
            f"Se observaron {len(rows)} combinaciones de categoría y procedencia.",
            "Las etiquetas múltiples cuentan una vez por categoría y pueden sumar más del 100 por ciento."))
        if rows:
            strata = sorted({(row["Naturaleza"], row["Procedencia"]) for row in rows})
            nature, origin = st.selectbox("Serie del gráfico", strata, format_func=lambda item: " · ".join(item), key="data_category_stratum")
            chart(category_plot([row for row in rows if (row["Naturaleza"], row["Procedencia"]) == (nature, origin)],
                                f"Distribución de {fields[field]}", figures, config.chart_categories), "categorias")
    measured = {field for record in records for field in record.numbers}
    if any(record.text_characters is not None for record in records):
        measured.add("text_characters")
    numeric = [key for key in NUMERIC_NAMES if key in measured]
    if numeric:
        field = st.selectbox("Variable numérica", numeric, format_func=lambda key: NUMERIC_NAMES[key][0], key="data_numeric")
        title, unit = NUMERIC_NAMES[field]
        samples = {}
        summaries = []
        for nature, label in NATURE_NAMES.items():
            subset = tuple(record for record in records if record.nature == nature)
            if subset:
                observations = numerical_values(subset, field)
                summaries.append({"Naturaleza": label, **numeric_summary(observations, len(subset), unit)})
                if observations:
                    samples[label] = observations
        total = sum(map(len, samples.values()))
        render_table(summaries, TableGuide(f"Resumen descriptivo de {title}", f"Media, mediana, dispersión y cuantiles en {unit}.",
            "Q1 y Q3 delimitan la mitad central. La desviación usa n−1 y requiere dos observaciones.",
            f"Se observaron {total} valores válidos de {len(records)} registros en {len(samples)} naturalezas.",
            "Se usa interpolación lineal para los cuartiles. Las fuentes y sus muestras describen poblaciones distintas."))
        choice = st.selectbox("Naturaleza del histograma", list(samples), key="data_numeric_stratum")
        chart(histogram(samples[choice], title + " · " + choice, unit, figures, config.histogram_bins), "histograma")
    if not fields and not numeric:
        st.info("La selección carece de variables válidas para graficar.")
    signature = (source.id, tuple(record.key for record in records), tuple(record.revision_sha256 for record in records))
    if st.button("Calcular frecuencias de términos protegidos", disabled="data_terms" in st.session_state, key="data_terms_button"):
        st.session_state["data_terms_scope"] = signature
        start("data_terms", partial(term_frequencies, records, config.vocabulary))
    if st.session_state.get("data_terms_scope") == signature and "data_terms_result" in st.session_state:
        rows, n = st.session_state["data_terms_result"]
        render_table(rows, TableGuide("Palabras y términos técnicos en descripciones protegidas",
            "Apariciones totales y porcentaje de documentos que contienen cada término.",
            "Un documento puede mencionar un término varias veces. El porcentaje cuenta documentos únicos por término.",
            f"{len(rows)} términos del vocabulario configurado aparecen en {n} documentos analizados.",
            "La lista técnica reduce la exposición de nombres y alias. Los términos compuestos pueden solaparse."))
        if rows:
            chart(term_plot(rows, n, figures, config.chart_categories), "terminos")
    st.caption("El análisis es descriptivo. Los muestreos y los incidentes compartidos limitan las comparaciones inferenciales.")


def manifests_view(view: DataView) -> None:
    status = holdout_status(view.inventory, view.groups)
    rows = [{"Objetivo": LABEL_NAMES[key], "Prueba disponible": "Sí" if ready else "Pendiente",
             "Casos revisados de la reserva": status["reviewed_cases"] if key == "tipo" else None}
            for key, ready in status["test_ready_by_target"].items()]
    render_table(rows, TableGuide("Estado de la prueba reservada por objetivo", "Casos en registros. La disponibilidad depende de evidencia de revisión.",
        "Consulta el resultado por objetivo antes de preparar experimentos.",
        f"{status['preparation_pending']} de {status['reserved_count']} candidatos reservados tienen decisiones pendientes. "
        f"El artefacto revisado figura como {status['artifact_status']}.", status["field_scope"]))
    for reason in status["reasons"]:
        st.warning(reason)
    if session.user.can("write") and st.button("Guardar manifiesto versionado", type="primary",
                                               disabled="data_manifest" in st.session_state, key="data_make_manifest"):
        start("data_manifest", partial(workspace.save_manifest, view, token))
    if saved := st.session_state.get("data_manifest_result"):
        st.success("Manifiesto guardado " + saved["run_id"])
        st.code(saved["content_sha256"], language=None)
        if st.button("Preparar descarga del manifiesto guardado", key="data_latest_manifest", disabled="data_download" in st.session_state):
            start("data_download", partial(workspace.read_manifest, saved["run_id"], token))
    if st.button("Consultar versiones guardadas", key="data_manifest_list", disabled="data_versions" in st.session_state):
        start("data_versions", partial(workspace.list_manifests, token))
    if "data_versions_result" in st.session_state:
        versions = st.session_state["data_versions_result"]
        render_table(versions, TableGuide("Manifiestos guardados", "Una fila por versión. Tamaño en bytes.",
            "Selecciona una versión para comprobar su huella y descargarla.",
            f"Hay {len(versions)} versiones en la vista.", "La fecha UTC forma parte del identificador de versión."))
        if versions:
            selected = st.selectbox("Versión para descargar", [row["Versión"] for row in versions], key="data_manifest_selection")
            if st.button("Preparar descarga de la versión", key="data_version_download", disabled="data_download" in st.session_state):
                start("data_download", partial(workspace.read_manifest, selected, token))
    if download := st.session_state.get("data_download_result"):
        version, payload = download
        st.download_button("Descargar manifiesto " + version, payload, file_name="manifest-" + version + ".json",
                           mime="application/json", key="data_manifest_download", on_click="ignore")


for operation, label in (
    ("data_view", "Leyendo fuentes y comprobando grupos y calidad…"),
    ("data_save", "Protegiendo la edición y registrando su autorización…"),
    ("data_history", "Consultando el historial…"),
    ("data_terms", "Contando términos técnicos en texto protegido…"),
    ("data_manifest", "Calculando la huella y guardando el manifiesto…"),
    ("data_versions", "Consultando versiones guardadas…"),
    ("data_download", "Comprobando la huella de la versión…"),
):
    poll_task(runtime, operation, label)
    if error := st.session_state.get(operation + "_error"):
        st.error(error)

view = st.session_state.get("data_view_result")
if revision := st.session_state.pop("data_save_result", None):
    st.session_state["data_last_saved"] = revision.version
    st.session_state.pop("data_history_result", None)
    st.session_state.pop("data_terms_result", None)
    if view:
        start("data_view", partial(workspace.refresh_revisions, view.original, token))
if saved_version := st.session_state.get("data_last_saved"):
    st.success(f"Revisión {saved_version} guardada y vinculada a la auditoría del SOC.")
if st.button("Actualizar inventario" if view else "Cargar inventario", type="primary",
             disabled="data_view" in st.session_state or "data_save" in st.session_state, key="data_load"):
    st.session_state.pop("data_history_result", None)
    st.session_state.pop("data_terms_result", None)
    start("data_view", partial(workspace.open, token))
if view is None:
    st.caption("Consulta las fuentes registradas con tu sesión del SOC.")
    st.stop()

section = st.radio("Vista", ("Explorar", "Catálogo", "Calidad", "Estadística", "Manifiestos"), horizontal=True, key="data_section")
if section == "Catálogo":
    catalog_view(view)
elif section == "Manifiestos":
    manifests_view(view)
elif section == "Calidad":
    sources = {item.id: item for item in view.inventory.sources}
    source_id = st.selectbox("Ámbito del informe", (None, *sources),
                             format_func=lambda key: sources[key].name if key in sources else "Inventario completo",
                             key="data_quality_source")
    quality_view(view, sources.get(source_id))
else:
    sources = {item.id: item for item in view.inventory.sources}
    identifiers = list(sources)
    index = identifiers.index("vcdb_pilot") if "vcdb_pilot" in sources else 0
    source_id = st.selectbox("Fuente", identifiers, index=index, format_func=lambda key: sources[key].name, key="data_source")
    source = sources[source_id]
    if source.status != "disponible":
        st.warning("La fuente seleccionada figura como " + source.status + ".")
    if section == "Explorar":
        explore_view(view, source)
    else:
        statistics_view(view, source)
