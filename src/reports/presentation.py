"""Data-derived interpretations for every table in the phase-0 interface."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableGuide:
    """Required reading guidance; units belong to column names or the legend."""

    title: str
    legend: str
    how_to_read: str
    finding: str
    limitations: str


def service_guide(rows: list[dict]) -> TableGuide:
    """Describe the observed health results without inferring LLM quality."""
    healthy = sum(row["Estado"] == "ok" for row in rows)
    return TableGuide("Disponibilidad observada de los servicios SOC", "Una fila por servicio; estado sin unidad física.",
                      "Lee el estado devuelto por FastAPI. Sin comprobar y local no equivalen a una conexión externa verificada.",
                      f"{healthy} de {len(rows)} servicios listados informan estado ok.",
                      "Una comprobación de salud no acredita clasificación correcta, rendimiento ni disponibilidad de Groq o Gemini.")


def catalog_guide(profiles: list[dict]) -> TableGuide:
    """Summarize actual registered source availability."""
    available = sum(row["status"] == "disponible" for row in profiles)
    synthetic = sum(row["synthetic"] for row in profiles)
    return TableGuide("Fuentes existentes registradas en el sistema", "Filas en registros; tamaño en columnas; n/d indica que no se consultó el endpoint.",
                      "Compara formato, procedencia y disponibilidad. El catálogo describe los originales y no convierte etiquetas provisionales en verdad de referencia.",
                      f"{available} de {len(profiles)} fuentes están disponibles como archivos; {synthetic} fuentes están identificadas como sintéticas.",
                      "El acceso operativo depende de JWT/RBAC. Los conteos de archivos no prueban calidad de etiquetas ni ausencia de fuga entre grupos.")


def preview_guide(source_name: str, snapshot: dict, limitation: str) -> TableGuide:
    """Describe the bounded preview and the exact scope of its fingerprint."""
    return TableGuide(f"Vista de metadatos de {source_name}", "Cada fila es un registro original; los campos de texto pueden mostrarse abreviados.",
                      "Revisa las columnas originales seleccionadas. Los valores ausentes se mantienen como ausentes.",
                      f"Se muestran {len(snapshot['rows'])} registros; la huella SHA-256 corresponde a {snapshot['hash_scope']}.", limitation)


def runs_guide(records: list[dict]) -> TableGuide:
    """Keep environment validations distinct from predictive experiments."""
    sources = len({row["dataset"]["source_id"] for row in records})
    audited = sum(row.get("audit_state") == "confirmada" for row in records)
    return TableGuide("Verificaciones de entorno registradas", "Una fila por verificación; fechas UTC y semilla sin unidad física.",
                      "Cada registro conserva configuración, métricas técnicas, versiones y huella de la fuente consultada.",
                      f"Hay {len(records)} verificaciones registradas sobre {sources} fuentes distintas; {audited} tienen auditoría confirmada.",
                      "Son verificaciones de fase 0. Local identifica registros previos sin confirmación específica del backend; pendiente indica confirmación incompleta. No son métricas predictivas.")
