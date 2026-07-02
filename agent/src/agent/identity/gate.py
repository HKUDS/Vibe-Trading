"""Identity gate for trading actions.

Sits alongside the existing mandate gate and order gate.
Verifies agent identity before allowing trade execution.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from agent.identity.verifier import AgentVerifier, StructuralVerifier, VerificationResult

logger = logging.getLogger(__name__)


# Permission requirements per action type
DEFAULT_ACTION_PERMISSIONS: Dict[str, List[str]] = {
    # Read-only actions
    "market_data": ["read"],
    "portfolio_view": ["read"],
    "analysis": ["read"],

    # Trading actions
    "buy": ["read", "trade"],
    "sell": ["read", "trade"],
    "short": ["read", "trade"],

    # Approval actions (risk committee)
    "approve_trade": ["read", "approve"],
    "reject_trade": ["read", "approve"],

    # Administrative
    "modify_mandate": ["admin"],
    "halt_trading": ["admin"],
}


class IdentityGate:
    """Pre-execution identity verification gate.

    Verifies agent credentials and checks action-level permissions
    before allowing trade execution. Integrates with the audit ledger
    by returning structured decision records.

    Args:
        verifier: AgentVerifier implementation. Required when enabled.
        enabled: Whether identity checking is active (default: False).
        action_permissions: Custom action-to-permission mapping.
    """

    def __init__(
        self,
        verifier: Optional[AgentVerifier] = None,
        enabled: bool = False,
        action_permissions: Optional[Dict[str, List[str]]] = None,
    ):
        self._enabled = enabled
        self._verifier = verifier
        self._action_permissions = {
            **DEFAULT_ACTION_PERMISSIONS,
            **(action_permissions or {}),
        }
        self._decisions: List[Dict[str, Any]] = []

        if enabled and verifier is None:
            raise ValueError(
                "IdentityGate requires a verifier when enabled. "
                "Pass a real AgentVerifier implementation, or "
                "StructuralVerifier() for development only."
            )

    def check(self, token: str, action: str) -> Optional[str]:
        """Check if an agent is authorized for an action.

        Args:
            token: The agent's credential token string.
            action: The action being attempted (e.g., "buy", "sell").

        Returns:
            None if authorized, or an error message if denied.
        """
        if not self._enabled:
            return None

        if not token:
            self._record("deny", "", action, "no credential provided")
            return "Agent identity required for this action"

        result = self._verifier.verify(token)

        if not result.verified:
            self._record("deny", "", action, result.reason)
            return f"Identity verification failed: {result.reason}"

        # Check action permissions
        required = self._action_permissions.get(action)
        if required:
            missing = [p for p in required if p not in result.credential.permissions]
            if missing:
                self._record(
                    "deny",
                    result.credential.agent_id,
                    action,
                    f"missing permissions: {missing}",
                )
                return (
                    f"Agent '{result.credential.agent_id}' lacks "
                    f"permissions {missing} for action '{action}'"
                )

        self._record("allow", result.credential.agent_id, action)
        logger.info(
            "Identity gate: ALLOW agent=%s action=%s role=%s",
            result.credential.agent_id,
            action,
            result.credential.role,
        )
        return None

    def _record(
        self, decision: str, agent_id: str, action: str, reason: str = ""
    ) -> None:
        """Record a decision for the audit ledger."""
        self._decisions.append({
            "decision": decision,
            "agent_id": agent_id,
            "action": action,
            "reason": reason,
            "timestamp": time.time(),
        })

    @property
    def decisions(self) -> List[Dict[str, Any]]:
        """Read-only access to decision history."""
        return list(self._decisions)
