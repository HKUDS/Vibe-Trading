"""Mandatory policy and hook ordering for a bound tool invocation."""
from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Dict

from src.agent.tuning import _heartbeat_interval_s, _tool_timeout_seconds
from src.kernel.progress import HeartbeatTimer, _set_emitter
from src.kernel.tool_runner import wait_for_tool
from src.product.tool_results import _is_tool_success
from src.product.resources.hooks import HookManager
from src.tools.redaction import redact_payload, redact_tool_result


def _parse_tool_payload(result: str) -> dict | None:
    try:
        value = json.loads(result)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


@dataclass(frozen=True)
class ToolRefusal:
    reason: str
    result: str
    elapsed_ms: int = 0


@dataclass(frozen=True)
class PreparedToolCall:
    arguments: dict[str, Any]
    post_result: Callable[[str, str], None] | None = None


def prepare_tool_call(
    name: str,
    arguments: dict[str, Any],
    *,
    check_policy: Callable[[str, dict], tuple[bool, str, dict]],
    hooks: HookManager | None,
    call_id: str,
    session_id: str,
) -> PreparedToolCall | ToolRefusal:
    """Apply the mandatory policy before allowing a hook to add a refusal."""
    allowed, reason, arguments = check_policy(name, arguments)
    if not allowed:
        return ToolRefusal(reason, json.dumps(
            {"status": "error", "skipped": True, "error": reason}, ensure_ascii=False,
        ))
    if hooks is None:
        return PreparedToolCall(arguments)

    payload = {
        "tool_name": name,
        "call_id": call_id,
        "arguments": redact_payload(arguments),
        "session_id": session_id,
    }
    decision = hooks.run("PreToolUse", payload)
    if decision.denied:
        reason = decision.reason or "PreToolUse hook denied the call"
        return ToolRefusal(reason, json.dumps(
            {"status": "error", "skipped": True, "error_code": "hook_denied", "tool": name, "message": reason},
            ensure_ascii=False,
        ), decision.elapsed_ms)

    def post_result(result: str, status: str) -> None:
        hooks.run("PostToolUse", {
            **payload, "result": redact_tool_result(result), "status": status,
        })

    return PreparedToolCall(arguments, post_result)


class ToolInvocation:
    """Bind mandatory preflight, hook audit and non-detachable order handling."""

    def __init__(self, env, replay, hooks, cancelled, progress):
        self.env = env
        self.replay = replay
        self.hooks = hooks
        self.cancelled = cancelled
        self.progress = progress
        self.stop_on_unknown = None
        self.successful_reads: dict[tuple[str, str], str] | None = None
        self._order_attempts = set()
        self._order_attempt_lock = threading.Lock()

    heartbeat_interval = staticmethod(_heartbeat_interval_s)

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
        if self.stop_on_unknown is not None and self.cancelled():
            return json.dumps({"status": "error", "error_code": "tool_cancelled", "skipped": True}), 0
        readonly = self.replay._is_tool_readonly(tool_name)
        order_tool = self._is_order_tool(tool_name)
        prepared = prepare_tool_call(
            tool_name, args,
            check_policy=self.env.registry.check_policy,
            hooks=self.hooks or getattr(self.env.registry, "hooks", None),
            call_id=call_id, session_id=self.env.session_id,
        )
        if isinstance(prepared, ToolRefusal):
            return prepared.result, prepared.elapsed_ms
        effective_args = prepared.arguments
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

        cache = self.successful_reads
        key = None
        if readonly and cache is not None:
            tool = self.env.registry.get(tool_name)
            bind_workspace = getattr(tool, "workspace_arguments", None)
            normalized, refusal = bind_workspace(effective_args) if bind_workspace else (effective_args, None)
            if refusal is None:
                key = self.replay._identical_call_key(tool_name, normalized)
        if key is not None and key in cache:
            cached = cache[key]
            payload = _parse_tool_payload(cached)
            if payload is not None:
                return json.dumps({**payload, "_vibe_repeat": True}, ensure_ascii=False), 0
            return f"{cached}\n\n[Repeat: prior successful read]", 0

        def heartbeat(emit):
            return HeartbeatTimer(tool_name=tool_name, interval=self.heartbeat_interval(), emit=emit)

        limit = _tool_timeout_seconds()
        def invoke():
            if self.stop_on_unknown is not None and self.cancelled():
                return json.dumps({"status": "error", "error_code": "tool_cancelled", "skipped": True})
            return self.env.registry.execute(tool_name, effective_args)

        result, elapsed_ms = wait_for_tool(
            tool_name, call_id, invoke,
            readonly=readonly, detachable=not order_tool,
            timeout=limit if not order_tool and limit > 0 else None,
            cancelled=self.cancelled, progress=self.progress,
            heartbeat=heartbeat, set_emitter=_set_emitter, post_result=prepared.post_result,
        )

        if self.stop_on_unknown is not None or key is not None:
            payload = _parse_tool_payload(result) or {}
            if payload.get("outcome") == "unknown":
                if self.stop_on_unknown is not None:
                    self.stop_on_unknown()
            elif key is not None and _is_tool_success(result):
                cache[key] = redact_tool_result(result)
        return result, elapsed_ms

    def _is_order_tool(self, tool_name: str) -> bool:
        """Return whether a tool name can submit or cancel an order."""
        from src.tools.spawn_agent_tool import is_order_action_name, is_trading_state_tool

        if is_order_action_name(str(tool_name or "")):
            return True

        get_tool = getattr(self.env.registry, "get", None)
        tool = get_tool(tool_name) if callable(get_tool) else None
        return bool(tool and getattr(tool, "name", None) and is_trading_state_tool(tool))
