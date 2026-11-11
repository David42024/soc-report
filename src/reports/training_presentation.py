"""Tables and scientific figures for the nested experiment and its live log."""
from __future__ import annotations

from collections import Counter
from statistics import median

from matplotlib import rc_context
from matplotlib.figure import Figure

from src.reports.figures import figure_style
from src.reports.presentation import TableGuide
from src.training.local import FAMILY_NAMES
from src.training.partition import PARTITIONS
from src.utils.config import FigureSettings


def partition_table(evidence: dict) -> tuple[list[dict], TableGuide]:
    columns = evidence["by_label"]
    total = [sum(row["counts"][i] for row in columns) for i in range(3)]
    rows = []
    for row in [*columns, {"label": "Total", "counts": total}]:
        n = sum(row["counts"])
        rows.append({"Clase": row["label"], **{name + " (n, %)": f"{count} ({count / n:.1%})"
                    for name, count in zip(PARTITIONS, row["counts"])}})
    synthetic = evidence["source"] == "sintetico"
    return rows, TableGuide("Partición técnica sintética por clase" if synthetic else "Partición de datos reales por clase",
        "n es el número de registros. El porcentaje se calcula dentro de cada fila.",
        "Comprueba el reparto por clase y el total. Cada grupo pertenece a una sola partición.",
        f"Desarrollo contiene {total[0]} de {sum(total)} registros en {evidence['development']['groups']} grupos.",
        "Las cuotas enteras se obtienen por mayor residuo. Prueba se muestra mediante conteos y huella. "
        + ("La muestra sintética comprueba el protocolo." if synthetic else "La reserva corresponde al manifiesto seleccionado."))


def readiness_table(status: dict) -> tuple[list[dict], TableGuide]:
    rows = [{"Clase": item["label"], "Candidatos (n)": item["candidates"], "Grupos distintos (n)": item["groups"],
             "Prueba revisada (n)": item["sealed"]} for item in status["classes"]]
    return rows, TableGuide("Disponibilidad de referencias humanas por clase",
        "Los conteos corresponden al objetivo y a la versión seleccionados.",
        "Cada clase necesita cinco grupos en Desarrollo, un grupo distinto en Validación y un sello de Prueba compatible.",
        f"Se observaron {status['eligible']} candidatos utilizables y {status['pending']} de {status['reserve_rows']} decisiones pendientes en la reserva.",
        f"Se excluyeron {status['excluded_overlap']} representaciones con riesgo de solapamiento. La validación del plan verifica las cuotas y los 20 folds.")


def log_table(events: list[dict]) -> tuple[list[dict], TableGuide]:
    rows = [{"Hora UTC": event["at_utc"], "Evento": event["event"], "Modelo": FAMILY_NAMES.get(event.get("model"), ""),
             "Fold externo": event.get("fold"), "Trial": event.get("trial"), "Fold interno": event.get("inner"),
             "F1 macro (0–1)": event.get("score"), "Tiempo de la medición (s)": event.get("seconds"),
             "Tiempo acumulado (s)": round(event["elapsed_seconds"], 3)} for event in reversed(events)]
    measured = sum(event["event"] in ("inner_medido", "outer_medido", "validacion_medida") for event in events)
    return rows, TableGuide("Bitácora reciente de la ejecución", "Las horas se muestran en UTC y los tiempos en segundos.",
        "Los identificadores indican qué fold y trial se midieron. Los eventos más recientes se muestran arriba.",
        f"Se observan {measured} mediciones en los {len(events)} eventos visibles.",
        "La bitácora completa se conserva en el directorio de la ejecución. El avance depende de la duración de cada ajuste o solicitud.")


