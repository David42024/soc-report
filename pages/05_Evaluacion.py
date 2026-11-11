"""Streamlit interface for the sealed statistical evaluation."""
from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from functools import partial
import json
from typing import Any

from matplotlib.figure import Figure
import streamlit as st

from src.data.models import LABEL_NAMES
from src.reports.evaluation_presentation import (
    class_table, comparison_tables, confusion_figure, critical_table, curve_figure, interval, operation_table,
    overall_table, readiness_table,
)
from src.reports.figures import export_png
from src.reports.presentation import TableGuide
from src.training.local import FAMILY_NAMES
from src.utils.streamlit_runtime import get_runtime, poll_task, render_guide, render_table, require_session, start_task

runtime = get_runtime()
st.title("Evaluación estadística del SOC")
session = require_session(runtime)
if session is None:
    st.stop()
workspace = runtime.evaluations
if workspace is None:
    st.error("El entorno de evaluación no está disponible.")
    st.stop()
token = session.token


def launch(key: str, function: Callable, *args: Any) -> None:
    start_task(runtime, key, function, *args)
    st.rerun()


def plot(figure: Figure, guide: TableGuide, key: str) -> None:
    st.pyplot(figure, width="stretch", clear_figure=False)
    render_guide(guide)
    st.download_button("Descargar PNG a 600 DPI", partial(export_png, figure, runtime.settings.figures),
                       file_name=key + ".png", mime="image/png", key="eval_png_" + key, on_click="ignore")


def download(report: dict, name: str, key: str) -> None:
    st.download_button("Descargar " + name, json.dumps(report, ensure_ascii=False, indent=2),
                       file_name=name + "-" + report["run_id"] + ".json", mime="application/json",
                       key=key, on_click="ignore")


def status_table(records: list[dict]) -> None:
    rows = [{"Evaluación": row["run_id"], "Modelo": FAMILY_NAMES[row["family"]], "Objetivo": LABEL_NAMES[row["target"]],
             "Fase 2": row["phase2_run_id"], "Estado": row["status"], "Creada (UTC)": row["created_at"]} for row in records]
    complete = sum(row["Estado"] == "completa" for row in rows)
    render_table(rows, TableGuide("Registro versionado de evaluaciones", "Una fila por configuración y cohorte. Fechas UTC.",
        "Abre una corrida completa para consultar métricas. Las reservas y fallos conservan el historial de uso.",
        f"Hay {complete} evaluaciones completas de {len(rows)} registradas para la modalidad.",
        "Una reserva impide repetir inferencias sobre el mismo conjunto y configuración. Una corrida técnica tiene naturaleza sintética."))


def evaluation_form(selections: list[dict], source: str, readiness: dict) -> None:
    if source == "real":
        if not readiness["seal_present"]:
            st.warning("Evaluación real pendiente. Falta el archivo de Prueba con revisión humana independiente.")
            return
        selections = [row for row in selections if readiness["ready_by_target"][row["target"]]]
    if not selections:
        st.info("Se requiere una configuración final verificable de Fase 2 para esta modalidad.")
        return
    options = {row["run_id"] + "|" + row["family"]: row for row in selections}
    chosen = st.selectbox("Configuración final de Fase 2", list(options),
        format_func=lambda key: f"{FAMILY_NAMES[options[key]['family']]} · {LABEL_NAMES[options[key]['target']]} · {options[key]['run_id']}",
        key="eval_selection_" + source)
    selected = options[chosen]
    if st.button("Verificar configuración y sello", key="eval_prepare", disabled="eval_preview" in st.session_state):
        launch("eval_preview", workspace.preview, selected["run_id"], selected["family"], token)
    preview = st.session_state.get("eval_preview_result")
    if not preview or (preview["phase2_run_id"], preview["family"]) != (selected["run_id"], selected["family"]):
        return
    st.caption(f"Prueba sellada · {preview['rows']} casos · SHA-256 {preview['seal']}")
    budget, approved = "0", False
    if preview["quote"] is not None:
        quote = preview["quote"]
        policy = runtime.settings.training.cloud
        st.write(f"Techo para {quote['planned_flow_calls']} solicitudes a LangFlow y {quote['max_provider_attempts']} intentos de proveedor.")
        st.caption(f"Estimación máxima declarada de USD {quote['reserved_usd']}. La salida no incluye facturación.")
        if Decimal(quote["reserved_usd"]) <= 0 or Decimal(quote["reserved_usd"]) > policy.max_run_budget_usd:
            st.warning("La evaluación cloud requiere un techo monetario configurado y suficiente.")
            return
        budget = str(st.number_input("Presupuesto autorizado (USD)", min_value=0.0,
            max_value=float(policy.max_run_budget_usd), value=0.0, step=.01, key="eval_budget"))
        approved = st.checkbox("Autorizo la inferencia de los casos protegidos dentro del presupuesto indicado",
                              key="eval_approved_" + preview["seal"] + chosen)
        if not approved or Decimal(budget) < Decimal(quote["reserved_usd"]):
            return
    confirmed = st.checkbox("Confirmo evaluar esta configuración final en el conjunto sellado",
                            key="eval_confirm_" + preview["seal"] + chosen)
    if st.button("Evaluar versión sellada", key="eval_run", type="primary",
                 disabled=not confirmed or "eval_execute" in st.session_state):
        launch("eval_execute", partial(workspace.evaluate, budget=budget, approved=approved),
               selected["run_id"], selected["family"], token)


