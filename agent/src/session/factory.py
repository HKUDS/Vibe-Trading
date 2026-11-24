"""Build and run an agent with the resources bound to one session attempt."""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy

import asyncio
import concurrent.futures
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from src.session.checkpoint import ResponseCheckpoint
from src.session.event_projection import ThreadEvents
from src.session.events import EventBus
from src.session.models import Attempt
from src.session.pending_inputs import PendingInputQueue, QueuedInputDelivery
from src.session.runtime import SessionRuntime
from src.session.store import SessionStore


# Dedicated thread pool limited to four concurrent agents to avoid exhausting the default executor.
_AGENT_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent")
logger = logging.getLogger(__name__)


@dataclass
class SessionAgentFactory:
    """Bind per-attempt agents to this service's recorder, event sinks and cancellation handles."""

    store: SessionStore
    event_bus: EventBus
    thread_events: ThreadEvents
    runs_dir: Path
    runtime: Callable[[str], SessionRuntime]
    pending_inputs: PendingInputQueue
    active_loops: dict
    background_handles: dict
    policy: ToolPolicy
    host_tools: dict[str, Any] = field(default_factory=dict)

    def register_tool(self, tool: Any) -> str:
        """Register one explicit host tool for subsequent attempts."""
        from src.agent.tools import host_tool_name
        from src.tools import _discover_subclasses

        names = {cls.name for cls in _discover_subclasses()} | self.host_tools.keys()
        name = host_tool_name(tool, names)
        self.host_tools[name] = tool
        return name

    def _publish_background_completion(self, owner_id: str, payload: dict) -> None:
        """Route a background task's terminal state to its owning session."""
        if not owner_id.startswith("session:"):
            return
        session_id = owner_id[len("session:"):]
        self.event_bus.emit(session_id, "background.completed", payload)

    async def run(
        self,
        attempt: Attempt,
        *,
        messages: list | None = None,
        include_shell_tools: bool = False,
        session_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute an attempt with its session-bound agent."""
        from src.tools import build_registry
        from src.tools.background_tools import BackgroundScope, get_background_manager
        from src.session.model_selection import chat_llm_for_session
        from src.agent.runtime import AgentRuntime
        from src.product.resources.memory import WorkspaceMemory
        from src.memory.persistent import PersistentMemory
        from src.config.loader import load_runtime_agent_config, sanitize_session_overrides

        llm = chat_llm_for_session(session_config, policy=self.policy)
        try:
            pm = PersistentMemory()

            session_id = attempt.session_id
            attempt_id = attempt.attempt_id
            loop = asyncio.get_running_loop()
            runtime = self.runtime(session_id)
            checkpoint = ResponseCheckpoint(self.store, attempt, runtime=runtime)

            safe_overrides = sanitize_session_overrides(session_config) if session_config else session_config
            agent_config = load_runtime_agent_config(overrides=safe_overrides)

            def event_callback(event_type: str, data: Dict[str, Any]) -> None:
                """Forward AgentRuntime events to the SSE event bus."""
                try:
                    checkpoint.handle_event(event_type, data)
                except OSError as exc:
                    # A checkpoint failure must not hide the live response or stop
                    # the agent. The terminal attempt write still gets a chance.
                    logger.warning(
                        "Could not checkpoint response for attempt %s: %s",
                        attempt_id,
                        exc,
                    )
                data["attempt_id"] = attempt_id
                self.thread_events.emit(session_id, event_type, data)

            def _mcp_collision_warn(msg: str) -> None:
                """Forward MCP server-name collision warnings to the operator event channel."""
                self.event_bus.emit(session_id, "mcp.warning", {"attempt_id": attempt_id, "message": msg})

            # Share cancellation with long-running tools.
            turn_cancel = threading.Event()

            # Keep background results accessible across a session's turns.
            background_scope = BackgroundScope(
                owner_id=f"session:{session_id}", attempt_id=attempt_id
            )
            background = get_background_manager(Path(self.runs_dir).parent).for_scope(
                background_scope,
                on_completion=self._publish_background_completion,
            )
            self.background_handles[session_id] = background

            registry = await loop.run_in_executor(
                _AGENT_EXECUTOR,
                lambda: build_registry(
                    policy=self.policy,
                    persistent_memory=pm,
                    include_shell_tools=include_shell_tools,
                    agent_config=agent_config,
                    session_id=session_id,
                    event_callback=event_callback,
                    warn_callback=_mcp_collision_warn,
                    cancel_event=turn_cancel,
                    background_manager=background,
                    background_scope=background_scope,
                    host_tools=list(self.host_tools.values()),
                ),
            )

            hook_manager = getattr(registry, "hooks", None)

            from src.config.accessor import get_env_config

            runtime_snapshot = getattr(llm, "runtime_snapshot", None)
            recorder = runtime.begin_turn(
                attempt_id,
                queued_input_id=attempt.queued_input_id,
                provider=getattr(runtime_snapshot, "provider", None),
                model=getattr(runtime_snapshot, "configured_model", None),
            )
            if hook_manager is not None:
                hook_manager.set_audit_sink(recorder)
            queued_inputs = QueuedInputDelivery(
                self.pending_inputs,
                session_id=session_id,
                turn_id=attempt_id,
                recorder=recorder,
                shell_tools=include_shell_tools,
                on_delivered=lambda pending, item: self.thread_events.sync(session_id),
            )
            agent = AgentRuntime(
                registry=registry,
                llm=llm,
                event_callback=event_callback,
                max_iterations=get_env_config().agent_tuning.vibe_trading_agent_max_iterations,
                persistent_memory=pm,
                cancel_event=turn_cancel,
                background_manager=background,
                thread_recorder=recorder,
                queued_inputs=queued_inputs,
                memory=WorkspaceMemory(session_workspace=str(runtime.workspace_path)),
            )
            self.active_loops[session_id] = agent

            try:
                result = await loop.run_in_executor(
                    _AGENT_EXECUTOR,
                    lambda: agent.run(
                        user_message=attempt.prompt,
                        history=recorder.history or None,
                        session_id=session_id,
                    ),
                )
            except asyncio.CancelledError:
                agent.cancel()
                raise
            finally:
                self.active_loops.pop(session_id, None)
                try:
                    checkpoint.flush()
                except OSError as exc:
                    logger.warning(
                        "Could not flush response checkpoint for attempt %s: %s",
                        attempt_id,
                        exc,
                    )

            result["streamed_text"] = checkpoint.text
            result["usage"] = recorder.usage

            if result.get("run_dir"):
                metrics = load_metrics(Path(result["run_dir"]))
                if metrics:
                    result["metrics"] = metrics

            return result
        finally:
            await llm.aclose()


def load_metrics(run_dir: Path) -> Optional[Dict[str, Any]]:
    """Load metrics.csv from a run directory."""
    import csv
    metrics_path = run_dir / "artifacts" / "metrics.csv"
    if not metrics_path.exists():
        return None
    try:
        with open(metrics_path, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return None
    if not rows:
        return None
    metrics: Dict[str, Any] = {}
    for key, value in rows[0].items():
        if not value:
            continue
        try:
            metrics[key] = float(value)
        except (TypeError, ValueError):
            continue
    return metrics or None


def compact_recorded_history(
    llm, runtime: SessionRuntime, recorder, messages: list, run_dir: Path, focus: str, *, policy: ToolPolicy,
) -> None:
    """Bind manual compaction to the same product policies as a conversation turn."""
    from src.agent.runtime import AgentRuntime
    from src.product.resources.memory import WorkspaceMemory
    from src.agent.tools import ToolRegistry

    agent = AgentRuntime(
        registry=ToolRegistry(policy=policy),
        llm=llm,
        memory=WorkspaceMemory(session_workspace=str(runtime.workspace_path)),
        thread_recorder=recorder,
    )
    agent.memory.run_dir = str(run_dir)
    agent._conversation.turn_messages = messages
    agent._context_compactor.auto_compact(messages, run_dir, recorder, focus, 0)
