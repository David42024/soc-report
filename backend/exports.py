"""Downloadable reports generated from the same data used by the operator board."""
from html import escape
from io import BytesIO
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from docx import Document
from docx.document import Document as WordDocument
from docx.shared import RGBColor
from openpyxl import Workbook
from fastapi import HTTPException

EXPORT_MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

FIELDS = [
    ("id", "ID"), ("titulo", "Título"), ("tipo", "Tipo"), ("severidad", "Severidad"),
    ("activo_afectado", "Activo afectado"), ("responsable", "Responsable"),
    ("recibido_at", "Recibido"), ("vence_respuesta_at", "Límite de respuesta"),
    ("respondido_at", "Primera respuesta"), ("vence_resolucion_at", "Límite de resolución"),
    ("resuelto_at", "Resolución"), ("motivo_revision", "Motivo de revisión"),
]


def office_bytes(document: WordDocument | Workbook) -> bytes:
    """Serialize an editable Office document using the operational export engines."""
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def pdf_bytes(content: str) -> bytes:
    """Render an HTML report with the SOC's WeasyPrint engine."""
    from weasyprint import HTML

    return HTML(string=content).write_pdf()


def display_value(key, value):
    if value is None:
        return "—"
    if key.endswith("_at"):
        timestamp = datetime.fromisoformat(value) if isinstance(value, str) else value
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(ZoneInfo("America/Lima")).strftime("%d/%m/%Y %H:%M")
    if key in ("tipo", "severidad"):
        return str(value).replace("_", " ").replace("critica", "crítica")
    return str(value)


def export_report(reports, metrics, format_name, *, fields=None, title="Reportes de incidentes SOC"):
    if len(reports) > 10000:
        raise HTTPException(413, "La exportación admite hasta 10000 reportes.")
    columns = fields or FIELDS
    if format_name == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Reportes"
        sheet.append([label for _, label in columns])
        for report in reports:
            sheet.append([str(report[key]) if report.get(key) is not None else "" for key, _ in columns])
            # Values beginning with '=' are incident text, never spreadsheet formulas.
            for cell in sheet[sheet.max_row]:
                cell.data_type = "s"
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = 26
        kpis = workbook.create_sheet("Indicadores")
        kpis.append(["Indicador", "Valor"])
        for key, value in metrics.items():
            kpis.append([key, value])
        return office_bytes(workbook), EXPORT_MIME["xlsx"]
    if format_name == "docx":
        document = Document()
        for name in ("Title", "Heading 1", "Heading 2"):
            document.styles[name].font.color.rgb = RGBColor(0, 0, 0)
        document.add_heading(title, 0)
        document.add_paragraph(f"Total de reportes incluidos {len(reports)}")
        if fields:
            table = document.add_table(rows=1, cols=len(columns))
            table.style = "Table Grid"
            for cell, (_, label) in zip(table.rows[0].cells, columns):
                cell.text = label
            for report in reports:
                for cell, (key, _) in zip(table.add_row().cells, columns):
                    cell.text = display_value(key, report.get(key))
            return office_bytes(document), EXPORT_MIME["docx"]
        for report in reports:
            document.add_heading(report["titulo"], 1)
            document.add_paragraph(report["descripcion"])
            for key, label in FIELDS:
                document.add_paragraph(f"{label} · {display_value(key, report.get(key))}")
        return office_bytes(document), EXPORT_MIME["docx"]
    if format_name == "pdf":
        pdf_columns = fields or [(key, label) for key, label in FIELDS if key in
                                  ("titulo", "tipo", "severidad", "responsable", "respondido_at", "resuelto_at")]
        headings = "".join(f"<th>{escape(label)}</th>" for _, label in pdf_columns)
        rows = "".join(
            "<tr>" + "".join(f"<td>{escape(display_value(key, report.get(key)))}</td>" for key, _ in pdf_columns) + "</tr>"
            for report in reports
        )
        content = """<!doctype html><html lang="es"><meta charset="utf-8">
        <style>@page {size:A4 landscape; margin:18mm} body {font:10pt Arial,sans-serif; color:#172c31}
        h1 {font-size:20pt} table {width:100%;border-collapse:collapse;table-layout:fixed}
        td,th {border:1px solid #b9c9c4;padding:6pt;overflow-wrap:anywhere;text-align:left}
        th {background:#e6f0ec} thead {display:table-header-group} tr {break-inside:avoid}</style>
        """ + f"<h1>{escape(title)}</h1><p>Filas incluidas {len(reports)} · Horas de Perú (UTC−5)</p><table><thead><tr>{headings}</tr></thead><tbody>{rows}</tbody></table></html>"
        return pdf_bytes(content), EXPORT_MIME["pdf"]
    raise HTTPException(404, "Formato no disponible.")
