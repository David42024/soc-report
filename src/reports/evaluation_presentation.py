"""Interpretable tables and scientific figures for sealed evaluations."""
from __future__ import annotations

import numpy as np
from matplotlib import rc_context
from matplotlib.figure import Figure

from src.data.models import LABEL_NAMES
from src.reports.figures import figure_style
from src.reports.presentation import TableGuide
from src.training.local import FAMILY_NAMES
from src.training.metrics import REVIEW
from src.utils.config import FigureSettings

NAMES = {"accuracy": "Exactitud", "balanced_accuracy": "Exactitud balanceada", "precision_macro": "Precisión macro",
         "recall_macro": "Recall macro", "specificity_macro": "Especificidad macro", "f1_macro": "F1 macro",
         "f1_weighted": "F1 ponderado", "mcc": "MCC", "kappa": "Kappa de Cohen", "kappa_quadratic": "Kappa cuadrático",
         "critical_lower_rate": "Subclasificación crítica", "critical_fnr": "Falsos negativos críticos"}


def interval(values: list[float] | None) -> str:
    return f"[{values[0]:.3f}, {values[1]:.3f}]" if values is not None else "No aplicable"


def readiness_table(status: dict) -> tuple[list[dict], TableGuide]:
    rows = [{"Objetivo": LABEL_NAMES[target], "Referencias candidatas (n)": count,
             "Sello validado": "Sí" if status["ready_by_target"][target] and status["seal_present"] else "Pendiente"}
            for target, count in status["candidates"].items()]
    available = sum(row["Sello validado"] == "Sí" for row in rows)
    finding = f"{available} de {len(rows)} objetivos tienen sello disponible. Corridas finales reales registradas: {status['final_real_runs']}."
    if status["pending"] is not None:
        finding += f" La preparación tiene {status['pending']} decisiones pendientes."
    return rows, TableGuide("Disponibilidad de la evaluación real", "Referencias y objetivos en conteos.",
        "Comprueba el sello y la corrida final para el objetivo. Se verifica la reserva antes de usarla.",
        finding, "Los candidatos pertenecen a la fase de datos. La reserva requiere referencias humanas independientes.")


def overall_table(report: dict) -> tuple[list[dict], TableGuide]:
    point = report["metrics"]
    uncertainty = report["uncertainty"]
    rows = []
    for key, value in point["overall"].items():
        limits = uncertainty["metrics"].get(key, {})
        rows.append({"Métrica": NAMES[key], "Estimación": value, "IC 95 %": interval(limits.get("ci95")),
                     "Réplicas válidas (n)": limits.get("valid"), "Motivo de IC ausente": limits.get("reason") or uncertainty["reason"]})
    return rows, TableGuide("Métricas del objetivo seleccionado", "Proporciones y F1 de 0 a 1. MCC y kappa de −1 a 1.",
        "F1 macro pondera las clases por igual. El intervalo remuestrea grupos completos.",
        f"F1 macro de {point['overall']['f1_macro']:.3f} en {point['rows']} casos y {report['groups']} grupos.",
        "Las derivaciones cuentan como errores para métricas nominales. Kappa cuadrático usa pares ordinales válidos. Los intervalos dependen del soporte y la variación.")


def class_table(report: dict) -> tuple[list[dict], TableGuide]:
    items = report["metrics"]["by_class"]
    unc = report["uncertainty"]["metrics"]
    rows = [{"Clase": row["label"], "Soporte (n)": row["support"], "Precisión": row["precision"], "Recall": row["recall"],
             "Especificidad": row["specificity"], "F1": row["f1"], "Falsos negativos (n)": row["fn"], "Tasa FN": row["fnr"],
             "IC 95 % F1": interval(unc.get(row["label"] + ".f1", {}).get("ci95"))} for row in items]
    misses = max(items, key=lambda row: row["fn"])
    return rows, TableGuide("Desempeño por clase de referencia", "Soporte y falsos negativos en casos. Las métricas son proporciones.",
        "Recall usa positivos de referencia. Especificidad usa negativos de referencia.",
        f"El máximo observado es {misses['fn']} falsos negativos en una clase con {misses['support']} casos de referencia.",
        "Precisión se fija en cero cuando la clase carece de predicciones. Los intervalos pueden faltar por soporte o falta de variación.")


def critical_table(report: dict) -> tuple[list[dict], TableGuide]:
    critical, ordinal = report["metrics"]["critical"], report["metrics"]["ordinal"]
    rows = [{"Críticos revisados (n)": critical["support"], "Predicción inferior (n)": critical["lower"],
             "Derivados a revisión (n)": critical["review"], "Tasa de predicción inferior": critical["lower_rate"],
             "Tasa de falsos negativos críticos": critical["fnr"], "Pares ordinales para kappa (n)": ordinal["ordinal_pairs"]}]
    return rows, TableGuide("Errores de severidad crítica", "Eventos en casos y tasas de 0 a 1.",
        "Distingue degradaciones a alta, media o baja de derivaciones a revisión. Ambas cuentan para el recall crítico.",
        f"{critical['lower']} de {critical['support']} incidentes críticos recibieron una severidad inferior.",
        "Los errores no implican por sí solos un incumplimiento del SLA. Kappa cuadrático excluye derivaciones.")


