"""Canonical protocol hashing."""

from __future__ import annotations

from typing import Any

from src.reliability.artifacts.hashing import sha256_json
from src.research_protocol.model import ResearchProtocol


HASH_EXCLUDED_FIELDS = {
    "protocol_id",
    "protocol_hash",
    "registered_at",
    "created_at",
    "status",
    "created_by",
    "metadata",
}


def protocol_hash_payload(protocol: ResearchProtocol) -> dict[str, Any]:
    """Return the canonical JSON payload used for protocol hashing."""

    payload = protocol.model_dump(mode="json")
    for field in HASH_EXCLUDED_FIELDS:
        payload.pop(field, None)
    return payload


def compute_protocol_hash(protocol: ResearchProtocol) -> str:
    """Return a cross-machine stable hash for research-design fields."""

    return sha256_json(protocol_hash_payload(protocol))
