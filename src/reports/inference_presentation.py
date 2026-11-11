"""Measured, explicitly limited interpretation for individual SOC inference."""
from __future__ import annotations

from matplotlib import rc_context
from matplotlib.figure import Figure
import numpy as np

from src.reports.figures import figure_style
from src.reports.presentation import TableGuide
from src.utils.config import FigureSettings, ReportingSettings


def prediction_table(snapshot: dict) -> tuple[list[dict], TableGuide]:
    """Present the original prediction and observable provider provenance separately."""
    report = snapshot["report"]
    prediction, captured = report["classification"], report["input"]
    timing, rules = report["timing"], report["routing"]["configuration"]
    model_label = "Modelo informado por el proveedor" if captured.get("model_scope") == "response" else "Modelo solicitado o histórico"
    trace = captured.get("trace")
    values = [
        ("Identificador", report["id"]), ("Tipo de incidente", prediction["tipo"]), ("Severidad", prediction["severidad"]),
        ("Activo afectado", prediction["activo_afectado"]), ("Confianza operacional (0–1)", f"{prediction['confianza']:.4f}"),
        ("Umbral de revisión aplicado (0–1)", f"{rules['umbral']:.4f}"),
        ("Estado de revisión", "Revisión registrada" if report["human_review"] else "Pendiente" if report["review_reason"] else "Sin derivación automática"),
        ("Motivo de revisión", report["review_reason"]), ("Origen del resultado", report["origin"]),
        ("Proveedor que respondió", captured.get("provider")), (model_label, captured.get("model")),
        ("Gemini activado por error técnico", str(trace["technical_fallback"]) if trace else None),
        ("Clasificación observada (s)", timing["classification_seconds"]), ("Flujo hasta notificación (s)", timing["end_to_end_seconds"]),
        ("Estado de la entrada", report["input_status"]),
    ]
    rows = [{"Variable": label, "Valor": "Sin dato" if value is None else f"{value:.4f}" if isinstance(value, float) else str(value)} for label, value in values]
    return rows, TableGuide("Resultado individual registrado", "Puntajes adimensionales y latencias en segundos.",
        "Consulta por separado la predicción original, su revisión y los metadatos técnicos. Un dato ausente conserva ese estado.",
        f"El reporte tiene confianza operacional {prediction['confianza']:.4f} y umbral {rules['umbral']:.4f}. "
        + ("Existe una revisión humana registrada." if report["human_review"] else
           f"Motivo de derivación observado {report['review_reason']}." if report["review_reason"] else "La política no registró derivación automática."),
        "El puntaje del LLM carece de evidencia de calibración. El origen fallback identifica protección hacia revisión humana. "
        "El modelo solicitado describe la petición. Un identificador devuelto por el proveedor puede seguir siendo un alias, sin revisión inmutable de pesos.")


def evidence_table(snapshot: dict) -> tuple[list[dict], TableGuide]:
    """Explain literal fragments and expose unsupported fields explicitly."""
    evidence = snapshot["evidence"]
    claims = evidence["claims"]
    rows = [{"Campo": row["field"], "Resultado asociado": row["value"], "Cita": row["quote"],
             "Inicio (carácter)": row["start"], "Fin exclusivo (carácter)": row["end"], "Negación detectada": row["negated"]} for row in claims]
    return rows, TableGuide("Evidencia textual de la justificación", "Offsets de caracteres sobre la entrada protegida, con fin exclusivo.",
        "Cada cita debe aparecer literalmente en el intervalo indicado. Contrasta negaciones y significado con el texto.",
        f"{evidence['validation']['literal_quotes']} de {len(claims)} citas tienen coincidencia literal. "
        f"{len(evidence['unsupported_fields'])} campos carecen de apoyo en los criterios configurados.",
        evidence["limitation"])


def routing_table(snapshot: dict) -> tuple[list[dict], TableGuide]:
    """Compare the stored assignment and deadlines against their effective rules."""
    report = snapshot["report"]
    route = report["routing"]
    expected = route["expected"]
    rows = [{"Equipo asignado": route["assigned_team"], "Equipo según reglas": expected["responsable"],
             "Respuesta (min)": expected["respuesta_min"], "Resolución (min)": expected["resolucion_min"],
             "Vence respuesta": str(route["response_due_at"]) if route["response_due_at"] else None,
             "Vence resolución": str(route["resolution_due_at"]) if route["resolution_due_at"] else None}]
    status = "Confirmada" if route["verified"] else "Pendiente" if route["verified"] is None else "Incompatibilidad detectada"
    return rows, TableGuide("Asignación y plazos de la versión efectiva", "Duraciones en minutos transcurridos y vencimientos con zona horaria.",
        "Los plazos parten de la recepción. La bitácora identifica el actor que asignó y notificó.",
        f"Correspondencia de equipo y vencimientos con reglas {status.lower()}. "
        f"Enrutador configurado {report['system']['router']}.",
        "El LLM aporta tipo, severidad y activo. n8n calcula la asignación y FastAPI contrasta las reglas. "
        "El modo local de demostración se identifica mediante su configuración y sus eventos.")


