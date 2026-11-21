"""spawn_agent: delegate one self-contained task to a child agent.

The child is a fresh ``AgentLoop`` with its own messages, instrument-identity
ledger, no-progress budget and cancel flag. It shares the parent's LLM
configuration and follows the parent's cancel signal. It works in its own
directory inside the parent's run directory, and that is the only place it can
write or point a ``run_dir`` at, so the parent can read every file it wrote.

What the child's registry leaves out is a fixed rule over the parent's tools
(:func:`child_exclusion`), not a counter:

* ``spawn_agent`` and ``run_swarm``, and the shell (``bash`` and the background
  task tools), which could start another agent. Depth is therefore 1 as far as
  the registry goes; a non-shell tool that starts an agent would have to be
  added to that rule.
* Every tool that places, modifies or cancels an order or changes trading
  state, so a trade cannot be delegated around the parent's conversation with
  the user.
* Every tool bound to the parent's session (research goal, autopilot,
  scheduled research) and every tool that writes what later prompts are built
  from (persistent memory, skills).
* An MCP tool its server does not declare read-only, because nothing else says
  what it does.

Research stores the parent may also write (hypotheses, strategies, research
artifacts) stay available. Cancellation is cooperative: a tool call the child
is running finishes before the child stops.

The child's provider usage is charged to the session's current research goal
as it happens, and the child is stopped once the goal's token budget is
reached. Its usage events are forwarded to the parent's event stream marked
``purpose: "subagent"`` and without a parent call index (the parent loop owns
that sequence): a consumer that keys usage by the parent's call index, such as
the live decision budget, refuses them instead of mistaking them for a call it
already counted. The parent run's ``llm_usage.json`` is not updated; the
child's own sits in its run directory and the totals are in the tool result.
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
#: Modules whose non-readonly tools change broker or live-trading state.
_TRADING_MODULES = ("src.tools.trading_connector_tool", "src.trading", "src.live")


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

    A tool that is not read-only and is either a live-broker order tool
    wrapped by the mandate gate, defined in a trading or live module, named
    with a broker prefix, or an MCP tool classified as write/unknown. Read-only
    broker tools (positions, quotes, order history) are not trading state
    changes.

    Args:
        tool: A registered tool.

    Returns:
        True when a child agent must not receive the tool.
    """
    # Child registries wrap tools to confine their workspace. Inspect the
    # source tool so the same rule remains valid after wrapping.
    candidate = getattr(tool, "_tool", tool)
    if getattr(candidate, "is_readonly", False) is True:
        return False
    from src.live.order_guard import LiveOrderGuardTool

    if isinstance(candidate, LiveOrderGuardTool):
        return True
    if type(candidate).__module__.startswith(_TRADING_MODULES):
        return True
    try:
        from src.tools.mcp import MCPRemoteTool
        from src.live.classification import ToolClass, classify_tool

        if isinstance(candidate, MCPRemoteTool):
            spec = getattr(candidate, "_spec", None)
            if spec is None:
                return True
            return classify_tool(spec.remote_name, spec.annotations) is not ToolClass.READ
    except ImportError:
        pass
    return str(candidate.name).startswith(_broker_tool_prefixes())


def _parent_bound_classes() -> tuple[type[BaseTool], ...]:
    """Tool classes that act for the parent beyond the child's task.

    Returns:
        The nesting tools, the shell and background tools, the session-bound
        tools and the tools that write persistent memory or skills.
    """
    from src.tools import session_bound_tool_classes
    from src.tools.background_tools import BackgroundRunTool, CancelBackgroundTool, CheckBackgroundTool
    from src.tools.bash_tool import BashTool
    from src.tools.remember_tool import RememberTool
    from src.tools.skill_writer_tool import DeleteSkillTool, PatchSkillTool, SaveSkillTool, SkillFileTool
    from src.tools.swarm_tool import SwarmTool

    return (
        SpawnAgentTool,
        SwarmTool,
        BashTool,
        BackgroundRunTool,
        CheckBackgroundTool,
        CancelBackgroundTool,
        RememberTool,
        SaveSkillTool,
        PatchSkillTool,
        DeleteSkillTool,
        SkillFileTool,
        *session_bound_tool_classes(),
    )


