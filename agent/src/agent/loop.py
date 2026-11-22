"""AgentLoop: ReAct core loop.

Five-layer context management:
  Layer 1 (microcompact)     — prunes old tool results once under memory pressure
  Layer 2 (context_collapse) — folds long text blocks without LLM call (zero cost)
  Layer 3 (auto_compact)     — LLM structured summary with token-budget tail protection
  Layer 4 (compact tool)     — model explicitly calls the compact tool to trigger L3
  Layer 5 (iterative update) — Nth compression updates previous summary instead of starting fresh

Tool execution:
  - Read/write batching: consecutive readonly tools run in parallel via threads
"""

from __future__ import annotations

import json
import logging
import threading
import time as _time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from src.agent.tuning import (
    TOKEN_THRESHOLD as TOKEN_THRESHOLD,
    _override as _override,
    _token_threshold as _token_threshold,
    _heartbeat_interval_s as _heartbeat_interval_s,
    _reasoning_delta_min_interval_s as _reasoning_delta_min_interval_s,
    _stream_retry_delay_s as _stream_retry_delay_s,
    _stream_retry_max_delay_s as _stream_retry_max_delay_s,
    _stream_retry_backoff_s as _stream_retry_backoff_s,
    _tool_timeout_seconds as _tool_timeout_seconds,
    _llm_timeout_seconds as _llm_timeout_seconds,
    _goal_max_continuations as _goal_max_continuations,
    _stall_timeout_seconds as _stall_timeout_seconds,
    _mid_turn_nudge_rounds as _mid_turn_nudge_rounds,
    _wrap_up_nudge_remaining as _wrap_up_nudge_remaining,
)

from src.agent.context import ContextBuilder
from src.agent.tool_loading import prepare_registry, request_definitions
from src.agent.instrument_identity import IdentityLedger
from src.agent.memory import WorkspaceMemory
from src.agent.progress import HeartbeatTimer as HeartbeatTimer, ProgressEvent as ProgressEvent, _set_emitter as _set_emitter
from src.agent.context_budget import (
    CompactionBudget,
    ContextMeter,
)
from src.agent.context_compact import (  # noqa: F401  (re-exported so loop imports keep working)
    COLLAPSE_HEAD,
    COLLAPSE_PRESERVE_RECENT,
    COLLAPSE_TAIL,
    COLLAPSE_TEXT_MIN,
    KEEP_RECENT,
    SUMMARY_CHUNK_CHARS,
    TAIL_TOKEN_BUDGET,
    _CLEARED_PREFIX,
    _ITERATIVE_UPDATE_PROMPT,
    _STRUCTURED_SUMMARY_PROMPT,
    _FOCUS_SECTION,
    _STUB_RESULT_CONTENT,
    _attach_tool_call_thought_signatures,
    _cleared_text,
    _context_collapse,
    _fix_tool_pairs,
    _is_cleared,
    _microcompact,
    _msg_estimate_chars,
    _replay_context_result as _replay_context_result,
    _result_data_gone as _result_data_gone,
    _summary_chunks,
    _tail_cut_index,
    _verification_ledger,
)
from src.agent.tool_progress import ToolProgress
from src.agent.tools import ToolRegistry
from src.agent.trace import TraceWriter
from src.core.state import RunStateStore
from src.goal.context import get_current_goal_context
from src.providers.chat import ChatLLM, LLMRuntimeSnapshot, ProviderStreamError, reported_model_source
from src.providers.session_context import bind_llm_session_id, reset_llm_session_id
from src.config.accessor import get_env_config
from src.config.paths import get_runs_dir, get_sessions_dir
from src.tools.background_tools import get_background_manager
from src.config.limits import truncate_tool_result as truncate_tool_result
from src.tools.redaction import redact_payload as redact_payload, redact_tool_result as redact_tool_result

from src.agent.tool_lifecycle import (
    ToolCallLifecycle,
    MAX_READONLY_REPLAY_RECOVERIES as MAX_READONLY_REPLAY_RECOVERIES,
    _format_timeout as _format_timeout,
)
from src.agent.hooks import HookDecision
from src.agent.loop_conversation import ConversationState
from src.agent.loop_usage_state import UsageLedger
from src.agent.loop_watchdog import StallWatchdog
from src.agent.loop_compaction import ContextCompactor
from src.agent.loop_driver import IterationDriver
from src.agent.loop_state import TurnSetup, TurnState
from src.agent.loop_directives import WriteTargetState

RUNS_DIR = get_runs_dir()
SESSIONS_DIR = get_sessions_dir()

# An LLM may return a transient empty completion (no text, no tool calls);
# retry once with a nudge before failing the run on a second consecutive one.
MAX_CONSECUTIVE_EMPTY_RESPONSE_SKIPS = 1