def results_view(report: dict) -> None:
    synthetic = report["source"] == "sintetico"
    if synthetic:
        st.info("Resultados de prueba técnica sintética. Alcance de verificación del evaluador.")
    render_table(*overall_table(report))
    render_table(*class_table(report))
    if report["metrics"]["critical"] is not None:
        render_table(*critical_table(report))
    strata = report["metrics"]["strata"]
    if strata:
        rows = [{"Estrato humano": LABEL_NAMES[row["field"]], "Etiqueta": row["label"], "Casos (n)": row["n"],
                 "Exactitud": row["accuracy"], "F1 macro": row["f1_macro"]} for row in strata]
        render_table(rows, TableGuide("Métricas por estrato revisado", "Exactitud y F1 de 0 a 1.",
            "Compara solo estratos con referencia independiente para ambos campos.",
            f"Hay {len(rows)} estratos con anotaciones de referencia cruzadas.",
            "Se muestra F1 macro cuando el estrato aporta más de una clase. Son estimaciones descriptivas."))
    normalized = st.toggle("Normalizar por clase de referencia", value=False, key="eval_matrix_normalized")
    plot(*confusion_figure(report["metrics"]["matrix"], runtime.settings.figures, normalized, synthetic), "confusion")
    curves = report["curves"]
    if curves["reason"]:
        st.info("ROC y Precisión–Recall · No aplicable. " + curves["reason"])
    else:
        available = [label for label, item in curves["classes"].items() if "roc_auc" in item]
        rows = [{"Clase": label, "AUC ROC": item.get("roc_auc"), "AUC PR trapezoidal": item.get("pr_auc"),
                 "AP": item.get("average_precision"), "Positivos (n)": item.get("positive"),
                 "IC 95 % AUC ROC": interval(report["uncertainty"]["metrics"].get(label + ".roc_auc", {}).get("ci95")),
                 "Motivo": item.get("reason")} for label, item in curves["classes"].items()]
        render_table(rows, TableGuide("Curvas y áreas por clase", "Áreas y AP de 0 a 1. Soporte en casos.",
            "Cada fila compara una clase contra todas las demás. AP y área PR trapezoidal usan métodos de integración distintos.",
            f"{len(available)} de {len(rows)} clases aportan scores continuos válidos.",
            "Los márgenes de SVM ordenan casos. Los valores probabilísticos de regresión logística se usan aquí como scores."))
        if available:
            label = st.selectbox("Clase para curvas", available, key="eval_curve_class")
            for pr, name in ((False, "roc"), (True, "precision-recall")):
                plot(*curve_figure(label, curves["classes"][label], runtime.settings.figures, pr=pr, synthetic=synthetic), name)
    if report["family"] == "langflow":
        render_table(*operation_table(report))
        operations = report["operations"]
        responses = [{"Proveedor": row["provider"], "Modelo": row["model"], "Respuestas (n)": row["n"]}
                     for row in operations["responses"]]
        render_table(responses, TableGuide("Proveedores observados en las respuestas",
            "Frecuencias en solicitudes. El modelo corresponde al proveedor observado y al grafo verificado.",
            "Gemini observado cuenta una conmutación del flujo. Los motivos de revisión se muestran por separado.",
            f"Se observaron {operations['gemini_observed']} respuestas de Gemini y {operations['technical_failures']} fallos técnicos terminales.",
            "Los fallos internos sin telemetría y el costo parcial se mantienen como datos ausentes."))
        st.write(f"Errores de formato {operations['format_errors']} · errores de taxonomía {operations['taxonomy_errors']} · "
                 f"respuestas sin proveedor identificado {operations.get('responses_without_provider', 0)}")
        with st.expander("Derivaciones y consumo"):
            st.json({key: operations[key] for key in ("review", "usage_observed", "input_tokens_observed",
                    "output_tokens_observed", "billed_observed", "cost_usd", "budget")}, expanded=False)