def _is_undeclared_remote_tool(tool: BaseTool) -> bool:
    """Whether an MCP tool is anything but declared read-only by its server."""
    try:
        from src.tools.mcp import MCPRemoteTool
    except ImportError:
        return False
    if not isinstance(tool, MCPRemoteTool):
        return False
    from src.live.classification import ToolClass, classify_tool

    spec = getattr(tool, "_spec", None)
    if spec is None:
        return True
    return classify_tool(spec.remote_name, spec.annotations) is not ToolClass.READ


def child_exclusion(tool: BaseTool) -> str | None:
    """Why a child agent must not receive a tool, if it must not.

    Args:
        tool: A tool of the parent's registry.

    Returns:
        ``"parent_bound"``, ``"trading_state"`` or ``"undeclared_remote"``,
        or ``None`` when the child may use the tool.
    """
    if isinstance(tool, _parent_bound_classes()):
        return "parent_bound"
    if _is_undeclared_remote_tool(tool):
        return "undeclared_remote"
    if is_trading_state_tool(tool):
        return "trading_state"
    return None


def _confine_run_dir(arguments: dict[str, Any], workspace: Path) -> tuple[dict[str, Any], str | None]:
    """Keep a call's ``run_dir`` inside the child's workspace.

    Mirrors the swarm worker's rule: an empty value is the workspace, a
    relative one resolves under it, and anything resolving outside it is
    refused rather than silently replaced.

    Args:
        arguments: The call's arguments; the loop has already injected or
            resolved ``run_dir``.
        workspace: The child's run directory, resolved.

    Returns:
        The arguments to run with, and a refusal message or ``None``.
    """
    args = dict(arguments)
    value = str(args.get("run_dir") or "").strip()
    if not value:
        args["run_dir"] = str(workspace)
        return args, None
    supplied = Path(value).expanduser()
    resolved = (supplied if supplied.is_absolute() else workspace / supplied).resolve()
    if not resolved.is_relative_to(workspace):
        return args, (
            f"run_dir {value!r} is outside this sub-agent's workspace. A run_dir must be "
            f"inside {workspace}; pass a relative path to a directory you created there."
        )
    args["run_dir"] = str(resolved)
    return args, None


class _WorkspaceTool(BaseTool):
    """A parent tool as a child sees it: run_dir and writes stay in the workspace.

    The class name stays empty so discovery never registers the wrapper.
    """

    def __init__(self, tool: BaseTool, workspace: Path) -> None:
        """Wrap one of the parent's tools.

        Args:
            tool: The parent's tool instance; its bindings stay the parent's.
            workspace: The child's run directory, resolved.
        """
        self._tool = tool
        self._workspace = workspace
        self.name = tool.name
        self.description = tool.description
        self.parameters = tool.parameters
        self.repeatable = tool.repeatable
        self.is_readonly = tool.is_readonly
        self.deterministic = tool.deterministic
        self.replay_after_compaction = tool.replay_after_compaction

    def __getattr__(self, item: str) -> Any:
        if item in {"_tool", "_workspace"}:
            raise AttributeError(item)
        return getattr(self._tool, item)

    def to_openai_schema(self) -> dict[str, Any]:
        """Return the wrapped tool's own schema."""
        return self._tool.to_openai_schema()

    def execute(self, **kwargs: Any) -> str:
        """Run the wrapped tool with run_dir and write roots held to the workspace."""
        from src.tools.path_utils import confined_write_roots

        args, refusal = _confine_run_dir(kwargs, self._workspace)
        if refusal is not None:
            return _error("outside_subagent_workspace", refusal)
        with confined_write_roots(self._workspace):
            return self._tool.execute(**args)


def child_registry(parent: ToolRegistry, workspace: Path) -> ToolRegistry:
    """Project the parent's registry onto the tools a child may use.

    Args:
        parent: The registry the parent agent was built with.
        workspace: The child's run directory. Every tool the child receives
            is held to it: a ``run_dir`` outside it is refused and file
            writes and edits may not leave it.

    Returns:
        The parent's tools minus every tool :func:`child_exclusion` names.
        The instances are shared, so their policies, roots and bindings stay
        the parent's apart from that confinement.
    """
    root = Path(workspace).resolve()
    child = ToolRegistry()
    child.hooks = getattr(parent, "hooks", None)
    child.sandbox = getattr(parent, "sandbox", None)
    for name in parent.tool_names:
        tool = parent.get(name)
        if tool is None or child_exclusion(tool) is not None:
            continue
        child.register(_WorkspaceTool(tool, root))
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