def _label(value: str) -> str:
    return "Revisión" if value == REVIEW else value.replace("_", " ")


def confusion_figure(matrix: dict, style: FigureSettings, normalized: bool, synthetic: bool) -> tuple[Figure, TableGuide]:
    columns, rows = matrix["prediction"], matrix["reference"]
    values = np.array(matrix["normalized" if normalized else "counts"])
    total = int(np.array(matrix["counts"]).sum())
    title = "Matriz de confusión normalizada" if normalized else "Matriz de confusión absoluta"
    title += " · sintética" if synthetic else ""
    with rc_context(figure_style(style)):
        figure = Figure(figsize=(max(6.5, min(16.0, len(columns) * 1.0 + 1.8)), max(4.0, min(13.0, len(rows) * .55 + 2.0))),
                        layout="constrained")
        axis = figure.subplots()
        shown = axis.imshow(values * 100 if normalized else values, cmap="Blues", vmin=0,
                            vmax=100 if normalized else max(1, int(values.max())))
        colorbar = figure.colorbar(shown, ax=axis)
        colorbar.set_label("Porcentaje de la clase de referencia" if normalized else "Casos (n)")
        axis.set(title=title, xlabel="Clase predicha", ylabel="Clase de referencia")
        axis.set_xticks(range(len(columns)), [_label(value) for value in columns], rotation=35, ha="right")
        axis.set_yticks(range(len(rows)), [_label(value) for value in rows])
        if len(rows) * len(columns) <= 144:
            for (i, j), value in np.ndenumerate(values):
                text = f"{value:.0%}" if normalized else str(int(value))
                axis.text(j, i, text, ha="center", va="center",
                          color="white" if value > (.55 if normalized else values.max() * .55) else "#182B3A")
    hits = int(np.array(matrix["counts"])[:, :len(rows)].trace())
    return figure, TableGuide(title, "Azul más oscuro indica una frecuencia mayor. La barra lateral indica la unidad.",
        "Sigue una fila de referencia hacia las predicciones. La diagonal muestra aciertos y la columna Revisión muestra derivaciones cuando existen.",
        f"La diagonal reúne {hits} aciertos de {total} casos.",
        "El porcentaje se calcula dentro de cada clase de referencia. La matriz agrupa casos relacionados sin convertirlos en observaciones independientes.")


def curve_figure(label: str, data: dict, style: FigureSettings, *, pr: bool, synthetic: bool) -> tuple[Figure, TableGuide]:
    name = "Precisión–Recall" if pr else "ROC"
    title = f"{name} · {_label(label)} frente al resto" + (" · sintética" if synthetic else "")
    with rc_context(figure_style(style)):
        fig = Figure(figsize=(6.9, 3.8), layout="constrained")
        axis = fig.subplots()
        if pr:
            axis.step(data["recall"], data["precision"], where="post", color=style.palette[0],
                      label=f"AP {data['average_precision']:.3f}")
            axis.axhline(data["prevalence"], linestyle="--", color=style.palette[1], label="Prevalencia")
            axis.set(xlabel="Recall (0–1)", ylabel="Precisión (0–1)")
            finding = f"AP {data['average_precision']:.3f} y área trapezoidal {data['pr_auc']:.3f}."
        else:
            axis.plot(data["fpr"], data["tpr"], color=style.palette[0], label=f"AUC {data['roc_auc']:.3f}")
            axis.plot([0, 1], [0, 1], linestyle="--", color=style.palette[1], label="Orden aleatorio")
            axis.set(xlabel="Tasa de falsos positivos (0–1)", ylabel="Tasa de verdaderos positivos (0–1)")
            finding = f"AUC {data['roc_auc']:.3f} con {data['positive']} positivos y {data['negative']} negativos."
        axis.set(title=title, xlim=(0, 1), ylim=(0, 1.025))
        axis.legend(loc="lower right")
    return fig, TableGuide(title, "La curva varía el umbral del score continuo. La línea discontinua es una referencia.",
        "El positivo es la clase seleccionada. Las demás clases forman el grupo negativo.", finding,
        "Los scores sirven para ordenar casos. La curva carece de información sobre calibración o costos operativos.")


def operation_table(report: dict) -> tuple[list[dict], TableGuide]:
    data = report["operations"]
    rows = [{"Serie": "LangFlow completo", "n": data["flow_latency"]["n"], "p50 (s)": data["flow_latency"]["p50_s"],
             "p95 (s)": data["flow_latency"]["p95_s"]}]
    for provider, values in data["flow_latency_by_responder"].items():
        rows.append({"Serie": f"LangFlow con respuesta de {provider}", "n": values["n"], "p50 (s)": values["p50_s"], "p95 (s)": values["p95_s"]})
    for provider, values in data["provider_latency"].items():
        rows.append({"Serie": f"Latencia informada por {provider}", "n": values["n"], "p50 (s)": values["p50_s"], "p95 (s)": values["p95_s"]})
    return rows, TableGuide("Latencia observada en la evaluación LangFlow", "Percentiles en segundos y tamaño en solicitudes.",
        "El tiempo del flujo incluye la orquestación y posibles reintentos. La latencia de proveedor requiere metadatos explícitos.",
        f"Se enviaron {data['requests']} solicitudes y se observaron {data['gemini_observed']} respuestas de Gemini.",
        "Los percentiles describen esta muestra. El costo facturado solo se informa con telemetría completa.")


