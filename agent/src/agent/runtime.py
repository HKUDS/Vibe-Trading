"""Compose the synchronous research runtime and manage a turn’s resources."""

from __future__ import annotations

from functools import partial
import logging
import threading
import time as _time
import traceback
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from src.agent.loop_conversation import ConversationState
from src.agent.loop_driver import IterationSteps
from src.agent.loop_state import TurnSetup, TurnState
from src.agent.loop_watchdog import StallWatchdog
from src.agent.tools import ToolRegistry
from src.agent.tuning import (
    _llm_timeout_seconds,
    _mid_turn_nudge_rounds,
    _override,
    _stall_timeout_seconds,
    _stream_retry_backoff_s,
    _stream_retry_max_delay_s,
)
from src.config.accessor import get_env_config
from src.config.paths import get_runs_dir, get_sessions_dir
from src.core.state import RunStateStore
from src.goal.context import get_current_goal_context
from src.kernel.contracts import LLMRuntimeSnapshot, LoopContext, LoopPorts, ModelMessage, RunLimits
from src.kernel.events import EventSink
from src.kernel.loop import run_loop
from src.kernel.state import RunActivity
from src.product.artifacts import ToolDelivery, write_run_manifest
from src.product.context import ContextBuilder
from src.product.goals import GoalBudget
from src.product.identity.ledger import IdentityLedger
from src.product.outcome import finish_outcome
from src.product.pacing import TurnPacing
from src.product.resources.hooks import HookDecision
from src.product.resources.memory import WorkspaceMemory
from src.product.tool_execution import ToolExecution
from src.product.tool_execution_context import ToolEnvironment
from src.product.tool_invocation import ToolInvocation
from src.product.tool_loading import DeferredToolRegistry, prepare_registry, request_definitions
from src.product.tool_replay import ToolReplay
from src.product.usage import UsageLedger, _new_llm_usage_summary
from src.product.verification import _verification_ledger
from src.product.write_directives import WriteTargetState
from src.providers.chat import ChatLLM
from src.providers.response import ProviderStreamError, reported_model_source
from src.providers.session_context import bind_llm_session_id, reset_llm_session_id
from src.session.compaction import ContextCompactor
from src.session.request import SessionRequest
from src.tools.background_tools import get_background_manager
from src.tools.redaction import redact_text

RUNS_DIR = get_runs_dir()
SESSIONS_DIR = get_sessions_dir()

logger = logging.getLogger(__name__)


