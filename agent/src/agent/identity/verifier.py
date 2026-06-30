"""Pluggable agent identity verification.

Provides a verifier interface and a structural dev stub.
Implement AgentVerifier for any identity system (JWT, DID, ZKP, etc.).
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class AgentCredential:
    """An agent's identity credential."""
    agent_id: str
    role: str  # e.g., "quant_desk", "risk_committee", "portfolio_manager"
    permissions: List[str]  # e.g., ["read", "trade", "approve"]
    expiry: float  # unix timestamp
    metadata: dict = field(default_factory=dict)

    def is_expired(self) -> bool:
        return self.expiry > 0 and self.expiry < time.time()


@dataclass
class VerificationResult:
    """Result of an identity verification check."""
    verified: bool
    credential: Optional[AgentCredential] = None
    reason: str = ""


class AgentVerifier(ABC):
    """Pluggable agent identity verifier.

    Implement for any identity system: JWT, API keys, ZKP proofs, etc.
    """

    @abstractmethod
    def verify(self, token: str) -> VerificationResult:
        """Verify an agent token and return the result."""


class StructuralVerifier(AgentVerifier):
    """Development verifier — checks JSON credential structure only.

    NOT for production. Accepts any well-formed JSON with the required
    fields. Use a real verifier for deployed systems.
    """

    def verify(self, token: str) -> VerificationResult:
        try:
            data = json.loads(token)
        except (json.JSONDecodeError, TypeError):
            return VerificationResult(verified=False, reason="invalid JSON")

        agent_id = data.get("agent_id", "")
        if not agent_id:
            return VerificationResult(verified=False, reason="missing agent_id")

        role = data.get("role", "")
        permissions = data.get("permissions", [])
        expiry = data.get("expiry", 0)

        if not expiry or expiry <= 0:
            return VerificationResult(verified=False, reason="missing expiry")

        credential = AgentCredential(
            agent_id=agent_id,
            role=role,
            permissions=permissions,
            expiry=expiry,
            metadata=data.get("metadata", {}),
        )

        if credential.is_expired():
            return VerificationResult(verified=False, reason="credential expired")

        return VerificationResult(verified=True, credential=credential)
