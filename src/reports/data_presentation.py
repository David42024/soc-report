"""Scientific plots and reading guides for the data module."""
from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from textwrap import shorten

from matplotlib import rc_context
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from src.data.models import DataRecord, DataSource, LABEL_NAMES
from src.data.statistics import NATURE_NAMES
from src.reports.figures import figure_style
from src.reports.presentation import TableGuide
from src.utils.config import FigureSettings


def inventory_rows(sources: Sequence[DataSource]) -> list[dict]:
    rows = []
    for source in sources:
        nature = Counter(record.nature for record in source.records)
        rows.append({
            "Fuente": source.name, "Formato": source.format, "Estado": source.status, "Versión": source.revision,
            "Filas (registros)": len(source.records) if source.sha256 else None, "Columnas (cantidad)": len(source.columns),
            "Reales (registros)": nature["real"], "DEMO (registros)": nature["demo"], "Sintéticos (registros)": nature["sintetica"],
        })
    return rows


def coverage_comparison(sources: Sequence[DataSource], field: str) -> list[dict]:
    rows = []
    for source in sources:
        n = len(source.records)
        observed = sum(bool(record.label(field).values) for record in source.records)
        human = sum(record.nature == "real" and record.label(field).human_reference for record in source.records)
        rows.append({
            "Fuente": source.name, "Total (registros)": n, "Con valor (registros)": observed, "Referencia humana (registros)": human,
            "Con valor (%)": round(100 * observed / n, 2) if n else None,
            "Referencia humana (%)": round(100 * human / n, 2) if n else None,
        })
    return rows


def _plot(*, height: float = 3.5) -> tuple[Figure, Axes]:
    figure = Figure(figsize=(7.2, height), layout="constrained")
    axes = figure.subplots()
    return figure, axes


def coverage_plot(rows: list[dict], field: str, settings: FigureSettings) -> tuple[Figure, TableGuide]:
    shown = [row for row in rows if row["Total (registros)"]]
    with rc_context({**figure_style(settings), "text.parse_math": False}):
        figure, axes = _plot(height=0.43 * len(shown) + 1.8)
        positions = list(range(len(shown)))
        axes.barh([index - 0.16 for index in positions], [row["Con valor (%)"] for row in shown], 0.3,
                  color=settings.palette[0], label="Valor disponible")
        axes.barh([index + 0.16 for index in positions], [row["Referencia humana (%)"] for row in shown], 0.3,
                  color=settings.palette[1], label="Referencia humana")
        axes.set_yticks(positions, [shorten(row["Fuente"], width=34) for row in shown])
        axes.set(xlabel="Registros de la fuente (%)", ylabel="Fuente", xlim=(0, 100), title="Cobertura de " + LABEL_NAMES[field])
        axes.invert_yaxis()
        axes.legend(loc="lower right")
    human_sources = sum(row["Referencia humana (registros)"] > 0 for row in shown)
    return figure, TableGuide(
        "Cobertura de " + LABEL_NAMES[field], "Azul indica valor disponible y naranja indica referencia humana. Porcentajes por fuente.",
        "Compara cada par de barras sobre el número de registros de esa fuente.",
        f"{human_sources} de {len(shown)} fuentes con registros aportan al menos una referencia humana para esta variable.",
        "Las etiquetas externas, simuladas y predichas tienen procedencias distintas. Los conteos de fuentes pueden compartir incidentes.",
    )


def category_plot(rows: list[dict], title: str, settings: FigureSettings, limit: int) -> tuple[Figure, TableGuide]:
    shown = sorted(rows, key=lambda row: (-row["Frecuencia (registros)"], row["Categoría"]))[:limit]
    with rc_context({**figure_style(settings), "text.parse_math": False}):
        figure, axes = _plot(height=0.32 * len(shown) + 1.5)
        axes.barh(range(len(shown)), [row["Frecuencia relativa (%)"] for row in shown], color=settings.palette[0])
        axes.set_yticks(range(len(shown)), [shorten(row["Categoría"], width=42) for row in shown])
        axes.invert_yaxis()
        axes.set(xlabel="Registros válidos del estrato (%)", ylabel="Categoría", xlim=(0, 100), title=title)
    n = shown[0]["Denominador (registros válidos)"]
    most = max(row["Frecuencia (registros)"] for row in shown)
    return figure, TableGuide(title, "Barras con porcentaje del estrato seleccionado.",
        "Compara las categorías dentro de la misma procedencia y naturaleza.",
        f"La mayor categoría se observa en {most} de {n} registros válidos.",
        f"Se dibujan {len(shown)} de {len(rows)} categorías. Una fila con varias etiquetas contribuye una vez a cada categoría.")


