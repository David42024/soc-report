"""Project verified Phase 1–4 aggregates into scientific reporting sections."""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import get_args

from backend.classifier import Severidad, Tipo
from src.data.models import LABEL_NAMES
from src.reports.evaluation_presentation import NAMES
from src.reports.presentation import TableGuide
from src.reports.scientific import ReportFigure, ReportSection, ReportTable
from src.reports.training_presentation import external_table, partition_table, summary_table
from src.training.local import FAMILY_NAMES
from src.training.metrics import REVIEW
from src.training.settings import LocalParameters

SYNTHETIC_LIMIT = "La referencia es sintética. Las métricas describen exclusivamente una comprobación técnica."
REAL_LIMIT = "Las métricas se restringen a la cohorte y referencia humanas archivadas."
SOURCE_LIMIT = "Las fuentes contienen representaciones solapadas. Sus filas se cuentan por archivo y versión."
METRIC_LIMIT = "Los intervalos y contrastes conservan los requisitos de soporte, independencia y variación de la Fase 3."


def pending(title: str, reason: str) -> ReportSection:
    """Retain an absent section with an explicit evidence status."""
    return ReportSection(title, ("Pendiente. " + reason,))


def _guide(title: str, units: str, read: str, finding: str, limits: str) -> TableGuide:
    return TableGuide(title, units, read, finding, limits)


def from_rows(rows: list[dict], guide: TableGuide, title: str | None = None) -> ReportTable:
    """Reuse existing presentation rules while preserving original numeric types."""
    columns = tuple(rows[0]) if rows else ()
    return ReportTable(replace(guide, title=title) if title else guide, columns,
                       tuple(tuple(row[key] for key in columns) for row in rows))


def _label(value: str, target: str, classes: list[str]) -> str:
    if value == REVIEW:
        return "Revisión humana"
    if target == "activo_afectado":
        return f"Categoría {classes.index(value) + 1}" if value in classes else "Categoría fuera de referencia"
    allowed = get_args(Severidad) if target == "severidad" else get_args(Tipo)
    return value.replace("_", " ") if value in allowed else "Fuera de taxonomía"


