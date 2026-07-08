from __future__ import annotations

import dataclasses
import hashlib
import json
import math
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


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def json_safe(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
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


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): _REDACTED if is_sensitive_key(str(k)) else redact_secrets(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(v) for v in value]
    if isinstance(value, tuple):
        return [redact_secrets(v) for v in value]
    return json_safe(value)
