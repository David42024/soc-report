"""Prepare two independent VCDB reviews and freeze their adjudicated manifest."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.classifier import Tipo
from backend.config import ROOT
from backend.report_input import ReportInput
from scripts.soc_dataset import OUTPUT, check_prior_pilots, encode, write_json
from scripts.vcdb import DATASET, MAPPING, REVISION, SENSITIVE, ReviewedSet, index_archive, validate_sample


class Preparation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_id: str
    disposition: Literal["include", "exclude"] | None = None
    exclusion_reason: str | None = Field(default=None, min_length=8, max_length=500)
    source_url: str | None = None
    group: str | None = Field(default=None, min_length=1, max_length=100)
    source_stage: Literal["initial_public_report", "retrospective_summary"] | None = None
    titulo: str | None = None
    descripcion: str | None = None
    redaction_reviewed: bool = False


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_id: str
    tipo: Tipo


class ReviewForm(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    packet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer: str = Field(min_length=2, max_length=80)
    cases: list[Decision] = Field(min_length=1)


class Adjudication(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    tipo: Tipo
    reason: str = Field(min_length=12, max_length=300)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def source_key(url):
    parts = urlsplit(url)
    return parts.hostname.removeprefix("www."), parts.path.rstrip("/").casefold()


def exposed(eligible):
    inputs = ROOT / "integrations/dataset"
    ids = set(read_json(inputs / "vcdb-pilot-exclusions.json")["source_ids"])
    ids.update(row["source_id"] for row in read_json(inputs / "vcdb-pilot.json")["cases"])
    ids.update(key for key, row in eligible.items() if row["suggested_partition"] == "pilot")
    urls = {source_key(url) for key in ids & eligible.keys() for url in eligible[key]["source_urls"]}
    for file in OUTPUT.glob("*/results.json"):
        run = read_json(file)["inputs"]
        if run["stage"] == "pilot":
            for key, entry in run.get("selection", {}).items():
                ids.add(key)
                urls.add(source_key(entry["source_url"]))
                urls.update(source_key(url) for url in eligible.get(key, {}).get("source_urls", []))
    return ids, urls


def select(eligible, per_type, seed):
    blocked, sources = exposed(eligible)
    counts = Counter()
    cases = []
    order = sorted(eligible.values(), key=lambda row: sha256(f"{seed}:{row['source_id']}".encode()).digest())
    for row in order:
        labels = row["suggested_types"]
        urls = {source_key(url) for url in row["source_urls"]}
        if row["source_id"] in blocked or urls & sources or len(labels) != 1 or counts[labels[0]] >= per_type:
            continue
        sources.update(urls)
        counts[labels[0]] += 1
        cases.append({key: row[key] for key in ("source_id", "vcdb_record", "source_urls", "incident_date_parts")})
    if len(cases) != per_type * len(set(MAPPING.values())):
        raise ValueError(f"Fuentes elegibles insuficientes para la cuota. Selección lograda: {dict(counts)}.")
    return {"status": "draft_for_independent_review", "dataset": DATASET, "seed": seed,
            "sampling": f"Preselección equilibrada de {per_type} candidatos por categoría provisional, ordenados por "
                        "SHA-256 de semilla e ID. Se excluyen casos piloto y referencias duplicadas. "
                        "Revisar campañas, redacción y etiquetas antes de congelar la muestra.", "cases": cases}


def verify_queue(queue):
    if queue.get("dataset") != DATASET or queue.get("status") != "draft_for_independent_review":
        raise ValueError("Se requiere la cola reservada de la revisión fijada de VCDB.")
    cases = queue["cases"]
    if not cases or len({row["source_id"] for row in cases}) != len(cases):
        raise ValueError("La cola debe tener candidatos únicos.")
    return cases


def initialize(queue):
    return {"cases": [Preparation(source_id=row["source_id"]).model_dump(mode="json")
                      for row in verify_queue(queue)]}


def make_packet(queue, preparation, eligible):
    queued = {row["source_id"] for row in verify_queue(queue)}
    rows = [Preparation.model_validate(row) for row in preparation["cases"]]
    if len(rows) != len(queued) or {row.source_id for row in rows} != queued:
        raise ValueError("Decide cada caso de la cola una sola vez.")
    undecided = sum(row.disposition is None for row in rows)
    if undecided:
        raise ValueError(f"Faltan decisiones de inclusión o exclusión en {undecided} casos.")
    exclusions = {}
    included = {}
    groups = set()
    blocked, sources = exposed(eligible)
    for row in rows:
        key = row.source_id
        if row.disposition == "exclude":
            if not row.exclusion_reason:
                raise ValueError(f"{key}: documenta el motivo de exclusión.")
            exclusions[key] = row.exclusion_reason
            continue
        entry = eligible.get(key)
        if not entry or entry["suggested_partition"] != "holdout_candidate" or row.source_url not in entry["source_urls"]:
            raise ValueError(f"{key}: caso o fuente fuera de la muestra reservada.")
        urls = {source_key(url) for url in entry["source_urls"]}
        if key in blocked or sources & urls:
            raise ValueError(f"{key}: el caso o su fuente ya aparecen en el piloto o el paquete.")
        if not row.group or row.group.casefold() in groups or not row.source_stage or not row.redaction_reviewed:
            raise ValueError(f"{key}: indica un grupo único, el momento de la fuente y la revisión de redacción.")
        payload = ReportInput(titulo=row.titulo, descripcion=row.descripcion)
        if SENSITIVE.search(payload.titulo + "\n" + payload.descripcion):
            raise ValueError(f"{key}: el texto incluye un enlace o indicador de datos sensibles.")
        groups.add(row.group.casefold())
        sources.update(urls)
        included[key] = {"source_id": key, "source_url": row.source_url, "group": row.group,
                         "source_stage": row.source_stage, "redaction_reviewed": True, **payload.model_dump()}
    if not included:
        raise ValueError("El paquete requiere al menos un caso incluido.")
    return {"dataset": DATASET, "sampling": queue["sampling"], "excluded": exclusions, "cases": included}


def review_template(packet):
    digest = sha256(encode(packet).encode()).hexdigest()
    return {"packet_sha256": digest, "reviewer": "", "cases": [
        {"source_id": case_id, "tipo": None} for case_id in packet["cases"]
    ]}


def freeze(packet, first, second, resolutions, eligible):
    if packet.get("dataset") != DATASET:
        raise ValueError("El paquete no corresponde a la revisión fijada de VCDB.")
    digest = sha256(encode(packet).encode()).hexdigest()
    if first.packet_sha256 != digest or second.packet_sha256 != digest:
        raise ValueError("Las dos revisiones deben corresponder al mismo paquete congelado.")
    if first.reviewer.casefold() == second.reviewer.casefold():
        raise ValueError("Se requieren dos revisores distintos.")
    types = []
    for review in (first, second):
        decisions = {decision.source_id: decision.tipo for decision in review.cases}
        if len(decisions) != len(review.cases) or decisions.keys() != packet["cases"].keys():
            raise ValueError("Cada revisión debe etiquetar todos los casos incluidos una sola vez.")
        types.append(decisions)
    disagreements = {key for key in packet["cases"] if types[0][key] != types[1][key]}
    if disagreements != resolutions.keys():
        missing = ", ".join(sorted(disagreements - resolutions.keys()))
        unexpected = ", ".join(sorted(resolutions.keys() - disagreements))
        raise ValueError(f"La adjudicación debe cubrir exactamente las discrepancias. Faltan: {missing or 'ninguna'}. "
                         f"Sobran: {unexpected or 'ninguna'}.")
    cases = []
    for key, case in packet["cases"].items():
        resolution = resolutions.get(key)
        cases.append({
            **case, "tipo": resolution.tipo if resolution else types[0][key],
            "adjudication": resolution.reason if resolution else None,
            "reviews": [{"reviewer": review.reviewer, "tipo": labels[key]}
                        for review, labels in zip((first, second), types, strict=True)],
        })
    sample = ReviewedSet(revision=REVISION, stage="holdout", sampling=packet["sampling"], cases=cases)
    validate_sample(sample, eligible)
    blocked, urls = exposed(eligible)
    for case in sample.cases:
        sources = {source_key(url) for url in eligible[case.source_id]["source_urls"]}
        if case.source_id in blocked or sources & urls:
            raise ValueError(f"{case.source_id}: el caso o su fuente se repiten en el piloto o la muestra.")
        urls.update(sources)
    check_prior_pilots(sample, OUTPUT)
    return sample, len(disagreements)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    selection = commands.add_parser("select", help="preseleccionar candidatos reproducibles sin mostrar tipos")
    selection.add_argument("--per-type", type=int, default=40, choices=range(1, 251), metavar="1-250")
    selection.add_argument("--seed", default="soc-vcdb-holdout-draft-v1")
    init = commands.add_parser("init", help="crear plantilla de preparación")
    packet = commands.add_parser("packet", help="generar material ciego y dos planillas")
    merge = commands.add_parser("freeze", help="validar revisiones y generar el manifiesto")
    for command in (selection, init, packet, merge):
        command.add_argument("--output", type=Path, required=True)
    for command in (init, packet):
        command.add_argument("--queue", type=Path, required=True)
    for command in (selection, packet, merge):
        command.add_argument("--archive", type=Path, required=True)
    packet.add_argument("--preparation", type=Path, required=True)
    for flag in ("packet", "review-a", "review-b"):
        merge.add_argument("--" + flag, type=Path, required=True)
    merge.add_argument("--adjudication", type=Path)
    options = parser.parse_args()
    try:
        if options.command == "select":
            eligible, _ = index_archive(options.archive)
            draft = select(eligible, options.per_type, options.seed)
            if options.output.exists():
                raise ValueError("La cola de destino ya existe.")
            write_json(options.output, draft)
            print(f"Cola reservada con {len(draft['cases'])} candidatos.")
        elif options.command == "init":
            template = initialize(read_json(options.queue))
            if options.output.exists():
                raise ValueError("La plantilla de destino ya existe.")
            write_json(options.output, template)
            print(f"Plantilla de preparación con {len(template['cases'])} candidatos.")
        elif options.command == "packet":
            eligible, _ = index_archive(options.archive)
            frozen = make_packet(read_json(options.queue), read_json(options.preparation), eligible)
            options.output.mkdir()
            write_json(options.output / "packet.json", frozen)
            write_json(options.output / "blinded-cases.json", {"cases": [
                {key: row[key] for key in ("source_id", "titulo", "descripcion")}
                for row in frozen["cases"].values()
            ]})
            template = review_template(frozen)
            for name in ("review-a.json", "review-b.json"):
                write_json(options.output / name, template)
            print(f"Paquete generado. Incluidos: {len(frozen['cases'])}. Excluidos: {len(frozen['excluded'])}.")
        else:
            eligible, _ = index_archive(options.archive)
            frozen = read_json(options.packet)
            first = ReviewForm.model_validate(read_json(options.review_a))
            second = ReviewForm.model_validate(read_json(options.review_b))
            raw = read_json(options.adjudication) if options.adjudication else {}
            decisions = {key: Adjudication.model_validate(value) for key, value in raw.items()}
            sample, disputed = freeze(frozen, first, second, decisions, eligible)
            if options.output.exists():
                raise ValueError("El manifiesto de destino ya existe.")
            write_json(options.output, sample.model_dump(mode="json"))
            print(f"Muestra congelada con {len(sample.cases)} casos y {disputed} discrepancias adjudicadas.")
        return 0
    except ValidationError as error:
        for issue in error.errors(include_input=False, include_context=False, include_url=False):
            print(f"{'.'.join(map(str, issue['loc']))}: {issue['msg']}")
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(f"Revisión interrumpida: {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
