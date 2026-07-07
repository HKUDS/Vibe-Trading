"""Evidence identity models for policy decision recording."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.2.1"

EvidenceWriteStatus = Literal[
    "complete",
    "partial_trace_only",
    "partial_artifact_only",
    "partial_ledger_only",
    "outbox_pending",
    "write_failed",
]


class EvidenceIdentity(BaseModel):
    """Stable IDs that identify one policy decision across evidence stores."""

    schema_version: str = SCHEMA_VERSION
    decision_id: str | None = None
    policy_decision_artifact_id: str | None = None
    trace_event_id: str | None = None
    ledger_event_hash: str | None = None
    run_id: str | None = None
    session_id: str | None = None
    trial_id: str | None = None
    protocol_hash: str | None = None
    idempotency_key: str


class EvidenceWriteOutcome(BaseModel):
    """Best-effort write result for non-transactional evidence sinks."""

    schema_version: str = SCHEMA_VERSION
    decision_id: str
    trace_written: bool = False
    artifact_written: bool = False
    ledger_written: bool = False
    index_written: bool = False
    outbox_written: bool = False
    trace_event_id: str | None = None
    policy_decision_artifact_id: str | None = None
    ledger_event_hash: str | None = None
    errors: list[str] = Field(default_factory=list)
    status: EvidenceWriteStatus


def canonical_json(value: Any) -> str:
    """Return strict canonical JSON for hashing/idempotency."""
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    )


def hash_params(params: dict[str, Any]) -> str:
    """Hash tool params without storing their raw values in evidence IDs."""
    return hashlib.sha256(canonical_json(params).encode("utf-8")).hexdigest()


def compute_idempotency_key(*, decision: Any, context: Any, params_hash: str) -> str:
    """Compute the v1.2.1 stable policy-decision idempotency key."""
    payload = {
        "run_id": getattr(context, "run_id", None),
        "session_id": getattr(context, "session_id", None),
        "trial_id": getattr(context, "trial_id", None),
        "protocol_hash": getattr(context, "protocol_hash", None),
        "tool_name": getattr(decision, "tool_name", None),
        "surface": getattr(context, "surface", "unknown"),
        "mode": getattr(context, "mode", "observe"),
        "risk_level": getattr(decision, "risk_level", "R1_READ"),
        "action": getattr(decision, "action", "allow"),
        "reason_codes": list(getattr(decision, "reason_codes", []) or []),
        "params_hash": params_hash,
        "policy_engine_version": getattr(decision, "policy_engine_version", None),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def decision_id_for_key(idempotency_key: str) -> str:
    """Return the semantic policy decision ID for an idempotency key."""
    return f"pd_{idempotency_key[:32]}"


def policy_decision_artifact_id_for_key(idempotency_key: str) -> str:
    """Return the policy decision artifact ID for an idempotency key."""
    return f"art_policy_decision_{idempotency_key[:32]}"


def trace_event_id_for_key(idempotency_key: str) -> str:
    """Return the trace event ID for an idempotent decision record."""
    return f"trace_policy_decision_{idempotency_key[:32]}"


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value