def detail_actions(run_id: str) -> None:
    if not session.user.can("review"):
        return
    with st.expander("Predicciones y registros mal clasificados"):
        if st.button("Consultar errores protegidos", key="eval_errors", disabled="eval_errors_task" in st.session_state):
            st.session_state["eval_errors_scope"] = run_id
            launch("eval_errors_task", workspace.errors, run_id, token)
        if st.session_state.get("eval_errors_scope") == run_id and "eval_errors_task_result" in st.session_state:
            errors = st.session_state["eval_errors_task_result"]
            rows = [{"Caso protegido": row["key"], "Referencia": row["truth"], "Predicción": row["predicted"],
                     "Proveedor": row["provider"], "Motivo de revisión": row["review_reason"]} for row in errors]
            render_table(rows, TableGuide("Registros mal clasificados o derivados", "Una fila por caso, con ID protegido.",
                "Selecciona un caso para consultar su fragmento enmascarado. La consulta queda auditada.",
                f"Se registraron {len(rows)} errores o derivaciones en la corrida.",
                "Los fragmentos se limitan a lo necesario para inspección y se conservan fuera del informe exportado."))
            if errors:
                case = st.selectbox("Caso protegido", [row["key"] for row in errors], key="eval_case_key")
                if st.button("Abrir fragmento protegido", key="eval_excerpt", disabled="eval_excerpt_task" in st.session_state):
                    st.session_state["eval_excerpt_scope"] = run_id, case
                    launch("eval_excerpt_task", workspace.inspect_error, run_id, case, token)
                if st.session_state.get("eval_excerpt_scope") == (run_id, case) and (value := st.session_state.get("eval_excerpt_task_result")):
                    st.text(value["title"])
                    st.text(value["description"])
        if st.button("Preparar descarga del informe completo", key="eval_export"):
            launch("eval_export_task", workspace.report, run_id, token)
        exported = st.session_state.get("eval_export_task_result")
        if exported and exported["run_id"] == run_id:
            download(exported, "evaluacion", "eval_download")


for key, message in (
    ("eval_catalog", "Consultando corridas y sellos registrados…"),
    ("eval_preview", "Verificando artefactos de Fase 2…"),
    ("eval_execute", "Verificando el sello y calculando métricas en segundo plano…"),
    ("eval_result", "Cargando el informe versionado…"),
    ("eval_compare", "Calculando diferencias pareadas por grupos…"),
    ("eval_errors_task", "Consultando los errores autorizados…"),
    ("eval_excerpt_task", "Recuperando el fragmento enmascarado…"),
    ("eval_export_task", "Preparando el informe de evaluación…"),
):
    poll_task(runtime, key, message)
    if error := st.session_state.get(key + "_error"):
        st.error(error)

if completed := st.session_state.pop("eval_execute_result", None):
    st.session_state["eval_new_id"] = completed["run_id"]
    st.session_state.pop("eval_catalog_result", None)
if not any(name in st.session_state for name in ("eval_catalog", "eval_catalog_result", "eval_catalog_error")):
    launch("eval_catalog", workspace.catalog, token)
if st.button("Actualizar disponibilidad", key="eval_reload", disabled="eval_catalog" in st.session_state):
    launch("eval_catalog", workspace.catalog, token)
catalog = st.session_state.get("eval_catalog_result")
if catalog is None:
    st.stop()

if "eval_source" not in st.session_state:
    available_sources = {row["source"] for row in catalog["evaluations"]}
    st.session_state["eval_source"] = "sintetico" if "sintetico" in available_sources and "real" not in available_sources else "real"
source = st.radio("Cohorte", ("real", "sintetico"), horizontal=True, key="eval_source",
                  format_func=lambda value: "Prueba real sellada" if value == "real" else "Prueba técnica sintética")
if source == "real":
    render_table(*readiness_table(catalog["readiness"]))
else:
    st.caption("Resultados de la prueba técnica sintética. Las referencias humanas reales conservan su estado independiente.")
if session.user.can("write"):
    evaluation_form([row for row in catalog["selections"] if row["source"] == source], source, catalog["readiness"])
evaluations = [row for row in catalog["evaluations"] if row["source"] == source]
status_table(evaluations)
choices = {row["run_id"]: row for row in evaluations if row["status"] == "completa"}
if choices:
    default = st.session_state.get("eval_new_id")
    identifiers = list(choices)
    if default in choices:
        st.session_state["eval_pick_" + source] = st.session_state.pop("eval_new_id")
    run_id = st.selectbox("Resultado publicado", identifiers, key="eval_pick_" + source,
                         format_func=lambda key: f"{FAMILY_NAMES[choices[key]['family']]} · {key}")
    if st.session_state.get("eval_result_scope") != run_id and "eval_result" not in st.session_state:
        st.session_state["eval_result_scope"] = run_id
        launch("eval_result", workspace.result, run_id, token)
    report = st.session_state.get("eval_result_result")
    if report and report["run_id"] == run_id:
        results_view(report)
        if st.button("Comparar configuraciones de esta cohorte", key="eval_compare_button",
                     disabled="eval_compare" in st.session_state):
            launch("eval_compare", workspace.comparison, run_id, token)
        comparison = st.session_state.get("eval_compare_result")
        if comparison and comparison["dataset_sha256"] == report["dataset_sha256"] and comparison["target"] == report["target"]:
            for rows, guide in comparison_tables(comparison):
                render_table(rows, guide)
            download(comparison, "comparacion", "eval_compare_download")
        detail_actions(run_id)