# A successful result from one of these tools is enough to let the pacing
# nudge ask for an answer without treating every readonly lookup as evidence.
_DATA_RESULT_TOOLS = frozenset({
    "get_market_data",
    "technical_indicators",
    "get_stock_profile",
    "get_fundamentals",
    "get_financial_statements",
    "get_options_chain",
    "news_search",
    "web_search",
    "backtest",
})


def _has_successful_data_result(messages: list[dict[str, Any]]) -> bool:
    """Return whether the model already has a successful data observation."""
    for message in messages:
        if message.get("role") != "tool" or message.get("name") not in _DATA_RESULT_TOOLS:
            continue
        content = message.get("content")
        try:
            payload = json.loads(content) if isinstance(content, str) else content
        except (TypeError, ValueError):
            payload = None
        if isinstance(payload, dict) and (payload.get("ok") is False or payload.get("success") is False):
            continue
        return True
    return False


logger = logging.getLogger(__name__)


def estimate_tokens(messages: list) -> int:
    """Rough token count estimate (~4 chars/token).

    Args:
        messages: Message list.

    Returns:
        Estimated token count.
    """
    return len(json.dumps(messages, default=str, ensure_ascii=False)) // 4


# --- Tool-result helpers, moved to src.agent.tool_results (issue #1624) ---
# Re-exported here so existing ``from src.agent.loop import ...`` keeps working.
from src.agent.tool_results import (  # noqa: E402
    _FORCED_TEXT_TOOL_CALL_RE as _FORCED_TEXT_TOOL_CALL_RE,
    _DSML_BAR_TOOL_CALL_RE as _DSML_BAR_TOOL_CALL_RE,
    _TARGET_PATH_RE as _TARGET_PATH_RE,
    _TARGET_ACTION_RE as _TARGET_ACTION_RE,
    _failure_code as _failure_code,
    _is_tool_success as _is_tool_success,
    _looks_like_tool_call_syntax,  # noqa: F401 - compatibility import
    _named_target_paths as _named_target_paths,
    _normalize_tool_run_dir as _normalize_tool_run_dir,
    _previously_archived as _previously_archived,
    _archive_backtest_result as _archive_backtest_result,
)
from src.agent.run_outcome import (  # noqa: E402
    OutcomeInputs,
    RunOutcome as RunOutcome,  # noqa: F401 — re-exported for callers/tests
    build_end_event,
    build_result_dict,
    resolve_final_status,
)


# --- LLM usage accounting, moved to src.agent.llm_usage (issue #1624) ---
# Re-exported here so existing ``from src.agent.loop import ...`` keeps working.
from src.agent.llm_usage import (  # noqa: E402
    LLM_USAGE_ARTIFACT as LLM_USAGE_ARTIFACT,
    _coerce_usage_int as _coerce_usage_int,
    _normalize_llm_usage as _normalize_llm_usage,
    _new_llm_usage_summary as _new_llm_usage_summary,
    _record_llm_usage as _record_llm_usage,
    _record_unreported_llm_call as _record_unreported_llm_call,
)


