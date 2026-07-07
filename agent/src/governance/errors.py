"""Governance exceptions."""

from __future__ import annotations

import json
from typing import Literal

from src.governance.decisions import PolicyDecision, RecordedPolicyDecision


class PolicyDenied(Exception):
    """Raised when governance policy blocks a tool call."""

    def __init__(
        self,
        decision: PolicyDecision | RecordedPolicyDecision,
        *,
        shadow: bool = False,
        user_safe_message: str | None = None,
        trace_status: Literal["denied", "skipped"] | None = None,
    ) -> None:
        self.decision = decision
        self.envelope = decision if isinstance(decision, RecordedPolicyDecision) else None
        self.shadow = shadow
        self.trace_status: Literal["denied", "skipped"] = trace_status or ("skipped" if shadow else "denied")
        self.user_safe_message = user_safe_message or self._default_message()
        super().__init__(self.user_safe_message)

    def _default_message(self) -> str:
        reason_text = "; ".join(self.decision.reasons) or "policy denied"
        return json.dumps(
            {
                "status": "error",
                "error_code": "policy_denied",
                "tool": self.decision.tool_name,
                "decision_id": getattr(self.decision, "decision_id", None),
                "rule_id": getattr(self.decision, "rule_id", None),
                "trace_status": self.trace_status,
                "shadow": self.shadow,
                "message": f"Tool call denied by governance policy: {reason_text}",
                "reasons": self.decision.reasons,
            },
            ensure_ascii=False,
        )