class AgentRuntime:
    """ReAct Agent core loop.

    Attributes:
        registry: Tool registry.
        llm: ChatLLM client.
        memory: Workspace memory.
        max_iterations: Maximum research iterations, plus one text-only answer retry.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        llm: ChatLLM,
        memory: Optional[WorkspaceMemory] = None,
        event_callback: Optional[EventSink] = None,
        max_iterations: int = 50,
        persistent_memory: Optional[Any] = None,
        cancel_event: Optional[threading.Event] = None,
        background_manager: Optional[Any] = None,
        thread_recorder: Optional[Any] = None,
        queued_inputs: Optional[Any] = None,
    ) -> None:
        """Initialize AgentRuntime.

        Args:
            registry: Tool registry.
            llm: ChatLLM client.
            memory: Workspace memory (created fresh if not provided).
            event_callback: Event callback (event_type, data).
            max_iterations: Maximum research iterations, plus one text-only answer retry.
            persistent_memory: PersistentMemory for cross-session recall.
            cancel_event: Optional cancellation flag to share with long-running
                tools (e.g. ``run_swarm``). The host session owns the event so a
                user stop reaches both the loop and the tools it is blocked in;
                ``None`` keeps the loop self-contained (CLI and tests).
            background_manager: Scoped handle over the background task table.
                Must be the same handle the registry bound to its background
                tools, so this loop drains the completions of its own tasks and
                never another conversation's. Falls back to the handle the
                registry recorded, and only then to an unowned one.
            thread_recorder: The conversation's sink for this turn
                (``src.session.runtime.TurnRecorder``). It receives every item
                the model sees, carries the identity records and loaded tool
                names earlier turns left, and brings their offloaded tool
                results into this run. ``None`` (CLI, tests) records nothing
                and starts every run fresh, as before.
            queued_inputs: Source of user messages sent while this turn runs
                (``src.session.pending_inputs.QueuedInputDelivery``). Its
                ``deliver()`` records each one in the thread and returns the
                user messages to append; the loop takes them only after a
                tool batch finished, before the next model call. ``None``
                takes none.
        """
        self._owns_recorder = thread_recorder is None
        self._conversation = ConversationState(thread_recorder, queued_inputs)
        self.registry = prepare_registry(registry)
        self._hooks = getattr(self.registry, "hooks", None)
        if self._hooks is not None and thread_recorder is not None:
            self._hooks.set_audit_sink(thread_recorder)
        self.llm = llm
        runtime_snapshot = getattr(llm, "runtime_snapshot", None)
        if not isinstance(runtime_snapshot, LLMRuntimeSnapshot):
            runtime_cfg = get_env_config().llm
            runtime_snapshot = LLMRuntimeSnapshot(
                provider=runtime_cfg.langchain_provider.strip().lower() or "openai",
                configured_model=(
                    getattr(llm, "model_name", None)
                    or runtime_cfg.langchain_model_name
                ).strip(),
                reasoning_effort=(
                    runtime_cfg.langchain_reasoning_effort.strip().lower()
                ),
            )
        self._llm_runtime = runtime_snapshot
        self.memory = memory or WorkspaceMemory()
        self._event_callback = event_callback
        self.max_iterations = max_iterations
        self.activity = RunActivity(cancel_event if cancel_event is not None else threading.Event())
        # Resolved once, not per iteration: an unowned handle is private to
        # itself, so re-deriving it would silently discard this loop's results.
        self._background_manager = (
            background_manager
            or getattr(registry, "background", None)
            or get_background_manager()
        )
        self._persistent_memory = persistent_memory
        self.instruction_launch_dir: Path | None = None
        self._has_run = False
        self._watchdog = StallWatchdog(self.activity, self._emit)
        self.goals = GoalBudget(self._emit)
        self.usage = UsageLedger(self.llm, self._emit, self.activity, self.goals, self.memory)
        self._write_targets = WriteTargetState(
            self.memory, runtime_snapshot, reported_model_source(runtime_snapshot, None)
        )
        self.tool_env = ToolEnvironment(self.registry, self.memory)
        self.replay = ToolReplay(self.tool_env)
        self._context_compactor = ContextCompactor(
            llm=self.llm, provider=runtime_snapshot.provider, conversation=self._conversation,
            replay=self.replay, state_summary=lambda: self.memory.to_summary(), should_stop=self._should_stop,
            threshold_override=lambda: _override("TOKEN_THRESHOLD"),
            record_usage=self.usage.record, verification_ledger=_verification_ledger,
            timeout_seconds=_llm_timeout_seconds, hook=self._run_hook, emit=self._emit,
        )
        self.delivery = ToolDelivery(self.tool_env, self.replay, self._conversation, self._emit,
                                     self.activity.touch, self._write_targets.record)
        self.invocation = ToolInvocation(self.tool_env, self.replay, self._hooks,
                                         self.activity.cancel.is_set, self.delivery._emit_tool_progress)
        self.tools = ToolExecution(self.tool_env, self.replay, self.delivery, self.invocation,
                                   self.activity.cancel, self._context_compactor._context_budget,
                                   self._context_compactor._prompt_tokens)
        spawn_agent = self.registry.get("spawn_agent")
        set_usage_callback = getattr(spawn_agent, "set_usage_callback", None)
        if callable(set_usage_callback):
            set_usage_callback(self.usage.record_subagent)

    def _should_stop(self) -> bool:
        return self.activity.cancel.is_set() or self.goals.stop_reason is not None

    def cancel(self) -> None:
        """Cancel the current loop.

        Sets a thread-safe flag polled at every iteration boundary, per LLM
        stream chunk, and between tool batches, so a running turn stops at the
        next cooperative checkpoint instead of only at the next iteration.
        """
        self.activity.cancel.set()
        self._run_hook("Stop", {"session_id": self.tool_env.session_id})
        # Stop must reach commands the current or an earlier turn spawned, not
        # only the ReAct cycle. Normal successful turns do not call cancel().
        if self._background_manager is not None:
            self._background_manager.cancel_all()

    def run(self, user_message: str, history: Optional[list[ModelMessage]] = None, session_id: str = "") -> Dict[str, Any]:
        """Run the ReAct loop synchronously.

        Binds ``session_id`` as the active LLM session for the whole run so
        provider adapters that need a stable per-conversation identity
        (OpenCode Go's ``x-opencode-session``) can read it at request time.

        Args:
            user_message: User message.
            history: Prior conversation messages.
            session_id: Session ID.

        Returns:
            Execution result dict.
        """
        token = bind_llm_session_id(session_id)
        result = None
        try:
            result = self._run_bound(user_message, history, session_id)
            return result
        finally:
            hooks = getattr(self, "_hooks", None)
            if hooks is not None:
                thread = self._conversation.thread
                if thread is not None:
                    hooks.set_audit_sink(
                        lambda decision: thread._runtime.thread.append(
                            "hook_decision", thread.turn_id, **decision
                        )
                    )
                self._run_hook(
                    "SessionEnd",
                    {"session_id": self.tool_env.session_id},
                )
            if self._owns_recorder and self._conversation.thread is not None:
                outcome = result or {}
                self._conversation.thread._runtime.finish_turn(
                    self._conversation.thread.turn_id, prompt=user_message,
                    status={"success": "completed", "waiting_user": "waiting_user", "cancelled": "cancelled"}.get(outcome.get("status"), "failed"),
                    usage=self._conversation.thread.usage, run_dir=outcome.get("run_dir"),
                    summary=outcome.get("content"), error=outcome.get("reason"),
                )
            reset_llm_session_id(token)
            if result is None or result.get("status") not in {"success", "waiting_user"}:
                self._background_manager.cancel_all()

    def _run_bound(self, user_message: str, history: Optional[list[ModelMessage]] = None, session_id: str = "") -> Dict[str, Any]:
        """Run the ReAct loop with the LLM session already bound.

        Args:
            user_message: User message.
            history: Prior conversation messages.
            session_id: Session ID.

        Returns:
            Execution result dict.
        """
        # Preserve cancellation accepted while the first run is queued.  A
        # completed loop may still be reused deliberately, so clear terminal
        # state only after the first run has begun.
        self.tool_env.session_id = session_id
        if self._has_run:
            self.activity.cancel.clear()
        else:
            self._has_run = True
        self.replay.reset()
        self.invocation.reset()
        self.delivery.reset()
        self._context_compactor.reset()
        self._write_targets.reset()
        self.goals.stop_reason = None
        self.activity.start()
        self._conversation.turn_messages = None
        self._conversation.delta = []
        setup = self._prepare_turn(user_message, history, session_id)
        if setup.denied_result is not None:
            return setup.denied_result
        state = setup.state
        assert state is not None
        try:
            pacing = TurnPacing(self._conversation, self._llm_runtime.provider, self.llm, self.max_iterations, self.goals)
            steps = IterationSteps(
                requests=SessionRequest(
                    llm=self.llm, cancel=self.activity.cancel, should_stop=self._should_stop,
                    record_usage=self.usage.record, recover_overflow=self._context_compactor.recover_context_overflow,
                    timeout_seconds=_llm_timeout_seconds, backoff=_stream_retry_backoff_s,
                    max_delay=_stream_retry_max_delay_s,
                ),
                state=state,
                activity=self.activity, goals=self.goals, tools=self.tools, compactor=self._context_compactor,
                conversation=self._conversation, writes=self._write_targets, usage=self.usage,
                background=self._background_manager,
                pacing=pacing,
            )
            ports = LoopPorts(
                before_iteration=steps.before_iteration, prepare_request=steps.prepare_request,
                request=steps.request, record_partial=steps.record_partial,
                after_text=partial(pacing.handle, state), run_tools=steps.run_tools,
                poll_inputs=steps.poll_inputs, on_cancel=steps.on_cancel,
                read_delta=self._conversation.delta.copy,
                read_usage=lambda: dict(self.usage.summary["totals"]),
            )
            turn = run_loop(
                state.view,
                ports, RunLimits(self.max_iterations), self.activity.cancel, self._emit,
            )
        except Exception as exc:
            return self._handle_bound_error(exc, setup)
        result = finish_outcome(
            setup, iterations=turn.iterations, activity=self.activity, runtime=self._llm_runtime, max_iterations=self.max_iterations,
            budget_reason=self.goals.stop_reason, waiting_user=self.delivery.waiting_user is not None,
            pending_write=self._write_targets.pending,
        )
        self._conversation.end_turn(self.tool_env, turn.usage)
        recorder = self._conversation.thread
        items = recorder._runtime.thread.turn_items(recorder.turn_id)
        result["tool_count"] = sum(item.type == "tool_result" for item in items)
        self.activity.done.set()

        return result

    def _prepare_turn(self, user_message: str, history: Optional[list[ModelMessage]], session_id: str) -> TurnSetup:
        """Build run resources and per-turn state before iteration."""
        if isinstance(self.registry, DeferredToolRegistry):
            self.registry.reset_exposure()
        else:
            self.tool_env.registry = self.registry = prepare_registry(self.registry)
        if self.memory.session_workspace:
            setattr(self.registry, "session_workspace", self.memory.session_workspace)
        if self._conversation.thread is not None and self._conversation.thread.loaded_tools is not None:
            restore_exposure = getattr(self.registry, "restore_exposure", None)
            if callable(restore_exposure):
                restore_exposure(self._conversation.thread.loaded_tools)
        schemas = request_definitions(self.registry)
        self._context_compactor.update_tool_schemas(schemas)
        run_started_wall = _time.time()
        state_store = RunStateStore()
        RUNS_DIR.mkdir(parents=True, exist_ok=True)

        if self.memory.run_dir and Path(self.memory.run_dir).exists():
            run_dir = Path(self.memory.run_dir)
        else:
            run_dir = state_store.create_run_dir(RUNS_DIR)
            self.memory.run_dir = str(run_dir)

        if self._owns_recorder:
            import uuid

            from src.session.runtime import SessionRuntime
            from src.session.thread import ThreadLog

            record_dir = SESSIONS_DIR / session_id if session_id else run_dir
            runtime = SessionRuntime(ThreadLog(record_dir / "thread.jsonl"), session_id)
            self._conversation.thread = runtime.begin_turn(uuid.uuid4().hex[:12])
            self.memory.session_workspace = str(runtime.workspace_path)
            setattr(self.registry, "session_workspace", self.memory.session_workspace)
            if self._hooks is not None:
                self._hooks.set_audit_sink(self._conversation.thread)

        state_store.save_request(
            run_dir,
            user_message,
            {
                "session_id": session_id,
                "session_workspace": self.memory.session_workspace,
                "turn_id": self._conversation.thread.turn_id,
            },
        )
        if self._conversation.thread is not None:
            self._conversation.thread.prepare_workspace(run_dir)
        from src.product.data_window import UserDataWindow

        self.tool_env.data_window = UserDataWindow.parse(user_message)
        # Authorization carried from an earlier turn comes only from the
        # ledger's own exported records. Replayed history (tool results, the
        # model's prose) is never parsed for symbols; for resolver constraints
        # the ledger reads what the user typed, as it did before replay.
        self.tool_env.identity = IdentityLedger(
            run_dir=run_dir,
            user_message=user_message,
            history=self._conversation.thread.user_history if self._conversation.thread is not None else history,
            contextual_identity_constraints=(
                get_env_config().agent_tuning.vibe_contextual_identity_constraints
            ),
            seed_prompt_symbols=self._conversation.thread is None or (
                self._conversation.thread.queued_input_id is None and self._conversation.thread.answer_to_question_id is None
            ),
            restored_state=self._conversation.thread.identity_state if self._conversation.thread is not None else None,
        )

        context = ContextBuilder(self.registry, self.memory,
                                  persistent_memory=self._persistent_memory,
                                  instruction_launch_dir=self.instruction_launch_dir)
        goal_context, active_goal_id = get_current_goal_context(session_id) if session_id else ("", None)
        llm_user_message = user_message
        if goal_context:
            llm_user_message = (
                f"{goal_context}\n\n"
                f"<user-message>\n{user_message}\n</user-message>"
            )
        messages = context.build_messages(llm_user_message, history)
        self._conversation.turn_messages = messages
        if self._conversation.thread is not None:
            # Before any model call: the user message exactly as it is sent,
            # agent-state and recalled-memory envelopes included, so a later
            # replay reproduces the request byte for byte.
            self._conversation.thread.start(
                prompt=user_message,
                message=messages[-1],
                model=self._llm_runtime.configured_model or None,
                provider=self._llm_runtime.provider or None,
            )
            self._conversation.sync_state(self.tool_env)
        self._run_hook(
            "SessionStart",
            {"session_id": session_id, "attempt_id": getattr(self._conversation.thread, "turn_id", "")},
        )
        write_run_manifest(run_dir, messages, self.registry, self.activity.iteration)
        trace = self._conversation.thread
        prompt_hook = self._run_hook(
            "UserPromptSubmit",
            {"session_id": session_id, "prompt": user_message, "attempt_id": getattr(self._conversation.thread, "turn_id", "")},
        )
        if prompt_hook is not None and prompt_hook.denied:
            reason = prompt_hook.reason or "UserPromptSubmit hook denied the prompt"
            trace.write({"type": "end", "iter": self.activity.iteration, "status": "failed", "reason": reason})
            state_store.mark_failure(run_dir, reason)
            self._conversation.end_turn(self.tool_env, self.usage.summary["totals"])
            return TurnSetup(
                run_dir=run_dir, trace=trace, state_store=state_store,
                denied_result={
                    "status": "failed", "error_code": "hook_denied", "reason": reason,
                    "run_dir": str(run_dir), "run_id": run_dir.name, "content": "",
                    "iterations": 0, "max_iterations": self.max_iterations,
                },
            )

        self.usage.summary = _new_llm_usage_summary(self.llm)
        self.goals.start(session_id, active_goal_id)
        mid_turn_nudge_rounds = _mid_turn_nudge_rounds()

        # Zombie-run watchdog: fail a run that makes no forward progress
        # (no LLM completion, no tool result) for the stall timeout instead
        # of leaving it "running" forever with no state.json. Heartbeats do
        # not count as progress - a hung tool keeps emitting them.
        stall_timeout = _stall_timeout_seconds()
        self._watchdog.start(trace, run_dir, state_store, stall_timeout)

        state = TurnState(
            view=LoopContext(messages, self._llm_runtime, schemas), run_dir=run_dir, trace=trace, context=context,
            user_message=user_message,
            run_started_wall=run_started_wall, session_id=session_id,
            mid_turn_nudge_rounds=mid_turn_nudge_rounds,
        )
        return TurnSetup(state=state, run_dir=run_dir, trace=trace, state_store=state_store)

    def _handle_bound_error(self, exc: Exception, setup: TurnSetup) -> Dict[str, Any]:
        """Persist an iteration exception using the historical error envelope."""
        state = setup.state
        assert state is not None and setup.run_dir is not None and setup.trace is not None and setup.state_store is not None
        reason = redact_text(exc)
        logger.error("AgentRuntime error: %s", redact_text(traceback.format_exc()))
        error_code = "provider_stream_error" if isinstance(exc, ProviderStreamError) else "agent_loop_error"
        setup.trace.write({"type": "end", "iter": self.activity.iteration, "status": "error", "reason": reason, "iterations": state.iteration})
        setup.state_store.mark_failure(setup.run_dir, reason)
        self._conversation.end_turn(self.tool_env, self.usage.summary["totals"])
        self.activity.done.set()
        return {"status": "failed", "error_code": error_code, "reason": reason, "run_dir": str(setup.run_dir), "run_id": setup.run_dir.name, "content": "", "iterations": state.iteration, "max_iterations": self.max_iterations}

    def _emit(self, event_type: str, data: Dict[str, Any]) -> None:
        """Fire an event via the callback."""
        if self._event_callback:
            try:
                self._event_callback(event_type, data)
            except Exception:
                pass

    def _run_hook(self, event: str, payload: Mapping[str, Any]) -> HookDecision | None:
        """Run one configured lifecycle hook without weakening core guards."""
        hooks = getattr(self, "_hooks", None)
        if hooks is None:
            return None
        try:
            return hooks.run(event, payload)
        except Exception as exc:  # pragma: no cover - defensive hook boundary
            logger.warning("Hook %s failed: %s", event, exc)
            return HookDecision(event=event, decision="deny" if event == "PreToolUse" else "error", reason=str(exc))