class AgentLoop(ToolCallLifecycle):
    """ReAct Agent core loop.

    Attributes:
        registry: Tool registry.
        llm: ChatLLM client.
        memory: Workspace memory.
        max_iterations: Maximum research iterations, plus one text-only answer retry.
    """

    _queued_inputs: Optional[Any] = None

    def __init__(
        self,
        registry: ToolRegistry,
        llm: ChatLLM,
        memory: Optional[WorkspaceMemory] = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        max_iterations: int = 50,
        persistent_memory: Optional[Any] = None,
        cancel_event: Optional[threading.Event] = None,
        background_manager: Optional[Any] = None,
        thread_recorder: Optional[Any] = None,
        queued_inputs: Optional[Any] = None,
    ) -> None:
        """Initialize AgentLoop.

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
        self._thread = thread_recorder
        self._queued_inputs = queued_inputs
        self._conversation = ConversationState(thread_recorder, queued_inputs)
        self._context_compactor = ContextCompactor(self)
        self._iteration_driver = IterationDriver(self)
        self._write_targets = WriteTargetState()
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
        self._active_model_id = runtime_snapshot.configured_model
        self._active_model_source = reported_model_source(runtime_snapshot, None)
        self.memory = memory or WorkspaceMemory()
        self._event_callback = event_callback
        self._waiting_user: Optional[Dict[str, Any]] = None
        self.max_iterations = max_iterations
        # Dedup identity is (tool name, canonical arguments) -- NOT the name
        # alone. Keying on the name blocked every legitimate second call to a
        # paginated or parameterised tool: get_financial_statements(
        # statement='income') then (statement='balance') is one name but two
        # different requests, and the second was answered with a synthetic
        # 'already completed successfully' skip. The model then correctly
        # reported that the balance sheet 'returned no readable content' -- a
        # true statement about a fabricated tool result.
        # Keys come from _identical_call_key, the same canonicaliser the
        # deterministic cache uses, so the block path and the cache path can
        # never disagree about what 'the same call' means.
        self._called_ok: set[tuple[str, str]] = set()
        # Capture successful identities before context collapse can stub args.
        # Skipped/error call IDs never enter this ledger.
        self._successful_call_keys: dict[str, tuple[str, str]] = {}
        self._cancel_event = cancel_event if cancel_event is not None else threading.Event()
        # Resolved once, not per iteration: an unowned handle is private to
        # itself, so re-deriving it would silently discard this loop's results.
        self._background_manager = (
            background_manager
            or getattr(registry, "background", None)
            or get_background_manager()
        )
        self._context_compactor.previous_summary = ""
        self._persistent_memory = persistent_memory
        # Set by the CLI to its launch directory so ./AGENTS.md is loaded too.
        self.instruction_launch_dir: Path | None = None
        self._run_iteration: int = 0
        self._has_run = False
        self._identity: IdentityLedger | None = None
        self._user_data_window = None
        self._released_fallback = False
        self._released_fallback_reason: str | None = None
        self._written_files: set[str] = set()
        self._stall_reason: str | None = None
        self._budget_stop_reason: str | None = None
        self._last_activity_wall: float = 0.0
        self._run_done = threading.Event()
        self._watchdog = StallWatchdog(self)
        # Identical deterministic tool calls (e.g. financial_rigor calc with
        # the same expression) are served from this cache instead of being
        # re-executed. Regression: after auto-compact cleared earlier tool
        # results, the model re-ran the same financial_rigor expressions
        # 5-9x each (2026-08-20 INTC run) because it could no longer see its
        # own verification records.
        self._called_identical: dict[tuple[str, str], str] = {}
        # Successful readonly results are retained only for this run. If
        # compaction removes the visible result, an exact repeat can restore it
        # without hitting the external source again. Repeatable tools require an
        # explicit replay policy for persistent post-compaction replay.
        self._readonly_replay_cache: dict[tuple[str, str], str] = {}
        self._readonly_replay_ready: set[tuple[str, str]] = set()
        self._readonly_replay_protected: set[tuple[str, str]] = set()
        # Replayed tool_call_ids whose restored payload no successful model
        # request has carried yet (message identity, not call identity).
        self._readonly_replay_visibility_pending: set[str] = set()
        self._readonly_replay_recoveries = 0
        self._tool_progress = ToolProgress()
        self._context_compactor.context_meter = ContextMeter()
        self._context_compactor.learned_context_window = None
        self._context_compactor.compacted_to_tokens = None
        self._context_compactor.tool_schema_tokens = 0
        self._llm_usage_summary = _new_llm_usage_summary(self.llm)
        self._usage_ledger = UsageLedger(self, self._llm_usage_summary)
        self._goal_usage_callback = None
        spawn_agent = self.registry.get("spawn_agent")
        set_usage_callback = getattr(spawn_agent, "set_usage_callback", None)
        if callable(set_usage_callback):
            set_usage_callback(self._record_subagent_usage)

    def cancel(self) -> None:
        """Cancel the current loop.

        Sets a thread-safe flag polled at every iteration boundary, per LLM
        stream chunk, and between tool batches, so a running turn stops at the
        next cooperative checkpoint instead of only at the next iteration.
        """
        self._cancel_event.set()
        self._run_hook("Stop", {"session_id": getattr(self, "_session_id", "")})
        # Stop must reach commands the current or an earlier turn spawned, not
        # only the ReAct cycle. Normal successful turns do not call cancel().
        if self._background_manager is not None:
            self._background_manager.cancel_all()

    def _write_run_manifest(self, trace_dir: "Path", messages: List[Dict[str, Any]]) -> None:
        """Record what methodology produced this run, beside its trace.

        Answers "under what system prompt, which skills, and which tool set was
        that number produced" -- the question a reproducibility review asks and
        that nothing in this repo could previously answer. Written once per run
        as ``run_manifest.json`` next to ``trace.jsonl``.

        The system-prompt hash transitively covers every skill injected at
        context-build time, because those skills ARE part of the prompt string.
        Skills pulled mid-run via ``load_skill`` are not, and appear in the
        trace instead; the manifest says so rather than implying coverage it
        does not have.

        The prompt itself is never stored -- only its hash. The prompt can carry
        user memory and workspace content, and this file is a provenance record,
        not a second copy of the conversation.

        Args:
            trace_dir: Directory holding this run's trace.
            messages: The fully built message list about to be sent.

        Note:
            Never raises. A provenance record that can break a run is worse than
            a missing one; a failure is logged and the run continues.
        """
        try:
            from datetime import datetime, timezone

            from src.governance.manifest import (
                build_run_manifest,
                collect_key_package_versions,
            )

            system_prompt = next(
                (m.get("content", "") for m in messages if m.get("role") == "system"), ""
            )
            manifest = build_run_manifest(
                run_id=f"iter-{self._run_iteration + 1}",
                timestamp=datetime.now(timezone.utc).isoformat(),
                system_prompt=str(system_prompt),
                tool_names=list(self.registry.tool_names),
                package_versions=collect_key_package_versions(),
                extra={
                    "skill_coverage": (
                        "skills injected at context-build time are inside the "
                        "hashed system prompt; skills loaded mid-run via "
                        "load_skill appear in trace.jsonl, not here"
                    ),
                },
            )
            path = trace_dir / "run_manifest.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(manifest.to_json(indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning("run manifest not written (%s: %s)", type(exc).__name__, exc)

    def run(self, user_message: str, history: Optional[List[Dict[str, Any]]] = None, session_id: str = "") -> Dict[str, Any]:
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
                thread = getattr(self, "_thread", None)
                if thread is not None:
                    hooks.set_audit_sink(
                        lambda decision: thread._runtime.thread.append(
                            "hook_decision", thread.turn_id, **decision
                        )
                    )
                self._run_hook(
                    "SessionEnd",
                    {"session_id": getattr(self, "_session_id", "")},
                )
            reset_llm_session_id(token)
            if result is None or result.get("status") not in {"success", "waiting_user"}:
                self._background_manager.cancel_all()

    def _run_bound(self, user_message: str, history: Optional[List[Dict[str, Any]]] = None, session_id: str = "") -> Dict[str, Any]:
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
        self._session_id = session_id
        if self._has_run:
            self._cancel_event.clear()
        else:
            self._has_run = True
        self._called_ok = set()
        self._successful_call_keys = {}
        self._context_compactor.reset()
        self._released_fallback = False
        self._released_fallback_reason = None
        self._write_targets.reset()
        self._stall_reason = None
        self._budget_stop_reason = None
        self._last_activity_wall = _time.time()
        self._run_done = threading.Event()
        self._called_identical = {}
        self._readonly_replay_cache = {}
        self._readonly_replay_ready = set()
        self._readonly_replay_protected = set()
        self._readonly_replay_visibility_pending = set()
        self._readonly_replay_recoveries = 0
        self._tool_progress = ToolProgress()
        self._turn_messages = None
        setup = self._prepare_turn(user_message, history, session_id)
        if setup.denied_result is not None:
            return setup.denied_result
        state = setup.state
        assert state is not None
        try:
            self._iteration_driver.run(state)
        except Exception as exc:
            return self._handle_bound_error(exc, setup)
        return self._complete_turn(setup)

    def _prepare_turn(self, user_message: str, history: Optional[List[Dict[str, Any]]], session_id: str) -> TurnSetup:
        """Build run resources and per-turn state before iteration."""
        self.registry = prepare_registry(self.registry)
        if self.memory.session_workspace:
            setattr(self.registry, "session_workspace", self.memory.session_workspace)
        if self._thread is not None and self._thread.loaded_tools is not None:
            restore_exposure = getattr(self.registry, "restore_exposure", None)
            if callable(restore_exposure):
                restore_exposure(self._thread.loaded_tools)
        self._context_compactor.tool_schema_tokens = estimate_tokens(request_definitions(self.registry))
        run_started_wall = _time.time()
        state_store = RunStateStore()
        RUNS_DIR.mkdir(parents=True, exist_ok=True)

        if self.memory.run_dir and Path(self.memory.run_dir).exists():
            run_dir = Path(self.memory.run_dir)
        else:
            run_dir = state_store.create_run_dir(RUNS_DIR)
            self.memory.run_dir = str(run_dir)

        state_store.save_request(
            run_dir,
            user_message,
            {
                "session_id": session_id,
                "session_workspace": self.memory.session_workspace,
            },
        )
        if self._thread is not None:
            self._thread.prepare_workspace(run_dir)
        from src.agent.data_window import UserDataWindow

        self._user_data_window = UserDataWindow.parse(user_message)
        # Authorization carried from an earlier turn comes only from the
        # ledger's own exported records. Replayed history (tool results, the
        # model's prose) is never parsed for symbols; for resolver constraints
        # the ledger reads what the user typed, as it did before replay.
        self._identity = IdentityLedger(
            run_dir=run_dir,
            user_message=user_message,
            history=self._thread.user_history if self._thread is not None else history,
            contextual_identity_constraints=(
                get_env_config().agent_tuning.vibe_contextual_identity_constraints
            ),
            restored_state=self._thread.identity_state if self._thread is not None else None,
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
        goal_store = None
        messages = context.build_messages(llm_user_message, history)
        self._turn_messages = messages
        if self._thread is not None:
            # Before any model call: the user message exactly as it is sent,
            # agent-state and recalled-memory envelopes included, so a later
            # replay reproduces the request byte for byte.
            self._thread.start(
                prompt=user_message,
                message=messages[-1],
                model=self._llm_runtime.configured_model or None,
                provider=self._llm_runtime.provider or None,
            )
            self._sync_thread_state()
        self._run_hook(
            "SessionStart",
            {"session_id": session_id, "attempt_id": getattr(self._thread, "turn_id", "")},
        )
        trace_dir = SESSIONS_DIR / session_id if session_id else run_dir
        trace = TraceWriter(trace_dir)
        self._write_run_manifest(trace_dir, messages)
        if self._run_iteration == 0 and trace.path.exists():
            existing = TraceWriter.read(trace_dir)
            self._run_iteration = max(
                (int(e.get("iter", 0)) for e in existing if "iter" in e),
                default=0,
            )
        trace.write_text_entry(
            {"type": "start", "iter": self._run_iteration + 1},
            field="prompt",
            value=user_message,
            offload_kind=f"start-{self._run_iteration + 1}",
        )
        trace.write_text_entry(
            {"type": "message", "iter": self._run_iteration + 1, "role": "user"},
            field="content",
            value=user_message,
            offload_kind=f"user-message-{self._run_iteration + 1}",
        )
        prompt_hook = self._run_hook(
            "UserPromptSubmit",
            {"session_id": session_id, "prompt": user_message, "attempt_id": getattr(self._thread, "turn_id", "")},
        )
        if prompt_hook is not None and prompt_hook.denied:
            reason = prompt_hook.reason or "UserPromptSubmit hook denied the prompt"
            trace.write({"type": "end", "iter": self._run_iteration, "status": "failed", "reason": reason})
            trace.close()
            state_store.mark_failure(run_dir, reason)
            self._end_thread_turn()
            return TurnSetup(
                run_dir=run_dir, trace=trace, state_store=state_store,
                denied_result={
                    "status": "failed", "error_code": "hook_denied", "reason": reason,
                    "run_dir": str(run_dir), "run_id": run_dir.name, "content": "",
                    "react_trace": [], "iterations": 0, "max_iterations": self.max_iterations,
                },
            )

        return self._configure_turn_control(
            messages, run_dir, trace, context, user_message, session_id,
            run_started_wall, state_store, active_goal_id, goal_store,
        )

    def _configure_turn_control(
        self, messages: list, run_dir: Path, trace: TraceWriter, context: ContextBuilder,
        user_message: str, session_id: str, run_started_wall: float,
        state_store: RunStateStore, active_goal_id: str | None, goal_store: Any,
    ) -> TurnSetup:
        """Configure usage, goal accounting, watchdog, and iteration state."""
        empty_model_response_iter: int | None = None
        self._llm_usage_summary = _new_llm_usage_summary(self.llm)
        goal_turn_accounted = False

        def check_goal_token_budget(snapshot: dict[str, Any] | None) -> None:
            goal = (snapshot or {}).get("goal") or {}
            limit = goal.get("token_budget")
            if limit is not None and int(goal.get("tokens_used") or 0) >= limit:
                self._budget_stop_reason = (
                    "goal_token_budget_exhausted: the research goal's token budget "
                    "has been reached. End the goal to continue; a new goal can set a "
                    "larger budget."
                )

        if active_goal_id and session_id:
            from src.goal import GoalStore

            goal_store = GoalStore()
            check_goal_token_budget(goal_store.get_goal_snapshot(active_goal_id))

        def account_goal_usage(usage_delta: dict[str, int] | None) -> None:
            nonlocal goal_store, goal_turn_accounted
            if not (active_goal_id and session_id):
                return
            token_delta = int(usage_delta.get("total_tokens") or 0) if usage_delta else 0
            turn_delta = 0 if goal_turn_accounted else 1
            if not (token_delta or turn_delta):
                return
            try:
                if goal_store is None:
                    from src.goal import GoalStore

                    goal_store = GoalStore()
                goal_store.account_usage(
                    session_id=session_id,
                    goal_id=active_goal_id,
                    expected_goal_id=active_goal_id,
                    token_delta=token_delta,
                    turn_delta=turn_delta,
                )
                goal_turn_accounted = True
                snapshot = goal_store.get_goal_snapshot(active_goal_id)
                check_goal_token_budget(snapshot)
                if snapshot is not None:
                    self._emit("goal.updated", {"goal": snapshot["goal"], "snapshot": snapshot})
            except Exception as exc:  # noqa: BLE001
                logger.debug("Goal usage accounting skipped: %s", exc)

        self._goal_usage_callback = account_goal_usage
        react_trace: List[Dict[str, Any]] = []
        wrap_up_remaining = _wrap_up_nudge_remaining()
        wrap_up_at = (
            max(2, self.max_iterations - wrap_up_remaining)
            if wrap_up_remaining > 0
            else None
        )
        no_commentary_rounds = 0
        mid_turn_nudge_rounds = _mid_turn_nudge_rounds()

        # Zombie-run watchdog: fail a run that makes no forward progress
        # (no LLM completion, no tool result) for the stall timeout instead
        # of leaving it "running" forever with no state.json. Heartbeats do
        # not count as progress - a hung tool keeps emitting them.
        stall_timeout = _stall_timeout_seconds()
        self._watchdog.start(trace, run_dir, state_store, stall_timeout)

        state = TurnState(
            messages=messages, run_dir=run_dir, trace=trace, context=context,
            react_trace=react_trace, user_message=user_message,
            run_started_wall=run_started_wall, session_id=session_id,
            state_store=state_store, goal_store=goal_store,
            active_goal_id=active_goal_id, empty_model_response_iter=empty_model_response_iter,
            wrap_up_at=wrap_up_at, no_commentary_rounds=no_commentary_rounds,
            mid_turn_nudge_rounds=mid_turn_nudge_rounds,
        )
        return TurnSetup(state=state, run_dir=run_dir, trace=trace, state_store=state_store, run_started_wall=run_started_wall, active_goal_id=active_goal_id)

    def _handle_bound_error(self, exc: Exception, setup: TurnSetup) -> Dict[str, Any]:
        """Persist an iteration exception using the historical error envelope."""
        state = setup.state
        assert state is not None and setup.run_dir is not None and setup.trace is not None and setup.state_store is not None
        logger.exception(f"AgentLoop error: {exc}")
        error_code = "provider_stream_error" if isinstance(exc, ProviderStreamError) else "agent_loop_error"
        setup.trace.write({"type": "end", "iter": self._run_iteration, "status": "error", "reason": str(exc), "iterations": state.iteration})
        setup.trace.close()
        setup.state_store.mark_failure(setup.run_dir, str(exc))
        self._end_thread_turn()
        self._run_done.set()
        return {"status": "failed", "error_code": error_code, "reason": str(exc), "run_dir": str(setup.run_dir), "run_id": setup.run_dir.name, "content": "", "react_trace": state.react_trace, "iterations": state.iteration, "max_iterations": self.max_iterations}

    def _complete_turn(self, setup: TurnSetup) -> Dict[str, Any]:
        """Resolve status, persist the terminal state, and return the result."""
        state = setup.state
        assert state is not None
        run_dir = setup.run_dir
        trace = setup.trace
        state_store = setup.state_store
        assert run_dir is not None and trace is not None and state_store is not None
        iteration = state.iteration
        final_content = state.final_content
        no_progress_reason = state.no_progress_reason
        content_filter_count = state.content_filter_count
        content_filter_circuit_breaker = state.content_filter_circuit_breaker
        empty_model_response_iter = state.empty_model_response_iter
        truncation_reason = state.truncation_reason
        last_response_model = state.last_response_model
        react_trace = state.react_trace
        # Determine final status. The reason is also propagated into the
        # returned dict so SessionService can surface a meaningful UI
        # message instead of "Execution failed: unknown" (issue #114).
        outcome = resolve_final_status(
            OutcomeInputs(
                stall_reason=self._stall_reason,
                cancelled=self._cancel_event.is_set(),
                no_progress_reason=no_progress_reason,
                content_filter_circuit_breaker=content_filter_circuit_breaker,
                has_output=(run_dir / "artifacts" / "metrics.csv").exists() or bool(final_content),
                released_fallback=self._released_fallback,
                released_fallback_reason=self._released_fallback_reason,
                pending_write_directive=lambda: self._pending_write_directive(
                    state.user_message, setup.run_started_wall
                ),
                empty_model_response_iter=empty_model_response_iter,
                empty_response_provider=self._llm_runtime.provider,
                empty_response_model=self._llm_runtime.configured_model or "(unset)",
                max_iterations=self.max_iterations,
                budget_reason=self._budget_stop_reason,
                answer_released=bool(final_content),
                truncation_reason=truncation_reason,
                waiting_user=self._waiting_user is not None,
            )
        )
        final_reason = outcome.reason
        if outcome.mark == "cancelled":
            state_store.mark_cancelled(run_dir, final_reason or "cancelled by user")
        elif outcome.mark == "failure":
            state_store.mark_failure(run_dir, final_reason or "")
        elif outcome.mark == "success":
            state_store.mark_success(run_dir)
        if outcome.mark == "success" and outcome.degraded and final_reason and not self._released_fallback:
            # A success that ended without writing the target file(s): the
            # pre-extraction code flagged it degraded only for this case.
            self._released_fallback = True

        trace.write(build_end_event(outcome, self._run_iteration, iteration))
        trace.close()

        result = build_result_dict(
            outcome,
            run_dir,
            react_trace,
            iteration,
            self.max_iterations,
            final_content,
            self._llm_runtime,
            last_response_model,
            content_filter_count,
        )

        self._end_thread_turn()
        self._run_done.set()

        return result

    # -- Conversation thread ----------------------------------------------------

    def _inject(self, messages: list, content: str) -> None:
        """Append a loop-authored user-role message and record it.

        Args:
            messages: The turn's messages (appended in place).
            content: Injected text (``<system>`` notes, background results).
        """
        self._conversation.inject(messages, content, self._turn_messages)

    def _take_queued_inputs(self, messages: list, trace: TraceWriter, current_iter: int) -> None:
        """Append the user messages sent while this turn was running.

        The one point a queued input enters a running turn: its tool batch has
        finished and the next model call has not been made. A stop or a spent
        budget takes nothing, so those inputs stay pending. Taking an input
        changes only what the model reads next, never the turn's tools,
        identity ledger, iteration cap or no-progress budget.

        Args:
            messages: The turn's messages (appended in place).
            trace: The run's trace.
            current_iter: Session-wide iteration number.
        """
        self._conversation.take_queued_inputs(messages, trace, current_iter, self)

    def _append_assistant(self, messages: list, message: Dict[str, Any], *, phase: str) -> None:
        """Append a model response to the turn's messages and record it.

        Args:
            messages: The turn's messages (appended in place).
            message: OpenAI-format assistant message, exactly as it will be sent.
            phase: ``commentary`` for a response more steps follow.
        """
        self._conversation.append_assistant(
            messages, message, phase=phase, turn_messages=self._turn_messages
        )

    def _record_final_answer(self, content: str) -> None:
        """Record the turn's released answer as the ``final`` assistant item.

        The loop never sends its final answer back within the turn, so the
        item holds the plain ``{role, content}`` a later turn replays.

        Args:
            content: Released answer text.
        """
        self._conversation.record_final_answer(content)

    def _sync_thread_state(self) -> None:
        """Record the conversation state a later turn or a restart restores."""
        self._conversation.sync_state(self)

    def _end_thread_turn(self) -> None:
        """Hand the turn's usage to the recorder and flush the final state."""
        self._conversation.end_turn(self)

    def _stall_watchdog(
        self,
        trace: TraceWriter,
        run_dir: Path,
        state_store: Any,
        stall_timeout: float,
    ) -> None:
        """Fail the run when no forward progress happens for the stall timeout.

        A run can hang inside a tool or provider call without ever raising:
        the bash subprocess stuck in ``communicate()`` (2026-08-20 INTC run,
        19:20:55 -> never returned) is the canonical case. Such a run stays
        "running" forever with no state.json - a zombie. This daemon thread
        watches wall-clock progress (LLM completions and tool results only,
        NOT heartbeats) and, once the stall timeout passes, writes a failed
        end event and state, and sets the cancel event so the loop exits at
        its next boundary.

        Args:
            trace: Trace writer for this run.
            run_dir: Run directory for state.json.
            state_store: RunStateStore.
            stall_timeout: Stall threshold in seconds.
        """
        self._watchdog.watch(trace, run_dir, state_store, stall_timeout)
        if self._watchdog.reason:
            self._stall_reason = self._watchdog.reason

    def _record_written_target(self, arguments: Mapping[str, Any]) -> None:
        """Track writes with the active response's model identity."""
        self._write_targets.record(arguments, self)

    def _pending_write_directive(
        self, user_message: str, run_started_wall: float
    ) -> str:
        """Name task targets not yet written in this run."""
        return self._write_targets.pending(user_message, run_started_wall)

    @property
    def _written_files(self) -> set[str]:
        """Compatibility view of the composed write-target ledger."""
        return self._write_targets.written_files

    @_written_files.setter
    def _written_files(self, value: set[str]) -> None:
        if not hasattr(self, "_write_targets"):
            self._write_targets = WriteTargetState()
        self._write_targets.written_files = value








    def _account_llm_usage(
        self, run_dir: Path, usage: Any, iteration: int, *, purpose: str | None = None,
        include_call_index: bool = True,
    ) -> None:
        """Persist reported usage and notify spending monitors before more work.

        Args:
            run_dir: Active run's artifact directory.
            usage: Provider metadata, or None when unavailable.
            iteration: Parent agent iteration, also for auxiliary calls.
            purpose: Auxiliary call kind; omitted for ordinary agent responses.
            include_call_index: Whether the emitted event belongs to the
                parent's call-indexed stream. Child calls have their own
                sequence and therefore omit this field.
        """
        self._usage_ledger.summary = self._llm_usage_summary
        self._usage_ledger.goal_callback = self._goal_usage_callback
        self._usage_ledger.record(
            run_dir, usage, iteration, purpose=purpose,
            include_call_index=include_call_index,
        )

    def _record_subagent_usage(self, event_type: str, data: dict[str, Any]) -> bool:
        """Account one child-provider usage event in the parent run.

        Args:
            event_type: ``item.delta`` with ``run.usage`` or ``run.usage_unavailable``.
            data: Provider usage payload without the child's iteration keys.

        Returns:
            True when the parent's goal budget has stopped further work.
        """
        self._usage_ledger.summary = self._llm_usage_summary
        self._usage_ledger.goal_callback = self._goal_usage_callback
        return self._usage_ledger.record_subagent(event_type, data)

    # -- Context compression ---------------------------------------------------


    def _context_budget(self, messages: list) -> CompactionBudget:
        """Return the active model's compaction budget."""
        return self._context_compactor._context_budget(messages)

    def _prompt_tokens(self, messages: list) -> int:
        """Return the next request's measured token count."""
        return self._context_compactor._prompt_tokens(messages)

    def _compact_to_budget(self, messages: list, run_dir: Path, trace: TraceWriter, iteration: int, current_iter: int, *, force: bool = False) -> None:
        """Apply context compaction layers through the composed component."""
        self._context_compactor._compact_to_budget(messages, run_dir, trace, iteration, current_iter, force=force)

    def _recover_context_overflow(self, exc: Exception, messages: list, run_dir: Path, trace: TraceWriter, iteration: int, current_iter: int) -> None:
        """Learn a provider-reported window and compact to it."""
        self._context_compactor._recover_context_overflow(exc, messages, run_dir, trace, iteration, current_iter)

    def _microcompact_and_unblock(self, messages: list, trace: TraceWriter, iteration: int, *, target_tokens: Optional[int] = None, measure: Optional[Callable[[list], int]] = None, preserve_tool_call_ids: Optional[set[str]] = None) -> list[str]:
        """Apply layer-one compaction and reopen lost readonly calls."""
        return self._context_compactor._microcompact_and_unblock(messages, trace, iteration, target_tokens=target_tokens, measure=measure, preserve_tool_call_ids=preserve_tool_call_ids)

    def _record_compaction_layer(self, messages: list, layer: int, before: list[dict[str, Any]]) -> None:
        """Persist a compaction layer through the context component."""
        # A few lightweight compatibility tests construct the loop without
        # calling ``__init__``. Keep the projection helper usable for those
        # instances while normal runs use the composed component directly.
        compactor = getattr(self, "_context_compactor", None)
        if compactor is None:
            compactor = ContextCompactor(self)
            self._context_compactor = compactor
        compactor._record_compaction_layer(messages, layer, before)

    def _auto_compact(self, messages: list, run_dir: Path, trace: TraceWriter, focus_topic: str = "", iteration: int = 0) -> None:
        """Run structured or degraded compaction through the context component."""
        self._context_compactor.auto_compact(messages, run_dir, trace, focus_topic=focus_topic, iteration=iteration)

    @property
    def _context_meter(self) -> ContextMeter:
        """Compatibility view of the composed context meter."""
        return self._context_compactor.context_meter

    @property
    def _previous_summary(self) -> str:
        """Compatibility view of the composed summary state."""
        return self._context_compactor.previous_summary

    @_previous_summary.setter
    def _previous_summary(self, value: str) -> None:
        self._context_compactor.previous_summary = value

    @property
    def _learned_context_window(self) -> int | None:
        """Compatibility view of the learned provider window."""
        return self._context_compactor.learned_context_window

    @_learned_context_window.setter
    def _learned_context_window(self, value: int | None) -> None:
        self._context_compactor.learned_context_window = value

    @property
    def _compacted_to_tokens(self) -> int | None:
        """Compatibility view of the last compacted size."""
        return self._context_compactor.compacted_to_tokens

    @_compacted_to_tokens.setter
    def _compacted_to_tokens(self, value: int | None) -> None:
        self._context_compactor.compacted_to_tokens = value

    @property
    def _tool_schema_tokens(self) -> int:
        """Compatibility view of the schema-token measurement."""
        return self._context_compactor.tool_schema_tokens

    @_tool_schema_tokens.setter
    def _tool_schema_tokens(self, value: int) -> None:
        self._context_compactor.tool_schema_tokens = value

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


_LEGACY_LAZY = {
    "MICROCOMPACT_THRESHOLD": lambda: int(_token_threshold() * 0.5),
    "COLLAPSE_THRESHOLD": lambda: int(_token_threshold() * 0.7),
    "HEARTBEAT_INTERVAL_S": _heartbeat_interval_s,
    "REASONING_DELTA_MIN_INTERVAL_S": _reasoning_delta_min_interval_s,
    "STREAM_RETRY_DELAY_S": _stream_retry_delay_s,
    "STREAM_RETRY_MAX_DELAY_S": _stream_retry_max_delay_s,
    "TOOL_TIMEOUT_SECONDS": _tool_timeout_seconds,
    "GOAL_MAX_CONTINUATIONS": _goal_max_continuations,
    "STALL_TIMEOUT_SECONDS": _stall_timeout_seconds,
}


def __getattr__(name: str):
    if name in _LEGACY_LAZY:
        return _LEGACY_LAZY[name]()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
