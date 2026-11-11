"""Scientific views of actual Optuna trials with applicability and interpretation."""
from __future__ import annotations

from collections import Counter
import json
from statistics import median

from matplotlib import rc_context
from matplotlib.figure import Figure
from matplotlib import colormaps
import numpy as np

from src.optimization.contracts import METRICS, SearchOptions
from src.reports.figures import figure_style
from src.reports.presentation import TableGuide


def space_table(options: SearchOptions) -> tuple[list[dict], TableGuide]:
    """Describe types, ranges and scales before an operator authorizes a run."""
    rows = [{"Parámetro": name, "Tipo": value.kind, "Mínimo": value.low, "Máximo": value.high, "Paso": value.step,
             "Escala logarítmica": value.log, "Categorías": json.dumps(value.choices, ensure_ascii=False) if value.choices else ""}
            for name, value in options.space.items()]
    return rows, TableGuide("Espacio de búsqueda validado", "Rangos y categorías en las unidades del hiperparámetro; C es adimensional.",
        "Cada fila define un parámetro muestreado. Los demás conservan su configuración base.",
        f"La búsqueda define {len(rows)} parámetros, {sum(r['Escala logarítmica'] for r in rows)} en escala logarítmica.",
        "El espacio se valida antes del ajuste. Ciertos subconjuntos pequeños todavía pueden producir trials fallidos, que se conservan.")


def live_table(data: dict) -> tuple[list[dict], TableGuide]:
    """Project the Phase 2 progress cache, including trial failures and pruning."""
    rows = [{"Modelo": row["model"], "Fold externo": row["fold"], "Trial": row["number"], "Estado": row["state"],
             "Interno medido": row.get("inner"), "Objetivo observado": row.get("objective"),
             "Mediciones acumuladas (s)": row["seconds"], "Parámetros": json.dumps(row.get("parameters", {}), ensure_ascii=False)}
            for row in data["state"].get("trials", {}).values()]
    counts = Counter(row["Estado"] for row in rows)
    return rows, TableGuide("Trials y progreso observado", "Índices de trial por estudio/fold; tiempos en segundos y objetivo en su escala.",
        "RUNNING muestra el último acumulado interno; COMPLETE contiene los tres folds. Cada fold tiene su propia numeración.",
        f"Se observan {len(rows)} trials: {counts['COMPLETE']} completos, {counts['PRUNED']} podados y {counts['FAIL']} fallidos.",
        "La cancelación se aplica en límites seguros. Un ajuste en curso puede terminar antes de atenderla. El estado sin trabajador activo requiere revisar recuperación.")


def trials_table(study: dict, metric: str) -> tuple[list[dict], TableGuide]:
    """Use persisted Optuna state as the authority for final trial inspection."""
    rows = [{"Trial": row["number"], "Estado": row["state"], METRICS[metric]: row["score"], "Duración (s)": row["seconds"],
             "CPU del hilo Python (s)": row["cpu_thread_seconds"], "Parámetros": json.dumps(row["parameters"], ensure_ascii=False)}
            for row in study["trials"]]
    complete = [row for row in study["trials"] if row["state"] == "COMPLETE"]
    best = (min if study["direction"] == "minimize" else max)([r["score"] for r in complete], default=None)
    finding = f"Hay {len(complete)} trials completos de {len(rows)} registrados. "
    finding += f"El mejor objetivo interno es {best:.5g}." if best is not None else "Aún no hay un mejor resultado completo."
    return rows, TableGuide("Registro persistido · " + study["name"], "Duración en segundos; CPU del hilo excluye hilos nativos. Objetivo: " + METRICS[metric],
        "Compara resultados completos dentro de este fold. Un valor podado resume solo los internos que llegó a medir.", finding,
        "Los trials comparten datos de validación interna y se seleccionan adaptativamente. Su distribución no es un intervalo de generalización.")


def winners_table(family: dict) -> tuple[list[dict], TableGuide]:
    """Compare winners descriptively; never rank candidates by outer measurements."""
    rows = [{"Fold externo": fold["fold"], "Trial ganador interno": fold["winner_trial"],
             "Objetivo interno": fold["best_inner_objective"], "Objetivo externo": fold["outer_objective"],
             "F1 macro externo": fold["outer_score"], "Parámetros": json.dumps(fold["winner"], ensure_ascii=False)} for fold in family["folds"]]
    chosen = family["validation_selection"]["winner"]
    return rows, TableGuide("Ganadores internos y mediciones externas", "Una observación externa por fold; objetivos en la escala configurada.",
        "Cada ganador procede de tres folds internos. La configuración final se elige después en el 15 % de Validación.",
        f"Hay {len(rows)} ganadores externos descriptivos. La selección de Validación obtuvo {chosen['objective']:.5g}.",
        "Los resultados externos no intervienen en los samplers, pruners ni en la selección final de parámetros.")


