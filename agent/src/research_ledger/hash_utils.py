from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from typing import Any, Iterable

import numpy as np
import pandas as pd

_REDACTED = "[redacted]"
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "client_secret",
    "password",
    "passphrase",
    "private_key",
    "secret",
    "token",
)
_PATH_KEY_PARTS = (
    "cache_dir",
    "directory",
    "filepath",
    "folder",
    "path",
    "root",
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(authorization|bearer|api[_-]?key|secret|token|password)\b\s*[:=]\s*\S+"
)
_OPENAI_STYLE_SECRET_RE = re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9._-]{5,}\b")
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)[^\r\n]+")
_POSIX_ABSOLUTE_PATH_RE = re.compile(r"^/(?:home|mnt|opt|private|root|tmp|Users|var|workspace)(?:/|$)")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def json_safe(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return json_safe(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def canonical_json(obj: Any, *, exclude_keys: Iterable[str] = ()) -> str:
    payload = json_safe(obj)
    excluded = set(exclude_keys)
    if isinstance(payload, dict) and excluded:
        payload = {k: v for k, v in payload.items() if k not in excluded}
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_json_hash(obj: Any, *, exclude_keys: Iterable[str] = ()) -> str:
    canonical = canonical_json(obj, exclude_keys=exclude_keys)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _is_path_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(part in lowered for part in _PATH_KEY_PARTS)


def _is_secret_like_value(value: str) -> bool:
    return bool(_SECRET_VALUE_RE.search(value) or _OPENAI_STYLE_SECRET_RE.search(value))


def _is_absolute_local_path(value: str, *, key: str | None = None) -> bool:
    if "://" in value:
        return False
    if _WINDOWS_ABSOLUTE_PATH_RE.match(value):
        return True
    return bool(key and _is_path_key(key) and _POSIX_ABSOLUTE_PATH_RE.match(value))


def _redact_string(value: str, *, key: str | None = None) -> str:
    if _is_secret_like_value(value) or _is_absolute_local_path(value, key=key):
        return _REDACTED
    return value


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            if is_sensitive_key(key):
                redacted[key] = _REDACTED
            elif isinstance(v, str):
                redacted[key] = _redact_string(v, key=key)
            else:
                redacted[key] = redact_secrets(v)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(v) for v in value]
    if isinstance(value, tuple):
        return [redact_secrets(v) for v in value]
    if isinstance(value, str):
        return _redact_string(value)
    return json_safe(value)