def data_section(envelope: dict | None, compact: bool = False) -> ReportSection:
    """Use a verified inventory manifest without accessing source text or test rows."""
    if envelope is None:
        return pending("Datos y calidad", "Selecciona un manifiesto de la Fase 1.")
    content = envelope["content"]
    sources = content["sources"]
    coverage = content["eligibility"]["candidates_by_target"]
    ready = content["holdout"]["test_ready_by_target"]
    status = [(LABEL_NAMES[target], len(coverage.get(target, [])), "Disponible" if available else "Pendiente")
              for target, available in ready.items()]
    tables = [ReportTable(_guide(
        "Referencias humanas y disponibilidad de Prueba", "Conteos por objetivo y estado del sello.",
        "Relaciona las referencias candidatas con la disponibilidad de un holdout revisado.",
        f"{sum(ready.values())} de {len(ready)} objetivos tienen Prueba disponible. "
        f"Hay {content['holdout']['preparation_pending']} decisiones pendientes.",
        "Los candidatos del piloto pueden tener exposición previa. El sello revisado y su integridad son requisitos para evaluar."),
        ("Objetivo", "Candidatos (n)", "Prueba revisada"), tuple(status))]
    if not compact:
        rows = [(s["id"], s["format"], s["status"], s["rows"],
                 sum(s.get("nature_counts", {}).get(key, 0) for key in ("sintetica", "sintetico")),
                 s.get("nature_counts", {}).get("demo", 0)) for s in sources]
        tables.append(ReportTable(_guide(
            "Inventario por fuente y naturaleza", "n cuenta filas dentro de cada fuente.",
            "Consulta disponibilidad y naturaleza antes de interpretar el tamaño.",
            f"{sum(s['status'] == 'disponible' for s in sources)} de {len(sources)} fuentes están disponibles.",
            SOURCE_LIMIT), ("Fuente", "Formato", "Estado", "Filas (n)", "Sintéticas (n)", "DEMO (n)"), tuple(rows)))
        quality = content["quality"]
        tables.append(ReportTable(_guide(
            "Controles de calidad del inventario", "La unidad corresponde a cada control.",
            "Lee el conteo junto a su unidad y estado. Los controles pueden solaparse.",
            f"{sum(r['status'] == 'Error' for r in quality)} controles indican error y "
            f"{sum(r['status'] == 'Advertencia' for r in quality)} indican advertencia.",
            "Los conteos de controles distintos describen dimensiones diferentes de calidad."),
            ("Control", "Estado", "Conteo", "Unidad"),
            tuple((r["name"], r["status"], r["count"], r["unit"]) for r in quality)))
        rows = []
        for source in sources:
            for item in source.get("label_coverage", []):
                total = item["Total (registros)"]
                valid = item["Válidos (registros)"]
                rows.append((source["id"], item["Variable"], item["Total (registros)"],
                             valid, item["Referencia humana (registros)"], valid / total if total else None))
        tables.append(ReportTable(_guide(
            "Cobertura descriptiva de etiquetas", "Conteos por fuente y variable. Cobertura en porcentaje.",
            "La cobertura divide etiquetas válidas entre el total. La columna humana identifica las referencias revisadas.",
            f"Hay {len(rows)} combinaciones de fuente y variable descritas en el manifiesto.",
            SOURCE_LIMIT + " La cobertura provisional requiere revisión antes de uso supervisado."),
            ("Fuente", "Variable", "Total (n)", "Válidos (n)", "Referencia humana (n)", "Cobertura"),
            tuple(rows), ((5, "percent"),), ratio=(3, 2)))
    available = [s for s in sources if s["status"] == "disponible" and s["rows"] is not None]
    figures = ()
    if available and not compact:
        guide = _guide("Distribución del tamaño de fuentes", "Barras en filas por archivo.",
                       "Compara las alturas manteniendo la unidad de fuente.",
                       f"La fuente de mayor tamaño contiene {max(s['rows'] for s in available)} filas.", SOURCE_LIMIT)
        figures = (ReportFigure(guide, "Fuente registrada", "Filas (n)", tuple(s["id"] for s in available),
                                (tuple(s["rows"] for s in available),)),)
    return ReportSection("Datos y calidad", (f"Manifiesto {envelope['run_id']}.", SOURCE_LIMIT), tuple(tables), figures)


def training_section(reports: list[dict]) -> ReportSection:
    """Include saved folds and final selected parameters without re-fitting models."""
    if not reports:
        return pending("Entrenamiento y experimentación", "Selecciona una corrida final de Fase 2.")
    tables = []
    notes = ["Metodología registrada. Particiones por grupos 70/15/15 y búsqueda anidada con cinco folds externos y tres internos."]
    for report in reports:
        scope = SYNTHETIC_LIMIT if report["request"]["source"] == "sintetico" else REAL_LIMIT
        prefix = report["run_id"][-6:]
        notes.append(f"Corrida {report['run_id']}. Semilla {report['request']['seed']}. {scope}")
        tables.append(from_rows(*partition_table(report["partition"]), title=f"Particiones · {prefix}"))
        summary_rows, guide = summary_table(report)
        # Keep print tables narrow while reusing the phase's derived interpretations.
        summary_rows = [{key: row[key] for key in ("Modelo", "Folds externos (n)", "F1 macro medio", "DE muestral", "Intervalo 95 %")}
                        for row in summary_rows]
        tables.append(from_rows(summary_rows, replace(guide, limitations=guide.limitations + " " + scope), f"Resumen externo · {prefix}"))
        for family, evidence in report["families"].items():
            model = FAMILY_NAMES.get(family, "Configuración LLM")
            rows, guide = external_table(evidence)
            rows = [{key: row[key] for key in ("Fold", "Entrenamiento (n)", "Validación externa (n)", "F1 externo", "Duración (s)")}
                    for row in rows]
            tables.append(from_rows(rows, replace(guide, limitations=guide.limitations + " " + scope), f"Resultados por fold · {model} · {prefix}"))
            configuration = evidence["validation_selection"]["winner"]["configuration"]
            keys = set(LocalParameters.model_fields) | {"prompt", "prompt_sha256", "threshold"}
            params = [(key, value) for key, value in sorted(configuration.items()) if key in keys and isinstance(value, (str, int, float, bool))]
            tables.append(ReportTable(_guide(
                f"Configuración final · {model} · {prefix}", "Parámetros del estimador o configuración LangFlow.",
                "Estos valores corresponden a la selección final con Validación.",
                f"Se conservaron {len(params)} parámetros seleccionados. "
                f"El F1 de selección es {evidence['validation_selection']['winner']['score']:.4f}.",
                "La validación participa en la selección. La evidencia de Prueba se describe en Evaluación."),
                ("Parámetro", "Valor"), tuple(params)))
    return ReportSection("Entrenamiento y experimentación", tuple(notes), tuple(tables))


