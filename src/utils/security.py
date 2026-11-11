"""Redaction for experiment metadata and logs; no report bodies are logged."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import SecretStr

SENSITIVE_KEY = re.compile(r"password|contrase|api.?key|secret|authorization|access.?token|refresh.?token|database_url|redis_url|credential|dsn", re.I)
SECRET_VALUE = re.compile(r"\b(?:gsk_|sk-|AIza)[A-Za-z0-9_\-]{12,}|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|(?<=://)[^\s/@]+:[^\s/@]+@")


def redact(value: Any) -> Any:
    """Return a JSON-compatible copy with nested credentials removed."""
    if isinstance(value, SecretStr):
        return "[redactado]"
    if isinstance(value, Mapping):
        return {str(key): "[redactado]" if SENSITIVE_KEY.search(str(key)) else redact(item)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return SECRET_VALUE.sub("[redactado]", value)
    return value
