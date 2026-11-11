"""Local, request-scoped minimization at cloud egress; never store source text.

This is a deterministic detector with a documented scope, not an assertion of
universal anonymization. Originals belong only to the existing protected store.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from hashlib import sha256
from html import unescape
from ipaddress import ip_address
import logging
import os
from pathlib import Path
import re
import unicodedata
from urllib.parse import unquote
from collections.abc import Iterable, Mapping
from typing import Any

import yaml

LOGGER = logging.getLogger(__name__)
DEFAULT_POLICY = Path(__file__).resolve().parents[2] / "config" / "privacy.yaml"
ALIAS = re.compile(r"\[SOC_[A-Z0-9_]+_(\d{1,8})\]")


class PrivacyError(RuntimeError):
    """Safe error: a privacy failure must prevent every external request."""


@dataclass(frozen=True)
class Rule:
    """Compiled local detector, with no user-supplied state."""

    kind: str
    pattern: re.Pattern[str] = field(repr=False)


@dataclass(frozen=True)
class Policy:
    """Immutable, cached policy; never cache redacted or original inputs."""

    version: str
    digest: str
    max_characters: int
    max_matches: int
    technical_pattern: re.Pattern[str] = field(repr=False)
    rules: tuple[Rule, ...] = field(repr=False)


@lru_cache(maxsize=4)
def _read_policy(path: str, modified: int, size: int) -> Policy:
    """Reload after a configuration change and reject incomplete policies."""
    del modified, size
    try:
        raw = Path(path).read_bytes()
        data = yaml.safe_load(raw)
        version = data["version"]
        limit, matches = data["max_text_characters"], data["max_matches"]
        if not isinstance(version, str) or not re.fullmatch(r"[a-zA-Z0-9._-]{1,64}", version):
            raise ValueError
        if type(limit) is not int or not 4000 <= limit <= 100000:
            raise ValueError
        if type(matches) is not int or not 1 <= matches <= 4096:
            raise ValueError
        rules = []
        for item in data["rules"]:
            if not re.fullmatch(r"[A-Z_]{2,32}", item["kind"]) or len(item["pattern"]) > 4000:
                raise ValueError
            pattern = re.compile(item["pattern"])
            if pattern.match(""):
                raise ValueError
            rules.append(Rule(item["kind"], pattern))
        required = {"SECRETO", "EMAIL", "PERSONA", "DOCUMENTO", "DIRECCION", "IP", "TELEFONO"}
        if not required.issubset(rule.kind for rule in rules) or len(rules) > 64:
            raise ValueError
        phrases = data["technical_phrases"]
        if not isinstance(phrases, list) or not 1 <= len(phrases) <= 128 or any(not isinstance(p, str) or not p.strip() or len(p) > 100 for p in phrases):
            raise ValueError
        technical = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(p) for p in sorted(phrases, key=len, reverse=True)) + r")(?!\w)", re.I)
        return Policy(version, sha256(raw).hexdigest(), limit, matches,
                      technical, tuple(rules))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError, re.error, OverflowError, yaml.YAMLError):
        LOGGER.warning("Envío cloud bloqueado: política local de privacidad inválida.")
        raise PrivacyError("No se pudo cargar la política local de privacidad; envío bloqueado.") from None


def load_policy(path: Path | str | None = None) -> Policy:
    """Resolve the existing project's policy or a server-only environment override."""
    try:
        source = Path(path or os.environ.get("SOC_PRIVACY_POLICY", DEFAULT_POLICY))
        if not source.is_absolute():
            source = DEFAULT_POLICY.parents[1] / source
        stat = source.stat()
        return _read_policy(str(source.resolve()), stat.st_mtime_ns, stat.st_size)
    except OSError:
        LOGGER.warning("Envío cloud bloqueado: política local de privacidad no disponible.")
        raise PrivacyError("La política local de privacidad no está disponible; envío bloqueado.") from None


@dataclass(frozen=True)
class ProtectedText:
    """Only protected content and non-sensitive evidence may leave this module."""

    text: str = field(repr=False)
    evidence: dict[str, Any]


