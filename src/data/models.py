"""Records and label provenance for the SOC data inventory."""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.classifier import Severidad, Tipo


LabelField = Literal["tipo", "severidad", "activo_afectado"]
ReviewState = Literal["pendiente", "revisado", "excluido"]
Nature = Literal["real", "demo", "sintetica"]
TARGETS = get_args(LabelField)
TYPES = get_args(Tipo)
SEVERITIES = get_args(Severidad)
LABEL_NAMES = {
    "tipo": "Tipo SOC",
    "severidad": "Severidad SOC",
    "activo_afectado": "Activo afectado",
    "tipo_fuente": "Tipo según la fuente",
    "activo_fuente": "Activo según la fuente",
    "clase_simulada": "Clase simulada",
    "severidad_simulada": "Severidad simulada",
}
PROVENANCE_NAMES = {
    "sin_etiqueta": "Sin etiqueta",
    "provisional": "Sugerencia provisional",
    "piloto_revisado": "Referencia humana del piloto",
    "revision_operativa": "Revisión humana operativa",
    "revision_analitica": "Anotación humana en el módulo",
    "prediccion": "Predicción operativa",
    "demo": "Etiqueta DEMO",
    "fuente_externa": "Taxonomía original de la fuente",
    "simulacion": "Etiqueta simulada",
    "propuesta": "Propuesta sin confirmar",
}


def content_hash(value: Any) -> str:
    """Hash canonical JSON rather than incidental ordering or indentation."""
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(data.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Annotation:
    """The values and review evidence for one target or native variable."""

    values: tuple[str, ...] = ()
    provenance: str = "sin_etiqueta"
    reviewers: int = 0

    @property
    def human_reference(self) -> bool:
        return bool(self.values and self.reviewers and self.provenance in (
            "piloto_revisado", "revision_operativa", "revision_analitica",
        ))


@dataclass(frozen=True, slots=True)
class DataRecord:
    """A protected projection; originals and source references stay in place."""

    key: str
    source_id: str
    incident_id: str
    base_sha256: str
    source_label: str
    nature: Nature
    partition: str
    origin: str
    title: str | None = None
    description: str | None = None
    text_sha256: str | None = None
    group: str | None = None
    links: tuple[str, ...] = ()
    labels: dict[str, Annotation] = field(default_factory=dict)
    predictions: dict[str, Annotation] = field(default_factory=dict)
    numbers: dict[str, float] = field(default_factory=dict)
    categories: dict[str, str] = field(default_factory=dict)
    issues: tuple[str, ...] = ()
    expects_text: bool = True
    pilot_exposure: bool = False
    review_state: str = "pendiente"
    reviewer: str | None = None
    reviewed_at: str | None = None
    notes: str | None = None
    version: int = 0
    applied_version: int = 0
    revision_sha256: str | None = None

    def label(self, field_name: str) -> Annotation:
        return self.labels.get(field_name, Annotation())

    @property
    def text_characters(self) -> int | None:
        return len(self.description) if self.description else None


@dataclass(frozen=True, slots=True)
class DataSource:
    """The dimensions, original fingerprint and projected rows of one source."""

    id: str
    name: str
    format: str
    location: str
    provenance: str
    limitation: str
    revision: str | None
    status: str
    sha256: str | None = None
    hash_scope: str = "archivo original completo"
    columns: tuple[str, ...] = ()
    original_columns: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    records: tuple[DataRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class HoldoutState:
    """Evidence observed about the reserved set and its release artifact."""

    reserved_count: int
    preparation_pending: int
    artifact_status: str
    artifact_sha256: str | None = None
    reviewed_cases: int = 0
    type_review_verified: bool = False
    reviewed_type_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DataInventory:
    """One authenticated view with fixed source and revision versions."""

    sources: tuple[DataSource, ...]
    holdout: HoldoutState
    privacy_sha256: str
    input_fingerprint: tuple[tuple[str, int, int], ...]
    pilot_evidence_sha256: dict[str, str] = field(default_factory=dict)

    def records(self) -> tuple[DataRecord, ...]:
        return tuple(record for source in self.sources for record in source.records)


class MetadataEdit(BaseModel):
    """Explicit field corrections with a separate human confirmation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)
    titulo: str | None = Field(default=None, max_length=500)
    descripcion: str | None = Field(default=None, max_length=20000)
    tipo: Tipo | None = None
    severidad: Severidad | None = None
    activo_afectado: str | None = Field(default=None, max_length=160)
    fuente: str | None = Field(default=None, max_length=160)
    origen: str | None = Field(default=None, max_length=160)
    grupo: str | None = Field(default=None, max_length=100)
    estado: ReviewState | None = None
    observaciones: str | None = Field(default=None, max_length=1000)
    campos_revisados: tuple[LabelField, ...] = ()

    @field_validator("titulo", "descripcion", "activo_afectado", "fuente", "origen", "grupo", "observaciones", mode="before")
    @classmethod
    def clean_input(cls, value: object) -> object:
        if isinstance(value, str):
            if "\x00" in value:
                raise ValueError("El campo contiene un carácter nulo.")
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def review_fields(self) -> MetadataEdit:
        if len(set(self.campos_revisados)) != len(self.campos_revisados):
            raise ValueError("Cada campo se confirma una vez por revisión.")
        if (self.estado == "revisado") != bool(self.campos_revisados):
            raise ValueError("Selecciona los campos que confirmas y el estado revisado.")
        if self.estado == "excluido" and not self.observaciones:
            raise ValueError("Registra el motivo en Observaciones.")
        return self
