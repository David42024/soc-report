"""Verify the Phase 1 manifest and open only its development candidates."""
from __future__ import annotations

from collections import Counter, defaultdict
import json
import re

from pydantic import ValidationError

from src.data.manifest import ManifestStore
from src.data.models import LabelField
from src.training.partition import Case, Partition, TestSeal, build_partition
from src.training.settings import TrainingSettings
from src.utils.errors import DatasetError

SHA256 = re.compile(r"^[0-9a-f]{64}$")


def read_manifest(store: ManifestStore, version: str) -> dict:
    """Read a verified envelope for the selected real data version."""
    envelope = json.loads(store.read(version))
    if envelope["content"].get("phase") != 1:
        raise DatasetError("Selecciona un manifiesto de datos de la Fase 1.")
    return envelope


def _target_candidates(content: dict, target: LabelField) -> list[dict]:
    reserved = set(content["groups"]["reserved"]) | set(content["groups"].get("possible_reserved_overlap", ()))
    return [item for item in content["eligibility"]["candidates_by_target"][target]
            if not item.get("possible_reserved_overlap") and item["group_id"] not in reserved]


def _test_counts(held: dict, target: LabelField) -> dict[str, int]:
    fallback = held.get("reviewed_type_counts", {}) if target == "tipo" else {}
    counts = held.get("reviewed_counts_by_target", {}).get(target, fallback)
    if any(not isinstance(label, str) or type(count) is not int or count <= 0 for label, count in counts.items()):
        raise DatasetError("El sello de Prueba contiene conteos de clase inválidos.")
    return counts


def readiness(envelope: dict, target: LabelField, policy: TrainingSettings) -> dict:
    """Explain the real blockers without reading protected texts or the reserved file."""
    content = envelope["content"]
    held = content["holdout"]
    try:
        eligible = _target_candidates(content, target)
        all_rows = len(content["eligibility"]["candidates_by_target"][target])
        labels = Counter(item.get("label") for item in eligible if item.get("label"))
        groups = defaultdict(set)
        for item in eligible:
            if item.get("label"):
                groups[item["label"]].add(item["group_id"])
        test_counts = _test_counts(held, target)
        reasons = []
        if not eligible:
            reasons.append("El objetivo no tiene referencias humanas utilizables.")
        elif len(labels) < 2:
            reasons.append("El objetivo requiere al menos dos clases identificadas en el manifiesto.")
        for label in sorted(groups):
            # Five independent development groups and one additional validation group.
            if len(groups[label]) < policy.outer_folds + 1:
                reasons.append(f"{label}: {labels[label]} registros en {len(groups[label])} grupos. Se necesitan 5 grupos en Desarrollo y al menos 1 distinto en Validación.")
        if not held.get("test_ready_by_target", {}).get(target, False):
            reasons.extend(held.get("reasons", ()))
            reasons.append("La prueba reservada carece de un sello de referencia verificable para este objetivo.")
        elif not test_counts or not SHA256.fullmatch(held.get("artifact_sha256") or ""):
            reasons.append("El sello requiere conteos de clase y una huella en un manifiesto actualizado.")
        if eligible and not content.get("development_snapshot_sha256"):
            reasons.append("Publica una nueva versión en Datos del SOC para vincular la copia protegida de candidatos.")
        return {
            "version": envelope["run_id"], "sha256": envelope["content_sha256"],
            "target": target, "eligible": len(eligible), "excluded_overlap": all_rows - len(eligible),
            "pending": held["preparation_pending"], "reserve_rows": held["reserved_count"],
            "ready": not reasons, "reasons": list(dict.fromkeys(reasons)),
            "classes": [{"label": label, "candidates": labels[label], "groups": len(groups[label]),
                         "sealed": test_counts.get(label, 0)} for label in sorted(set(labels) | test_counts.keys())],
        }
    except (KeyError, TypeError, AttributeError):
        raise DatasetError("El manifiesto no contiene el esquema de elegibilidad de la Fase 1.") from None


def real_partition(store: ManifestStore, envelope: dict, target: LabelField,
                   policy: TrainingSettings, seed: int) -> Partition:
    """Bind accessible rows to a manifest and use only the test seal metadata."""
    status = readiness(envelope, target, policy)
    if not status["ready"]:
        raise DatasetError(" ".join(status["reasons"]))
    content = envelope["content"]
    try:
        expected = {item["record_key"]: (item["group_id"], item["label"])
                    for item in _target_candidates(content, target)}
        data = store.read_development(envelope["run_id"], content["development_snapshot_sha256"])
        cases = tuple(Case(key=row["key"], group=row["group"], label=row["labels"][target],
                           title=row["title"], description=row["description"])
                      for row in data if target in row["labels"])
        if len(cases) != len(expected) or {case.key: (case.group, case.label) for case in cases} != expected:
            raise ValueError
        held = content["holdout"]
        seal = TestSeal(held["artifact_sha256"], _test_counts(held, target), tuple(content["groups"]["reserved"]), "reserva_revisada")
        if not seal.groups or sum(seal.counts.values()) != held["reviewed_cases"]:
            raise ValueError
    except (ValueError, ValidationError, KeyError, TypeError):
        raise DatasetError("La copia de candidatos o los conteos del sello difieren del manifiesto.") from None
    return build_partition(cases, policy, seed, envelope["content_sha256"], seal=seal, version=envelope["run_id"])
