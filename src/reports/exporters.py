"""Scientific layouts reusing the SOC PDF, Word and Excel serialization engines."""
from __future__ import annotations

from base64 import b64encode
from dataclasses import asdict, dataclass
from datetime import datetime
from html import escape
from io import BytesIO
import json
from threading import RLock
from textwrap import fill
from zipfile import ZIP_DEFLATED, ZipFile

from docx import Document
from docx.document import Document as WordDocument
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from matplotlib import rc_context
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator, PercentFormatter
import numpy as np
from openpyxl import Workbook
from openpyxl.drawing.image import Image as SheetImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.workbook.properties import CalcProperties
from openpyxl.worksheet.worksheet import Worksheet

from backend.exports import EXPORT_MIME, office_bytes, pdf_bytes
from src.data.models import content_hash
from src.reports.figures import export_png, figure_style
from src.reports.presentation import TableGuide
from src.reports.scientific import Cell, ReportFigure, ReportSnapshot, ReportTable, display_cell, guide_items
from src.utils.config import AnalyticsSettings

PLOT_LOCK = RLock()


@dataclass(frozen=True)
class FigureExport:
    spec: ReportFigure
    png: bytes
    svg: bytes


@dataclass(frozen=True)
class ReportExport:
    """Download payload isolated to the authenticated browser session."""

    filename: str
    mime: str
    data: bytes


def snapshot_payload(snapshot: ReportSnapshot) -> dict:
    """Serialize only aggregate scientific content with an independent digest."""
    payload = asdict(snapshot)
    payload["request"] = snapshot.request.model_dump(mode="json")
    return {"schema_version": 1, "phase": 5, **payload}


def snapshot_digest(snapshot: ReportSnapshot) -> str:
    return content_hash(snapshot_payload(snapshot))


def render_figure(spec: ReportFigure, settings: AnalyticsSettings) -> FigureExport:
    """Create accessible raster and vector versions of an observed aggregate."""
    with PLOT_LOCK, rc_context(figure_style(settings.figures)):
        figure = Figure(figsize=(settings.reporting.figure_width_inches, settings.reporting.figure_height_inches),
                        layout="constrained")
        axis = figure.subplots()
        values = np.asarray(spec.values, dtype=float)
        axis.set(title=fill(spec.guide.title, 64), xlabel=spec.xlabel, ylabel=spec.ylabel)
        labels = [fill(label.replace("_", " "), 18) for label in spec.labels]
        if spec.matrix_rows:
            mapped = axis.imshow(values, cmap="Blues", vmin=0, vmax=1 if spec.percent else max(1, values.max()))
            legend = figure.colorbar(mapped, ax=axis)
            legend.set_label("Proporción de referencia (0–1)" if spec.percent else "Casos (n)")
            axis.set_xticks(range(len(labels)), labels, rotation=30, ha="right")
            axis.set_yticks(range(len(spec.matrix_rows)), [fill(label, 18) for label in spec.matrix_rows])
            for (i, j), value in np.ndenumerate(values):
                axis.text(j, i, f"{value:.0%}" if spec.percent else f"{value:.0f}", ha="center", va="center",
                          color="white" if value > (0.5 if spec.percent else values.max() * .5) else "#182B3A")
        else:
            axis.bar(range(len(labels)), values[0], color=settings.figures.palette[0], label=spec.ylabel)
            axis.set_xticks(range(len(labels)), labels, rotation=25, ha="right")
            axis.yaxis.set_major_locator(MaxNLocator(integer=True))
            axis.set_ylim(bottom=0)
            axis.grid(axis="y", alpha=.2)
            axis.set_axisbelow(True)
            axis.legend()
            if spec.percent:
                axis.yaxis.set_major_formatter(PercentFormatter(1))
        png = export_png(figure, settings.figures)
        svg = BytesIO()
        figure.savefig(svg, format="svg", bbox_inches="tight", metadata={"Date": None, "Description": spec.guide.finding})
        figure.clear()
        return FigureExport(spec, png, svg.getvalue())