def stability_table(family: dict, options: SearchOptions) -> tuple[list[dict], TableGuide]:
    """Describe the observed consistency of parameters across the five inner winners."""
    rows = []
    for name in options.space:
        values = [fold["winner"][name] for fold in family["folds"]]
        counts = Counter(json.dumps(value, ensure_ascii=False) for value in values)
        mode, frequency = counts.most_common(1)[0]
        numeric = all(type(value) in (int, float) for value in values)
        rows.append({"Parámetro": name, "Ganadores (n)": len(values), "Valores distintos": len(counts), "Moda observada": mode,
                     "Frecuencia modal (0–1)": frequency / len(values), "Mínimo": min(values) if numeric else None,
                     "Mediana": median(values) if numeric else None, "Máximo": max(values) if numeric else None})
    stable = sum(row["Valores distintos"] == 1 for row in rows)
    return rows, TableGuide("Estabilidad descriptiva de parámetros entre folds", "Conteos, frecuencia modal y unidades originales del parámetro.",
        "Una sola variante indica coincidencia de los ganadores observados; las diferencias reflejan búsqueda y datos distintos.",
        f"{stable} de {len(rows)} parámetros coinciden en todos los ganadores registrados.",
        "Los cinco conjuntos de entrenamiento se solapan. Esta frecuencia carece de interpretación causal o de garantía fuera de muestra.")


def _axes(settings, title: str, x: str, y: str):
    figure = Figure(figsize=(settings.reporting.figure_width_inches, settings.reporting.figure_height_inches), layout="constrained")
    axis = figure.subplots()
    axis.set(title=title, xlabel=x, ylabel=y)
    axis.grid(axis="y", alpha=.2)
    return figure, axis


def _guide(title: str, study: dict, options: SearchOptions, finding: str, limitation: str) -> TableGuide:
    if study.get("source") == "sintetico":
        title += " · prueba sintética"
    return TableGuide(title, f"Estudio {study['name']}. Objetivo: {METRICS[options.metric]}. "
        "Las métricas de calidad son adimensionales; latencia en segundos.",
        "Lee cada observación dentro de su estudio y fold. Consulta parámetros y estado en el registro persistido.", finding,
        limitation + " Los datos sintéticos, cuando se seleccionan, verifican el procedimiento y no acreditan calidad real.")


def history_plot(study: dict, options: SearchOptions, settings) -> tuple[Figure | None, TableGuide]:
    """Show complete results, partial pruned values and best complete history."""
    trials = [row for row in study["trials"] if row["score"] is not None and row["state"] in ("COMPLETE", "PRUNED")]
    guide = _guide("Historial de optimización", study, options, f"Se registraron {len(trials)} valores observables.",
        "La línea de mejor valor solo usa COMPLETE. Un punto podado puede contener menos de tres internos.")
    if not trials:
        return None, guide
    with rc_context(figure_style(settings.figures)):
        figure, axis = _axes(settings, guide.title, "Trial (índice dentro del estudio)", METRICS[options.metric])
        for status, marker, color in (("COMPLETE", "o", settings.figures.palette[0]), ("PRUNED", "x", settings.figures.palette[1])):
            values = [row for row in trials if row["state"] == status]
            if values:
                axis.scatter([r["number"] for r in values], [r["score"] for r in values], marker=marker, color=color, label=status)
        complete = [r for r in trials if r["state"] == "COMPLETE"]
        if complete:
            best = np.minimum.accumulate if options.direction == "minimize" else np.maximum.accumulate
            axis.step([r["number"] for r in complete], best([r["score"] for r in complete]), where="post", label="Mejor completo provisional", color=settings.figures.palette[2])
        axis.legend()
    return figure, guide