class _GoalMeter:
    """Charges the child's provider usage to the session's current research goal."""

    def __init__(self, session_id: str, emit: Callable[[str, dict], None] | None) -> None:
        """Find the session's current goal.

        Args:
            session_id: The parent's session.
            emit: The parent's event callback, for ``goal.updated``.
        """
        from src.goal import GoalStore

        self._session_id = session_id
        self._emit = emit
        self._store = GoalStore()
        goal = self._store.get_current_goal(session_id)
        self.goal_id = goal.goal_id if goal is not None else None
        self.exhausted = goal is not None and self._over_budget(goal)

    @staticmethod
    def _over_budget(goal: Any) -> bool:
        return goal.token_budget is not None and goal.tokens_used >= goal.token_budget

    def charge(self, tokens: int) -> bool:
        """Add tokens to the goal, the way the parent loop accounts its own calls.

        Args:
            tokens: Provider-reported total tokens of one child call.

        Returns:
            True when the goal's token budget is now reached.
        """
        if self.goal_id is None or tokens <= 0:
            return self.exhausted
        try:
            goal = self._store.account_usage(
                session_id=self._session_id,
                goal_id=self.goal_id,
                expected_goal_id=self.goal_id,
                token_delta=tokens,
            )
            self.exhausted = self._over_budget(goal)
            snapshot = self._store.get_goal_snapshot(self.goal_id)
            if snapshot is not None and self._emit is not None:
                self._emit("goal.updated", {"goal": snapshot["goal"], "snapshot": snapshot})
        except Exception as exc:  # noqa: BLE001 - the parent loop skips the same way
            logger.debug("spawn_agent goal usage accounting skipped: %s", exc)
        return self.exhausted


