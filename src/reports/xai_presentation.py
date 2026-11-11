"""Scientific, accessible text attribution and evidence presentation."""
from html import escape

from matplotlib import rc_context
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from src.reports.figures import figure_style
from src.reports.presentation import TableGuide
from src.utils.config import FigureSettings


def summary_tables(report: dict) -> list[tuple[list[dict], TableGuide]]:
    """Provide interpretation and measured findings for every aggregate table."""
    data = report["summary"]
    patterns = [{"Clase predicha": row["class"], "Referencia": row["outcome"], "Casos (n)": row["cases"]} for row in data["patterns"]]
    issues = [{"Control": key, "Hallazgos (n)": n} for key, n in data["inconsistencies"].items()]
    stable = data["stability"]
    return [(patterns, TableGuide("Patrones por clase y disponibilidad de referencia", "Frecuencia en casos dentro de esta corrida.",
        "Las categorías acierto y error comparan la decisión con la referencia identificada en el registro.",
        f"Se explicaron {data['cases']} casos y se observaron {sum(row['cases'] for row in data['patterns'] if row['outcome'] == 'error')} errores frente a la referencia disponible.",
        "Desarrollo y Validación son subconjuntos experimentales. Las referencias sintéticas se identifican en la modalidad.")),
        (issues, TableGuide("Controles de consistencia de evidencia", "Conteos de hallazgos. Un caso puede aportar varios.",
        "Inspecciona las citas y los campos sin apoyo. La coincidencia literal requiere una revisión semántica adicional.",
        f"Se detectaron {sum(data['inconsistencies'].values())} hallazgos de evidencia en {data['cases']} casos.",
        "El detector usa criterios léxicos versionados y una lista limitada de negaciones.")),
        ([{"Variantes (n)": stable["variants"], "Predicción conservada (n)": stable["prediction_same"],
           "Fracción estable": stable["same_fraction"]}], TableGuide("Estabilidad experimental del modelo local",
        "Variantes en conteos y fracción de 0 a 1.", "Compara mayúsculas y espaciado manteniendo el modelo y el objetivo.",
        f"Se conservaron {stable['prediction_same']} predicciones de {stable['variants']} variantes comprobadas.",
        "La estabilidad se midió en transformaciones limitadas de modelos locales. La estabilidad del proveedor LLM requiere ejecuciones controladas adicionales."))]


def terms_figure(report: dict, settings: FigureSettings, maximum: int) -> tuple[Figure, TableGuide]:
    """Plot the document frequency of positive features or supported citations."""
    totals = {}
    for row in report["summary"]["terms"]:
        totals[row["term"]] = totals.get(row["term"], 0) + row["cases"]
    top = sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:maximum]
    with rc_context(figure_style(settings)):
        fig = Figure(figsize=(7.5, max(3.2, len(top) * .32 + 1.7)), layout="constrained")
        ax = fig.subplots()
        ax.barh([term for term, _ in reversed(top)], [n for _, n in reversed(top)], color=settings.palette[0], label="Casos con término")
        ax.set(title="Frecuencia de términos con apoyo positivo", xlabel="Casos (n)", ylabel="Término o fragmento")
        ax.legend()
    finding = f"El término más frecuente aparece en {top[0][1]} de {report['summary']['cases']} casos." if top else "La corrida no contiene términos positivos observados."
    return fig, TableGuide("Frecuencia de términos con apoyo positivo", "Una aparición por término y caso. Un caso aporta varios términos.",
        "La longitud indica cuántos casos contienen una contribución positiva o una cita de apoyo.", finding,
        "La frecuencia depende del corpus y del modelo. Los n-gramas y términos pueden compartir tokens.")


