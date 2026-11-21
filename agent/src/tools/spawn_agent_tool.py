"""spawn_agent: delegate one self-contained task to a child agent.

The child is a fresh ``AgentLoop`` with its own messages, instrument-identity
ledger and no-progress budget. It shares the parent's LLM configuration, its
cancel signal and its run workspace: the child works in a directory inside the
parent's run directory, so the parent can read every file it wrote.

Depth is 1 by construction, not by a counter: the child's registry never holds
``spawn_agent`` or ``run_swarm``. Nor does it hold a tool that places, modifies
or cancels an order or changes trading state, so a trade cannot be delegated
around the parent's own conversation with the user.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

from src.agent.tools import BaseTool, ToolRegistry

logger = logging.getLogger(__name__)

#: How often the cancel watcher looks at the parent's signal and the deadline.
_CANCEL_POLL_SECONDS = 0.2
#: Child run directories live under this folder of the parent's run directory.
SUBAGENT_DIRNAME = "subagents"


def _broker_tool_prefixes() -> tuple[str, ...]:
    """Tool-name prefixes of the broker surface, as the tool policy ships them.

    The shipped default of the provider tool policy's broker deny list, not
    the operator's value: that setting is a convenience filter an operator may
    empty, and emptying it must not hand order tools to a child.

    Returns:
        The prefixes, e.g. ``("trading_", "etoro_")``.
    """
    from src.config.env_schema import LLMConfig

    raw = LLMConfig.model_fields["claude_cli_deny_tool_prefixes"].default
    return tuple(p.strip() for p in raw.split(",") if p.strip())


def is_trading_state_tool(tool: BaseTool) -> bool:
    """Whether a tool places, modifies or cancels orders or changes trading state.

    A broker-surface tool that is not read-only, or a live-broker order tool
    wrapped by the mandate gate. Read-only broker tools (positions, quotes,
    order history) are not trading state changes.

    Args:
        tool: A registered tool.

    Returns:
        True when a child agent must not receive the tool.
    """
    if getattr(tool, "is_readonly", False) is True:
        return False
    from src.live.order_guard import LiveOrderGuardTool

    if isinstance(tool, LiveOrderGuardTool):
        return True
    return str(tool.name).startswith(_broker_tool_prefixes())


def child_registry(parent: ToolRegistry) -> ToolRegistry:
    """Project the parent's registry onto the tools a child may use.

    Args:
        parent: The registry the parent agent was built with.

    Returns:
        The parent's tools minus ``spawn_agent``, ``run_swarm`` and every
        trading-state tool. The instances are shared, so their policies,
        roots and bindings stay exactly the parent's.
    """
    from src.tools.swarm_tool import SwarmTool

    no_nesting = {SpawnAgentTool.name, SwarmTool.name}
    child = ToolRegistry()
    for name in parent.tool_names:
        tool = parent.get(name)
        if tool is None or name in no_nesting or is_trading_state_tool(tool):
            continue
        child.register(tool)
    for module_name, reason in parent.import_failures.items():
        child.record_import_failure(module_name, reason)
    for tool_name, reason in parent.registration_failures.items():
        child.record_registration_failure(tool_name, reason)
    return child


def _error(error_code: str, error: str, **extra: Any) -> str:
    """Serialize a tool error envelope."""
    return json.dumps({"status": "error", "error_code": error_code, "error": error, **extra}, ensure_ascii=False)


def _child_usage(run_dir: Path) -> dict[str, Any]:
    """Read the child's provider-reported token totals from its run artifact.

    Shaped like ``run_swarm``'s ``token_usage``: those field names are the ones
    tool-result redaction releases, where ``total_tokens`` would be blanked.

    Args:
        run_dir: The child's run directory.

    Returns:
        Input/output totals, the call counts, and ``token_source`` —
        ``"provider"`` when the provider reported usage, else ``None``.
    """
    from src.agent.llm_usage import LLM_USAGE_ARTIFACT

    try:
        summary = json.loads((run_dir / LLM_USAGE_ARTIFACT).read_text(encoding="utf-8"))
        totals = dict(summary["totals"])
    except (OSError, ValueError, KeyError, TypeError):
        totals = {}
    calls = int(totals.get("calls") or 0)
    return {
        "total_input_tokens": int(totals.get("input_tokens") or 0),
        "total_output_tokens": int(totals.get("output_tokens") or 0),
        "calls": calls,
        "unreported_calls": int(totals.get("unreported_calls") or 0),
        "token_source": "provider" if calls else None,
    }


class SpawnAgentTool(BaseTool):
    """Run one child agent on a self-contained task and return its final answer."""

    name = "spawn_agent"
    description = (
        "Delegate one self-contained sub-task to a child agent and wait for its final answer. "
        "The child starts with an empty conversation: it sees ONLY the task text, not this "
        "conversation, your files or your resolved symbols, so write every instruction, "
        "instrument name, date range and expected output into the task. It resolves "
        "instruments itself. It has your tools except spawn_agent, run_swarm and every "
        "tool that places, modifies or cancels orders or changes trading state, so never "
        "delegate a trade. Files it writes stay in relative_run_dir inside your run "
        "directory, readable with read_file. Returns status, the child's final text, "
        "iterations and token usage."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The complete, self-contained instruction for the child agent.",
            },
            "label": {
                "type": "string",
                "description": "Optional short name for this sub-task, shown in progress.",
            },
        },
        "required": ["task"],
    }
    # The child writes files and runs backtests: batching it in parallel with
    # readonly reads would race them, and a readonly call can be abandoned by
    # the hard tool timeout while its thread keeps writing. A write runs on the
    # loop thread, so the child's context bindings and SUBAGENT_TIMEOUT apply.
    is_readonly = False

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        cancel_event: threading.Event | None = None,
        llm_factory: Callable[[], Any] | None = None,
    ) -> None:
        """Bind the tool to the registry it was built into.

        Args:
            registry: The parent's registry, read when the tool runs so tools
                registered after this one (MCP wrappers) are seen.
            cancel_event: The parent turn's cancel signal; setting it stops
                the child at its next cooperative checkpoint.
            llm_factory: Builds the child's LLM client. Defaults to
                ``ChatLLM()``, which reads the same configuration the parent's
                client was built from.
        """
        self._registry = registry
        self._cancel_event = cancel_event
        self._llm_factory = llm_factory

    def execute(self, **kwargs: Any) -> str:
        """Run the child to completion.

        Args:
            **kwargs: ``task`` (required) and ``label``. ``run_dir`` is the
                parent's run directory, injected by the agent loop.

        Returns:
            JSON with ``status`` (``ok`` or ``error``), ``child_status``,
            ``content`` (the child's final text), ``iterations``,
            ``max_iterations``, ``token_usage``, ``run_dir`` and, inside an
            agent run, ``relative_run_dir``. An error also carries
            ``error_code`` (``subagent_failed`` / ``subagent_timeout`` /
            ``subagent_cancelled`` / ``subagent_start_failed`` /
            ``invalid_arguments`` / ``outside_run_roots``) and ``error``.
        """
        task = kwargs.get("task")
        if not isinstance(task, str) or not task.strip():
            return _error("invalid_arguments", "task must be a non-empty string")
        label = str(kwargs.get("label") or "").strip()

        from src.agent.progress import ProgressEvent, _get_emitter
        from src.config.accessor import get_env_config
        from src.config.paths import get_runs_dir
        from src.core.state import RunStateStore
        from src.tools.path_utils import safe_run_dir

        parent_dir = kwargs.get("run_dir")
        try:
            # Outside an agent loop there is no parent run: the child is an
            # ordinary run of its own.
            base = safe_run_dir(str(parent_dir)) / SUBAGENT_DIRNAME if parent_dir else get_runs_dir()
        except ValueError as exc:
            return _error("outside_run_roots", str(exc))
        child_dir = RunStateStore().create_run_dir(base)

        # Captured now: the child's own write tools reset this thread's emitter.
        parent_emit = _get_emitter()

        def progress(stage: str, message: str) -> None:
            if parent_emit is None:
                return
            try:
                parent_emit(ProgressEvent(stage=stage, message=message))
            except Exception:  # noqa: BLE001 - progress must never break the child
                logger.debug("spawn_agent progress forwarding failed", exc_info=True)

        def forward(event_type: str, data: dict[str, Any]) -> None:
            # Tool name and status only: child text never reaches the parent's stream.
            if event_type == "tool_call":
                progress("subagent_tool", f"{data.get('tool')}: running")
            elif event_type == "tool_result":
                progress("subagent_tool", f"{data.get('tool')}: {data.get('status')}")

        tuning = get_env_config().agent_tuning
        max_iterations = tuning.subagent_max_iter
        timeout = tuning.subagent_timeout
        try:
            child = self._build_child(child_dir, forward, max_iterations)
        except Exception as exc:  # noqa: BLE001 - a child that cannot start is a tool error
            logger.warning("spawn_agent could not start a child: %s", exc, exc_info=True)
            return _error("subagent_start_failed", f"{type(exc).__name__}: {exc}", run_dir=str(child_dir))

        progress("subagent_started", label or "sub-task")
        stop_reason: dict[str, str] = {}
        finished = threading.Event()
        watcher = threading.Thread(
            target=self._watch, args=(child, finished, timeout, stop_reason),
            name="spawn-agent-cancel", daemon=True,
        )
        watcher.start()
        try:
            from src.agent.instrument_identity import agent_authored_request

            with agent_authored_request():
                result = child.run(task)
        except Exception as exc:  # noqa: BLE001 - never kill the parent turn
            logger.warning("spawn_agent child raised: %s", exc, exc_info=True)
            result = {"status": "failed", "reason": f"{type(exc).__name__}: {exc}", "content": ""}
        finally:
            finished.set()
            watcher.join(timeout=_CANCEL_POLL_SECONDS * 5)
            close = getattr(child.llm, "close", None)
            if callable(close):
                close()

        payload = self._payload(result, child_dir, label, max_iterations, stop_reason, timeout)
        if parent_dir:
            # read_file paths are relative to the parent's run directory.
            payload["relative_run_dir"] = f"{SUBAGENT_DIRNAME}/{child_dir.name}"
        progress("subagent_finished", f"{label or 'sub-task'}: {payload['status']}")
        return json.dumps(payload, ensure_ascii=False)

    def _build_child(self, child_dir: Path, forward: Callable, max_iterations: int) -> Any:
        """Build a fresh AgentLoop over the child registry and the child directory."""
        from src.agent.loop import AgentLoop
        from src.agent.memory import WorkspaceMemory
        from src.tools.background_tools import BackgroundScope, get_background_manager

        if self._llm_factory is not None:
            llm = self._llm_factory()
        else:
            from src.providers.chat import ChatLLM

            llm = ChatLLM()
        # The child's tools stay bound to the parent's background owner, so a
        # task it starts reports to the parent. Its loop holds a private,
        # empty handle: ending or cancelling the child cancels nothing of the
        # parent's and drains none of the parent's notifications.
        parent_background = getattr(self._registry, "background", None)
        scope = BackgroundScope(owner_id=f"subagent:{child_dir.name}")
        background = (
            parent_background.for_scope(scope)
            if parent_background is not None
            else get_background_manager()
        )
        return AgentLoop(
            registry=child_registry(self._registry),
            llm=llm,
            memory=WorkspaceMemory(run_dir=str(child_dir)),
            event_callback=forward,
            max_iterations=max_iterations,
            # Its own flag: the child's stall watchdog sets it, and that must
            # not cancel the parent's turn. The parent's flag is forwarded.
            cancel_event=threading.Event(),
            background_manager=background,
        )

    def _watch(self, child: Any, finished: threading.Event, timeout: float, stop_reason: dict[str, str]) -> None:
        """Cancel the child when the parent is cancelled or its time runs out."""
        deadline = time.monotonic() + timeout if timeout > 0 else None
        while not finished.is_set():
            if self._cancel_event is not None:
                if self._cancel_event.wait(_CANCEL_POLL_SECONDS):
                    stop_reason["reason"] = "cancelled"
                    child.cancel()
                    return
            elif finished.wait(_CANCEL_POLL_SECONDS):
                return
            if deadline is not None and time.monotonic() >= deadline and not finished.is_set():
                stop_reason["reason"] = "timeout"
                child.cancel()
                return

    @staticmethod
    def _payload(
        result: dict[str, Any],
        child_dir: Path,
        label: str,
        max_iterations: int,
        stop_reason: dict[str, str],
        timeout: float,
    ) -> dict[str, Any]:
        """Turn the child's run result into the tool result."""
        child_status = str(result.get("status") or "failed")
        payload: dict[str, Any] = {
            "status": "ok" if child_status == "success" else "error",
            "child_status": child_status,
            "content": str(result.get("content") or ""),
            "iterations": result.get("iterations"),
            "max_iterations": max_iterations,
            "token_usage": _child_usage(child_dir),
            "run_dir": str(child_dir),
        }
        if label:
            payload["label"] = label
        if result.get("degraded"):
            payload["degraded"] = True
        reason = result.get("reason")
        if payload["status"] == "ok":
            if reason:
                payload["reason"] = reason
            return payload
        stopped = stop_reason.get("reason")
        if stopped == "timeout":
            payload["error_code"] = "subagent_timeout"
            payload["error"] = f"child agent exceeded SUBAGENT_TIMEOUT ({timeout:g}s) and was cancelled"
        elif stopped == "cancelled" or child_status == "cancelled":
            payload["error_code"] = "subagent_cancelled"
            payload["error"] = "the parent turn was cancelled; the child stopped"
        else:
            payload["error_code"] = "subagent_failed"
            payload["error"] = str(reason or "child agent failed")
        return payload