def evaluation_section(reports: list[dict], comparisons: list[dict]) -> ReportSection:
    """Read archived estimates and inference status, including missing intervals."""
    if not reports:
        return pending("Evaluación estadística", "Selecciona evaluaciones publicadas en la Fase 3.")
    tables, figures, notes = [], [], []
    for report in reports:
        target, classes = report["target"], report["classes"]
        name = FAMILY_NAMES.get(report["family"], "Configuración LLM") + " · " + report["run_id"][-6:]
        scope = SYNTHETIC_LIMIT if report["source"] == "sintetico" else REAL_LIMIT
        notes.append(f"{name}. Objetivo {LABEL_NAMES[target]}. Referencia {report['reference']}. {scope}")
        uncertainty = report["uncertainty"]
        metrics = report["metrics"]
        estimates = []
        for key, value in metrics["overall"].items():
            limits = uncertainty["metrics"].get(key, {})
            ci = limits.get("ci95")
            estimates.append((NAMES.get(key, key), value, ci[0] if ci else None, ci[1] if ci else None,
                              limits.get("reason") or uncertainty.get("reason") or "Estimación disponible"))
        guide = _guide(
            f"Métricas de Prueba · {name}", "Métricas y límites en escala 0–1. MCC y kappa en −1 a 1.",
            "Los IC 95 % remuestrean grupos. Un límite ausente conserva el motivo técnico.",
            f"F1 macro {metrics['overall']['f1_macro']:.4f} en {report['rows']} casos y {report['groups']} grupos.",
            scope + " " + METRIC_LIMIT)
        tables.append(ReportTable(guide, ("Métrica", "Estimación", "IC inferior", "IC superior", "Estado del IC"), tuple(estimates)))
        rows = [( _label(row["label"], target, classes), row["support"], row["precision"], row["recall"], row["f1"], row["fn"])
                for row in metrics["by_class"]]
        tables.append(ReportTable(_guide(
            f"Desempeño por clase · {name}", "Soporte y FN en casos. Precisión, recall y F1 entre 0 y 1.",
            "Relaciona el recall con los falsos negativos y el tamaño de la clase.",
            f"Se observaron {sum(row[-1] for row in rows)} falsos negativos entre las {len(rows)} clases.", scope),
            ("Clase", "Soporte (n)", "Precisión", "Recall", "F1", "FN (n)"), tuple(rows)))
        matrix = metrics["matrix"]
        labels = tuple(_label(value, target, classes) for value in matrix["prediction"])
        row_labels = tuple(_label(value, target, classes) for value in matrix["reference"])
        counts = matrix["counts"]
        hits = sum(counts[i][i] for i in range(min(len(counts), len(labels))))
        for normalized in (False, True):
            title = ("Matriz normalizada" if normalized else "Matriz absoluta") + " · " + name
            guide = _guide(title, "Frecuencia relativa por fila." if normalized else "Casos (n).",
                           "Filas de referencia y columnas predichas. La diagonal reúne aciertos.",
                           f"La diagonal contiene {hits} de {report['rows']} casos.",
                           scope + " Las categorías de activos usan identificadores ordinales para proteger etiquetas textuales.")
            values = tuple(tuple(row) for row in matrix["normalized" if normalized else "counts"])
            figures.append(ReportFigure(guide, "Clase predicha", "Clase de referencia", labels, values, row_labels, normalized))
            tables.append(ReportTable(guide, ("Referencia", *labels),
                                      tuple((label, *row) for label, row in zip(row_labels, values)),
                                      tuple((i + 1, "percent") for i in range(len(labels))) if normalized else ()))
        curves = report.get("curves", {})
        curve_rows = [(_label(label, target, classes), row["positive"], row["negative"],
                       row["roc_auc"], row["pr_auc"], row["average_precision"])
                      for label, row in curves.get("classes", {}).items()]
        if curve_rows:
            tables.append(ReportTable(_guide(
                f"Áreas ROC y Precision–Recall · {name}", "Áreas de 0 a 1, por clase frente al resto.",
                "ROC AUC resume ordenación. AP y área PR trapezoidal usan definiciones diferentes.",
                f"Hay scores continuos archivados para {len(curve_rows)} clases.",
                scope + " Los scores carecen de evidencia de calibración en este informe."),
                ("Clase", "Positivos (n)", "Negativos (n)", "ROC AUC", "PR AUC", "AP"), tuple(curve_rows)))
        else:
            notes.append(f"Curvas ROC/PR · {name}. No aplicable. {curves.get('reason') or 'Faltan scores continuos válidos por clase.'}")
        if critical := metrics.get("critical"):
            tables.append(ReportTable(_guide(
                f"Errores críticos · {name}", "Casos de severidad crítica y tasas entre 0 y 1.",
                "Separa severidad inferior de derivación a revisión humana.",
                f"{critical['lower']} de {critical['support']} críticos recibieron severidad inferior.", scope),
                ("Soporte (n)", "Inferior (n)", "Revisión (n)", "Tasa inferior", "Tasa FN"),
                ((critical["support"], critical["lower"], critical["review"], critical["lower_rate"], critical["fnr"]),)))
        operations = report["operations"]
        notes.append(f"Telemetría de {name}. Solicitudes externas {operations['requests']}. "
                     f"Fallos técnicos {operations['technical_failures']}. Gemini observado {operations['gemini_observed']}.")
        if operations["requests"]:
            latency = operations["flow_latency"]
            tables.append(ReportTable(_guide(
                f"Operación experimental · {name}", "Latencia en segundos. Solicitudes y fallos en conteos. Costo en USD.",
                "El costo requiere telemetría completa. Gemini requiere identificación explícita del proveedor.",
                f"{operations['gemini_observed']} respuestas de Gemini y {operations['technical_failures']} fallos técnicos observados.",
                "El origen fallback de revisión segura carece de equivalencia automática con una respuesta de Gemini."),
                ("Solicitudes (n)", "p50 (s)", "p95 (s)", "Gemini (n)", "Fallos (n)", "Costo (USD)"),
                ((operations["requests"], latency["p50_s"], latency["p95_s"], operations["gemini_observed"],
                  operations["technical_failures"], operations["cost_usd"]),)))
            responses = operations.get("responses", [])
            if responses:
                tables.append(ReportTable(_guide(
                    f"Proveedores efectivos · {name}", "Respuestas con identificación de proveedor y modelo.",
                    "Se incluyen únicamente metadatos registrados para las respuestas.",
                    f"{sum(row['n'] for row in responses)} respuestas tienen proveedor observado.",
                    "La configuración de un proveedor de respaldo indica disponibilidad configurada."),
                    ("Proveedor", "Modelo", "Respuestas (n)"),
                    tuple((row["provider"], row["model"], row["n"]) for row in responses)))
    selected = {row["run_id"] for row in reports}
    available_comparisons = 0
    for comparison in comparisons:
        for pair in comparison["comparisons"]:
            if pair["left"] not in selected or pair["right"] not in selected:
                continue
            available_comparisons += 1
            test = pair["correctness"]
            effect = pair["differences"]["accuracy"]
            ci = effect["ci95"]
            guides = _guide("Contraste pareado archivado", "Diferencia en proporción. p ajustado con Holm.",
                            "El efecto resta el segundo modelo del primero. Interpreta soporte y relevancia operacional.",
                            f"Diferencia de exactitud {effect['delta']:.4f}. "
                            + ("Contraste pendiente por requisitos estadísticos." if test.get("p_holm") is None
                               else f"p de Holm {test['p_holm']:.4g}."),
                            test.get("reason") or pair.get("bootstrap_reason") or METRIC_LIMIT)
            tables.append(ReportTable(guides, ("Contraste", "Δ exactitud", "IC inferior", "IC superior", "p Holm"),
                                      ((test["test"], effect["delta"], ci[0] if ci else None, ci[1] if ci else None, test.get("p_holm")),)))
            notes.append(f"Comparación {comparison['run_id']}. Primero {pair['left']}. Segundo {pair['right']}.")
    if not available_comparisons:
        notes.append("Contrastes pareados pendientes. No hay una comparación archivada entre las evaluaciones seleccionadas.")
    return ReportSection("Evaluación estadística", tuple(notes), tuple(tables), tuple(figures))


