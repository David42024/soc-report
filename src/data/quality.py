"""Data quality, linked incidents and candidate duplicate checks."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from heapq import heappush, heappushpop
import re
from typing import Literal
import unicodedata

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer

from src.data.models import DataInventory, DataRecord, SEVERITIES, TARGETS, TYPES, content_hash
from src.utils.config import DataSettings
from src.utils.privacy import ALIAS


def normalized_words(text: str) -> list[str]:
    """Normalize tokens locally, excluding privacy placeholders."""
    clean = ALIAS.sub(" ", text).casefold()
    plain = "".join(char for char in unicodedata.normalize("NFKD", clean) if not unicodedata.combining(char))
    return re.findall(r"[^\W\d_]+", plain, flags=re.UNICODE)


@dataclass(frozen=True, slots=True)
class Groups:
    by_record: dict[str, str]
    members: dict[str, tuple[str, ...]]
    reserved: frozenset[str]
    exposed: frozenset[str]

    @property
    def conflicts(self) -> frozenset[str]:
        return self.reserved & self.exposed


def group_records(records: tuple[DataRecord, ...]) -> Groups:
    """Join transitive links from incident IDs, declared groups, references and exact text."""
    parents = {record.key: record.key for record in records}

    def find(key: str) -> str:
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    first_by_link = {}
    for record in records:
        links = record.links
        if record.text_sha256:
            links += ("texto:" + record.text_sha256,)
        for link in links:
            previous = find(first_by_link.setdefault(link, record.key))
            current = find(record.key)
            if previous != current:
                parents[max(previous, current)] = min(previous, current)
    components = defaultdict(list)
    for key in sorted(parents):
        components[find(key)].append(key)
    members = {content_hash(keys): tuple(keys) for keys in components.values()}
    by_record = {key: group for group, keys in members.items() for key in keys}
    reserved = frozenset(by_record[r.key] for r in records if r.partition == "reservado")
    exposed = frozenset(by_record[r.key] for r in records if r.partition == "piloto" or r.pilot_exposure)
    return Groups(by_record, members, reserved, exposed)


@dataclass(frozen=True, slots=True)
class Similarity:
    compared_records: int
    pairs: int
    examples: tuple[tuple[float, str, str], ...]
    pairs_by_source: dict[str, int]
    reserved_risk_groups: frozenset[str]
    cross_reserved_pairs: int


def find_similar(records: tuple[DataRecord, ...], groups: Groups, settings: DataSettings) -> Similarity:
    """Find candidates with fixed n-grams and a configured map of technical equivalents."""
    aliases = {}
    for phrase, concept in settings.similarity_aliases.items():
        words = normalized_words(concept)
        if words and (phrase_words := normalized_words(phrase)):
            canonical = "_".join(words)
            aliases.setdefault(" ".join(words), canonical)
            aliases[" ".join(phrase_words)] = canonical
    phrases = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(alias) for alias in sorted(aliases, key=lambda x: (-len(x), x))) +
                         r")(?!\w)") if aliases else None
    unique = {}
    for record in sorted(records, key=lambda item: item.key):
        if record.nature != "real" or not record.text_sha256 or not record.description or record.review_state == "excluido":
            continue
        words = normalized_words(record.description)
        if len(words) >= settings.similarity_min_words:
            normalized = " ".join(words)
            if phrases:
                normalized = phrases.sub(lambda match: aliases[match[0]], normalized)
            unique.setdefault(record.text_sha256, (record, normalized))
    candidates = list(unique.values())
    if len(candidates) < 2:
        return Similarity(len(candidates), 0, (), {}, frozenset(), 0)
    vectors = HashingVectorizer(
        n_features=settings.similarity_features, alternate_sign=False,
        ngram_range=(1, 2), norm="l2", dtype=np.float32,
    ).transform(text for _, text in candidates)
    transposed = vectors.T.tocsr()
    pairs, cross_reserved_pairs = 0, 0
    examples, by_source, risk = [], Counter(), set()
    for start in range(0, vectors.shape[0], settings.similarity_batch_size):
        scores = (vectors[start:start + settings.similarity_batch_size] @ transposed).tocsr()
        for offset in range(scores.shape[0]):
            index = start + offset
            left = candidates[index][0]
            group_left = groups.by_record[left.key]
            first, last = scores.indptr[offset:offset + 2]
            neighbors, similarities = scores.indices[first:last], scores.data[first:last]
            selected = (neighbors > index) & (similarities >= settings.similarity_threshold)
            for other, score in zip(neighbors[selected], similarities[selected]):
                right = candidates[other][0]
                group_right = groups.by_record[right.key]
                if group_left == group_right:
                    continue
                pairs += 1
                by_source.update({left.source_id, right.source_id})
                if (group_left in groups.reserved) != (group_right in groups.reserved):
                    risk.update((group_left, group_right))
                    cross_reserved_pairs += 1
                entry = (round(min(float(score), 1.0), 6), left.key, right.key)
                if len(examples) < settings.max_examples:
                    heappush(examples, entry)
                else:
                    heappushpop(examples, entry)
    return Similarity(len(candidates), pairs, tuple(sorted(examples, reverse=True)), dict(by_source),
                      frozenset(risk), cross_reserved_pairs)


@dataclass(frozen=True, slots=True)
class Check:
    code: str
    name: str
    status: Literal["Aprobado", "Advertencia", "Error"]
    count: int
    unit: str
    criterion: str
    recommendation: str
    examples: tuple[str, ...] = ()


def _duplicates(records: tuple[DataRecord, ...], prefix: str) -> tuple[int, list[str]]:
    buckets = defaultdict(list)
    for record in records:
        link = record.text_sha256 if prefix == "texto" else next(
            (item for item in record.links if item.startswith("incidente:")), None
        )
        if link:
            buckets[record.source_id, link].append(record.key)
    repeated = [keys for keys in buckets.values() if len(keys) > 1]
    return len(repeated), [key for keys in repeated for key in keys]


def quality_checks(inventory: DataInventory, groups: Groups, similarity: Similarity,
                   settings: DataSettings, source_id: str | None = None) -> tuple[Check, ...]:
    """Summarize verifiable criteria over the inventory or the selected source."""
    sources = tuple(source for source in inventory.sources if source_id is None or source.id == source_id)
    records = tuple(record for source in sources for record in source.records)
    visible_groups = {groups.by_record[record.key] for record in records}
    missing = [record.key for record in records if record.expects_text and not record.description and record.review_state != "excluido"]
    incomplete = [record.key for record in records if record.source_id in ("operational_reports", "vcdb_pilot")
                  and not record.title and record.review_state != "excluido"]
    invalid_fields = {"estructura_invalida", "identificador_ausente", "columnas_inconsistentes",
                      "vcdb_original_no_encontrado", "referencia_piloto_invalida", "disposicion_invalida",
                      "numero_invalido", "confianza_invalida", "origen_invalido", "revision_operativa_invalida"}
    invalid = [r.key for r in records if invalid_fields.intersection(r.issues)]
    wrong_label = [r.key for r in records if any(issue in r.issues for issue in (
        "tipo_invalido", "severidad_invalido", "activo_afectado_invalido", "clase_simulada_invalida", "severidad_simulada_invalida",
    ))]
    privacy = [r.key for r in records if set(r.issues) & {"proteccion_texto_no_disponible", "texto_fuera_de_limite", "etiqueta_protegida"}]
    duplicate_ids, id_examples = _duplicates(records, "incidente")
    duplicate_text, text_examples = _duplicates(records, "texto")
    conflicting = sorted(groups.conflicts & visible_groups)
    grouped = sum(len(groups.members[group]) > 1 for group in visible_groups)
    related = sum(len(groups.members[groups.by_record[r.key]]) > 1 for r in records)
    natures = {record.nature for record in records}
    mixed = len(natures) if "real" in natures and len(natures) > 1 else 0
    classes = defaultdict(Counter)
    for record in records:
        for target in ("tipo", "severidad"):
            label = record.label(target)
            if label.values and record.review_state != "excluido":
                classes[record.source_id, record.nature, target, label.provenance].update(label.values)
    imbalanced = 0
    for (_, _, target, _), counts in classes.items():
        expected = TYPES if target == "tipo" else SEVERITIES
        if set(expected) - counts.keys() or max(counts.values()) / min(counts.values()) >= settings.imbalance_ratio:
            imbalanced += 1
    lacking_review = [r.key for r in records if r.nature == "real" and r.review_state != "excluido"
                      and any(not r.label(field).human_reference for field in TARGETS)]
    near = similarity.pairs if source_id is None else similarity.pairs_by_source.get(source_id, 0)
    unknown_review = [r.key for r in records if "revision_operativa_no_consultada" in r.issues]
    stale = [r.key for r in records if "revision_desactualizada" in r.issues]

    def check(code: str, name: str, count: int, unit: str, criterion: str, recommendation: str,
              examples: list[str] | tuple[str, ...] = (), *, error: bool = False, insufficient: bool = False) -> Check:
        status = "Error" if error and count else "Advertencia" if count or insufficient else "Aprobado"
        return Check(code, name, status, count, unit, criterion, recommendation,
                     tuple(sorted(set(examples))[:settings.max_examples]))

    return (
        check("fuentes", "Fuentes con acceso incompleto", sum(s.status != "disponible" for s in sources), "fuentes",
              "Cada fuente debe abrirse y conservar su huella durante la lectura.",
              "Comprueba ruta, servicio y esquema de las fuentes afectadas.", error=True),
        check("estructura", "Registros inválidos", len(invalid), "registros",
              "ID y estructura esperados, valores numéricos válidos y referencias verificables.",
              "Revisa el registro de origen y documenta la corrección.", invalid, error=True),
        check("faltantes", "Texto incompleto", len(set(missing + incomplete)), "registros",
              "Descripción disponible cuando el esquema la espera. Piloto y operación requieren además título.",
              "Completa la preparación con una descripción revisada cuando exista evidencia.", missing + incomplete),
        check("etiquetas", "Etiquetas fuera de esquema", len(wrong_label), "registros",
              "Tipos y severidades SOC según el backend. Las etiquetas externas conservan su taxonomía.",
              "Valida y corrige la etiqueta en una revisión del módulo.", wrong_label, error=True),
        check("duplicado_id", "Identificadores repetidos", duplicate_ids, "grupos dentro de una fuente",
              "El mismo identificador original aparece en más de una fila de su fuente.",
              "Conserva los registros y verifica si representan el mismo incidente.", id_examples, error=True),
        check("duplicado_texto", "Descripciones exactas repetidas", duplicate_text, "grupos dentro de una fuente",
              "SHA-256 del texto con espacios y mayúsculas normalizados.",
              "Confirma la relación y conserva el grupo unido al preparar particiones.", text_examples),
        check("similitud", "Posibles duplicados textuales", near, "pares",
              f"Coseno ≥ {settings.similarity_threshold:.2f} sobre unigramas/bigramas protegidos con equivalencias técnicas. "
              f"Se compararon {similarity.compared_records} descripciones reales únicas en el inventario.",
              "Revisa las parejas como candidatas. Confirma el incidente con evidencia.", insufficient=similarity.compared_records < 2),
        Check("grupos", "Relaciones de incidentes", "Aprobado" if records else "Advertencia", grouped, "grupos vinculados",
              f"Los grupos vinculados incluyen {related} filas del ámbito. Vínculos por ID, campaña VCDB, grupo, artículo o texto.",
              "Valida campañas y relaciones que el esquema todavía no documenta."),
        check("fuga", "Solapamiento de piloto y reserva", len(conflicting), "grupos",
              "Un grupo relacionado contiene registros expuestos en piloto y registros reservados.",
              "Revisa el conflicto antes de habilitar un conjunto de prueba.", conflicting, error=True),
        check("fuga_posible", "Similitud con registros reservados", len(visible_groups & similarity.reserved_risk_groups), "grupos",
              f"{similarity.cross_reserved_pairs} pares del inventario conectan reserva con otro grupo por similitud textual.",
              "Revisa ambos incidentes antes de incluirlos en desarrollo o prueba."),
        check("naturaleza", "Mezcla de procedencias", mixed, "naturalezas coexistentes",
              "Detecta casos reales junto a DEMO o simulaciones en el ámbito consultado.",
              "Mantén cohortes separadas y conserva la naturaleza original en las revisiones."),
        check("desbalance", "Cobertura o desbalance de clases", imbalanced, "estratos con advertencia",
              f"Por fuente, naturaleza, variable y procedencia. Falta una clase SOC o razón máximo/mínimo observado ≥ {settings.imbalance_ratio:g}.",
              "Revisa cobertura por clase y procedencia antes de comparar desempeños.", insufficient=not classes),
        check("revision", "Referencia humana incompleta", len(lacking_review), "registros reales",
              "Cada objetivo requiere un valor respaldado por revisión humana del texto y etiqueta correspondientes.",
              "Completa las revisiones con evidencia y registra las discrepancias.", lacking_review),
        check("revision_api", "Revisión operativa sin confirmar", len(unknown_review), "registros",
              "La colaboración debe devolver explícitamente una revisión o un valor nulo.",
              "Actualiza la consulta de FastAPI.", unknown_review),
        check("privacidad", "Texto o etiqueta omitidos por protección", len(privacy), "registros",
              "Se excluyen del análisis de contenido los campos que la protección no permite mostrar.",
              "Revisa una versión protegida antes de usarla como referencia.", privacy),
        check("vigencia", "Revisiones de otro original", len(stale), "registros",
              "Solo se aplican revisiones que corresponden a la huella del original y la política actuales.",
              "Revisa el original actual y confirma una nueva edición.", stale),
    )
