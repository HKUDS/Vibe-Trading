"""Offline numeric evidence diagnostics. Never imported by research runtime.

These checks produce findings for evaluation; they cannot rewrite, redact,
retry or withhold a user answer. Legacy figures declarations are understood
only to replay historical cases, not required by the product.
"""
from src.agent.resolution_context import IdentityConstraint, ResolutionContext
from src.agent.instrument_identity import IdentityRecord, ToolAuthorization
from evals.grounding.evidence import EvidenceRecord
from evals.grounding.policies import ValidationResult
from evals.grounding.ledger import GROUNDING_ARTIFACT, GroundingLedger

__all__ = ["GROUNDING_ARTIFACT", "EvidenceRecord", "GroundingLedger", "IdentityConstraint",
           "IdentityRecord", "ResolutionContext", "ToolAuthorization", "ValidationResult"]
