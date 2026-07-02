"""Agent identity verification for multi-agent trading workflows.

Provides pluggable identity verification so each agent in a swarm can
prove its identity and permissions before executing trading actions.
Integrates with the existing mandate gate and audit ledger systems.
"""

from agent.identity.verifier import (
    AgentCredential,
    AgentVerifier,
    StructuralVerifier,
    VerificationResult,
)
from agent.identity.gate import IdentityGate

__all__ = [
    "AgentCredential",
    "AgentVerifier",
    "IdentityGate",
    "StructuralVerifier",
    "VerificationResult",
]
