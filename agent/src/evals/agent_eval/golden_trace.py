"""Golden-trace comparison with allowed dynamic-field tolerance."""

from __future__ import annotations

import re
from typing import Any


_DYNAMIC_KEYS = {
    "timestamp",
    "timestamps",
    "created_at",
    "updated_at",
    "duration",
    "duration_ms",
    "durations",
    "elapsed_ms",
    "elapsed_s",
    "latency_ms",
    "decision_id",
    "uuid",
    "run_id",
    "artifact_id",
}
_HEX64_RE = re.compile(r"\b[a-fA-F0-9]{64}\b")
_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


def assert_golden_trace_equal(expected: Any, actual: Any) -> None:
    """Assert traces are equal after normalizing approved dynamic fields."""
    assert _normalize(expected) == _normalize(actual)


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _normalize(item)
            for key, item in sorted(value.items())
            if key not in _DYNAMIC_KEYS
        }
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, str):
        value = _UUID_RE.sub("<uuid>", value)
        value = _HEX64_RE.sub("<sha256>", value)
    return value