def contribution_figure(case: dict, settings: FigureSettings) -> tuple[Figure, TableGuide]:
    """Show signed present-feature contributions in the predicted/rival contrast."""
    data = case["linear"]
    terms = sorted(data["terms"], key=lambda row: row["contribution"])
    with rc_context(figure_style(settings)):
        fig = Figure(figsize=(7.6, max(3.2, len(terms) * .33 + 1.7)), layout="constrained")
        ax = fig.subplots()
        ax.barh([row["feature"] for row in terms], [row["contribution"] for row in terms],
                color=[settings.palette[0] if row["contribution"] >= 0 else settings.palette[1] for row in terms])
        ax.axvline(0, color="#303A45", linewidth=.8)
        ax.set(title=f"Contribuciones de {data['focus']} frente a {data['rival']}",
               xlabel="Contribución al contraste (" + data["unit"] + ")", ylabel="Característica TF-IDF")
        ax.legend(handles=[Patch(color=settings.palette[0], label="Apoyo a la clase"),
                           Patch(color=settings.palette[1], label="Apoyo al rival")])
    positive = sum(row["contribution"] > 0 for row in terms)
    return fig, TableGuide("Contribuciones firmadas del texto", "Azul apoya la clase explicada. Naranja apoya su rival.",
        "Cada barra es coeficiente de contraste por TF-IDF del término presente.",
        f"Entre los {len(terms)} términos mostrados, {positive} tienen contribución positiva. El contraste completo es {data['score']:.4f}.",
        "El gráfico muestra los términos principales. SHAP incluye también características ausentes y usa una base diferente al intercepto.")


def term_html(case: dict, settings: FigureSettings) -> tuple[str, TableGuide]:
    """Escape every input character and apply a redundant signed text encoding."""
    text = case["text"]
    if "linear" in case:
        spans = case["linear"]["tokens"]
    else:
        spans = [{"start": row["start"], "end": row["end"], "weight": -1 if row["negated"] else 1}
                 for row in case["evidence"]["claims"]]
    # Segment at every endpoint to preserve overlap and the exact input order.
    boundaries = sorted({0, len(text), *(item[key] for item in spans for key in ("start", "end"))})
    parts, colored = [], 0
    for start, end in zip(boundaries, boundaries[1:]):
        value = sum(item["weight"] for item in spans if item["start"] <= start and item["end"] >= end)
        fragment = escape(text[start:end])
        if value:
            colored += 1
            color = settings.palette[0] if value > 0 else settings.palette[1]
            sign = "+" if value > 0 else "−"
            fragment = f'<mark style="background:{color}22;border-bottom:2px solid {color};color:inherit" title="{sign}{abs(value):.5f}">{fragment}</mark>'
        parts.append(fragment)
    html = '<div style="white-space:pre-wrap;line-height:1.9">' + "".join(parts) + "</div>"
    limitation = "El mapa local representa contribuciones, y el mapa LLM representa citas verificables. Los colores carecen de interpretación causal."
    if "linear" in case:
        residue = case["linear"].get("token_projection_residual")
        limitation += f" Residuo de proyección a tokens {residue:.2e}." if residue is not None else " El residuo de proyección no está registrado en esta versión."
    return html, TableGuide("Mapa de términos sobre la entrada protegida", "Azul y signo + indican apoyo. Naranja y signo − indican oposición o negación.",
        "El texto conserva su orden. El valor de cada token local reparte contribuciones de n-gramas que lo contienen.",
        f"Se resaltaron {colored} segmentos de un texto de {len(text)} caracteres.",
        limitation)


