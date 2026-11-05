"""Pinned VCDB input and the human-reviewed evaluation manifest."""
from collections import Counter, defaultdict
from hashlib import file_digest, sha256
import json
from pathlib import PurePosixPath
import re
from urllib.parse import urlsplit
from zipfile import ZipFile

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from typing import Literal
from uuid import UUID

from backend.classifier import Severidad, Tipo
from backend.report_input import ReportInput


REVISION = "f6f98c00f66ab35f5b49977a5852ce94a5bb31d1"
ARCHIVE_HASH = "3882cbd28f587a6a0d39a68b68e8bbf64652e91530ce2a1e8d5be64cc7e8f385"
REPOSITORY = "https://github.com/vz-risk/VCDB"
DATASET = {"repository": REPOSITORY, "revision": REVISION, "sha256": ARCHIVE_HASH, "license": "CC-BY-SA-4.0"}
SOURCE_PREFIX = f"{REPOSITORY}/blob/{REVISION}/data/json/validated/"
MAPPING = {
    ("social", "Phishing"): "phishing",
    ("malware", "Ransomware"): "malware",
    ("hacking", "Use of stolen creds"): "acceso_no_autorizado",
    ("misuse", "Privilege abuse"): "uso_indebido",
}
SENSITIVE = re.compile(
    r"https?://|[\w.+-]+@[\w.-]+\.[a-z]{2,}|\b(?:\d{1,3}\.){3}\d{1,3}\b"
    r"|\b(?:\d[ -]?){13,19}\b|\b(?:gsk_|sk-|AIza)[A-Za-z0-9_-]{12,}"
    r"|\b(?:password|token|contraseña|api.?key|secret)\s*[:=]\s*\S+",
    re.IGNORECASE,
)


def references(case):
    urls = []
    reference = re.sub(r",\s*(?=https?://)", " ", case.get("reference") or "")
    for value in re.findall(r"https?://[^\s;<>]+", reference):
        try:
            url = urlsplit(value)
            if url.hostname and not (url.username or url.password or url.query or url.fragment):
                urls.append(value)
        except ValueError:
            continue
    return sorted(set(urls))


def canonical_text(text):
    return sha256(" ".join(text.casefold().split()).encode()).hexdigest()


def index_archive(path):
    with path.open("rb") as handle:
        if file_digest(handle, "sha256").hexdigest() != ARCHIVE_HASH:
            raise ValueError("SHA-256 inesperado. Usa el ZIP de la revisión fijada de VCDB.")
    exclusions = Counter()
    ids = Counter()
    summaries = Counter()
    candidates = []
    with ZipFile(path) as archive:
        for name in archive.namelist():
            if not (name.endswith(".json") and "/data/json/validated/" in name):
                continue
            case = json.loads(archive.read(name))
            filename = PurePosixPath(name).name
            source_id = PurePosixPath(filename).stem.lower()
            internal_id = str(case["incident_id"]).strip().lower()
            ids[internal_id] += 1
            try:
                if str(UUID(source_id)) != source_id:
                    raise ValueError
            except ValueError:
                exclusions["identificador_de_archivo_no_canonico"] += 1
                continue
            if str(case.get("security_incident", "")).lower() != "confirmed":
                exclusions["no_confirmado"] += 1
                continue
            try:
                payload = ReportInput(titulo=f"Incidente público {source_id}", descripcion=case.get("summary"))
            except ValidationError:
                exclusions["resumen_fuera_de_contrato"] += 1
                continue
            urls = references(case)
            if not urls:
                exclusions["sin_url_publica_simple"] += 1
                continue
            action = case.get("action", {})
            labels = sorted({label for (category, term), label in MAPPING.items()
                             if term in action.get(category, {}).get("variety", [])})
            if not labels:
                exclusions["sin_etiqueta_inicial_en_el_alcance"] += 1
                continue
            digest = canonical_text(payload.descripcion)
            summaries[digest] += 1
            date = case.get("timeline", {}).get("incident", {})
            candidates.append((internal_id, digest, {
                "source_id": source_id, "vcdb_record": SOURCE_PREFIX + filename,
                "source_urls": urls, "incident_date_parts": date,
                "suggested_types": labels,
            }))
    eligible = {}
    for internal_id, digest, item in candidates:
        if ids[internal_id] > 1 or summaries[digest] > 1:
            exclusions["identificador_o_resumen_duplicado"] += 1
        else:
            eligible[item["source_id"]] = item

    # Preserve the earlier pilot's deterministic ranking. Review remains manual.
    groups = defaultdict(list)
    for item in eligible.values():
        if len(item["suggested_types"]) == 1:
            groups[item["suggested_types"][0]].append(item["source_id"])
    pilot = {source_id for group in groups.values() for source_id in sorted(
        group, key=lambda key: sha256(f"soc-fit-v1:{key}".encode()).hexdigest())[:8]}
    for key, item in eligible.items():
        item["suggested_partition"] = "pilot" if key in pilot else "holdout_candidate"
    return eligible, {
        "dataset": DATASET, "validated_files": ids.total(), "eligible": len(eligible),
        "exclusions": dict(exclusions), "single_suggested_type": {key: len(value) for key, value in sorted(groups.items())},
        "multiple_suggested_types": sum(len(item["suggested_types"]) > 1 for item in eligible.values()),
        "pilot_suggestions": len(pilot),
    }


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reviewer: str = Field(min_length=2, max_length=80)
    tipo: Tipo


