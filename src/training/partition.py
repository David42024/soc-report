"""Stratified group partitions and nested splits with an inaccessible test payload."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_array
from sklearn.model_selection import StratifiedGroupKFold

from src.data.models import content_hash
from src.training.settings import TrainingSettings
from src.utils.errors import DatasetError

PARTITIONS = ("Desarrollo", "Validación", "Prueba")


class Case(BaseModel):
    """One protected text with a single reference for the selected target."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    key: str = Field(pattern=r"^[0-9a-f]{64}$")
    group: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str = Field(min_length=5, max_length=120, repr=False)
    description: str = Field(min_length=15, max_length=4000, repr=False)
    label: str = Field(min_length=1, max_length=160)

    @property
    def text(self) -> str:
        return self.title + "\n" + self.description


@dataclass(frozen=True, slots=True)
class TestSeal:
    """Aggregate counts and a fingerprint only. Text and row labels stay sealed."""

    sha256: str
    counts: dict[str, int]
    groups: tuple[str, ...]
    kind: Literal["reserva_revisada", "prueba_tecnica_sintetica"]


@dataclass(frozen=True, slots=True)
class Partition:
    development: tuple[Case, ...]
    validation: tuple[Case, ...]
    test: TestSeal
    source: Literal["real", "sintetico"]
    source_sha256: str
    manifest_version: str | None = None

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(sorted({case.label for case in self.development}))

    def evidence(self) -> dict:
        """Fingerprint both accessible partitions and summarize the sealed part."""
        splits = [split_identity(rows) for rows in (self.development, self.validation)]
        by_label = []
        for label in self.labels:
            counts = [split["classes"].get(label, 0) for split in splits] + [self.test.counts[label]]
            by_label.append({"label": label, "counts": counts})
        return {
            "source": self.source, "source_sha256": self.source_sha256, "manifest_version": self.manifest_version,
            "development": splits[0], "validation": splits[1],
            "test": {"state": "sellada", "sha256": self.test.sha256, "classes": self.test.counts,
                     "groups_sha256": content_hash(self.test.groups), "blocked_groups": len(self.test.groups),
                     "kind": self.test.kind},
            "by_label": by_label, "groups_disjoint": True,
        }


@dataclass(frozen=True, slots=True)
class Split:
    train: tuple[int, ...]
    validation: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Fold:
    outer: Split
    inner: tuple[Split, ...]


def split_identity(rows: tuple[Case, ...]) -> dict:
    """Fingerprint membership and groups without exporting report contents."""
    return {
        "rows": len(rows), "groups": len({case.group for case in rows}),
        "classes": dict(Counter(case.label for case in rows)),
        "keys_sha256": content_hash(sorted(case.key for case in rows)),
        "groups_sha256": content_hash(sorted({case.group for case in rows})),
    }


def quotas(total: int, ratios: tuple[float, ...]) -> tuple[int, ...]:
    """Use the largest remainder and resolve equal fractions in partition order."""
    ideal = [total * Fraction(str(value)) for value in ratios]
    counts = [int(value) for value in ideal]
    order = sorted(range(len(counts)), key=lambda i: (counts[i] - ideal[i], i))
    for i in order[:total - sum(counts)]:
        counts[i] += 1
    return tuple(counts)


def _by_group(cases: tuple[Case, ...]) -> dict[str, Counter]:
    groups = defaultdict(Counter)
    for case in cases:
        groups[case.group][case.label] += 1
    return dict(sorted(groups.items()))


def _allocate(cases: tuple[Case, ...], policy: TrainingSettings, seed: int,
              sealed_counts: dict[str, int] | None) -> tuple[tuple[Case, ...], ...]:
    """Allocate whole groups with exact integer quotas and minimum class coverage."""
    labels = sorted({case.label for case in cases})
    if len(labels) < 2:
        raise DatasetError("La clasificación requiere al menos dos clases con referencia suficiente.")
    if sealed_counts is not None and set(sealed_counts) != set(labels):
        raise DatasetError("Las clases de la reserva revisada y de los candidatos deben coincidir.")
    groups = _by_group(cases)
    group_ids = tuple(groups)
    counts = Counter(case.label for case in cases)
    part_count = 3 if sealed_counts is None else 2
    needed = (policy.outer_folds,) + (1,) * (part_count - 1)
    target = {label: quotas(counts[label] + (sealed_counts or {}).get(label, 0), policy.ratios) for label in labels}
    positions = defaultdict(list)
    for index, group in enumerate(group_ids):
        for label, count in groups[group].items():
            positions[label].append((index, count))
    for label in labels:
        expected = target[label]
        if any(expected[i] < needed[i] for i in range(part_count)) or expected[2] < 1:
            raise DatasetError(f"{label}: las cuotas {expected} carecen de soporte para 5 folds externos y las tres particiones.")
        if len(positions[label]) < sum(needed):
            raise DatasetError(f"{label}: {len(positions[label])} grupos disponibles y {sum(needed)} necesarios para Desarrollo y las particiones abiertas.")
        if sealed_counts is not None and sealed_counts[label] != expected[2]:
            raise DatasetError(f"{label}: la reserva contiene {sealed_counts[label]} casos y la cuota del 15 % requiere {expected[2]}.")

    row_idx, col_idx, values, lower, upper = [], [], [], [], []

    def constraint(entries: list[tuple[int, int]], lo: int, hi: float) -> None:
        row_idx.extend([len(lower)] * len(entries))
        col_idx.extend(index for index, _ in entries)
        values.extend(value for _, value in entries)
        lower.append(lo)
        upper.append(hi)

    width = len(group_ids)
    for group in range(width):
        constraint([(part * width + group, 1) for part in range(part_count)], 1, 1)
    for part in range(part_count):
        for label, members in positions.items():
            count = target[label][part]
            constraint([(part * width + group, n) for group, n in members], count, count)
            constraint([(part * width + group, 1) for group, _ in members], needed[part], np.inf)
    size = width * part_count
    matrix = coo_array((np.array(values, dtype=float), (row_idx, col_idx)), shape=(len(lower), size)).tocsc()
    objective = (np.random.default_rng(seed).permutation(size) + 1) / size
    solution = milp(objective, integrality=np.ones(size, dtype=int), bounds=Bounds(0, 1),
                    constraints=LinearConstraint(matrix, lower, upper),
                    options={"time_limit": policy.partition_timeout_seconds})
    if not solution.success or solution.x is None:
        if solution.status == 2:
            raise DatasetError("Los tamaños y clases de los grupos impiden satisfacer las cuotas y el mínimo de folds.")
        raise DatasetError("El asignador agotó su margen sin certificar una partición reproducible.")
    assignments = dict(zip(group_ids, np.argmax(solution.x.reshape(part_count, width), axis=0)))
    parts = tuple(tuple(case for case in cases if assignments[case.group] == i) for i in range(part_count))
    for i, part in enumerate(parts):
        if Counter(case.label for case in part) != {label: target[label][i] for label in labels}:
            raise DatasetError("La partición calculada no coincide con las cuotas por clase.")
    return parts


