"""Mandatory policy and hook ordering for a bound tool invocation."""
from __future__ import annotations

import json
import threading
from typing import Any, Dict

from src.agent.tuning import _heartbeat_interval_s, _tool_timeout_seconds
from src.kernel.progress import HeartbeatTimer, _set_emitter
from src.kernel.tool_runner import wait_for_tool
from src.tools.redaction import redact_payload, redact_tool_result


class ToolInvocation:
    """Bind mandatory preflight, hook audit and non-detachable order handling."""

    def __init__(self, env, replay, hooks, cancelled, progress):
        self.env = env
        self.replay = replay
        self.hooks = hooks
        self.cancelled = cancelled
        self.progress = progress
        self._order_attempts = set()
        self._order_attempt_lock = threading.Lock()

    def reset(self) -> None:
        self._order_attempts.clear()

    def _invoke_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        *,
        call_id: str,
    ) -> tuple[str, int]:
        """Screen effective arguments, run hooks and invoke with the bound wait policy."""
        readonly = self.replay._is_tool_readonly(tool_name)
        order_tool = self._is_order_tool(tool_name)
        # Apply the provider tool policy before invoking a hook.  A hook can
        # add a refusal, while a hook result can never skip the policy gate.
        policy_check = getattr(self.env.registry, "check_policy", None)
        effective_args = args
        if callable(policy_check):
            allowed, policy_reason, effective_args = policy_check(tool_name, args)
            if not allowed:
                return json.dumps(
                    {"status": "error", "skipped": True, "error": policy_reason},
                    ensure_ascii=False,
                ), 0
        hooks = self.hooks or getattr(self.env.registry, "hooks", None)
        hook_payload = {
            "tool_name": tool_name,
            "call_id": call_id,
            "arguments": redact_payload(effective_args),
            "session_id": self.env.session_id,
        }
        if hooks is not None:
            decision = hooks.run("PreToolUse", hook_payload)
            if decision.denied:
                return json.dumps(
                    {
                        "status": "error",
                        "skipped": True,
                        "error_code": "hook_denied",
                        "tool": tool_name,
                        "message": decision.reason or "PreToolUse hook denied the call",
                    },
                    ensure_ascii=False,
                ), decision.elapsed_ms
        if order_tool:
            # Broker errors can mean that the response was lost after acceptance.
            # Latch before dispatch, including concurrent copies in one batch.
            key = self.replay._identical_call_key(tool_name, effective_args)
            if key is None:
                return json.dumps({
                    "status": "error", "skipped": True,
                    "error_code": "order_identity_invalid", "retryable": False,
                    "message": "Cannot safely identify this order request.",
                }), 0
            with self._order_attempt_lock:
                repeated = key in self._order_attempts
                self._order_attempts.add(key)
            if repeated:
                return json.dumps({
                    "status": "error", "skipped": True,
                    "error_code": "order_retry_blocked", "retryable": False,
                    "message": "This order action was already attempted in this turn. "
                               "Check broker state before requesting another action.",
                }), 0

        def post_result(result: str, status: str) -> None:
            hooks.run("PostToolUse", {
                **hook_payload, "result": redact_tool_result(result), "status": status,
            })

        def heartbeat(emit):
            return HeartbeatTimer(tool_name=tool_name, interval=_heartbeat_interval_s(), emit=emit)

        limit = _tool_timeout_seconds()
        return wait_for_tool(
            tool_name, call_id, lambda: self.env.registry.execute(tool_name, effective_args),
            readonly=readonly, detachable=not order_tool,
            timeout=limit if not order_tool and limit > 0 else None,
            cancelled=self.cancelled, progress=self.progress,
            heartbeat=heartbeat, set_emitter=_set_emitter, post_result=post_result if hooks is not None else None,
        )

    def _is_order_tool(self, tool_name: str) -> bool:
        """Return whether a tool name can submit or cancel an order."""
        name = str(tool_name or "").casefold()
        if any(marker in name for marker in ("place_order", "cancel_order", "submit_order", "replace_order")):
            return True
        from src.tools.spawn_agent_tool import is_trading_state_tool

        get_tool = getattr(self.env.registry, "get", None)
        tool = get_tool(tool_name) if callable(get_tool) else None
        return bool(tool and getattr(tool, "name", None) and is_trading_state_tool(tool))