def _html_guide(guide: TableGuide) -> str:
    return '<div class="guide">' + "".join(
        f"<p><strong>{escape(label)}</strong> {escape(text)}</p>" for label, text in guide_items(guide)) + "</div>"


def _html_table(table: ReportTable, number: int) -> str:
    header = "".join(f"<th>{escape(label)}</th>" for label in table.columns)
    rows = "".join("<tr>" + "".join(
        f'<td class="{"numeric" if isinstance(value, (int, float)) else "text"}">'
        f"{escape(display_cell(value, table.style(index)))}</td>" for index, value in enumerate(row)) + "</tr>" for row in table.rows)
    return (f"<h3>Tabla {number}. {escape(table.guide.title)}</h3>"
            f"<table><thead><tr>{header}</tr></thead><tbody>{rows}</tbody></table>" + _html_guide(table.guide))


def _metadata(snapshot: ReportSnapshot) -> tuple[tuple[str, str], ...]:
    return (("Versión de informe", snapshot.run_id), ("Generado UTC", snapshot.generated_at),
            ("SHA-256 del contenido", snapshot_digest(snapshot)), ("Intervalo operativo", snapshot.period),
            ("Secciones seleccionadas", ", ".join(snapshot.request.sections)), *snapshot.provenance)


def _methodology() -> str:
    return ("Se consolidan resultados publicados y verificados por SHA-256. La selección de configuraciones, "
            "los folds, las métricas, los IC y los contrastes conservan las definiciones de sus corridas. "
            "El periodo elegido filtra la recepción de reportes operativos en hora de Lima. "
            "Los experimentos conservan su cohorte y fecha originales. Un guion largo indica valor no disponible.")


def scientific_pdf(snapshot: ReportSnapshot, figures: tuple[FigureExport, ...]) -> bytes:
    """Format paginated HTML with repeated headers and vector scientific figures."""
    content = ["""<!doctype html><html lang="es"><head><meta charset="utf-8">
    <style>
    @page {size:A4; margin:19mm 17mm 19mm;
      @bottom-left {content:"SOC · Informe de evidencia";font-size:8pt;color:#52616d}
      @bottom-right {content:counter(page) " / " counter(pages);font-size:8pt;color:#52616d}}
    body {font:10pt Arial,sans-serif;line-height:1.35;color:#182B3A}
    h1 {font-size:25pt;color:#005f91;margin:0 0 12pt} h2 {font-size:16pt;color:#005f91;margin-top:20pt}
    h3 {font-size:11pt;margin:16pt 0 6pt} h2,h3 {break-after:avoid}
    p {margin:5pt 0} .metadata {font-size:8pt;overflow-wrap:anywhere}
    table {width:100%;border-collapse:collapse;table-layout:fixed;font-size:8pt}
    thead {display:table-header-group} th {background:#e8f0f6;border-top:1pt solid #5d7685;text-align:left}
    th,td {padding:5pt 4pt;border-bottom:.5pt solid #cedae1;overflow-wrap:anywhere;vertical-align:top}
    .numeric {text-align:right} tr {break-inside:avoid} .guide {font-size:8pt;color:#3e515d;margin:7pt 0 12pt}
    figure {margin:14pt 0 8pt;break-inside:avoid} img {width:100%}
    .provenance {font-size:8pt;overflow-wrap:anywhere}
    </style></head><body>""",
               f"<h1>{escape(snapshot.template.title)}</h1>",
               f"<p>{escape(snapshot.template.context)}</p>",
               f'<p class="metadata">Versión {escape(snapshot.run_id)}<br>Generado UTC {escape(snapshot.generated_at)}<br>'
               f"{escape(snapshot.period)}</p><h2>Contexto y metodología</h2><p>{escape(_methodology())}</p>"]
    table_number, figure_number = 0, 0
    for index, section in enumerate(snapshot.sections, 1):
        content.append(f"<h2>{index}. {escape(section.title)}</h2>")
        content.extend(f"<p>{escape(note)}</p>" for note in section.notes)
        for table in section.tables:
            table_number += 1
            content.append(_html_table(table, table_number))
        for _ in section.figures:
            exported = figures[figure_number]
            figure_number += 1
            encoded = b64encode(exported.svg).decode("ascii")
            content.append(f'<figure><h3>Figura {figure_number}. {escape(exported.spec.guide.title)}</h3>'
                           f'<img src="data:image/svg+xml;base64,{encoded}" alt="{escape(exported.spec.guide.title)}"></figure>')
            content.append(_html_guide(exported.spec.guide))
    content.append("<h2>Discusión, limitaciones y conclusiones</h2>")
    content.extend(f"<p>{escape(note)}</p>" for note in snapshot.conclusions)
    content.append("<h2>Reproducibilidad y trazabilidad</h2><div class=\"provenance\">")
    content.extend(f"<p><strong>{escape(key)}</strong> {escape(value)}</p>" for key, value in _metadata(snapshot))
    content.append("</div></body></html>")
    return pdf_bytes("".join(content))