def case_tables(case: dict) -> list[tuple[list[dict], TableGuide]]:
    """Build separate views for decisions, evidence, interpretation and fixed rules."""
    if "linear" in case:
        data = case["linear"]
        values = [{"Término": row["feature"], "TF-IDF": row["tfidf"], "Coeficiente": row["coefficient"],
                   "Contribución": row["contribution"], "SHAP": row["shap"], "Presente": row["present"]}
                  for row in data["shap_terms"]]
        reliability = case["reliability"]
        return [(values, TableGuide("Valores de Shapley del contraste lineal", "SHAP y contribuciones usan " + data["unit"] + ". TF-IDF es adimensional.",
            "La suma de SHAP y su base reconstruye el contraste. Se conserva la contribución de características omitidas.",
            f"Base {data['baseline']:.6f}, suma SHAP {data['shap_sum']:.6f}, contraste {data['score']:.6f}. Residuo {data['reconstruction_error']:.2e}.", data["limitation"])),
            (reliability["stability"], TableGuide("Perturbaciones leves del caso", "Jaccard de términos de 0 a 1. Diferencia de score en la unidad del modelo.",
            "Comprueba si el resultado y los términos principales se conservan al cambiar mayúsculas o espacios.",
            f"La predicción se conservó en {sum(row['prediction_same'] for row in reliability['stability'])} variantes de {len(reliability['stability'])}.",
            reliability["limitation"])),
            ([reliability["deletion"]] if reliability["deletion"] else [], TableGuide("Sensibilidad a la eliminación de un token positivo",
             "Diferencia de contraste en " + data["unit"] + ". Offsets de caracteres con inicio inclusivo y fin exclusivo.",
             "Se elimina el token de mayor apoyo positivo y se recalculan todas las características con el vectorizador congelado.",
             f"La caída de contraste observada fue {reliability['deletion']['score_drop']:.6f}." if reliability["deletion"] else "El caso carece de tokens positivos para eliminar.",
             reliability["limitation"]))]
    data, operational = case["evidence"], case["operational"]
    source = operational["input"]
    prediction = data["classification"]
    classification = [{**prediction, "proveedor": source.get("provider"), "modelo": source.get("model"),
                       "estado_entrada": operational["input_status"], "alcance_entrada": source.get("scope")}]
    verified_original = {row["claim"]: row["exists"] for row in data.get("original_quotes") or []}
    quotes = [{"Campo": row["field"], "Valor": row["value"], "Cita": row["quote"], "Inicio": row["start"], "Fin": row["end"],
               "Criterio": row["criterion"], "Negada": row["negated"], "Existe en original": verified_original.get(i)}
              for i, row in enumerate(data["claims"])]
    policy = operational["routing"]
    severity = prediction["severidad"]
    sla = policy["configuration"]["sla"][severity]
    rules = [{"Versión de reglas": policy["version"], "Responsable registrado": policy["assigned_team"],
              "Regla de equipo por tipo": policy["configuration"]["equipos"][prediction["tipo"]],
              "Equipo de revisión": policy["configuration"]["equipo_revision"], "Respuesta (min)": sla["respuesta_min"],
              "Resolución (min)": sla["resolucion_min"], "Umbral de revisión": policy["configuration"]["umbral"]}]
    return [(classification, TableGuide("Clasificación original y procedencia registrada", "Confianza operacional de 0 a 1, para decidir revisión.",
        "Los campos describen la decisión guardada. Un metadato vacío indica ausencia de evidencia histórica.",
        f"Tipo {prediction['tipo']} con severidad {prediction['severidad']} y confianza {prediction['confianza']:.3f}.",
        "La confianza es operacional. Una entrada reconstruida se identifica con la política actual. El origen fallback corresponde a revisión segura.")),
        (quotes, TableGuide("Evidencia textual y criterios observables", "Offsets en caracteres. Inicio inclusivo y fin exclusivo.",
        "Comprueba cada cita en la entrada y su presencia en el original. Revisa las negaciones y la correspondencia semántica.",
        f"Se verificaron {data['validation']['literal_quotes']} citas literales de {len(quotes)}. Campos sin apoyo observable: {len(data['unsupported_fields'])}.", data["limitation"])),
        (rules, TableGuide("Reglas determinísticas asociadas al reporte", "SLA en minutos transcurridos desde la recepción. Confianza de 0 a 1.",
        "La versión del reporte identifica su política. El responsable registrado y el equipo de revisión pertenecen al sistema de enrutamiento.",
        f"La regla de severidad {severity} define {sla['respuesta_min']} minutos de respuesta y {sla['resolucion_min']} de resolución.",
        "La ausencia de versión publicada identifica las reglas del archivo efectivo. El cumplimiento requiere los hitos operativos."))]