def build_partition(cases: tuple[Case, ...], policy: TrainingSettings, seed: int, source_sha256: str, *,
                    seal: TestSeal | None = None, version: str | None = None) -> Partition:
    """Make an experimental plan without opening real test inputs."""
    ordered = tuple(sorted(cases, key=lambda case: case.key))
    if len({case.key for case in ordered}) != len(ordered):
        raise DatasetError("Hay identificadores repetidos en los candidatos.")
    if seal and set(seal.groups) & {case.group for case in ordered}:
        raise DatasetError("Un grupo de la reserva aparece en los candidatos. Corrige el manifiesto.")
    parts = _allocate(ordered, policy, seed, seal.counts if seal else None)
    if seal is None:
        development, validation, test = parts
        seal = TestSeal(content_hash([case.model_dump() for case in test]), dict(Counter(case.label for case in test)),
                        tuple(sorted({case.group for case in test})), "prueba_tecnica_sintetica")
        source = "sintetico"
    else:
        development, validation = parts
        source = "real"
    group_sets = [{case.group for case in rows} for rows in (development, validation)] + [set(seal.groups)]
    if sum(map(len, group_sets)) != len(set.union(*group_sets)):
        raise DatasetError("Las particiones comparten grupos. No se puede iniciar el experimento.")
    return Partition(development, validation, seal, source, source_sha256, version)


def _split(cases: tuple[Case, ...], indices: np.ndarray, n_splits: int, seed: int) -> tuple[Split, ...] | None:
    labels = np.array([cases[i].label for i in indices])
    groups = np.array([cases[i].group for i in indices])
    expected = set(labels)
    groups_per_class = {label: len(set(groups[labels == label])) for label in expected}
    if min(groups_per_class.values(), default=0) < n_splits:
        return None
    splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    result = []
    for train, validation in splitter.split(indices, labels, groups):
        if set(labels[train]) != expected or set(labels[validation]) != expected:
            return None
        if set(groups[train]) & set(groups[validation]):
            raise DatasetError("La validación cruzada produjo grupos compartidos.")
        result.append(Split(tuple(map(int, indices[train])), tuple(map(int, indices[validation]))))
    return tuple(result)


def nested_folds(cases: tuple[Case, ...], policy: TrainingSettings, seed: int) -> tuple[Fold, ...]:
    """Verify all five outer and all fifteen inner splits before any fit or call."""
    by_class = defaultdict(set)
    for case in cases:
        by_class[case.label].add(case.group)
    if len(by_class) < 2 or any(len(groups) < policy.outer_folds for groups in by_class.values()):
        details = ", ".join(f"{label}={len(groups)} grupos" for label, groups in sorted(by_class.items()))
        raise DatasetError(f"Desarrollo necesita 5 grupos por clase para los folds externos. Observado: {details or 'sin clases'}.")
    for attempt in range(policy.fold_seed_attempts):
        base = (seed + attempt) % (2**32)
        outer = _split(cases, np.arange(len(cases)), policy.outer_folds, base)
        if outer is None:
            continue
        folds = []
        for i, split in enumerate(outer):
            inner = next((candidate for offset in range(policy.fold_seed_attempts)
                          if (candidate := _split(cases, np.array(split.train), policy.inner_folds,
                                                 (base + i * policy.fold_seed_attempts + offset) % (2**32))) is not None), None)
            if inner is None:
                break
            folds.append(Fold(split, inner))
        if len(folds) == policy.outer_folds:
            return tuple(folds)
    raise DatasetError("No se obtuvieron 5 folds externos con 3 internos completos y todas las clases por grupo. Revisa la distribución de Desarrollo.")