class ReviewedCase(ReportInput):
    source_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    source_url: str
    group: str = Field(min_length=1, max_length=100)
    source_stage: Literal["initial_public_report", "retrospective_summary"]
    redaction_reviewed: Literal[True]
    tipo: Tipo
    severidad: Severidad | None = None
    activo_afectado: str | None = Field(default=None, max_length=160)
    reviews: list[Review] = Field(min_length=1, max_length=10)
    adjudication: str | None = Field(default=None, min_length=12, max_length=300)

    @model_validator(mode="after")
    def valid_review(self):
        if len({review.reviewer.casefold() for review in self.reviews}) != len(self.reviews):
            raise ValueError("Los revisores deben ser distintos.")
        if any(review.tipo != self.tipo for review in self.reviews) and not self.adjudication:
            raise ValueError("Documenta cómo se resolvió la discrepancia de tipo.")
        if SENSITIVE.search(self.titulo + "\n" + self.descripcion):
            raise ValueError("La entrada contiene un indicador de datos sensibles o un enlace. Revisa la redacción.")
        return self


class ReviewedSet(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    revision: Literal[REVISION]
    stage: Literal["pilot", "holdout"]
    sampling: str = Field(min_length=20, max_length=2000)
    cases: list[ReviewedCase] = Field(min_length=1, max_length=1000)


def validate_sample(sample, eligible):
    ids = set()
    groups = set()
    summaries = set()
    pilot_urls = {url for item in eligible.values() if item["suggested_partition"] == "pilot"
                  for url in item["source_urls"]}
    for case in sample.cases:
        entry = eligible.get(case.source_id)
        if not entry or case.source_url not in entry["source_urls"]:
            raise ValueError(f"Caso o referencia fuera del manifiesto VCDB: {case.source_id}.")
        digest = canonical_text(case.descripcion)
        if case.source_id in ids or case.group.casefold() in groups or digest in summaries:
            raise ValueError(f"Caso, grupo o descripción repetidos: {case.source_id}.")
        if sample.stage == "holdout" and (len(case.reviews) < 2 or entry["suggested_partition"] == "pilot"
                                           or pilot_urls.intersection(entry["source_urls"])):
            raise ValueError(f"El caso reservado exige dos revisores y separación del piloto: {case.source_id}.")
        ids.add(case.source_id)
        groups.add(case.group.casefold())
        summaries.add(digest)