def comparison_tables(comparison: dict) -> list[tuple[list[dict], TableGuide]]:
    rows = [{"Modelo": FAMILY_NAMES[row["family"]], "Evaluación": row["run_id"], "Exactitud": row["metrics"]["accuracy"],
             "F1 macro": row["metrics"]["f1_macro"], "Cobertura": row["coverage"]} for row in comparison["models"]]
    if comparison["target"] == "severidad":
        for row, model in zip(rows, comparison["models"]):
            row.update({"Tasa de subclasificación crítica": model["metrics"].get("critical_lower_rate"),
                        "Tasa de FN críticos": model["metrics"].get("critical_fnr")})
    best = max(row["F1 macro"] for row in rows)
    summary = TableGuide("Comparación en la misma cohorte sellada", "Exactitud, F1 y cobertura de 0 a 1.",
        "Compara los modelos sobre los mismos casos. Cobertura es la proporción sin derivación.",
        f"F1 macro máximo de {best:.3f} entre {len(rows)} configuraciones.", "Las diferencias puntuales requieren considerar la incertidumbre y el impacto de los errores.")
    paired, auc, critical = [], [], []
    for pair in comparison["comparisons"]:
        test = pair["correctness"]
        label = pair["left"][-6:] + " − " + pair["right"][-6:]
        paired.append({"Par (sufijos)": label, "Contraste": test["test"], "Grupos (n)": test["groups"],
                       "Δ exactitud (pp)": 100 * test["accuracy_delta"], "IC 95 % Δ (pp)": interval(
                           [100 * value for value in pair["differences"]["accuracy"]["ci95"]]
                           if pair["differences"]["accuracy"]["ci95"] is not None else None),
                       "Δ F1 macro": pair["differences"]["f1_macro"]["delta"],
                       "IC 95 % Δ F1": interval(pair["differences"]["f1_macro"]["ci95"]),
                       "p Holm": test["p_holm"], "Significativo al 5 %": test["significant"],
                       "Magnitud ≥ umbral": test["practical_magnitude"], "Motivo": test["reason"]})
        for name, value in pair["auc"].items():
            auc.append({"Par (sufijos)": label, "Clase": name, "Δ AUC ROC": value["delta"], "IC 95 %": interval(value["ci95"]),
                        "p Holm": value["p_holm"], "Significativo al 5 %": value["significant"], "Motivo": value["reason"]})
        for metric in ("critical_lower_rate", "critical_fnr"):
            if value := pair["differences"].get(metric):
                bounds = value["ci95"]
                critical.append({"Par (sufijos)": label, "Métrica": NAMES[metric], "Δ (pp)": 100 * value["delta"],
                                 "IC 95 % (pp)": interval([100 * bound for bound in bounds] if bounds is not None else None),
                                 "Motivo de IC ausente": value.get("reason") or pair["bootstrap_reason"]})
    supported = sum(row["p Holm"] is not None for row in paired)
    threshold = 100 * comparison["policy"]["practical_accuracy_delta"]
    tables = [(rows, summary), (paired, TableGuide("Contrastes de aciertos y diferencias pareadas",
        "pp indica puntos porcentuales. F1 y p-valores son adimensionales.",
        "El delta es el primer modelo menos el segundo. Evalúa por separado p de Holm y magnitud operacional.",
        f"{supported} de {len(paired)} pares cumplen los requisitos de un contraste de aciertos.",
        f"McNemar requiere un caso por grupo. Con varios casos se contrastan signos por grupo. La magnitud usa un umbral predeclarado de {threshold:g} pp.")),
        (auc, TableGuide("Diferencias pareadas de AUC ROC", "Diferencia de áreas entre −1 y 1, por clase frente al resto.",
         "El remuestreo usa los mismos grupos en ambos modelos. El p aproximado se ajusta con Holm.",
         f"{sum(row['p Holm'] is not None for row in auc)} de {len(auc)} contrastes de AUC tienen p ajustado.",
         "El contraste requiere scores continuos completos, soporte y variación bootstrap. Los intervalos son nominales."))]
    if critical:
        largest = max(critical, key=lambda row: abs(row["Δ (pp)"]))
        tables.append((critical, TableGuide("Diferencias en errores críticos", "Tasas comparadas en puntos porcentuales.",
            "El delta resta la tasa del segundo modelo de la del primero. Un delta positivo indica más errores críticos en el primero.",
            f"La mayor diferencia absoluta es {abs(largest['Δ (pp)']):.1f} pp en {largest['Métrica'].lower()}.",
            "Los críticos de referencia son el denominador. Las tasas describen la cohorte evaluada.")))
    return tables
