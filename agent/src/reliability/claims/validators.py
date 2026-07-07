"""Validation helpers for structured research claims."""

from __future__ import annotations

import re
from typing import Any

from src.reliability.claims.model import ClaimAudit, ClaimSet
from src.reliability.redaction import REDACTED, redact_secrets

_SECRET_VALUE_RE = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._~+/=-]{16,}|(?:sk|rk|pk|ghp|gho|ghu|github_pat)-[A-Za-z0-9_\-]{20,})"
)


def validate_claim_set(claim_set: ClaimSet) -> ClaimAudit:
    """Validate a ClaimSet before it is persisted or used by gates."""
    errors: list[str] = []
    seen_claim_ids: set[str] = set()
    for claim in claim_set.claims:
        if claim.claim_id in seen_claim_ids:
            errors.append(f"duplicate claim_id: {claim.claim_id}")
        seen_claim_ids.add(claim.claim_id)
        if claim.requires_gate and not claim.source_ref:
            errors.append(f"claim {claim.claim_id} requires source_ref")
        if _contains_secret(claim.claim_text):
            errors.append(f"claim {claim.claim_id} contains secret-like claim_text")
        if _contains_secret(claim.source_ref):
            errors.append(f"claim {claim.claim_id} contains secret-like source_ref")
        if _contains_secret(claim.evidence_refs):
            errors.append(f"claim {claim.claim_id} contains secret-like evidence_refs")
    if _contains_secret(claim_set.generated_by):
        errors.append("claim_set generated_by contains secret-like value")
    audit = ClaimAudit(
        run_id=claim_set.run_id,
        claim_set_id=claim_set.claim_set_id,
        checked_claim_ids=[claim.claim_id for claim in claim_set.claims],
        errors=errors,
    )
    if errors:
        raise ValueError("; ".join(errors))
    return audit


def _contains_secret(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(_SECRET_VALUE_RE.search(value) or redact_secrets(value) == REDACTED)
    redacted = redact_secrets(value)
    return redacted != value
