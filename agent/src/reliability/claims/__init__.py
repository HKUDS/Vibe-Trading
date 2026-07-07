"""Structured claim capture for v1.2.1 research evidence."""

from __future__ import annotations

from src.reliability.claims.extractor import build_claim_set_from_research_card
from src.reliability.claims.model import ClaimAudit, ClaimSet, ResearchClaim
from src.reliability.claims.validators import validate_claim_set

__all__ = [
    "ClaimAudit",
    "ClaimSet",
    "ResearchClaim",
    "build_claim_set_from_research_card",
    "validate_claim_set",
]
