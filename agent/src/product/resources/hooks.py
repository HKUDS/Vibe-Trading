"""Command hooks for the agent lifecycle.

Hooks are deliberately a small, fail-closed boundary.  They observe the same
tool call that the loop is about to execute, while authorization and the live
order guards remain owned by the normal registry and identity paths.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import re
import subprocess
import time
from src.tools.redaction import redact_text

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from src.config.accessor import get_env_value
from src.config.paths import get_runtime_root

logger = logging.getLogger(__name__)

HOOK_EVENTS = frozenset({
    "PreToolUse", "PostToolUse", "UserPromptSubmit", "SessionStart",
    "SessionEnd", "Stop", "PreCompact",
})
DEFAULT_HOOK_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class HookDecision:
    """Result of one configured command hook."""

    event: str
    decision: str
    reason: str = ""
    command: str = ""
    elapsed_ms: int = 0
    timed_out: bool = False
    exit_code: int | None = None

    @property
    def denied(self) -> bool:
        """Whether this hook adds a refusal to the normal safety gates."""
        return self.decision == "deny"


def _hook_file(runtime_root: Path) -> Path:
    configured = get_env_value("VIBE_TRADING_HOOKS_FILE", "").strip()
    return Path(configured).expanduser() if configured else runtime_root / "hooks.json"


def _matcher_matches(matcher: Any, payload: Mapping[str, Any]) -> bool:
    if matcher in (None, "", "*"):
        return True
    value = str(payload.get("tool_name") or payload.get("tool") or "")
    pattern = str(matcher)
    if pattern.startswith("re:"):
        try:
            return re.search(pattern[3:], value) is not None
        except re.error:
            return False
    return fnmatch.fnmatchcase(value, pattern)


def _command_specs(raw: Any) -> list[tuple[Any, str]]:
    """Normalize Claude-style and compact hook declarations."""
    if isinstance(raw, str):
        return [(None, raw)]
    if isinstance(raw, Mapping):
        if raw.get("type", "command") != "command":
            return []
        command = raw.get("command")
        return [(raw.get("matcher"), str(command))] if isinstance(command, str) else []
    if not isinstance(raw, list):
        return []
    result: list[tuple[Any, str]] = []
    for item in raw:
        if isinstance(item, Mapping) and "hooks" in item:
            matcher = item.get("matcher")
            for nested in _command_specs(item.get("hooks")):
                result.append((matcher if nested[0] is None else nested[0], nested[1]))
        else:
            result.extend(_command_specs(item))
    return result


class HookManager:
    """Load and run command hooks for one runtime root."""

    def __init__(
        self,
        runtime_root: Path | None = None,
        *,
        config_path: Path | None = None,
        timeout_seconds: float | None = None,
        audit: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.runtime_root = Path(runtime_root or get_runtime_root()).expanduser()
        self.runtime_root = self.runtime_root.resolve()
        configured_path = Path(config_path or _hook_file(self.runtime_root)).expanduser().resolve()
        try:
            configured_path.relative_to(self.runtime_root)
        except ValueError:
            logger.warning("Ignoring hook config outside the runtime root: %s", configured_path)
            configured_path = self.runtime_root / "hooks.json"
        self.config_path = configured_path
        configured_timeout = timeout_seconds
        if configured_timeout is None:
            configured_timeout = get_env_value(
                "VIBE_TRADING_HOOK_TIMEOUT_SECONDS", str(DEFAULT_HOOK_TIMEOUT_SECONDS)
            )
        try:
            self.timeout_seconds = max(0.01, float(configured_timeout))
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid hook timeout %r", configured_timeout)
            self.timeout_seconds = DEFAULT_HOOK_TIMEOUT_SECONDS
        self.audit = audit
        self._hooks: dict[str, list[tuple[Any, str]]] = self._load()

    def _load(self) -> dict[str, list[tuple[Any, str]]]:
        if not self.config_path.exists():
            return {}
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not load hooks from %s: %s", self.config_path, exc)
            return {}
        if isinstance(raw, Mapping) and isinstance(raw.get("hooks"), Mapping):
            raw = raw["hooks"]
        if not isinstance(raw, Mapping):
            logger.warning("Ignoring hooks file with a non-object root: %s", self.config_path)
            return {}
        loaded: dict[str, list[tuple[Any, str]]] = {}
        for event, declarations in raw.items():
            if event in HOOK_EVENTS:
                specs = _command_specs(declarations)
                if specs:
                    loaded[event] = specs
            else:
                logger.warning("Ignoring unknown hook event %r", event)
        return loaded

    def set_audit_sink(self, sink: Any | None) -> None:
        """Attach a thread recorder or callback after a turn is created."""
        if sink is None:
            self.audit = None
        elif callable(sink):
            self.audit = sink
        else:
            self.audit = getattr(sink, "hook", None)

    def run(self, event: str, payload: Mapping[str, Any] | None = None) -> HookDecision:
        """Run matching hooks and return the first refusal.

        A pre-hook timeout, crash, or non-zero exit denies the tool. Other
        lifecycle hooks record the failure and continue because they are
        observational.
        """
        if event not in HOOK_EVENTS:
            raise ValueError(f"unknown hook event {event!r}")
        context = dict(payload or {})
        context.setdefault("event", event)
        first = HookDecision(event=event, decision="allow")
        for matcher, command in self._hooks.get(event, ()):
            if not _matcher_matches(matcher, context):
                continue
            started = time.perf_counter()
            decision = "allow"
            reason = ""
            timed_out = False
            exit_code: int | None = None
            try:
                proc = subprocess.run(
                    command,
                    input=json.dumps(context, ensure_ascii=False, default=str),
                    text=True,
                    capture_output=True,
                    cwd=self.runtime_root,
                    timeout=self.timeout_seconds,
                    shell=True,
                    env=dict(os.environ),
                )
                exit_code = proc.returncode
                output = (proc.stdout or "").strip()
                if output:
                    try:
                        result = json.loads(output)
                    except json.JSONDecodeError:
                        result = {"decision": output} if output.casefold() in {"deny", "block"} else {}
                    if isinstance(result, Mapping):
                        decision = str(result.get("decision") or result.get("action") or "allow").casefold()
                        reason = str(result.get("reason") or result.get("message") or "")
                if proc.returncode != 0:
                    decision = "deny" if event == "PreToolUse" else "error"
                    reason = reason or f"hook exited with status {proc.returncode}"
                if decision in {"block", "reject", "refuse"}:
                    decision = "deny"
                elif decision not in {"deny", "error"}:
                    decision = "allow"
            except subprocess.TimeoutExpired:
                timed_out = True
                decision = "deny" if event == "PreToolUse" else "error"
                reason = f"hook timed out after {self.timeout_seconds:g}s"
            except Exception as exc:  # pragma: no cover - defensive subprocess boundary
                decision = "deny" if event == "PreToolUse" else "error"
                reason = f"hook failed: {type(exc).__name__}: {exc}"
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            current = HookDecision(
                event=event,
                decision=decision,
                reason=redact_text(reason),
                command=command,
                elapsed_ms=elapsed_ms,
                timed_out=timed_out,
                exit_code=exit_code,
            )
            self._audit(current, context)
            if current.denied:
                return current
            if first.decision == "allow" and current.decision == "error":
                first = current
        return first

    def _audit(self, decision: HookDecision, payload: Mapping[str, Any]) -> None:
        if self.audit is None:
            return
        audit = {
            "event": decision.event,
            "decision": decision.decision,
            "reason": decision.reason,
            "elapsed_ms": decision.elapsed_ms,
            "timed_out": decision.timed_out,
            "exit_code": decision.exit_code,
        }
        if payload.get("tool_name") or payload.get("tool"):
            audit["tool"] = payload.get("tool_name") or payload.get("tool")
        try:
            self.audit(audit)
        except Exception:
            logger.warning("Could not record hook decision", exc_info=True)


def load_hooks(*, audit: Callable[[dict[str, Any]], None] | None = None) -> HookManager:
    """Construct the manager bound to the active runtime root."""
    return HookManager(audit=audit)


__all__ = ["HOOK_EVENTS", "HookDecision", "HookManager", "load_hooks"]
