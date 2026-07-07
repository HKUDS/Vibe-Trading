"""Runtime context and policy decision models."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from src.governance.manifest import ToolSurface
from src.reliability.artifacts.hashing import sha256_json
from src.reliability.redaction import redact_secrets


GovernanceMode = Literal["off", "observe", "warn", "enforce"]
PolicyAction = Literal["allow", "warn", "deny"]


class RuntimeContext(BaseModel):
    """Context available to the policy engine at call time."""

    surface: ToolSurface
    mode: GovernanceMode = "observe"
    session_id: str | None = None
    run_id: str | None = None
    user_auth_state: dict[str, Any] = Field(default_factory=dict)
    live_state: dict[str, Any] = Field(default_factory=dict)
    budget_state: dict[str, Any] = Field(default_factory=dict)
    state_authoritative: bool = False

    def with_authoritative_state(
        self,
        *,
        live_state: Mapping[str, Any] | None = None,
        user_auth_state: Mapping[str, Any] | None = None,
        budget_state: Mapping[str, Any] | None = None,
    ) -> "RuntimeContext":
        """Return a copy with provider-supplied state for policy checks."""

        return self.model_copy(
            update={
                "live_state": dict(live_state or {}),
                "user_auth_state": dict(user_auth_state or {}),
                "budget_state": dict(budget_state or {}),
                "state_authoritative": True,
            }
        )


class ParamAudit(BaseModel):
    """Hash plus redacted preview for tool parameters."""

    params_hash: str
    preview: dict[str, Any]


class PolicyDecision(BaseModel):
    """Result of evaluating one tool call against governance policy."""

    decision_id: str = Field(default_factory=lambda: f"pd_{uuid4().hex}")
    tool_name: str
    action: PolicyAction
    mode: GovernanceMode
    reasons: list[str]
    required_checks: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    rule_id: str | None = None
    params_hash: str | None = None
    params_preview: dict[str, Any] | None = None


def build_param_audit(params: dict[str, Any] | None) -> ParamAudit:
    """Build a stable hash and redacted preview without storing raw params."""

    redacted = redact_secrets(params or {})
    preview = _json_safe(redacted)
    if not isinstance(preview, dict):
        preview = {"value": preview}
    try:
        params_hash = sha256_json({"params": preview})
    except Exception:  # noqa: BLE001 - fall back to canonical text for exotic objects
        payload = json.dumps(preview, ensure_ascii=False, sort_keys=True, default=str)
        import hashlib

        params_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return ParamAudit(params_hash=params_hash, preview=preview)


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return repr(value)[:120]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in list(value.items())[:50]:
            safe[str(key)] = _json_safe(item, depth=depth + 1)
        return safe
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item, depth=depth + 1) for item in list(value)[:50]]
    return repr(value)[:200]