class RedactionSession:
    """Replace detected spans with typed aliases, consistent only in this request."""

    def __init__(self, *, policy_path: Path | str | None = None,
                 known_secrets: Iterable[str] = (), policy: Policy | None = None) -> None:
        self.policy = policy if policy is not None else load_policy(policy_path)
        self._aliases: dict[tuple[str, str], str] = {}
        self._counts: dict[str, int] = {}
        self._next_alias = 1
        self._characters = 0
        self._secrets = tuple(self._normalize(value) for value in known_secrets if isinstance(value, str) and len(value) >= 8)

    def new_session(self) -> RedactionSession:
        """Reuse the policy and known secrets while starting with empty aliases."""
        session = RedactionSession(policy=self.policy)
        session._secrets = self._secrets
        return session

    @staticmethod
    def _normalize(text: str) -> str:
        """Detect common HTML/URL and Unicode disguises without changing originals."""
        result = unicodedata.normalize("NFKC", unescape(text))
        for _ in range(2):
            decoded = unquote(result, errors="strict")
            if decoded == result:
                break
            result = decoded
        return "".join(char for char in result if char in "\n\t" or not unicodedata.category(char).startswith("C"))

    def protect(self, text: str) -> str:
        """Mask overlapping spans as one interval so partial matches cannot leak."""
        if not isinstance(text, str):
            raise PrivacyError("Entrada de privacidad inválida; envío bloqueado.")
        self._characters += len(text)
        if self._characters > self.policy.max_characters:
            raise PrivacyError("Entrada demasiado extensa para protegerla; envío bloqueado.")
        try:
            clean = self._normalize(text)
        except (UnicodeError, ValueError):
            raise PrivacyError("Codificación de entrada inválida; envío bloqueado.") from None
        # A second boundary can discover an additional identifier. Do not give
        # it an alias already assigned by the first boundary to another entity.
        for alias in ALIAS.finditer(clean):
            self._next_alias = max(self._next_alias, int(alias.group(1)) + 1)
        spans: list[tuple[int, int, str, int]] = []
        for secret in self._secrets:
            if secret:
                start = clean.find(secret)
                while start >= 0:
                    end = start + len(secret)
                    spans.append((start, end, "SECRETO", -1000))
                    start = clean.find(secret, end)
        for priority, rule in enumerate(self.policy.rules):
            for match in rule.pattern.finditer(clean):
                group = "value" if "value" in match.groupdict() and match.group("value") is not None else 0
                start, end = match.span(group)
                value = clean[start:end]
                if ALIAS.fullmatch(value.strip("\"'")):
                    continue  # A marker contains no identity or credential.
                if not value:
                    continue
                kind = rule.kind
                if kind == "PERSONA" and group == 0:
                    # Preserve technical phrases even inside a longer capitalized
                    # match: "Active Directory de María Pérez" keeps the asset
                    # type while masking the person. Explicit personal labels
                    # receive no exemption. Other detector kinds never use it.
                    cursor = 0
                    for technical in self.policy.technical_pattern.finditer(value):
                        fragment = value[cursor:technical.start()]
                        if fragment.strip() and fragment.strip().casefold() not in {"de", "del", "la", "las", "los", "y"}:
                            spans.append((start + cursor, start + technical.start(), kind, priority))
                        cursor = technical.end()
                    fragment = value[cursor:]
                    if fragment.strip() and fragment.strip().casefold() not in {"de", "del", "la", "las", "los", "y"}:
                        spans.append((start + cursor, end, kind, priority))
                    if len(spans) > self.policy.max_matches:
                        raise PrivacyError("Demasiados identificadores para protegerlos; envío bloqueado.")
                    continue
                if kind == "IP":
                    try:
                        address = ip_address(value)
                    except ValueError:
                        continue  # E.g. a software version or an incomplete IPv6.
                    kind = f"IPV{address.version}_{'PUBLICA' if address.is_global else 'PRIVADA'}"
                # Explicit labels (e.g. Teléfono:) take precedence over a bare
                # numeric recognizer while the union still protects all bytes.
                spans.append((start, end, kind, priority - 100 if group == "value" else priority))
                if len(spans) > self.policy.max_matches:
                    raise PrivacyError("Demasiados identificadores para protegerlos; envío bloqueado.")
        merged: list[tuple[int, int, str, int]] = []
        for start, end, kind, priority in sorted(spans):
            if merged and start < merged[-1][1]:
                old_start, old_end, old_kind, old_priority = merged.pop()
                merged.append((old_start, max(old_end, end), kind if priority < old_priority else old_kind,
                               min(priority, old_priority)))
            else:
                merged.append((start, end, kind, priority))
        parts, cursor = [], 0
        for start, end, kind, _ in merged:
            value = clean[start:end]
            key = kind, value.casefold()
            if key not in self._aliases:
                self._aliases[key] = f"[SOC_{kind}_{self._next_alias}]"
                self._next_alias += 1
            parts.extend((clean[cursor:start], self._aliases[key]))
            self._counts[kind] = self._counts.get(kind, 0) + 1
            cursor = end
        parts.append(clean[cursor:])
        return "".join(parts)

    def evidence(self) -> dict[str, Any]:
        """Audit only version, hash, category counts and success; no source values."""
        return {"status": "protected", "policy_version": self.policy.version,
                "policy_sha256": self.policy.digest, "counts": dict(sorted(self._counts.items()))}


def protect_text(text: str, *, policy_path: Path | str | None = None,
                 known_secrets: Iterable[str] = ()) -> ProtectedText:
    """Create a fresh session; originals and aliases are never cached or logged."""
    session = RedactionSession(policy_path=policy_path, known_secrets=known_secrets)
    protected = session.protect(text)
    return ProtectedText(protected, session.evidence())


def protect_messages(messages: Iterable[Mapping[str, str]], *,
                     known_secrets: Iterable[str] = ()) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Copy and protect all turns with one request-local dictionary, including history."""
    session = RedactionSession(known_secrets=known_secrets)
    protected = [{"role": message["role"], "content": session.protect(message["content"])} for message in messages]
    return protected, session.evidence()
