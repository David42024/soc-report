"""Seed numerical tools without altering the production LLM configuration."""
from __future__ import annotations

import os
import random
from importlib.metadata import PackageNotFoundError, version

import numpy as np


def seed_everything(seed: int) -> dict[str, int | bool]:
    """Seed Python and NumPy; report whether hash seeding preceded process start."""
    hash_seed_active = os.environ.get("PYTHONHASHSEED") == str(seed)
    random.seed(seed)
    np.random.seed(seed)
    return {"seed": seed, "hash_seed_at_start": hash_seed_active}


def software_versions(packages: tuple[str, ...]) -> dict[str, str]:
    """Capture installed versions without importing model libraries."""
    result = {}
    for package in packages:
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = "no instalado"
    return result