def importance_plot(study: dict, options: SearchOptions, settings) -> tuple[Figure | None, TableGuide]:
    """Visualize fANOVA only after its evidence gates pass."""
    importance = study.get("importance", {"values": {}, "reason": "Inspección pendiente."})
    values = importance["values"]
    finding = (f"La mayor importancia estimada es {max(values, key=values.get)} con {max(values.values()):.3f}." if values else
               "No aplicable: " + importance["reason"])
    guide = _guide("Importancia exploratoria de hiperparámetros", study, options, finding,
        "fANOVA depende de la cobertura del espacio y del bosque ajustado a los trials. No demuestra causalidad ni significancia estadística.")
    if not values:
        return None, guide
    with rc_context(figure_style(settings.figures)):
        figure, axis = _axes(settings, guide.title, "Importancia normalizada (0–1)", "Parámetro")
        axis.barh(list(values), list(values.values()), color=settings.figures.palette[0], label="fANOVA")
        axis.set_xlim(0, 1)
        axis.legend()
    return figure, guide


def _coordinates(trials: list[dict], name: str, options: SearchOptions) -> tuple[np.ndarray, str, list[str] | None]:
    values = [r["parameters"][name] for r in trials]
    distribution = options.space[name]
    if distribution.kind == "categorical":
        labels = [str(value) for value in distribution.choices]
        return np.array([distribution.choices.index(value) for value in values], dtype=float), name + " (categorías)", labels
    numbers = np.array(values, dtype=float)
    return (np.log10(numbers), "log10(" + name + ")", None) if distribution.log else (numbers, name, None)


def slice_plot(study: dict, options: SearchOptions, settings) -> tuple[Figure | None, TableGuide]:
    """Scatter actual objective values against each sampled coordinate."""
    trials = [r for r in study["trials"] if r["state"] == "COMPLETE"]
    guide = _guide("Slice de parámetros y objetivo", study, options, f"Hay {len(trials)} trials completos para las relaciones observadas.",
        "Los demás parámetros varían simultáneamente. Una asociación gráfica no aísla el efecto del parámetro.")
    if not trials:
        return None, guide
    names = list(options.space)[:settings.optimization.max_plot_parameters]
    with rc_context(figure_style(settings.figures)):
        figure = Figure(figsize=(settings.reporting.figure_width_inches, settings.reporting.figure_height_inches * len(names)), layout="constrained")
        figure.suptitle(guide.title)
        for i, name in enumerate(names, 1):
            axis = figure.add_subplot(len(names), 1, i)
            x, label, ticks = _coordinates(trials, name, options)
            axis.scatter(x, [r["score"] for r in trials], color=settings.figures.palette[0], label="Trials completos")
            if ticks:
                axis.set_xticks(range(len(ticks)), ticks)
            axis.set(xlabel=label, ylabel=METRICS[options.metric], title="Slice · " + name)
            axis.legend()
    return figure, guide


def parallel_plot(study: dict, options: SearchOptions, settings) -> tuple[Figure | None, TableGuide]:
    """Normalize individual axes and explicitly disclose categorical encodings."""
    trials = [r for r in study["trials"] if r["state"] == "COMPLETE"]
    names = list(options.space)[:settings.optimization.max_plot_parameters]
    guide = _guide("Coordenadas paralelas de los trials", study, options, f"Se representan {len(trials)} trials y {len(names)} parámetros.",
        "Cada eje se reescala a 0–1 dentro del estudio. Las categorías usan su orden configurado, sin distancia semántica. El color representa el objetivo.")
    if not trials or len(names) < 2:
        return None, guide
    with rc_context(figure_style(settings.figures)):
        figure, axis = _axes(settings, guide.title, "Parámetro; categorías según tabla del espacio", "Coordenada reescalada (0–1)")
        columns = []
        for name in names:
            values, _, _ = _coordinates(trials, name, options)
            width = float(np.ptp(values))
            columns.append((values - values.min()) / width if width else np.zeros_like(values))
        table = np.array(columns).T
        objective = np.array([r["score"] for r in trials])
        normalized = (objective - objective.min()) / np.ptp(objective) if np.ptp(objective) else np.zeros_like(objective)
        cmap = colormaps["viridis"]
        for values, color in zip(table, normalized):
            axis.plot(range(len(names)), values, color=cmap(color), alpha=.65)
        axis.set_xticks(range(len(names)), [name + (" (log)" if options.space[name].log else " (cat.)" if options.space[name].kind == "categorical" else "") for name in names], rotation=15)
        from matplotlib.cm import ScalarMappable
        from matplotlib.colors import Normalize
        color = ScalarMappable(norm=Normalize(vmin=objective.min(), vmax=objective.max()), cmap=cmap)
        figure.colorbar(color, ax=axis, label=METRICS[options.metric])
    return figure, guide


