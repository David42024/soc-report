"""Descriptive statistics on observed records and their distinct label sources."""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from math import ceil

import numpy as np

from src.data.models import DataRecord, LABEL_NAMES, PROVENANCE_NAMES, TARGETS
from src.data.quality import normalized_words

NATURE_NAMES = {"real": "Real", "demo": "DEMO", "sintetica": "Sintética"}
NUMERIC_NAMES = {
    "text_characters": ("Longitud de la descripción protegida", "caracteres"),
    "confianza": ("Confianza operativa", "puntaje 0–1"),
    "number_attributions": ("Atribuciones registradas", "atribuciones"),
    "number_political_responses": ("Respuestas políticas registradas", "respuestas"),
    "unweighted_intensity": ("Intensidad EuRepoC sin ponderar", "puntos de índice"),
    "weighted_intensity": ("Intensidad EuRepoC ponderada", "puntos de índice"),
    "confidence_assumed": ("Confianza asumida en simulación", "puntaje 0–1"),
    "manual_active_minutes_assumed": ("Tiempo activo manual asumido", "minutos"),
    "guarded_active_minutes_assumed": ("Tiempo activo con protección asumido", "minutos"),
    "response_deadline_minutes": ("Plazo de respuesta simulado", "minutos"),
    "resolution_deadline_minutes": ("Plazo de resolución simulado", "minutos"),
}


@dataclass(frozen=True, slots=True)
class RecordFilters:
    search: str = ""
    nature: str | None = None
    review_state: str | None = None
    partition: str | None = None
    provenance: str | None = None
    native_labels: tuple[tuple[str, str], ...] = ()


def select_records(records: tuple[DataRecord, ...], filters: RecordFilters,
                   groups: Mapping[str, str] | None = None) -> tuple[DataRecord, ...]:
    """Combine search and all selected dimensions within the same private view."""
    words = filters.search.casefold().split()
    selected = []
    for record in records:
        if filters.nature and record.nature != filters.nature:
            continue
        if filters.review_state and record.review_state != filters.review_state:
            continue
        if filters.partition and record.partition != filters.partition:
            continue
        if filters.provenance and filters.provenance not in {label.provenance for label in record.labels.values()}:
            continue
        if any(value not in record.label(field).values for field, value in filters.native_labels):
            continue
        if words:
            searchable = " ".join(str(value or "") for value in (
                record.incident_id, record.key, record.title, record.description, record.group,
                groups.get(record.key) if groups else None, record.notes,
            )).casefold()
            if not all(word in searchable for word in words):
                continue
        selected.append(record)
    return tuple(selected)


def page_slice(records: tuple[DataRecord, ...], page: int, size: int) -> tuple[tuple[DataRecord, ...], int, int]:
    """Clamp page number after a filter narrows the records."""
    if size < 1:
        raise ValueError("El tamaño de página debe ser positivo.")
    total = max(1, ceil(len(records) / size))
    current = max(1, min(page, total))
    return records[(current - 1) * size:current * size], current, total


def label_fields(records: tuple[DataRecord, ...]) -> list[str]:
    observed = {field for record in records for field, label in record.labels.items() if label.values}
    return [field for field in LABEL_NAMES if field in observed]


def coverage(records: tuple[DataRecord, ...]) -> list[dict]:
    """Keep availability, missingness and human provenance per field."""
    rows = []
    for name in dict.fromkeys((*TARGETS, *label_fields(records))):
        valid = [record.label(name) for record in records if record.label(name).values]
        origins = Counter(label.provenance for label in valid)
        rows.append({
            "Variable": LABEL_NAMES[name], "Total (registros)": len(records), "Válidos (registros)": len(valid),
            "Faltantes (registros)": len(records) - len(valid),
            "Cobertura (%)": round(100 * len(valid) / len(records), 2) if records else None,
            "Referencia humana (registros)": sum(record.nature == "real" and record.label(name).human_reference for record in records),
            "Procedencia de etiquetas": ", ".join(f"{PROVENANCE_NAMES.get(key, key)} ({n})" for key, n in sorted(origins.items())),
        })
    return rows


def frequencies(records: tuple[DataRecord, ...], field: str) -> list[dict]:
    """Count each tag once per row and keep separate denominators by provenance."""
    totals, counts = Counter(), Counter()
    for record in records:
        label = record.label(field)
        if label.values:
            group = (record.nature, label.provenance)
            totals[group] += 1
            for value in label.values:
                counts[group, value] += 1
        elif field in record.categories:
            group = (record.nature, "fuente_externa")
            totals[group] += 1
            counts[group, record.categories[field]] += 1
    return [{"Naturaleza": NATURE_NAMES[nature], "Procedencia": PROVENANCE_NAMES[origin],
             "Categoría": category, "Frecuencia (registros)": count,
             "Denominador (registros válidos)": totals[nature, origin],
             "Frecuencia relativa (%)": round(100 * count / totals[nature, origin], 2)}
            for ((nature, origin), category), count in sorted(counts.items(), key=lambda item: (item[0][0], -item[1], item[0][1]))]


def numerical_values(records: tuple[DataRecord, ...], field: str) -> list[float]:
    return [value for record in records
            if (value := record.text_characters if field == "text_characters" else record.numbers.get(field)) is not None]


def numeric_summary(values: list[float], total: int, unit: str) -> dict:
    """Use sample standard deviation and linear quartiles when defined."""
    summary = {"n (registros)": len(values), "Faltantes (registros)": total - len(values), "Unidad": unit}
    if not values:
        return summary
    numbers = np.array(values, dtype=float)
    lower, median, upper = np.quantile(numbers, (0.25, 0.5, 0.75))
    summary.update({
        "Media": float(numbers.mean()), "Mediana": float(median),
        "Desviación estándar (muestral)": float(numbers.std(ddof=1)) if len(values) > 1 else None,
        "Q1": float(lower), "Q3": float(upper), "Mínimo": float(numbers.min()), "Máximo": float(numbers.max()),
        "Rango": float(numbers.max() - numbers.min()),
    })
    return summary


def term_frequencies(records: tuple[DataRecord, ...], vocabulary: tuple[str, ...]) -> tuple[list[dict], int]:
    """Count allowed technical terms in protected text, with document denominators."""
    lexicon = defaultdict(set)
    display = {}
    for term in vocabulary:
        normalized = tuple(normalized_words(term))
        if normalized:
            lexicon[len(normalized)].add(normalized)
            display[normalized] = term
    counts, documents, total = Counter(), Counter(), 0
    for record in records:
        words = normalized_words(record.description or "")
        if not words:
            continue
        total += 1
        present = set()
        for length, accepted in lexicon.items():
            for position in range(len(words) - length + 1):
                term = tuple(words[position:position + length])
                if term in accepted:
                    counts[term] += 1
                    present.add(term)
        documents.update(present)
    return [
        {"Término": display[term], "Frecuencia (apariciones)": count, "Documentos (registros)": documents[term],
         "Documentos con término (%)": round(100 * documents[term] / total, 2)}
        for term, count in sorted(counts.items(), key=lambda item: (-item[1], display[item[0]]))
    ], total
