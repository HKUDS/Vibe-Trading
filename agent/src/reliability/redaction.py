"""Secret redaction helpers for IRR-AGL records."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

_SECRET_KEY_FRAGMENTS = (
    "secret",
    "token",
    "api_key",
    "apikey",
    "password",
    "credential",
    "broker",
    "authorization",
    "cookie",
    "session",
    "private_key",
    "refresh_token",
    "access_token",
)

_BEARER_RE = re.compile(r"^\s*bearer\s+[A-Za-z0-9._~+/=-]{16,}\s*$", re.IGNORECASE)
_INLINE_BEARER_RE = re.compile(
    r"\bauthorization\s*:\s*bearer\s+[^\s,;]+|\bbearer\s+[A-Za-z0-9._~+/=-]{8,}",
    re.IGNORECASE,
)
_ENV_ASSIGNMENT_SECRET_RE = re.compile(
    r"\b[A-Z0-9_]*(?:SECRET|TOKEN|API_KEY|ACCESS_KEY|PRIVATE_KEY)[A-Z0-9_]*\s*=\s*[^\s,;]+",
    re.IGNORECASE,
)
_KEY_PREFIX_RE = re.compile(r"^\s*(sk|rk|pk|ghp|gho|ghu|github_pat)-[A-Za-z0-9_\-]{8,}\s*$", re.IGNORECASE)
_LONG_RANDOM_RE = re.compile(r"^(?=.*[A-Z])(?=.*[a-z])(?=.*\d)[A-Za-z0-9_\-+/=]{40,}$")


def redact_secrets(value: Any) -> Any:
    """Recursively redact secret-like keys and values."""
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _key_is_secret_like(key_text):
                redacted[key_text] = REDACTED
            else:
                redacted[key_text] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str) and _value_is_secret_like(value):
        return REDACTED
    return value


def _key_is_secret_like(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SECRET_KEY_FRAGMENTS)


def _value_is_secret_like(value: str) -> bool:
    return bool(
        _BEARER_RE.match(value)
        or _INLINE_BEARER_RE.search(value)
        or _ENV_ASSIGNMENT_SECRET_RE.search(value)
        or _KEY_PREFIX_RE.match(value)
        or _LONG_RANDOM_RE.match(value)
    )