def _word_guide(document: WordDocument, guide: TableGuide) -> None:
    for label, text in guide_items(guide):
        paragraph = document.add_paragraph(style="Caption")
        paragraph.add_run(label + ". ").bold = True
        paragraph.add_run(text)


def scientific_word(snapshot: ReportSnapshot, figures: tuple[FigureExport, ...]) -> bytes:
    """Build editable, numbered Word tables and captions with repeatable headers."""
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Inches(8.2677), Inches(11.6929)
    section.top_margin = section.bottom_margin = Inches(.72)
    section.left_margin = section.right_margin = Inches(.67)
    for name in ("Normal", "Title", "Heading 1", "Heading 2", "Caption"):
        style = document.styles[name]
        style.font.name = "Arial"
        style.font.color.rgb = RGBColor.from_string("182B3A")
    document.styles["Normal"].font.size = Pt(10)
    document.styles["Normal"].paragraph_format.space_after = Pt(5)
    document.styles["Caption"].font.size = Pt(8)
    document.styles["Caption"].font.italic = False
    document.styles["Caption"].font.bold = False
    document.styles["Title"].font.size = Pt(25)
    document.styles["Title"].font.color.rgb = RGBColor(0, 0, 0)
    for border in document.styles["Title"].element.xpath(".//w:pBdr"):
        border.getparent().remove(border)
    for name in ("Heading 1", "Heading 2"):
        document.styles[name].font.color.rgb = RGBColor.from_string("005F91")
    footer = section.footer.paragraphs[0]
    footer.text = "SOC · Informe de evidencia                                     "
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    document.core_properties.title = snapshot.template.title
    document.core_properties.subject = snapshot.run_id
    document.core_properties.author = "SOC"
    document.core_properties.created = datetime.fromisoformat(snapshot.generated_at)
    document.core_properties.modified = datetime.fromisoformat(snapshot.generated_at)
    document.add_heading(snapshot.template.title, 0)
    document.add_paragraph(snapshot.template.context)
    document.add_paragraph(f"Versión {snapshot.run_id}\nGenerado UTC {snapshot.generated_at}\n{snapshot.period}", style="Caption")
    document.add_heading("Contexto y metodología", 1)
    document.add_paragraph(_methodology())
    table_number, figure_number = 0, 0
    for index, part in enumerate(snapshot.sections, 1):
        document.add_heading(f"{index}. {part.title}", 1)
        for note in part.notes:
            document.add_paragraph(note)
        for spec in part.tables:
            table_number += 1
            document.add_heading(f"Tabla {table_number}. {spec.guide.title}", 2)
            table = document.add_table(rows=1, cols=len(spec.columns))
            table.style = "Light Shading Accent 1"
            repeat = OxmlElement("w:tblHeader")
            table.rows[0]._tr.get_or_add_trPr().append(repeat)
            for cell, label in zip(table.rows[0].cells, spec.columns):
                cell.text = label
                for run in cell.paragraphs[0].runs:
                    run.bold = True
            for values in spec.rows:
                for position, (cell, value) in enumerate(zip(table.add_row().cells, values)):
                    cell.text = display_cell(value, spec.style(position))
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        paragraph.paragraph_format.space_after = Pt(3)
                        for run in paragraph.runs:
                            run.font.size = Pt(8)
            _word_guide(document, spec.guide)
        for _ in part.figures:
            figure = figures[figure_number]
            figure_number += 1
            document.add_heading(f"Figura {figure_number}. {figure.spec.guide.title}", 2)
            document.add_picture(BytesIO(figure.png), width=Inches(6.8))
            _word_guide(document, figure.spec.guide)
    document.add_heading("Discusión, limitaciones y conclusiones", 1)
    for note in snapshot.conclusions:
        document.add_paragraph(note)
    document.add_heading("Reproducibilidad y trazabilidad", 1)
    for label, value in _metadata(snapshot):
        document.add_paragraph(label + "\n" + value, style="Caption")
    return office_bytes(document)