def missing_plot(rows: list[dict], settings: FigureSettings) -> tuple[Figure, TableGuide]:
    total = rows[0]["Total (registros)"]
    human = [row["Referencia humana (registros)"] for row in rows]
    observed = [row["Válidos (registros)"] - human[index] for index, row in enumerate(rows)]
    missing = [row["Faltantes (registros)"] for row in rows]
    with rc_context(figure_style(settings)):
        figure, axes = _plot(height=0.42 * len(rows) + 2.4)
        positions = list(range(len(rows)))
        axes.barh(positions, human, color=settings.palette[0], label="Referencia humana")
        axes.barh(positions, observed, left=human, color=settings.palette[1], label="Otro valor disponible")
        axes.barh(positions, missing, left=[left + right for left, right in zip(human, observed)],
                  color=settings.palette[4], label="Faltante")
        axes.set_yticks(positions, [row["Variable"] for row in rows])
        axes.invert_yaxis()
        axes.set(xlabel="Registros (cantidad)", ylabel="Variable", xlim=(0, total), title="Disponibilidad de etiquetas")
        axes.legend(loc="upper center", bbox_to_anchor=(0.5, -0.17), ncols=3)
    greatest = max(rows, key=lambda row: row["Faltantes (registros)"])
    return figure, TableGuide("Disponibilidad de etiquetas", "Cada barra representa todos los registros de la selección.",
        "Lee los tramos de referencia humana, otros valores disponibles y faltantes en el eje de conteo.",
        f"{greatest['Variable']} tiene {greatest['Faltantes (registros)']} faltantes de {total} registros.",
        "La cobertura se calcula por variable. Los valores disponibles tienen distintos niveles de respaldo.")


def term_plot(rows: list[dict], documents: int, settings: FigureSettings, limit: int) -> tuple[Figure, TableGuide]:
    shown = rows[:limit]
    with rc_context(figure_style(settings)):
        figure, axes = _plot(height=0.32 * len(shown) + 1.5)
        axes.barh(range(len(shown)), [row["Frecuencia (apariciones)"] for row in shown], color=settings.palette[0])
        axes.set_yticks(range(len(shown)), [row["Término"] for row in shown])
        axes.invert_yaxis()
        axes.set(xlabel="Frecuencia (apariciones)", ylabel="Término", title="Términos técnicos más frecuentes")
    top = shown[0]
    return figure, TableGuide("Términos técnicos más frecuentes", "Las barras cuentan apariciones en descripciones protegidas.",
        "Cada documento puede contribuir varias apariciones del mismo término.",
        f"«{top['Término']}» aparece {top['Frecuencia (apariciones)']} veces en {top['Documentos (registros)']} de {documents} documentos.",
        f"Se muestran {len(shown)} de {len(rows)} términos del vocabulario configurado. Los términos compuestos pueden solaparse.")


def histogram(values: list[float], title: str, unit: str, settings: FigureSettings, bins: int) -> tuple[Figure, TableGuide]:
    with rc_context(figure_style(settings)):
        figure, axes = _plot()
        axes.hist(values, bins=min(bins, len(set(values))), color=settings.palette[0], edgecolor="white")
        axes.set(xlabel=f"{title} ({unit})", ylabel="Frecuencia (registros)", title=title)
    return figure, TableGuide(title, f"Cada barra cuenta registros en un intervalo medido en {unit}.",
        "Lee el intervalo en el eje horizontal y el número de observaciones en el vertical.",
        f"{len(values)} observaciones válidas abarcan de {min(values):.3g} a {max(values):.3g} {unit}.",
        "Se omiten los valores faltantes. La distribución describe la selección actual.")


def length_comparison(series: list[tuple[str, list[float]]], settings: FigureSettings) -> tuple[Figure, TableGuide]:
    with rc_context({**figure_style(settings), "text.parse_math": False}):
        figure, axes = _plot(height=0.48 * len(series) + 1.9)
        axes.boxplot([values for _, values in series], orientation="horizontal", showfliers=True,
                     tick_labels=[shorten(f"{name} (n={len(values)})", width=39) for name, values in series])
        axes.set(xlabel="Longitud de la descripción protegida (caracteres)", ylabel="Fuente", title="Longitud del texto por fuente")
    lengths = [value for _, values in series for value in values]
    return figure, TableGuide("Longitud del texto por fuente", "Caja Q1–Q3, línea de mediana, bigotes de 1,5 IQR y puntos fuera de los bigotes.",
        "Compara la dispersión en caracteres entre los textos disponibles de cada fuente.",
        f"{len(lengths)} descripciones de {len(series)} fuentes abarcan de {min(lengths):g} a {max(lengths):g} caracteres.",
        "Los textos se miden después de protegerlos. Hay fuentes con incidentes compartidos y muestreos distintos.")


def record_rows(records: Sequence[DataRecord]) -> list[dict]:
    """Show protected metadata, with the original prediction available separately."""
    return [{
        "Incidente": record.incident_id, "Título protegido": record.title, "Naturaleza": NATURE_NAMES[record.nature],
        "Tipo SOC": ", ".join(record.label("tipo").values), "Severidad": ", ".join(record.label("severidad").values),
        "Activo afectado": ", ".join(record.label("activo_afectado").values),
        "Tipo fuente": ", ".join(record.label("tipo_fuente").values or record.label("clase_simulada").values),
        "Grupo declarado": record.group, "Reserva": record.partition, "Revisión": record.review_state,
        "Versión vigente": record.applied_version,
    } for record in records]