def summary_table(result: dict) -> tuple[list[dict], TableGuide]:
    rows = []
    for name, family in result["families"].items():
        summary = family["summary"]
        lower, upper = summary["ci95"]
        rows.append({"Modelo": FAMILY_NAMES[name], "Folds externos (n)": summary["folds"],
                     "F1 macro medio": summary["mean"], "DE muestral": summary["sample_sd"],
                     "Intervalo 95 %": f"[{lower:.4f}, {upper:.4f}]",
                     "F1 macro de selección": family["validation_selection"]["winner"]["score"],
                     "Tiempo externo acumulado (s)": sum(row["seconds"] for row in family["folds"])})
    best = max(row["F1 macro medio"] for row in rows)
    leaders = sum(row["F1 macro medio"] == best for row in rows)
    return rows, TableGuide("Comparación de modelos en los cinco folds externos",
        "F1 macro, desviación e intervalo en escala 0–1. Tiempo en segundos.",
        "La media externa resume Desarrollo. La columna de selección usa el 15 % de Validación.",
        f"La mayor media externa es {best:.4f}, observada en {leaders} de {len(rows)} modelos.",
        "El intervalo t se aproxima con corrección por solapamiento. Los folds comparten parte del entrenamiento. La métrica de selección es exploratoria.")


def external_table(family: dict) -> tuple[list[dict], TableGuide]:
    rows = [{"Fold": fold["fold"], "Entrenamiento (n)": fold["outer"]["train"]["rows"],
             "Validación externa (n)": fold["outer"]["validation"]["rows"],
             "Internos verificados (n)": len(fold["inner"]), "Mediciones externas (n)": fold["outer_evaluations"],
             "Mejor F1 interno": fold["best_inner_score"], "F1 externo": fold["outer_score"],
             "Trial elegido": fold["winner_trial"], "Duración (s)": fold["seconds"],
             "Grupos disjuntos": fold["outer"]["groups_disjoint"]} for fold in family["folds"]]
    return rows, TableGuide("Evidencia por fold externo", "Registros y folds en conteos. F1 macro 0–1 y duración en segundos.",
        "Relaciona los tres folds internos, el trial elegido y la medición externa del fold.",
        f"Se registraron {sum(row['Mediciones externas (n)'] for row in rows)} mediciones externas en {len(rows)} folds.",
        "Cada medición usa una parte de Desarrollo. El archivo JSON conserva las huellas de las pertenencias y los soportes por clase.")


def validation_table(family: dict) -> tuple[list[dict], TableGuide]:
    selection = family["validation_selection"]
    winner = selection["winner"]
    rows = []
    for item in selection["candidates"]:
        params = item["configuration"]
        detail = (f"C={params['c']:.5g}, n-gramas {params['ngram_min']}–{params['ngram_max']}" if "c" in params else
                  f"{params['prompt']}, umbral {params['threshold']:.2f}")
        rows.append({"Configuración": detail, "F1 macro (0–1)": item["score"], "Duración (s)": item["seconds"],
                     "Seleccionada": item["sha256"] == winner["sha256"]})
    return rows, TableGuide("Selección con el 15 % de Validación", "Duración en segundos. F1 macro en escala 0–1.",
        "Cada fila corresponde a una configuración única elegida en algún fold externo.",
        f"Se compararon {len(rows)} configuraciones en {selection['rows']} registros. La seleccionada obtuvo {winner['score']:.4f}.",
        "La validación interviene en la selección. El resultado de prueba final corresponde a una fase posterior.")


def _axes(title: str, x: str, y: str) -> tuple:
    figure = Figure(figsize=(7.1, 3.8), layout="constrained")
    axis = figure.subplots()
    axis.set(title=title, xlabel=x, ylabel=y)
    axis.grid(axis="y", alpha=.25)
    return figure, axis