def _sheet_value(sheet: Worksheet, row: int, column: int, value: Cell) -> None:
    cell = sheet.cell(row, column, value)
    if isinstance(value, str):
        cell.data_type = "s"
    cell.alignment = Alignment(vertical="top", wrap_text=True)


def _sheet_paragraph(sheet: Worksheet, row: int, text: str) -> int:
    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
    _sheet_value(sheet, row, 1, text)
    sheet.row_dimensions[row].height = max(20, 13 * (1 + len(text) // 115))
    return row + 1


def _sheet_guide(sheet: Worksheet, row: int, guide: TableGuide) -> int:
    for label, value in guide_items(guide):
        row = _sheet_paragraph(sheet, row, label + ". " + value)
    return row + 1


def scientific_excel(snapshot: ReportSnapshot, figures: tuple[FigureExport, ...]) -> bytes:
    """Preserve typed observations and add formulas checking measured proportions."""
    workbook = Workbook()
    workbook.properties.title = snapshot.template.title
    workbook.properties.creator = "SOC"
    workbook.properties.created = datetime.fromisoformat(snapshot.generated_at).replace(tzinfo=None)
    workbook.properties.modified = workbook.properties.created
    workbook.calculation = CalcProperties(calcId=191029, fullCalcOnLoad=True)
    metadata = workbook.active
    metadata.title = "Metadatos"
    for row, (label, value) in enumerate(_metadata(snapshot), 1):
        _sheet_value(metadata, row, 1, label)
        metadata.merge_cells(start_row=row, start_column=2, end_row=row, end_column=6)
        _sheet_value(metadata, row, 2, value)
        metadata.row_dimensions[row].height = max(24, 14 * (1 + len(value) // 110),
                                                  14 * (1 + len(label) // 24))
    row = len(_metadata(snapshot)) + 2
    row = _sheet_paragraph(metadata, row, snapshot.template.context)
    row = _sheet_paragraph(metadata, row, _methodology())
    for note in snapshot.conclusions:
        row = _sheet_paragraph(metadata, row, note)
    for index, part in enumerate(snapshot.sections, 1):
        sheet = workbook.create_sheet(f"{index:02d} {part.title}"[:31])
        row = _sheet_paragraph(sheet, 1, part.title)
        for note in part.notes:
            row = _sheet_paragraph(sheet, row, note)
        row += 1
        for number, table in enumerate(part.tables, 1):
            row = _sheet_paragraph(sheet, row, f"Tabla {index}.{number}. {table.guide.title}")
            for column, label in enumerate(table.columns, 1):
                _sheet_value(sheet, row, column, label)
                sheet.cell(row, column).font = Font(bold=True, color="FFFFFF")
                sheet.cell(row, column).fill = PatternFill("solid", fgColor="005F91")
            if table.ratio is not None:
                _sheet_value(sheet, row, len(table.columns) + 1, "Comprobación con fórmula")
            sheet.row_dimensions[row].height = 32
            row += 1
            for values in table.rows:
                for position, value in enumerate(values):
                    _sheet_value(sheet, row, position + 1, value)
                    cell = sheet.cell(row, position + 1)
                    if isinstance(value, (int, float)):
                        formats = {"percent": "0.00%", "scientific": "0.000E+00", "decimal": "0.0000"}
                        cell.number_format = "0" if isinstance(value, int) else formats[table.style(position)]
                        cell.alignment = Alignment(horizontal="right", vertical="top")
                        cell.font = Font(color="182B3A")
                    if row % 2 == 0:
                        cell.fill = PatternFill("solid", fgColor="F0F5F8")
                if table.ratio is not None:
                    numerator, denominator = table.ratio
                    left, right = f"{get_column_letter(numerator + 1)}{row}", f"{get_column_letter(denominator + 1)}{row}"
                    cell = sheet.cell(row, len(table.columns) + 1, f'=IF({right}=0,"",{left}/{right})')
                    cell.number_format = "0.00%"
                    cell.font = Font(color="008060")
                sheet.row_dimensions[row].height = max(24, min(96, 12 * (1 + max(len(str(v)) for v in values) // 28)))
                row += 1
            row = _sheet_guide(sheet, row + 1, table.guide)
    for index, figure in enumerate(figures, 1):
        sheet = workbook.create_sheet(f"Figura {index:02d}")
        row = _sheet_paragraph(sheet, 1, f"Figura {index}. {figure.spec.guide.title}")
        image = SheetImage(BytesIO(figure.png))
        image.height = image.height * 700 / image.width
        image.width = 700
        sheet.add_image(image, f"A{row}")
        row += int(image.height / 20) + 2
        _sheet_guide(sheet, row, figure.spec.guide)
    for sheet in workbook:
        sheet.sheet_view.showGridLines = False
        sheet.freeze_panes = "B2"
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 1 if sheet.title.startswith("Figura ") else 0
        sheet.sheet_properties.tabColor = "0072B2"
        for column in range(1, max(6, sheet.max_column) + 1):
            sheet.column_dimensions[get_column_letter(column)].width = 18 if sheet.title.startswith("Figura ") else 26
        for cells in sheet:
            for cell in cells:
                if cell.font == Font():
                    cell.font = Font(name="Arial", size=10, color="182B3A")
    return office_bytes(workbook)


def export_all(snapshot: ReportSnapshot, settings: AnalyticsSettings) -> tuple[ReportExport, ...]:
    """Render every output from one frozen report without requesting new inference."""
    figures = tuple(render_figure(spec, settings) for section in snapshot.sections for spec in section.figures)
    outputs = (
        ReportExport(snapshot.filename + ".pdf", EXPORT_MIME["pdf"], scientific_pdf(snapshot, figures)),
        ReportExport(snapshot.filename + ".docx", EXPORT_MIME["docx"], scientific_word(snapshot, figures)),
        ReportExport(snapshot.filename + ".xlsx", EXPORT_MIME["xlsx"], scientific_excel(snapshot, figures)),
    )
    archive = BytesIO()
    with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
        for index, figure in enumerate(figures, 1):
            bundle.writestr(f"figura-{index:02d}.png", figure.png)
            bundle.writestr(f"figura-{index:02d}.svg", figure.svg)
        bundle.writestr("interpretaciones.json", json.dumps(
            [asdict(figure.spec.guide) for figure in figures], ensure_ascii=False, indent=2))
    return (*outputs, ReportExport(snapshot.filename + "-figuras.zip", "application/zip", archive.getvalue()))