def explanation_section(reports: list[dict]) -> ReportSection:
    """Use aggregate XAI findings only, excluding text, names and quoted fragments."""
    if not reports:
        return pending("Explicabilidad", "Selecciona resultados de explicabilidad de la Fase 4.")
    tables, notes = [], []
    for report in reports:
        summary = report["summary"]
        stability = summary["stability"]
        scope = SYNTHETIC_LIMIT if report["source"] == "sintetico" else (
            "Las verificaciones léxicas de citas requieren revisión semántica autorizada.")
        prefix = report["run_id"][-6:]
        notes.append(f"Registro {report['run_id']}. Modalidad {report['mode']}. {scope}")
        issues = sum(summary["inconsistencies"].values())
        variants = stability["variants"]
        tables.append(ReportTable(_guide(
            f"Fiabilidad observable · {prefix}", "Casos, hallazgos y variantes en conteos. Estabilidad en proporción.",
            "Un caso puede tener varios hallazgos. La estabilidad exige perturbaciones observadas.",
            f"Se registraron {issues} hallazgos en {summary['cases']} casos y {variants} variantes controladas.", scope),
            ("Casos (n)", "Hallazgos (n)", "Variantes (n)", "Conservadas (n)", "Fracción estable"),
            ((summary["cases"], issues, variants, stability["prediction_same"], stability["same_fraction"]),),
            ((4, "percent"),)))
        patterns = Counter()
        for row in summary["patterns"]:
            # The class text can contain sensitive asset identifiers.
            key = row["outcome"] if row["outcome"] in ("acierto", "error", "sin_referencia") else "Referencia no evaluable"
            patterns[key] += row["cases"]
        tables.append(ReportTable(_guide(
            f"Disponibilidad de referencia XAI · {prefix}", "Casos por relación con la referencia registrada.",
            "Acierto y error dependen del origen de la referencia. La ausencia de referencia mantiene el estado observado.",
            f"{patterns.get('error', 0)} errores y {patterns.get('acierto', 0)} aciertos tienen referencia identificada.", scope),
            ("Relación con referencia", "Casos (n)"), tuple(sorted(patterns.items()))))
        if variants == 0:
            notes.append(f"Estabilidad · {prefix}. Pendiente. Faltan perturbaciones registradas.")
    notes.append("Los mapas y fragmentos individuales se consultan en Explicabilidad con autorización de revisión. "
                 "Este informe contiene agregados de los controles y su trazabilidad.")
    return ReportSection("Explicabilidad", tuple(notes), tuple(tables))