def attempts_table(snapshot: dict) -> tuple[list[dict], TableGuide]:
    """Show bounded attempts without retaining provider response bodies."""
    trace = snapshot["report"]["input"].get("trace")
    attempts = trace["attempts"] if trace else []
    rows = [{"Intento": i, "Proveedor": a["provider"], "Modelo solicitado": a["model"],
             "Modelo informado": a.get("response_model"), "Estado": a["outcome"],
             "Duración (s)": a["seconds"], "HTTP observado": a["http_status"]} for i, a in enumerate(attempts, 1)]
    return rows, TableGuide("Intentos técnicos observados", "Duración en segundos e identificadores de HTTP cuando constan.",
        "Sigue el orden de intentos. Un rechazo de política termina la conmutación. La confianza baja conserva el proveedor que respondió.",
        f"Se registraron {len(attempts)} intentos, de los cuales {sum(a['provider'] == 'gemini' for a in attempts)} corresponden a Gemini.",
        "La ausencia de telemetría histórica impide atribuir intentos. Los fallos se registran con códigos y estados acotados, sin cuerpos del proveedor.")


def metrics_table(data: dict) -> tuple[list[dict], TableGuide]:
    """Summarize descriptive latencies with denominators and a qualified SPEC comparison."""
    series = [("Clasificación", data["latency"]["classification"]), ("Hasta notificación", data["latency"]["end_to_end"])]
    series.extend((provider, values) for provider, values in data["latency"]["providers"].items())
    rows = [{"Serie": name, "Observaciones (n)": record["n"], "p50 (s)": record["p50_s"], "p95 (s)": record["p95_s"]} for name, record in series]
    p95 = data["latency"]["end_to_end"]["p95_s"]
    finding = f"Se incluyeron {data['non_demo']} reportes y se excluyeron {data['demo_excluded']} DEMO. "
    finding += f"El p95 del flujo observado es {p95:.4f} s frente a la meta de {data['target_p95_seconds']:g} s." if p95 is not None else "El flujo carece de tiempos de notificación medibles."
    return rows, TableGuide("Desempeño observado del sistema", "Percentiles muestrales en segundos. n cuenta las observaciones de cada serie.",
        "Cada serie usa su propio denominador. La latencia de proveedor incluye intentos fallidos observados.",
        finding, data["limitations"] + f" La referencia de tamaño mínimo es {data['sample_minimum']} reportes. "
        "La comparación descriptiva conserva pendiente la acreditación del objetivo del SPEC.")


def event_table(snapshot: dict) -> tuple[list[dict], TableGuide]:
    """Present the unchanged operational event sequence."""
    events = snapshot["report"]["events"]
    rows = [{"Evento": item["accion"], "Actor": item["actor"], "Fecha UTC": str(item["ocurrido_at"])} for item in events]
    return rows, TableGuide("Bitácora del recorrido operativo", "Una fila por evento y marca temporal UTC.",
        "Contrasta recibido, clasificado, asignado y notificación, junto a su actor.",
        f"Se recuperaron {len(events)} eventos asociados al reporte.",
        "Las marcas de bitácora indican cuándo se registró cada evento. La latencia usa los campos temporales del reporte, "
        "incluida la recepción anterior a la llamada del clasificador. Los hitos pendientes conservan sus estados.")


def latency_figure(data: dict, style: FigureSettings, layout: ReportingSettings) -> tuple[Figure | None, TableGuide]:
    """Draw sample latency quantiles using the common accessible scientific style."""
    rows, guide = metrics_table(data)
    measured = [row for row in rows if row["Observaciones (n)"]]
    if not measured:
        return None, guide
    with rc_context(figure_style(style)):
        figure = Figure(figsize=(layout.figure_width_inches, layout.figure_height_inches), layout="constrained")
        axis = figure.subplots()
        positions = np.arange(len(measured))
        axis.bar(positions - .18, [row["p50 (s)"] for row in measured], width=.36, color=style.palette[0], label="p50 observado")
        axis.bar(positions + .18, [row["p95 (s)"] for row in measured], width=.36, color=style.palette[1], label="p95 observado")
        axis.set_xticks(positions, [row["Serie"] for row in measured], rotation=15)
        axis.set(title="Latencias descriptivas por tramo", xlabel="Tramo medido", ylabel="Duración (s)", ylim=(0, None))
        axis.legend()
        axis.grid(axis="y", alpha=.2)
    return figure, TableGuide("Latencias descriptivas por tramo", guide.legend, guide.how_to_read, guide.finding, guide.limitations)


def human_review_table(snapshot: dict) -> tuple[list[dict], TableGuide]:
    """Keep an authorized human correction separate from the original classifier output."""
    review = snapshot["report"]["human_review"]
    original = snapshot["report"]["classification"]
    rows = [{"Campo": key, "Predicción original": original[key], "Revisión humana": value} for key, value in (review or {}).items()]
    changed = sum(original[key] != value for key, value in (review or {}).items())
    return rows, TableGuide("Revisión humana registrada", "Etiquetas de tipo, severidad y activo, sin unidad física.",
        "Compara cada campo corregido con la predicción original conservada.",
        f"La revisión registrada difiere en {changed} de {len(rows)} campos.",
        "La revisión operacional es retrospectiva y carece de la independencia requerida para sustituir un holdout humano.")