def fold_plot(result: dict, style: FigureSettings, *, seconds: bool = False) -> tuple[Figure, TableGuide]:
    title = "Duración de búsqueda y medición por fold" if seconds else "F1 macro por fold externo"
    if result["partition"]["source"] == "sintetico":
        title += " · prueba sintética"
    column = "seconds" if seconds else "outer_score"
    unit = "segundos" if seconds else "F1 macro (0–1)"
    collected = []
    with rc_context(figure_style(style)):
        figure, axis = _axes(title, "Fold externo (índice)", unit)
        for i, (name, family) in enumerate(result["families"].items()):
            rows = family["folds"]
            values = [row[column] for row in rows]
            collected.extend(values)
            axis.plot([row["fold"] for row in rows], values, marker=("o", "s", "^")[i],
                      markersize=9 - i * 2, markerfacecolor="none" if i == 0 else style.palette[i],
                      markeredgewidth=1.5, linestyle=("solid", "dashed", "dotted")[i],
                      color=style.palette[i], label=FAMILY_NAMES[name])
        axis.set_xticks(range(1, max(len(family["folds"]) for family in result["families"].values()) + 1))
        if not seconds:
            axis.set_ylim(0, 1.04)
        axis.legend()
    return figure, TableGuide(title, f"Cada marcador corresponde a un fold externo. Eje vertical en {unit}.",
        "Compara los puntos del mismo fold entre modelos y observa la dispersión entre folds.",
        f"Los {len(collected)} valores observados abarcan de {min(collected):.4g} a {max(collected):.4g}.",
        "El tiempo incluye búsqueda y evaluación. Los F1 se calculan sobre Desarrollo con validación externa por grupos.")


def trial_plot(fold: dict, style: FigureSettings) -> tuple[Figure, TableGuide]:
    valid = [trial for trial in fold["trials"] if trial["score"] is not None]
    with rc_context(figure_style(style)):
        figure, axis = _axes(f"Búsqueda Optuna en el fold externo {fold['fold']}", "Trial (índice)", "F1 macro interno (0–1)")
        axis.plot([trial["number"] for trial in valid], [trial["score"] for trial in valid],
                  marker="o", color=style.palette[0], label="Media de los 3 internos")
        axis.scatter(fold["winner_trial"], fold["best_inner_score"], color=style.palette[1], marker="D", label="Trial elegido")
        axis.set_ylim(0, 1.04)
        axis.legend()
    return figure, TableGuide("Historial de búsqueda interna", "Cada punto válido es una media de tres observaciones internas.",
        "Usa el eje horizontal para seguir el orden de Optuna y el rombo para localizar la elección.",
        f"El trial {fold['winner_trial']} obtuvo {fold['best_inner_score']:.4f} entre {len(valid)} trials válidos.",
        f"Los {len(fold['trials']) - len(valid)} trials fallidos quedan en el registro. Esta curva describe búsqueda, con parámetros distintos entre puntos.")


def stability_plot(family: dict, style: FigureSettings) -> tuple[Figure, TableGuide]:
    rows = family["folds"]
    with rc_context(figure_style(style)):
        if "c" in rows[0]["winner"]:
            figure, axis = _axes("Estabilidad de C entre folds", "Fold externo (índice)", "Regularización C (escala logarítmica)")
            for i, order in enumerate(sorted({row["winner"]["ngram_max"] for row in rows})):
                subset = [row for row in rows if row["winner"]["ngram_max"] == order]
                axis.scatter([row["fold"] for row in subset], [row["winner"]["c"] for row in subset],
                             marker=("o", "s", "^")[i], color=style.palette[i % len(style.palette)], label=f"n-grama máximo {order}")
            axis.set_yscale("log")
            axis.set_xticks([row["fold"] for row in rows])
            axis.legend()
            cs = [row["winner"]["c"] for row in rows]
            finding = f"C varió de {min(cs):.4g} a {max(cs):.4g}, con mediana {median(cs):.4g}."
        else:
            combinations = Counter(f"{row['winner']['prompt']} · {row['winner']['threshold']:.2f}" for row in rows)
            figure, axis = _axes("Estabilidad de la configuración LangFlow", "Folds externos (n)", "Prompt y umbral")
            axis.barh(list(combinations), list(combinations.values()), color=style.palette[0])
            finding = f"Se eligieron {len(combinations)} configuraciones distintas en {len(rows)} folds."
    return figure, TableGuide("Estabilidad de la configuración elegida",
        "Cada valor corresponde a una elección hecha dentro del entrenamiento externo.",
        "Observa cuánto cambian las configuraciones ganadoras al cambiar los grupos disponibles.",
        finding, "La estabilidad depende del rango y número de trials. La coincidencia entre folds carece de garantía sobre otros datos.")