def _category_counts(values: dict, allowed: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
    counts = Counter()
    for key, value in values.items():
        if isinstance(value, int) and value >= 0:
            counts[key if key in allowed else "fuera_de_taxonomia"] += value
    return tuple(sorted(counts.items()))


def operational_section(summary: dict | None, compact: bool = False) -> ReportSection:
    """Reuse FastAPI aggregates, SLA denominators and review counts."""
    if summary is None:
        return pending("Clasificación operativa y SLA", "FastAPI no pudo entregar el tablero autorizado en esta consulta.")
    total, demo = summary["total"], summary["demo"]
    scope = f"El tablero incluye {total} reportes, de los cuales {demo} están marcados DEMO. "
    scope += "El cumplimiento conserva la población y los denominadores del tablero operativo."
    sla = summary["sla"]
    rows = []
    for milestone in ("respuesta", "resolucion"):
        eligible = sla.get(milestone + "_evaluable", 0)
        on_time = sla.get(milestone + "_a_tiempo", 0)
        rows.append((milestone, on_time, eligible, on_time / eligible if eligible else None))
    guide = _guide("Cumplimiento de SLA observado", "Conteos en hitos y cumplimiento en porcentaje.",
                   "El denominador incluye hitos terminados o ya vencidos con plazo configurado.",
                   f"Hay {sum(row[2] for row in rows)} hitos evaluables en {total} reportes. "
                   f"{sum(row[2] - row[1] for row in rows)} hitos evaluables incumplieron su plazo.",
                   scope + " Los hitos de respuesta y resolución pueden pertenecer al mismo incidente.")
    tables = [ReportTable(guide, ("Hito", "A tiempo (n)", "Evaluables (n)", "Cumplimiento"), tuple(rows),
                          ((3, "percent"),), ratio=(1, 2))]
    origins = summary["clasificador"]
    validated = sum(row["validados"] for row in origins)
    matches = sum(row["aciertos"] for row in origins)
    review = sum(row["revision"] for row in origins)
    tables.append(ReportTable(_guide(
        "Clasificación y revisión humana", "Conteos en reportes y concordancia conjunta en porcentaje.",
        "La concordancia exige revisión humana de tipo, severidad y activo en los registros revisados.",
        f"{review} reportes tienen motivo de revisión y {validated} poseen validación humana.",
        scope + " La muestra revisada puede tener sesgo de selección. Los metadatos de origen requieren telemetría para identificar el proveedor efectivo."),
        ("Reportes (n)", "Con motivo de revisión (n)", "Validados (n)", "Concordantes (n)", "Concordancia"),
        ((total, review, validated, matches, matches / validated if validated else None),), ((4, "percent"),), ratio=(3, 2)))
    severities = _category_counts(summary["severidades"], get_args(Severidad))
    figures = ()
    if severities:
        maximum = max(n for _, n in severities)
        guide = _guide("Distribución operativa de severidad", "Frecuencia en reportes recibidos dentro del intervalo.",
                       "Compara los conteos de cada severidad. Las categorías indican clasificación registrada.",
                       f"La mayor frecuencia de una severidad es {maximum} de {total} reportes.", scope)
        tables.append(ReportTable(guide, ("Severidad", "Reportes (n)"), severities))
        figures = (ReportFigure(guide, "Severidad registrada", "Reportes (n)", tuple(x for x, _ in severities),
                                (tuple(n for _, n in severities),)),)
    if not compact:
        types = _category_counts(summary["tipos"], get_args(Tipo))
        tables.append(ReportTable(_guide(
            "Distribución operativa de tipos", "Frecuencia en reportes del intervalo.",
            "Relaciona cada categoría con el total incluido.",
            f"Se observaron {len(types)} categorías de tipo en {total} reportes.", scope),
            ("Tipo", "Reportes (n)"), types))
        timings = [(name, row["muestra"], row["segundos"]) for name, row in summary["tiempos"].items()
                   if name in ("clasificacion", "respuesta", "resolucion")]
        tables.append(ReportTable(_guide(
            "Tiempos descriptivos de atención", "Duración media en segundos. Muestra en hitos terminados.",
            "Cada media usa los hitos que tienen fecha de terminación.",
            f"{len(timings)} hitos poseen duraciones observadas.", scope + " Los tiempos abiertos carecen de fecha final."),
            ("Hito", "Terminados (n)", "Media (s)"), tuple(timings)))
    return ReportSection("Clasificación operativa y SLA", (scope,), tuple(tables), figures)