class SpawnAgentTool(BaseTool):
    """Run one child agent on a self-contained task and return its final answer."""

    name = "spawn_agent"
    description = (
        "Delegate one self-contained sub-task to a child agent and wait for its final answer. "
        "The child starts with an empty conversation: it is given ONLY the task text, not this "
        "conversation or your resolved symbols, so write every instruction, instrument name, "
        "date range and expected output into the task. It resolves instruments itself. It has "
        "your tools except spawn_agent, run_swarm, the shell and background tools, every tool "
        "that places, modifies or cancels orders or changes trading state (so never delegate a "
        "trade), the research-goal, autopilot, scheduled-research, memory and skill-writing "
        "tools, and MCP tools not declared read-only. It can write files and set run_dir only "
        "inside relative_run_dir in your run directory; read its files there with read_file. "
        "A stop or timeout takes effect once the tool call it is running returns. Its tokens "
        "count toward the research goal's budget. Returns status, the child's final text, "
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
        session_id: str | None = None,
        event_callback: Callable[[str, dict], None] | None = None,
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
            session_id: The parent's session, whose current research goal is
                charged for the child's provider usage. Never handed to the
                child.
            event_callback: The parent's event sink: the child's usage events
                and goal updates are forwarded there.
        """
        self._registry = registry
        self._cancel_event = cancel_event
        self._llm_factory = llm_factory
        self._session_id = session_id or None
        self._event_callback = event_callback
        self._usage_callback: Callable[[str, dict[str, Any]], bool] | None = None

    def set_usage_callback(self, callback: Callable[[str, dict[str, Any]], bool] | None) -> None:
        """Set the parent loop's usage sink for child provider calls.

        The parent installs this after constructing its registry. Direct uses
        of the tool keep the local goal-meter fallback when no sink is set.

        Args:
            callback: Receives ``llm_usage`` or ``llm_usage_unavailable`` and
                returns whether the parent budget has been exhausted.
        """
        self._usage_callback = callback

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
            ``subagent_cancelled`` / ``goal_token_budget_exhausted`` /
            ``subagent_start_failed`` / ``invalid_arguments`` /
            ``outside_run_roots``) and ``error``.
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

        meter = (
            _GoalMeter(self._session_id, self._event_callback)
            if self._session_id and self._usage_callback is None
            else None
        )
        if meter is not None and meter.exhausted:
            return _error(
                "goal_token_budget_exhausted",
                "the research goal's token budget has been reached; a child agent would spend past it",
            )

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
        stop_reason: dict[str, str] = {}
        holder: dict[str, Any] = {}

        def progress(stage: str, message: str) -> None:
            if parent_emit is None:
                return
            try:
                parent_emit(ProgressEvent(stage=stage, message=message))
            except Exception:  # noqa: BLE001 - progress must never break the child
                logger.debug("spawn_agent progress forwarding failed", exc_info=True)

        def emit_parent(event_type: str, data: dict[str, Any]) -> None:
            if self._event_callback is None:
                return
            try:
                self._event_callback(event_type, data)
            except Exception:  # noqa: BLE001 - a sink failure must never break the child
                logger.debug("spawn_agent event forwarding failed", exc_info=True)

        def forward(event_type: str, data: dict[str, Any]) -> None:
            # Tool name, status and usage only: child text never reaches the parent's stream.
            if event_type == "tool_call":
                progress("subagent_tool", f"{data.get('tool')}: running")
            elif event_type == "tool_result":
                progress("subagent_tool", f"{data.get('tool')}: {data.get('status')}")
            elif event_type in ("llm_usage", "llm_usage_unavailable"):
                usage = {k: v for k, v in data.items() if k not in ("iter", "call_index")}
                if self._usage_callback is not None:
                    try:
                        exhausted = self._usage_callback(event_type, usage)
                    except Exception:  # noqa: BLE001 - a sink must not break the child
                        logger.debug("spawn_agent usage callback failed", exc_info=True)
                        exhausted = False
                else:
                    emit_parent(event_type, {**usage, "purpose": "subagent", "subagent": child_dir.name})
                    exhausted = (
                        event_type == "llm_usage"
                        and meter is not None
                        and meter.charge(int(data.get("total_tokens") or 0))
                    )
                if exhausted and "reason" not in stop_reason:
                    stop_reason["reason"] = "goal_budget"
                    child = holder.get("child")
                    if child is not None:
                        child.cancel()

        tuning = get_env_config().agent_tuning
        max_iterations = tuning.subagent_max_iter
        timeout = tuning.subagent_timeout
        try:
            child = self._build_child(child_dir, forward, max_iterations)
        except Exception as exc:  # noqa: BLE001 - a child that cannot start is a tool error
            logger.warning("spawn_agent could not start a child: %s", exc, exc_info=True)
            return _error("subagent_start_failed", f"{type(exc).__name__}: {exc}", run_dir=str(child_dir))
        holder["child"] = child

        progress("subagent_started", label or "sub-task")
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
        # The child gets no background tools; its loop still needs a handle to
        # drain, and a private, empty one means ending or cancelling the child
        # cancels nothing of the parent's and drains none of its notifications.
        parent_background = getattr(self._registry, "background", None)
        scope = BackgroundScope(owner_id=f"subagent:{child_dir.name}")
        background = (
            parent_background.for_scope(scope)
            if parent_background is not None
            else get_background_manager()
        )
        return AgentLoop(
            registry=child_registry(self._registry, child_dir),
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
                    stop_reason.setdefault("reason", "cancelled")
                    child.cancel()
                    return
            elif finished.wait(_CANCEL_POLL_SECONDS):
                return
            if deadline is not None and time.monotonic() >= deadline and not finished.is_set():
                stop_reason.setdefault("reason", "timeout")
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
            payload["error"] = (
                f"child agent passed SUBAGENT_TIMEOUT ({timeout:g}s) and was stopped "
                "once its running tool call returned"
            )
        elif stopped == "goal_budget":
            payload["error_code"] = "goal_token_budget_exhausted"
            payload["error"] = "the research goal's token budget was reached; the child stopped"
        elif stopped == "cancelled" or child_status == "cancelled":
            payload["error_code"] = "subagent_cancelled"
            payload["error"] = "the parent turn was cancelled; the child stopped"
        else:
            payload["error_code"] = "subagent_failed"
            payload["error"] = str(reason or "child agent failed")
        return payload
