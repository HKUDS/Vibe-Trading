"""Deterministic strict-JSON serialization of public pt-v2.0 wire payloads.

Sorted keys + compact separators keep bytes stable; every hostile numeric is
rejected by the shared normalizer before ``json.dumps`` can emit a
non-standard token. INTERNAL faults raised by the builders propagate here as
transport errors, never as serialized envelopes.
"""

from __future__ import annotations

import json
from typing import Any

from .orchestrator import OrchestrationCode
from .wire_normalize import _normalize_json
from .wire_success import build_success_payload
from .wire_validation import build_error_payload


def dumps_payload(payload: Any) -> str:
    """Serialize a public payload with the deterministic strict-JSON spelling.

    Sorted keys + compact separators keep bytes stable; ``ensure_ascii=False``
    keeps UTF-8 raw; every float/Decimal/non-finite/invalid-UTF-8 value is
    rejected before ``json.dumps`` can emit a non-standard token.
    """
    normalized = _normalize_json(payload, "$")
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def serialize_success(document: Any) -> str:
    """Build and dump the public success document in one call."""
    return dumps_payload(build_success_payload(document))


def serialize_error(
    raw_input: Any,
    *,
    code: OrchestrationCode,
    reason: str,
    path: str = "$",
    detail: str = "",
    bucket_id: str | None = None,
) -> str:
    """Build and dump one public error envelope in one call."""
    return dumps_payload(
        build_error_payload(
            raw_input,
            code=code,
            reason=reason,
            path=path,
            detail=detail,
            bucket_id=bucket_id,
        )
    )
