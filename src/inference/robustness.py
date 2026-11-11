"""Applicability gates and observable uncertainty for production LLM inference."""
from __future__ import annotations

from hashlib import sha256
import re

from src.data.models import LABEL_NAMES
from src.reports.presentation import TableGuide
from src.utils.config import AnalyticsSettings


def lexical_coverage(text: str, settings: AnalyticsSettings) -> dict:
    """Expose a prespecified lexical warning without estimating distributional probability."""
    terms = [term for term in settings.data.vocabulary
             if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, flags=re.I)]
    return {"method": "cobertura_lexica_soc", "matched_terms": len(terms),
            "minimum_terms": settings.inference.lexical_min_terms,
            "potential_ood": len(terms) < settings.inference.lexical_min_terms,
            "reference": sha256("\n".join(settings.data.vocabulary).encode()).hexdigest(),
            "limitation": "Señal heurística de cobertura. La ausencia de términos puede señalar una entrada ajena al dominio "
                          "o un vocabulario distinto. Faltan una referencia de distribución y validación humana para estimar "
                          "tasas de error. La señal no modifica la clasificación ni las reglas de revisión."}


def matching_evaluations(snapshot: dict, reports: list[dict]) -> list[dict]:
    """Reuse eligible archived aggregates without invoking the test reader or fitting thresholds."""
    observed, matches = snapshot["input"], []
    configuration = snapshot["routing"]["configuration"]
    for report in reports:
        params = report.get("configuration", {})
        responses = report.get("operations", {}).get("responses", [])
        if (report.get("source") != "real" or report.get("reference") != "humana_independiente"
                or report.get("family") != "langflow" or not observed.get("prompt_sha256") or not observed.get("model")):
            continue
        if (params.get("prompt_sha256") != observed["prompt_sha256"] or params.get("threshold") != configuration["umbral"]
                or not any(item.get("provider") == observed.get("provider") and item.get("model") == observed["model"] for item in responses)):
            continue
        matches.append({"run_id": report["run_id"], "target": report["target"], "dataset_sha256": report["dataset_sha256"],
                        "configuration_sha256": report["configuration_sha256"], "reference": report["reference"],
                        "rows": report["rows"], "groups": report["groups"], "metrics": report["metrics"]["overall"],
                        "uncertainty": report["uncertainty"]})
    return matches


def statistical_applicability(snapshot: dict, archived: list[dict]) -> tuple[list[dict], TableGuide]:
    """Keep operational scores separate from validated probabilistic estimates."""
    matched = matching_evaluations(snapshot, archived)
    interval_count = sum(bool(value.get("ci95")) for report in matched for value in report["uncertainty"]["metrics"].values())
    rows = [
        {"Análisis": "Incertidumbre individual", "Estado": "Diagnóstico operacional",
         "Evidencia": "Confianza y umbral de revisión de la versión de reglas del reporte.",
         "Limitación": "El puntaje autodeclarado del LLM carece de evidencia de calibración. No produce un IC individual."},
        {"Análisis": "Calibración, Brier y predicción conforme", "Estado": "No aplicable",
         "Evidencia": "El contrato productivo contiene un puntaje operacional escalar.",
         "Limitación": "Faltan probabilidades válidas por clase y una referencia de calibración humana independiente, separada de Prueba."},
        {"Análisis": "IC 95 % de métricas agregadas", "Estado": "Disponible archivado" if interval_count else "Pendiente",
         "Evidencia": f"{interval_count} intervalos en {len(matched)} evaluaciones humanas con prompt, modelo y umbral compatibles.",
         "Limitación": "Se conserva el protocolo por grupos de Fase 3. Los intervalos describen la cohorte archivada."},
        {"Análisis": "Comparación con referencias y errores críticos", "Estado": "Disponible archivado" if matched else "Pendiente",
         "Evidencia": f"{len(matched)} evaluaciones reales elegibles.",
         "Limitación": "Los valores sintéticos, provisionales y predicciones del LLM están excluidos como verdad real."},
        {"Análisis": "Fuera de distribución", "Estado": "Heurística disponible",
         "Evidencia": "Cobertura del vocabulario SOC configurado sobre la entrada protegida.",
         "Limitación": "La señal léxica no constituye un detector de OOD validado ni una probabilidad de error."},
        {"Análisis": "Estabilidad del LLM", "Estado": "Observación agregada",
         "Evidencia": "Coincidencia de decisiones en repeticiones exactas con igual entrada protegida, modelo y prompt.",
         "Limitación": "Requiere repeticiones observadas. Faltan experimentos independientes para estabilidad ante paráfrasis."},
    ]
    guide = TableGuide("Aplicabilidad de los análisis de incertidumbre", "Estados y cantidades de evidencia, sin unidad física.",
        "Consulta qué datos sostienen cada análisis y su limitación antes de interpretar el resultado.",
        f"Se identificaron {len(matched)} evaluaciones humanas compatibles y {interval_count} intervalos publicados.",
        "Este módulo consume resultados archivados. El conjunto de Prueba conserva su uso único y sus versiones.")
    return rows, guide


def archived_metric_rows(snapshot: dict, reports: list[dict]) -> tuple[list[dict], TableGuide]:
    """Display matching Phase 3 metrics and intervals as historical cohort evidence."""
    rows = []
    for report in matching_evaluations(snapshot, reports):
        for metric, value in report["metrics"].items():
            interval = report["uncertainty"]["metrics"].get(metric, {})
            bounds = interval.get("ci95")
            rows.append({"Evaluación": report["run_id"], "Objetivo": LABEL_NAMES[report["target"]], "Métrica": metric,
                         "Estimación": value, "IC inferior": bounds[0] if bounds else None,
                         "IC superior": bounds[1] if bounds else None,
                         "Estado del IC": interval.get("reason") or report["uncertainty"].get("reason") or "Publicado"})
    return rows, TableGuide("Resultados agregados de referencia compatibles", "Métricas adimensionales e IC de la cohorte archivada.",
        "Cada fila conserva la evaluación original y su objetivo. Estos intervalos describen métricas agregadas.",
        f"Hay {len(rows)} estimaciones agregadas compatibles para mostrar.",
        "La coincidencia exige proveedor, modelo, prompt y umbral. Otras condiciones de la cohorte y las versiones conservan su evidencia en Fase 3.")