def contour_plot(study: dict, options: SearchOptions, settings) -> tuple[Figure | None, TableGuide]:
    """Interpolate only inside the convex hull of sufficiently diverse numeric trials."""
    trials = [r for r in study["trials"] if r["state"] == "COMPLETE"]
    names = [name for name, value in options.space.items() if value.kind != "categorical"][:2]
    reason = None
    if len(trials) < settings.optimization.contour_min_points or len(names) < 2:
        reason = "Faltan trials completos o dos parámetros numéricos."
    elif len({r["score"] for r in trials}) < 2:
        reason = "El objetivo es constante."
    if reason is None:
        x, xname, _ = _coordinates(trials, names[0], options)
        y, yname, _ = _coordinates(trials, names[1], options)
        if np.linalg.matrix_rank(np.column_stack((x - x.mean(), y - y.mean()))) < 2:
            reason = "Las observaciones son constantes o colineales."
    guide = _guide("Contorno exploratorio entre dos parámetros", study, options,
        "No aplicable: " + reason if reason else f"Interpolación basada en {len(trials)} trials completos con objetivo variable.",
        "La superficie interpola observaciones, sin nuevas evaluaciones. Otros parámetros pueden cambiar entre puntos. No representa incertidumbre ni una función causal.")
    if reason:
        return None, guide
    with rc_context(figure_style(settings.figures)):
        figure, axis = _axes(settings, guide.title, xname, yname)
        try:
            scores = np.array([r["score"] for r in trials])
            surface = axis.tricontourf(x, y, scores, cmap="viridis",
                levels=np.linspace(scores.min(), scores.max(), settings.data.histogram_bins + 1))
        except (ValueError, RuntimeError):
            return None, _guide(guide.title, study, options, "No aplicable: geometría insuficiente para triangular los puntos.", guide.limitations)
        axis.scatter(x, y, color=settings.figures.palette[-1], s=14, label="Trials observados")
        axis.legend()
        axis.margins(x=.03, y=.04)
        figure.colorbar(surface, ax=axis, label=METRICS[options.metric])
    return figure, guide


def distribution_plot(study: dict, options: SearchOptions, settings) -> tuple[Figure | None, TableGuide]:
    """Describe the searched objective distribution without treating trials as IID samples."""
    values = [row["score"] for row in study["trials"] if row["state"] == "COMPLETE"]
    finding = f"Hay {len(values)} trials completos." + (f" La mediana observada es {median(values):.5g}." if values else "")
    guide = _guide("Distribución de objetivos completos", study, options, finding,
        "El sampler y el pruner condicionan qué valores se observan. Esta distribución no estima desempeño poblacional.")
    if not values:
        return None, guide
    with rc_context(figure_style(settings.figures)):
        figure, axis = _axes(settings, guide.title, METRICS[options.metric], "Trials completos (n)")
        axis.hist(values, bins=min(len(values), settings.data.histogram_bins), color=settings.figures.palette[0], label="Objetivo interno")
        axis.legend()
    return figure, guide


def stability_plot(family: dict, options: SearchOptions, settings, *, source: str | None = None) -> tuple[Figure | None, TableGuide]:
    """Plot winner coordinates across folds with explicit per-parameter scaling."""
    pseudo = [{"parameters": fold["winner"]} for fold in family["folds"]]
    names = list(options.space)[:settings.optimization.max_plot_parameters]
    rows, base_guide = stability_table(family, options)
    title = "Variación de ganadores entre folds" + (" · prueba sintética" if source == "sintetico" else "")
    guide = TableGuide(title, "Coordenadas reescaladas a 0–1 por parámetro; fold como índice.",
        "Sigue cada parámetro y consulta sus valores originales en la tabla de estabilidad.", base_guide.finding,
        "Las escalas de parámetros distintos no son comparables entre sí. Las categorías usan el orden configurado. " + base_guide.limitations)
    with rc_context(figure_style(settings.figures)):
        figure, axis = _axes(settings, guide.title, "Fold externo (índice)", "Coordenada del ganador (0–1)")
        for name in names:
            values, _, _ = _coordinates(pseudo, name, options)
            width = float(np.ptp(values))
            scaled = (values - values.min()) / width if width else np.zeros_like(values)
            axis.plot([fold["fold"] for fold in family["folds"]], scaled, marker="o", label=name)
        axis.legend()
    return figure, guide
