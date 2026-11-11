"""Shared, aggregate-only document model for preview and all export formats."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from backend.insights import DateRange
from src.data.manifest import VERSION_ID
from src.reports.presentation import TableGuide

TemplateId = Literal["academico", "tecnico", "ejecutivo"]
SectionId = Literal["datos", "entrenamiento", "evaluacion", "explicabilidad", "operacion"]
VersionId = Annotated[str, Field(pattern=VERSION_ID.pattern)]
Cell = str | int | float | None
NumberStyle = Literal["decimal", "percent", "scientific"]

SECTION_TITLES: dict[SectionId, str] = {
    "datos": "Datos y calidad",
    "entrenamiento": "Entrenamiento y experimentación",
    "evaluacion": "Evaluación estadística",
    "explicabilidad": "Explicabilidad",
    "operacion": "Clasificación operativa y SLA",
}


@dataclass(frozen=True)
class Template:
    title: str
    context: str
    sections: tuple[SectionId, ...]


TEMPLATES: dict[TemplateId, Template] = {
    "academico": Template(
        "Informe académico completo",
        "Caso 06 del SOC. El informe reúne evidencia de calidad de datos, metodología experimental, "
        "validación de modelos y explicabilidad de la clasificación de reportes de seguridad.",
        ("datos", "entrenamiento", "evaluacion", "explicabilidad", "operacion"),
    ),
    "tecnico": Template(
        "Informe técnico SOC",
        "Seguimiento de clasificación, derivaciones a revisión humana y cumplimiento de SLA. "
        "Los resultados experimentales adjuntos describen las cohortes identificadas.",
        ("operacion", "evaluacion", "explicabilidad"),
    ),
    "ejecutivo": Template(
        "Resumen ejecutivo",
        "Indicadores de atención y brechas de evidencia para el seguimiento del SOC.",
        ("operacion", "datos"),
    ),
}


class ReportRequest(DateRange):
    """Explicit evidence selection and operational date window."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    template: TemplateId
    sections: tuple[SectionId, ...] = Field(min_length=1, max_length=len(SECTION_TITLES))
    manifest: VersionId | None = None
    experiments: tuple[VersionId, ...] = ()
    evaluations: tuple[VersionId, ...] = ()
    explanations: tuple[VersionId, ...] = ()


@dataclass(frozen=True)
class ReportTable:
    guide: TableGuide
    columns: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...]
    formats: tuple[tuple[int, NumberStyle], ...] = ()
    ratio: tuple[int, int] | None = None

    def style(self, index: int) -> NumberStyle:
        return next((style for column, style in self.formats if column == index), "decimal")


@dataclass(frozen=True)
class ReportFigure:
    guide: TableGuide
    xlabel: str
    ylabel: str
    labels: tuple[str, ...]
    values: tuple[tuple[float | int | None, ...], ...]
    matrix_rows: tuple[str, ...] = ()
    percent: bool = False


@dataclass(frozen=True)
class ReportSection:
    title: str
    notes: tuple[str, ...] = ()
    tables: tuple[ReportTable, ...] = ()
    figures: tuple[ReportFigure, ...] = ()


@dataclass(frozen=True)
class ReportSnapshot:
    """Frozen scientific content and provenance captured once for every format."""

    run_id: str
    generated_at: str
    request: ReportRequest
    sections: tuple[ReportSection, ...]
    provenance: tuple[tuple[str, str], ...]
    conclusions: tuple[str, ...]

    @property
    def filename(self) -> str:
        return f"soc-{self.request.template}-{self.run_id}"

    @property
    def template(self) -> Template:
        return TEMPLATES[self.request.template]

    @property
    def period(self) -> str:
        start, end = self.request.desde, self.request.hasta
        if start and end:
            return f"Del {start.isoformat()} al {end.isoformat()}, inclusive, hora de Lima"
        if start:
            return f"Desde {start.isoformat()}, inclusive, hora de Lima"
        if end:
            return f"Hasta {end.isoformat()}, inclusive, hora de Lima"
        return "Todas las fechas de recepción disponibles, hora de Lima"


def display_cell(value: Cell, style: NumberStyle = "decimal") -> str:
    """Format one value consistently across documents and preview."""
    if value is None:
        return "—"
    if isinstance(value, (int, float)) and style == "percent":
        return f"{value:.2%}"
    if isinstance(value, (int, float)) and style == "scientific":
        return f"{value:.3e}"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def guide_items(guide: TableGuide) -> tuple[tuple[str, str], ...]:
    """Ordered annotations shared by all output formats."""
    return (("Variables y unidades", guide.legend), ("Cómo leerlo", guide.how_to_read),
            ("Hallazgo clave", guide.finding), ("Limitaciones", guide.limitations))
