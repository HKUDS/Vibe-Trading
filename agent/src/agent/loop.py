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

import contextvars
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
)

from src.agent.loop_grounding import validate_and_release
from src.agent.loop_streaming import TurnStream
from src.agent.context import ContextBuilder
from src.agent.tool_loading import prepare_registry, request_definitions
from src.agent.grounding import GroundingLedger
from src.agent.grounding.release import MAX_GROUNDING_REVISIONS
from src.agent.memory import WorkspaceMemory
from src.agent.progress import HeartbeatTimer as HeartbeatTimer, ProgressEvent as ProgressEvent, _set_emitter as _set_emitter
from src.agent.context_budget import (
    MIN_CONVERSATION_TOKENS,
    CompactionBudget,
    ContextMeter,
    is_context_overflow,
    parse_context_limit,
    resolve_window,
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
from src.goal.context import (
    format_goal_continuation_prompt,
    get_current_goal_context,
    goal_needs_continuation,
    goal_progress_tuple,
)
from src.providers.chat import ChatLLM, LLMRuntimeSnapshot, ProviderStreamError
from src.providers.session_context import bind_llm_session_id, reset_llm_session_id
from src.providers.content_filter import (
    CONTENT_FILTER_SKIP_MESSAGE,
    MAX_CONSECUTIVE_CONTENT_FILTER_SKIPS,
)
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

RUNS_DIR = get_runs_dir()
SESSIONS_DIR = get_sessions_dir()

# An LLM may return a transient empty completion (no text, no tool calls);
# retry once with a nudge before failing the run on a second consecutive one.
MAX_CONSECUTIVE_EMPTY_RESPONSE_SKIPS = 1




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
    _looks_like_tool_call_syntax,
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
        """
        self.registry = prepare_registry(registry)
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
        self._active_model_source = "configured"
        self.memory = memory or WorkspaceMemory()
        self._event_callback = event_callback
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
        self._previous_summary: str = ""
        self._persistent_memory = persistent_memory
        self._run_iteration: int = 0
        self._has_run = False
        self._grounding: GroundingLedger | None = None
        self._released_fallback = False
        self._released_fallback_reason: str | None = None
        self._written_files: set[str] = set()
        self._stall_reason: str | None = None
        self._budget_stop_reason: str | None = None
        self._last_activity_wall: float = 0.0
        self._run_done = threading.Event()
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
        self._context_meter = ContextMeter()
        self._learned_context_window: int | None = None
        self._compacted_to_tokens: int | None = None
        self._tool_schema_tokens = 0
        self._llm_usage_summary = _new_llm_usage_summary(self.llm)
        self._goal_usage_callback = None

    def cancel(self) -> None:
        """Cancel the current loop.

        Sets a thread-safe flag polled at every iteration boundary, per LLM
        stream chunk, and between tool batches, so a running turn stops at the
        next cooperative checkpoint instead of only at the next iteration.
        """
        self._cancel_event.set()
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
        if self._has_run:
            self._cancel_event.clear()
        else:
            self._has_run = True
        self._called_ok = set()
        self._successful_call_keys = {}
        self._previous_summary = ""
        self._released_fallback = False
        self._released_fallback_reason = None
        self._written_files = set()
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
        self._context_meter = ContextMeter()
        self._learned_context_window: int | None = None
        self._compacted_to_tokens: int | None = None
        self.registry = prepare_registry(self.registry)
        # Sent with every request and never compacted, so they count against
        # the window exactly like the system prompt.
        self._tool_schema_tokens = estimate_tokens(request_definitions(self.registry))
        run_started_wall = _time.time()

        state_store = RunStateStore()
        RUNS_DIR.mkdir(parents=True, exist_ok=True)

        if self.memory.run_dir and Path(self.memory.run_dir).exists():
            run_dir = Path(self.memory.run_dir)
        else:
            run_dir = state_store.create_run_dir(RUNS_DIR)
            self.memory.run_dir = str(run_dir)

        state_store.save_request(run_dir, user_message, {"session_id": session_id})
        self._grounding = GroundingLedger(
            run_dir=run_dir,
            user_message=user_message,
            history=history,
            contextual_identity_constraints=(
                get_env_config().agent_tuning.vibe_contextual_identity_constraints
            ),
        )

        context = ContextBuilder(self.registry, self.memory,
                                  persistent_memory=self._persistent_memory)
        goal_context, active_goal_id = get_current_goal_context(session_id) if session_id else ("", None)
        llm_user_message = user_message
        if goal_context:
            llm_user_message = (
                f"{goal_context}\n\n"
                f"<user-message>\n{user_message}\n</user-message>"
            )
        goal_store = None
        goal_turn_accounted = False
        messages = context.build_messages(llm_user_message, history)
        react_trace: List[Dict[str, Any]] = []

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

        iteration = 0
        final_content = ""
        no_progress_reason: str | None = None
        content_filter_count = 0
        consecutive_content_filter_count = 0
        content_filter_circuit_breaker = False
        empty_model_response_iter: int | None = None
        consecutive_empty_responses = 0
        grounding_revisions = 0
        # A normal grounding correction is a text revision, not a new research
        # turn. Explicit grounding recovery (identity / missing price evidence)
        # keeps tools available; ordinary correction turns do not.
        grounding_correction_text_only = False
        pending_grounding_draft = ""
        self._llm_usage_summary = _new_llm_usage_summary(self.llm)

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
        last_response_model: str | None = None
        goal_continuations = 0
        goal_last_progress: tuple[int, int] | None = None
        wrap_up_at = max(1, int(self.max_iterations * 0.8))

        # Zombie-run watchdog: fail a run that makes no forward progress
        # (no LLM completion, no tool result) for the stall timeout instead
        # of leaving it "running" forever with no state.json. Heartbeats do
        # not count as progress - a hung tool keeps emitting them.
        stall_timeout = _stall_timeout_seconds()
        if stall_timeout > 0:
            watchdog = threading.Thread(
                target=self._stall_watchdog,
                args=(trace, run_dir, state_store, stall_timeout),
                name="run-stall-watchdog",
                daemon=True,
            )
            watchdog.start()

        stream_failure_streak = 0
        final_answer_retry_pending = False
        try:
            while iteration < self.max_iterations or final_answer_retry_pending:
                final_answer_retry = final_answer_retry_pending
                final_answer_retry_pending = False
                self._tool_schema_tokens = estimate_tokens(request_definitions(self.registry))
                if self._budget_stop_reason is not None:
                    break
                if self._cancel_event.is_set():
                    trace.write({"type": "cancelled", "iter": self._run_iteration + 1})
                    logger.info("AgentLoop cancelled by user")
                    break

                iteration += 1
                self._run_iteration += 1
                current_iter = self._run_iteration

                # Inject background task notifications for this conversation.
                notifs = self._background_manager.drain_notifications()
                if notifs:
                    notif_text = "\n".join(f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs)
                    messages.append({"role": "user", "content": f"<background-results>\n{notif_text}\n</background-results>\n\n<system>Continue processing with the background results above.</system>"})

                if _override("TOKEN_THRESHOLD") is not None:
                    # Test hook: a monkeypatched module-level TOKEN_THRESHOLD
                    # keeps the old estimate-based layers so compaction tests
                    # can force each layer with a tiny number.
                    tokens = estimate_tokens(messages)
                    if tokens > int(_token_threshold() * 0.5):
                        self._microcompact_and_unblock(
                            messages,
                            trace,
                            iteration,
                            preserve_tool_call_ids=self._readonly_replay_visibility_pending,
                        )
                        tokens = estimate_tokens(messages)
                    if tokens > int(_token_threshold() * 0.7):
                        _context_collapse(messages, preserve_tool_call_ids=self._readonly_replay_visibility_pending)
                        tokens = estimate_tokens(messages)
                    _tok_threshold = _token_threshold()
                    if tokens > _tok_threshold:
                        logger.info(f"Auto compact triggered: {tokens} tokens > {_tok_threshold}")
                        self._auto_compact(messages, run_dir, trace, iteration=current_iter)
                else:
                    self._compact_to_budget(messages, run_dir, trace, iteration, current_iter)

                # A compaction response also costs tokens. Its usage callback
                # can exhaust the caller's budget before the next agent call.
                if self._cancel_event.is_set() or self._budget_stop_reason is not None:
                    break

                logger.info(f"ReAct iteration {iteration}/{self.max_iterations}")

                # Inject wrap-up nudge when approaching iteration limit.
                # Skip on the first iteration (tiny budgets) and on the last
                # iteration (the forced text-only path already guarantees an
                # answer there) so the nudge never displaces the active-goal
                # context as the most recent user message.
                if iteration == wrap_up_at and 1 < iteration < self.max_iterations:
                    remaining = self.max_iterations - iteration
                    wrap_content = (
                        f"[SYSTEM] You have {remaining} iterations remaining out of "
                        f"{self.max_iterations}. Wrap up your work now: finish any "
                        "outstanding file writes or data updates that are part of your "
                        "task FIRST, while tools are still available for a few more "
                        "iterations. Do not start new analysis or re-verify data you "
                        "already hold. Then provide your final answer as plain text; "
                        "if your task was to update a file, state that it is done and where."
                    )
                    pending_directive = self._pending_write_directive(
                        user_message, run_started_wall
                    )
                    if pending_directive:
                        wrap_content += "\n\n" + pending_directive
                        trace.write(
                            {
                                "type": "pending_write_directive",
                                "iter": current_iter,
                            }
                        )
                    messages.append({"role": "user", "content": wrap_content})

                # Safety net: on the second-to-last iteration tools are still
                # available, but the final iteration is text-only and cannot
                # call tools. If the task names a target file that has not been
                # written, force the write now so the run does not end
                # "answered but incomplete".
                if iteration == self.max_iterations - 1:
                    pending_directive = self._pending_write_directive(
                        user_message, run_started_wall
                    )
                    if pending_directive:
                        trace.write(
                            {
                                "type": "pending_write_directive",
                                "iter": current_iter,
                            }
                        )
                        messages.append({"role": "system", "content": pending_directive})

                stream = TurnStream(
                    grounding=self._grounding, emit=self._emit, iteration=current_iter,
                    heartbeat_interval=_heartbeat_interval_s,
                    reasoning_interval=_reasoning_delta_min_interval_s,
                )

                # The final iteration is always text-only. A grounding correction
                # whose validator requested no explicit recovery is text-only too:
                # the model must revise from evidence already gathered instead of
                # starting another research/refetch loop merely to reformat a draft.
                is_last_iteration = iteration >= self.max_iterations
                correction_text_only = grounding_correction_text_only
                tool_defs = (
                    None
                    if is_last_iteration or correction_text_only
                    else request_definitions(self.registry)
                )
                if is_last_iteration:
                    trace.write({"type": "forced_text_only", "iter": current_iter})
                elif correction_text_only:
                    trace.write(
                        {
                            "type": "grounding_correction_text_only",
                            "iter": current_iter,
                        }
                    )

                _llm_timeout_s = _llm_timeout_seconds()
                llm_timeout = _llm_timeout_s if _llm_timeout_s > 0 else None

                def stream_request():
                    """Count usage from a failed request before any retry."""
                    try:
                        return self.llm.stream_chat(
                            messages,
                            tools=tool_defs,
                            on_text_chunk=stream.on_text,
                            on_reasoning_chunk=stream.on_reasoning,
                            on_waiting_chunk=stream.on_waiting,
                            timeout=llm_timeout,
                            idle_timeout_s=llm_timeout,
                            should_cancel=self._cancel_event.is_set,
                        )
                    except ProviderStreamError as error:
                        self._account_llm_usage(
                            run_dir, getattr(error, "usage_metadata", None), current_iter,
                            purpose="failed_stream",
                        )
                        raise

                try:
                    response = stream_request()
                except ProviderStreamError as exc:
                    # One retry for transient mid-stream failures (connection
                    # reset, relay hiccup) — mirrors the swarm worker policy.
                    # Deterministic 4xx errors fail immediately. Deltas from
                    # the failed attempt are dropped so the trace does not
                    # contain duplicated thinking text. The delay escalates
                    # across consecutive retryable failures, honoring the
                    # provider's Retry-After header (bounded by the configured
                    # cap) when present. A successful retry does not reset the
                    # streak — only a clean first-attempt success does.
                    context_overflow = is_context_overflow(str(exc))
                    if not exc.retryable and not context_overflow:
                        raise
                    if context_overflow:
                        # Deterministic, so no backoff: shrink to the limit the
                        # provider reported and send once more.
                        self._recover_context_overflow(
                            exc, messages, run_dir, trace, iteration, current_iter
                        )
                        retry_delay_s = 0.0
                    else:
                        stream_failure_streak += 1
                        retry_delay_s = (
                            min(exc.retry_after_s, _stream_retry_max_delay_s())
                            if exc.retry_after_s is not None
                            else _stream_retry_backoff_s(stream_failure_streak)
                        )
                    logger.warning(
                        "Provider stream failed (iter %s), retrying once in %.2fs: %s",
                        current_iter,
                        retry_delay_s,
                        exc,
                    )
                    self._emit(
                        "stream_reset",
                        {
                            "iter": current_iter,
                            "reason": "context_overflow" if context_overflow else "provider_stream_retry",
                            "provider": exc.provider,
                            "model": exc.model,
                            "retry_delay_s": retry_delay_s,
                        },
                    )
                    stream.reset_for_retry()
                    # Wait on the cancel event, not time.sleep: the delay now
                    # escalates to the configured cap (30s by default) and a
                    # provider Retry-After can ask for that much on the first
                    # failure. A blocking sleep would make Stop take that long
                    # to be observed; the event returns the moment it is set.
                    self._cancel_event.wait(retry_delay_s)
                    if self._cancel_event.is_set() or self._budget_stop_reason is not None:
                        break
                    response = stream_request()
                else:
                    stream_failure_streak = 0

                self._consume_readonly_replay_visibility(messages, trace, current_iter)

                # An LLM response arrived - real progress for the stall watchdog.
                self._last_activity_wall = _time.time()

                usage = getattr(response, "usage_metadata", None)
                current_response_model = getattr(response, "response_model", None)
                # `messages` is still exactly what this request sent.
                self._context_meter.observe(
                    usage.get("context_input_tokens", usage.get("input_tokens")) if isinstance(usage, dict) else None,
                    messages,
                    tool_schema_tokens=estimate_tokens(tool_defs) if tool_defs else 0,
                )
                if current_response_model:
                    last_response_model = current_response_model
                self._account_llm_usage(run_dir, usage, current_iter)
                # A caller's spending monitor can cancel synchronously on the
                # usage event. Do not execute tools from that paid response; a
                # text-only answer that crossed a goal budget is still released.
                if self._cancel_event.is_set() or (
                    self._budget_stop_reason is not None and response.has_tool_calls
                ):
                    break
                thinking_text = "".join(stream.thinking_chunks)
                if thinking_text:
                    trace.write_text_entry(
                        {"type": "thinking", "iter": current_iter},
                        field="content",
                        value=thinking_text,
                        offload_kind=f"thinking-{current_iter}",
                    )
                    if not stream.buffer_text_output:
                        self._emit(
                            "thinking_done",
                            {
                                "iter": current_iter,
                                "content": (
                                    thinking_text[: self._grounding.streamable_length(thinking_text)]
                                    if self._grounding is not None
                                    else thinking_text
                                )[:500],
                            },
                        )

                # Content-filter skip: provider blocked the response — continue
                # to the next iteration instead of finalising on empty/garbage
                # content.  Checked *before* the tool-call branch so a filtered
                # response never executes its (likely empty) tool calls.
                # Use getattr for duck-typed response objects from mock LLMs.
                if getattr(response, "content_filter_triggered", False):
                    content_filter_count += 1
                    consecutive_content_filter_count += 1
                    if consecutive_content_filter_count >= MAX_CONSECUTIVE_CONTENT_FILTER_SKIPS:
                        trace.write({
                            "type": "content_filter_circuit_breaker",
                            "iter": current_iter,
                            "count": content_filter_count,
                        })
                        content_filter_circuit_breaker = True
                        break
                    trace.write({"type": "content_filter_skipped", "iter": current_iter})
                    messages.append({
                        "role": "user",
                        "content": f"<system>{CONTENT_FILTER_SKIP_MESSAGE}</system>",
                    })
                    continue

                # Not filtered — reset the consecutive-skip counter.
                consecutive_content_filter_count = 0

                forced_grounding_release = False
                if correction_text_only and response.has_tool_calls:
                    # An unoffered call consumes the same bounded correction
                    # budget as an invalid revised draft, but is never executed
                    # or inserted into the transcript as an unanswered tool call.
                    grounding_revisions += 1
                    trace.write(
                        {
                            "type": "grounding_correction_tool_call_blocked",
                            "iter": current_iter,
                            "round": grounding_revisions,
                        }
                    )
                    if stream.streamed_chars:
                        self._emit(
                            "stream_reset",
                            {"iter": current_iter, "reason": "grounding_tool_call_blocked"},
                        )
                    forced_grounding_release = (
                        grounding_revisions >= MAX_GROUNDING_REVISIONS
                        or iteration == self.max_iterations
                    )
                    if not forced_grounding_release:
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "<system>This is a grounding correction turn. "
                                    "Do not call tools. Revise the previous draft using "
                                    "the evidence already gathered, or remove claims "
                                    "that cannot be supported.</system>"
                                ),
                            }
                        )
                        continue

                unoffered_retry_call = final_answer_retry and response.has_tool_calls
                if (
                    forced_grounding_release
                    or unoffered_retry_call
                    or not response.has_tool_calls
                ):
                    # At the cap, release the last actual draft through the
                    # existing gate. The forbidden call's text is not an answer.
                    final_content = (
                        pending_grounding_draft
                        if forced_grounding_release
                        else response.content or ""
                    )
                    syntax_fallback_emitted = False
                    if not final_content and not unoffered_retry_call:
                        empty_model_response_iter = iteration
                        trace.write(
                            {
                                "type": "empty_model_response",
                                "iter": current_iter,
                                "provider": get_env_config().llm.langchain_provider,
                                "model": getattr(self.llm, "model_name", None) or get_env_config().llm.langchain_model_name,
                            }
                        )
                        # A transient empty completion (no text, no tool calls)
                        # must not kill a run that has already done its work:
                        # nudge once and retry, failing only on a second
                        # consecutive empty response.
                        if consecutive_empty_responses >= MAX_CONSECUTIVE_EMPTY_RESPONSE_SKIPS:
                            break
                        consecutive_empty_responses += 1
                        messages.append(
                            {
                                "role": "system",
                                "content": (
                                    "[SYSTEM] Your previous response was empty (no text, no tool "
                                    "calls). Respond again with either your next tool call or "
                                    "your final plain-text answer."
                                ),
                            }
                        )
                        continue
                    # A real response resets the consecutive-empty counter.
                    consecutive_empty_responses = 0
                    # A model can answer the forced-text final iteration with its
                    # native tool-call DSL as prose (see _looks_like_tool_call_syntax).
                    # That is not an answer: allow one text-only retry after the
                    # iteration cap, then use a deterministic fallback if it also
                    # fails. Cancellation and goal budgets still stop that retry.
                    if unoffered_retry_call or _looks_like_tool_call_syntax(
                        final_content
                    ):
                        if stream.streamed_chars:
                            self._emit(
                                "stream_reset",
                                {
                                    "iter": current_iter,
                                    "reason": "tool_call_syntax_in_answer",
                                },
                            )
                        trace.write(
                            {
                                "type": "tool_call_syntax_in_answer",
                                "iter": current_iter,
                            }
                        )
                        messages.append({"role": "assistant", "content": final_content})
                        messages.append(
                            {
                                "role": "system",
                                "content": (
                                    "[SYSTEM] Your previous response was not released: it contained "
                                    "tool-call syntax even though tool calling is unavailable now. "
                                    "Provide the final answer as plain prose only, with no XML/DSML tags."
                                ),
                            }
                        )
                        final_content = ""
                        if iteration <= self.max_iterations:
                            # One extra text-only turn can re-emit a withheld final
                            # answer; it does not extend the research/tool budget.
                            final_answer_retry_pending = (
                                iteration == self.max_iterations
                            )
                            continue
                        # The bounded retry also failed: never leak the raw markup. The
                        # grounding safe-fallback talks about instrument identity,
                        # which is wrong for non-market tasks, so use a neutral
                        # message here instead.
                        final_content = (
                            "My final response could not be delivered: it contained "
                            "tool-call syntax instead of a plain-text answer. "
                            "Please ask me to continue."
                        )
                        self._released_fallback = True
                        self._released_fallback_reason = (
                            "final answer withheld: it contained tool-call syntax on "
                            "the forced-text iteration"
                        )
                        self._emit(
                            "text_delta",
                            {"delta": final_content, "iter": current_iter},
                        )
                        syntax_fallback_emitted = True
                    grounded = validate_and_release(
                        self, final_content=final_content, grounding_revisions=grounding_revisions,
                        grounding_correction_text_only=grounding_correction_text_only,
                        pending_grounding_draft=pending_grounding_draft,
                        forced_grounding_release=forced_grounding_release,
                        syntax_fallback_emitted=syntax_fallback_emitted, stream=stream,
                        trace=trace, react_trace=react_trace, messages=messages,
                        iteration=iteration, current_iter=current_iter,
                        max_revisions=MAX_GROUNDING_REVISIONS,
                    )
                    final_content = grounded.content
                    grounding_revisions = grounded.revisions
                    grounding_correction_text_only = grounded.text_only
                    pending_grounding_draft = grounded.pending_draft
                    if grounded.retry:
                        continue
                    # The correction has ended. A goal continuation is a new
                    # research turn and must regain its normal tool access.
                    grounding_correction_text_only = False
                    pending_grounding_draft = ""
                    should_continue_goal = False
                    continuation_snapshot = None
                    _max_cont = _goal_max_continuations()
                    if (
                        not final_answer_retry
                        and not forced_grounding_release
                        and active_goal_id
                        and session_id
                        and _max_cont > 0
                    ):
                        try:
                            if goal_store is None:
                                from src.goal import GoalStore

                                goal_store = GoalStore()
                            continuation_snapshot = goal_store.get_goal_snapshot(active_goal_id)
                            should_continue_goal = bool(
                                continuation_snapshot
                                and goal_needs_continuation(continuation_snapshot)
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.debug("Goal continuation check skipped: %s", exc)

                    if should_continue_goal and continuation_snapshot is not None:
                        current_progress = goal_progress_tuple(continuation_snapshot)
                        no_new_progress = (
                            goal_last_progress is not None
                            and current_progress <= goal_last_progress
                        )
                        if goal_continuations >= _max_cont or (
                            no_new_progress and goal_continuations > 0
                        ):
                            trace.write(
                                {
                                    "type": "goal_continuation_suppressed",
                                    "iter": current_iter,
                                    "goal_id": active_goal_id,
                                    "progress": current_progress,
                                    "continuations": goal_continuations,
                                }
                            )
                        else:
                            trace.write_text_entry(
                                {
                                    "type": "goal_intermediate_answer",
                                    "iter": current_iter,
                                    "goal_id": active_goal_id,
                                    "progress": current_progress,
                                },
                                field="content",
                                value=final_content,
                                offload_kind=f"goal-intermediate-answer-{current_iter}",
                            )
                            trace.write_text_entry(
                                {"type": "message", "iter": current_iter, "role": "assistant"},
                                field="content",
                                value=final_content,
                                offload_kind=f"assistant-message-{current_iter}",
                            )
                            react_trace.append(
                                {"type": "goal_intermediate_answer", "content": final_content[:500]}
                            )
                            messages.append({"role": "assistant", "content": final_content})
                            messages.append(
                                {
                                    "role": "user",
                                    "content": format_goal_continuation_prompt(
                                        continuation_snapshot,
                                        previous_answer=final_content,
                                    ),
                                }
                            )
                            goal_last_progress = current_progress
                            goal_continuations += 1
                            continue

                    trace.write_text_entry(
                        {"type": "answer", "iter": current_iter},
                        field="content",
                        value=final_content,
                        offload_kind=f"answer-{current_iter}",
                    )
                    trace.write_text_entry(
                        {"type": "message", "iter": current_iter, "role": "assistant"},
                        field="content",
                        value=final_content,
                        offload_kind=f"assistant-message-{current_iter}",
                    )
                    react_trace.append({"type": "answer", "content": final_content[:500]})
                    break

                if not stream.buffer_text_output and self._grounding is not None:
                    # The turn is over, so a held-back last line is complete: it is
                    # shown unless it opens a figures block.
                    turn_text = "".join(stream.thinking_chunks)
                    safe = min(len(turn_text), self._grounding.streamable_length(turn_text + "\n"))
                    if safe > stream.streamed_chars:
                        self._emit(
                            "text_delta",
                            {"delta": turn_text[stream.streamed_chars:safe], "iter": current_iter},
                        )
                        stream.streamed_chars = safe
                assistant_message = context.format_assistant_tool_calls(
                    response.tool_calls,
                    content=response.content,
                    reasoning_content=response.reasoning_content or thinking_text or None,
                    provider_items=getattr(response, "provider_items", None),
                )
                _attach_tool_call_thought_signatures(assistant_message, response.tool_calls)
                messages.append(assistant_message)

                # Execute tools with read/write batching
                self._active_model_id = (
                    current_response_model or self._llm_runtime.configured_model
                )
                self._active_model_source = (
                    "provider_response" if current_response_model else "configured"
                )
                compact_requested, focus_topic = self._process_tool_calls(
                    response.tool_calls, context, messages, trace, react_trace, current_iter,
                )

                if (
                    not self._cancel_event.is_set()
                    and self._tool_progress.finish_iteration()
                ):
                    final_content = self._tool_progress.recovery_message()
                    no_progress_reason = "no_progress: " + final_content
                    trace.write(
                        {
                            "type": "no_progress",
                            "iter": current_iter,
                            "iterations_without_progress": self._tool_progress.stalled_iterations,
                        }
                    )
                    trace.write_text_entry(
                        {"type": "answer", "iter": current_iter},
                        field="content",
                        value=final_content,
                        offload_kind=f"answer-{current_iter}",
                    )
                    react_trace.append({"type": "answer", "content": final_content})
                    self._emit(
                        "text_delta", {"delta": final_content, "iter": current_iter}
                    )
                    break

                # Layer 3: compress after all tools have executed
                if compact_requested:
                    logger.info("Manual compact triggered by model")
                    self._auto_compact(messages, run_dir, trace, focus_topic=focus_topic, iteration=current_iter)

        except Exception as exc:
            logger.exception(f"AgentLoop error: {exc}")
            error_code = (
                "provider_stream_error"
                if isinstance(exc, ProviderStreamError)
                else "agent_loop_error"
            )
            trace.write({"type": "end", "iter": self._run_iteration, "status": "error", "reason": str(exc), "iterations": iteration})
            trace.close()
            state_store.mark_failure(run_dir, str(exc))
            self._run_done.set()
            return {
                "status": "failed",
                "error_code": error_code,
                "reason": str(exc),
                "run_dir": str(run_dir),
                "run_id": run_dir.name,
                "content": "",
                "react_trace": react_trace,
                "iterations": iteration,
                "max_iterations": self.max_iterations,
            }

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
                grounding_validation_count=(
                    self._grounding.validation_count if self._grounding else 0
                ),
                pending_write_directive=lambda: self._pending_write_directive(
                    user_message, run_started_wall
                ),
                empty_model_response_iter=empty_model_response_iter,
                empty_response_provider=self._llm_runtime.provider,
                empty_response_model=self._llm_runtime.configured_model or "(unset)",
                max_iterations=self.max_iterations,
                budget_reason=self._budget_stop_reason,
                answer_released=bool(final_content),
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

        self._run_done.set()

        return result

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
        # Capture the done-event locally: a reused AgentLoop replaces
        # self._run_done when the next run starts, and this thread must
        # not keep watching with the old run timeout.
        run_done = self._run_done
        warned = False
        while not run_done.is_set():
            wait_s = min(30.0, max(5.0, stall_timeout / 4))
            if run_done.wait(timeout=wait_s):
                return
            idle = _time.time() - self._last_activity_wall
            if idle < stall_timeout:
                warned = False
                continue
            if not warned:
                warned = True
                self._emit(
                    "stall_warning",
                    {"idle_s": round(idle, 1), "timeout_s": stall_timeout},
                )
                continue
            reason = (
                "run stalled: no LLM completion or tool result for "
                + str(int(idle)) + "s (stall watchdog)"
            )
            self._stall_reason = reason
            try:
                trace.write(
                    {
                        "type": "end",
                        "iter": self._run_iteration,
                        "status": "failed",
                        "reason": reason,
                        "stalled": True,
                    }
                )
            except Exception:  # noqa: BLE001 - best-effort
                pass
            try:
                state_store.mark_failure(run_dir, reason)
            except Exception:  # noqa: BLE001 - best-effort
                pass
            self._emit("stalled", {"reason": reason})
            self._cancel_event.set()
            return

    def _record_written_target(self, arguments: Mapping[str, Any]) -> None:
        """Track writes with the active response's model identity."""
        from src.agent.write_targets import record_written_target

        record_written_target(
            arguments, written_files=self._written_files,
            run_dir=self.memory.run_dir, llm_runtime=self._llm_runtime,
            active_model_id=self._active_model_id,
            active_model_source=self._active_model_source,
        )

    def _pending_write_directive(
        self, user_message: str, run_started_wall: float
    ) -> str:
        """Name task targets not yet written in this run."""
        from src.agent.write_targets import pending_write_directive

        return pending_write_directive(
            user_message, run_started_wall, written_files=self._written_files,
        )

    def _context_budget(self, messages: list) -> CompactionBudget:
        """Compaction thresholds for the active model's real context window."""
        cfg = get_env_config()
        provider = (cfg.llm.langchain_provider or "").strip().lower().replace("_", "-")
        model = getattr(self.llm, "model_name", "") or cfg.llm.langchain_model_name
        window, source = resolve_window(
            provider,
            str(model or ""),
            env_window=cfg.agent_tuning.vibe_trading_context_window,
            learned_window=self._learned_context_window,
        )
        return CompactionBudget(
            window=window,
            source=source,
            max_tokens=cfg.agent_tuning.vibe_trading_context_max_tokens,
            static_tokens=self._context_meter.static(messages, self._tool_schema_tokens),
        )

    def _prompt_tokens(self, messages: list) -> int:
        """Real-token size the next request would have."""
        return self._context_meter.tokens(messages, self._tool_schema_tokens)

    def _compact_to_budget(
        self,
        messages: list,
        run_dir: Path,
        trace: TraceWriter,
        iteration: int,
        current_iter: int,
        *,
        force: bool = False,
    ) -> None:
        """Run the compaction layers the prompt has actually grown into.

        Args:
            messages: Message list, mutated in place.
            run_dir: Active run directory.
            trace: Run trace.
            iteration: Loop-local iteration (the microcompact event's key).
            current_iter: Session-wide iteration number.
            force: Summarise even under budget (the provider said it overflowed).
        """
        budget = self._context_budget(messages)
        tokens = self._prompt_tokens(messages)
        if tokens > budget.micro_at:
            # Oldest results first and only until the prompt fits again:
            # clearing all but the last few is what sent a 12-company
            # comparison back to re-fetch its own evidence.
            self._microcompact_and_unblock(
                messages,
                trace,
                iteration,
                target_tokens=budget.micro_at,
                measure=self._prompt_tokens,
                preserve_tool_call_ids=self._readonly_replay_visibility_pending,
            )
            tokens = self._prompt_tokens(messages)
        if tokens > budget.collapse_at:
            _context_collapse(messages, preserve_tool_call_ids=self._readonly_replay_visibility_pending)
            tokens = self._prompt_tokens(messages)
        # A summary keeps the static prompt plus a ~20K-token tail, so on a
        # window that small the prompt stays over the line after compacting;
        # without this every later iteration paid for another summary call.
        regrown = (
            self._compacted_to_tokens is None
            or tokens > self._compacted_to_tokens + MIN_CONVERSATION_TOKENS
        )
        if force or (tokens > budget.compact_at and regrown):
            logger.info(
                "Auto compact triggered: %s real tokens > %s (window %s from %s)",
                tokens, budget.compact_at, budget.window, budget.source,
            )
            self._auto_compact(messages, run_dir, trace, iteration=current_iter)
            self._compacted_to_tokens = self._prompt_tokens(messages)

    def _recover_context_overflow(
        self,
        exc: Exception,
        messages: list,
        run_dir: Path,
        trace: TraceWriter,
        iteration: int,
        current_iter: int,
    ) -> None:
        """Learn the real window from a context-length error and compact to it.

        A model missing from ``context_windows.json`` runs on the default
        window; if that is larger than the real one the provider says so, and
        the run shrinks to the limit instead of failing.

        Args:
            exc: The provider error that reported the overflow.
            messages: Message list, mutated in place.
            run_dir: Active run directory.
            trace: Run trace.
            iteration: Loop-local iteration.
            current_iter: Session-wide iteration number.
        """
        sent = self._prompt_tokens(messages)
        stated = parse_context_limit(str(exc))
        # The provider's own number when it gives one; otherwise the prompt
        # that did not fit, with a margin for our estimate of it.
        self._learned_context_window = stated or int(sent * 0.9)
        trace.write({
            "type": "context_overflow",
            "iter": current_iter,
            "prompt_tokens": sent,
            "stated_limit": stated,
            "learned_window": self._learned_context_window,
        })
        self._compact_to_budget(messages, run_dir, trace, iteration, current_iter, force=True)

    def _microcompact_and_unblock(
        self,
        messages: list,
        trace: TraceWriter,
        iteration: int,
        *,
        target_tokens: Optional[int] = None,
        measure: Optional[Callable[[list], int]] = None,
        preserve_tool_call_ids: Optional[set[str]] = None,
    ) -> list[str]:
        """Run layer-1 microcompact and re-open lost readonly call identities.

        A readable result for another argument variant, or a synthetic skip,
        cannot satisfy "use the previous result". Keep an exact call gated if
        any successful copy survives; never re-open mutating tools just because
        their results were compacted away.

        Args:
            messages: Message list, mutated in place by the compaction.
            trace: Run trace; a ``microcompact_cleared`` event is written
                whenever the ledger is re-opened, because this layer used to
                act silently and left no evidence for diagnosis.
            iteration: Current ReAct iteration, recorded on the trace event.
            target_tokens: Clear oldest-first only until the prompt fits.
            measure: Prompt-size function for ``target_tokens``.
            preserve_tool_call_ids: Replayed results still owed one model request.

        Returns:
            The tool names re-opened, for callers and tests to assert on.
        """
        readable_before = self._readable_success_keys(messages)
        _microcompact(
            messages,
            target_tokens=target_tokens,
            measure=measure,
            preserve_tool_call_ids=preserve_tool_call_ids,
        )
        unreadable_tools = self._unblock_lost_readonly_results(messages, readable_before)
        if unreadable_tools:
            trace.write({
                "type": "microcompact_cleared",
                "iter": iteration,
                "tools": unreadable_tools,
            })
        return unreadable_tools


    def _account_llm_usage(
        self, run_dir: Path, usage: Any, iteration: int, *, purpose: str | None = None,
    ) -> None:
        """Persist reported usage and notify spending monitors before more work.

        Args:
            run_dir: Active run's artifact directory.
            usage: Provider metadata, or None when unavailable.
            iteration: Parent agent iteration, also for auxiliary calls.
            purpose: Auxiliary call kind; omitted for ordinary agent responses.
        """
        delta = _record_llm_usage(
            run_dir, self._llm_usage_summary, usage, iteration, purpose=purpose,
        )
        if self._goal_usage_callback is not None:
            self._goal_usage_callback(delta)
        metadata = {"iter": iteration}
        if purpose is not None:
            metadata["purpose"] = purpose
        if delta:
            self._emit("llm_usage", {
                **delta, **metadata,
                "call_index": self._llm_usage_summary["totals"]["calls"],
            })
        elif purpose is None and not self._cancel_event.is_set():
            self._emit("llm_usage_unavailable", metadata)
        else:
            # A failed stream, a compaction call or a cancelled response that
            # reported nothing is counted as unreported, not announced as a
            # missing bill: the live decision budget halts on that event, so a
            # retried connection reset stopped live decisions for the day.
            _record_unreported_llm_call(run_dir, self._llm_usage_summary)

    # -- Context compression ---------------------------------------------------

    def _auto_compact(
        self,
        messages: list,
        run_dir: Path,
        trace: TraceWriter,
        focus_topic: str = "",
        iteration: int = 0,
    ) -> None:
        """Layer 3/4/5: structured LLM summary with token-budget tail protection.

        Upgrades over the original:
          - Token-budget tail: keeps ~20K tokens of recent messages (not a fixed count).
          - Structured summary template: preserves goal, progress, decisions, files, etc.
          - Iterative update: Nth compression updates previous summary, zero info decay.
          - Tool pair fix: repairs orphaned tool_call/tool_result after compression.
          - Focus-topic: optionally prioritize specific topic in summary.

        Args:
            messages: Message list (replaced in place).
            run_dir: Run directory.
            trace: TraceWriter.
            focus_topic: Optional topic to prioritize in the summary.
            iteration: Current trace iteration.
        """
        if self._cancel_event.is_set() or self._budget_stop_reason is not None:
            return
        # Save full transcript before compressing next to the active trace.
        transcript_path = trace.dir_path / f"transcript_{int(_time.time())}.jsonl"
        with open(transcript_path, "w", encoding="utf-8") as f:
            for msg in messages:
                f.write(json.dumps(msg, default=str, ensure_ascii=False) + "\n")

        readable_before = self._readable_success_keys(messages)
        system_msg = messages[0]
        body = messages[1:]

        # Token-budget tail: size messages with their tool-call arguments so
        # oversized tool calls are folded instead of hiding in the tail.
        cut_idx = _tail_cut_index(body)

        head = body[:cut_idx]
        tail = body[cut_idx:]

        if not head:
            # All body fits in tail budget — force a split to avoid infinite loop
            if len(body) > 2:
                cut_idx = max(1, len(body) // 2)
                head = body[:cut_idx]
                tail = body[cut_idx:]
            else:
                logger.warning("Auto compact: nothing to compress (body too small)")
                return

        # Replayed results are owed one successful writing request. Keep the
        # entire assistant-call/result pair out of summaries until then.
        pending = self._readonly_replay_visibility_pending
        leased = [msg for msg in head if (
            msg.get("role") == "tool" and msg.get("tool_call_id") in pending
        ) or any(call.get("id") in pending for call in msg.get("tool_calls") or [])]
        if leased:
            head = [msg for msg in head if all(msg is not kept for kept in leased)]
            tail = leased + tail

        # Build focus section
        focus_section = _FOCUS_SECTION.format(topic=focus_topic) if focus_topic else ""

        # Fold every head chunk so no message falls between the summary prompt
        # and the preserved tail. The first fresh chunk gets the full
        # structured handoff; subsequent chunks incrementally update it.
        # Encrypted provider items are opaque to the summariser and only
        # cost tokens there; the messages they belong to are being folded.
        chunks = _summary_chunks(
            [{k: v for k, v in m.items() if k != "provider_items"} for m in head]
        )
        logger.info("Auto compact: folding %d summary chunks", len(chunks))
        summary = self._previous_summary or ""
        degraded_compact = False
        _compact_timeout = _llm_timeout_seconds()
        for conv_text in chunks:
            if self._cancel_event.is_set() or self._budget_stop_reason is not None:
                return
            # Structured template while there is still nothing to update — that
            # covers a fresh session's first chunk and the corner case where
            # every fold so far returned empty content.
            if not summary:
                prompt = _STRUCTURED_SUMMARY_PROMPT.format(focus_section=focus_section) + conv_text
            else:
                prompt = _ITERATIVE_UPDATE_PROMPT.format(
                    previous_summary=summary,
                    new_turns=conv_text,
                    focus_section=focus_section,
                )

            # A silent provider stall on the summary call used to freeze the
            # whole run (no chunk arrives, so nothing aborts it). The provider
            # httpx timeout only bounds time-between-bytes, not total time, and
            # LangChain does not honor a per-call config "timeout", so a slow
            # but alive server can run for many minutes. Enforce a hard
            # wall-clock deadline via a daemon thread; on expiry fall back to
            # hard truncation so the loop continues.
            _compact_result: list = []
            _compact_error: list = []

            def _run_compact_summary() -> None:
                try:
                    resp = self.llm.chat(
                        [{"role": "user", "content": prompt}],
                        timeout=_compact_timeout if _compact_timeout > 0 else None,
                    )
                    _compact_result.append(resp)
                except BaseException as exc:  # noqa: BLE001 - compaction must not crash the run
                    _compact_error.append(exc)

            if _compact_timeout > 0:
                # A new thread starts with an empty context, so the session
                # bound by run() (x-opencode-session, #1416) would not reach
                # this call: run it inside a copy of the caller's context.
                worker = threading.Thread(
                    target=contextvars.copy_context().run,
                    args=(_run_compact_summary,),
                    name="compact-summary",
                    daemon=True,
                )
                worker.start()
                worker.join(timeout=_compact_timeout)
                if worker.is_alive():
                    logger.warning(
                        "Auto compact summary call exceeded %.1fs; degrading compaction",
                        _compact_timeout,
                    )
                    degraded_compact = True
                    self._account_llm_usage(run_dir, None, iteration, purpose="compaction")
                    break
                if _compact_error:
                    logger.warning(
                        "Auto compact LLM call failed (%s); degrading compaction",
                        _compact_error[0],
                    )
                    degraded_compact = True
                    self._account_llm_usage(run_dir, None, iteration, purpose="compaction")
                    break
                summary_resp = _compact_result[0]
            else:
                try:
                    summary_resp = self.llm.chat([{"role": "user", "content": prompt}])
                except Exception:
                    self._account_llm_usage(run_dir, None, iteration, purpose="compaction")
                    raise
            self._account_llm_usage(
                run_dir, getattr(summary_resp, "usage_metadata", None), iteration,
                purpose="compaction",
            )
            if self._cancel_event.is_set() or self._budget_stop_reason is not None:
                return
            if summary_resp.content:
                summary = summary_resp.content
        if degraded_compact and not summary:
            summary = (
                "[compaction degraded: LLM summarization timed out or failed; "
                "earlier tool results were truncated. "
                f"Full transcript: {transcript_path}]"
            )
        self._previous_summary = summary

        # Preserve deterministic verification records across the compaction.
        # The LLM summary does not reliably retain exact calc results, so the
        # model used to re-run the same financial_rigor expressions after a
        # compact to "re-verify" numbers it could no longer see (2026-08-20
        # INTC run: identical calcs re-ran 5-9x each). Re-attach a terse
        # ledger of already-verified values so the model does not re-run them.
        verification_ledger = _verification_ledger(head)

        tokens_before = estimate_tokens(messages)
        trace.write_text_entry(
            {
                "type": "compact",
                "iter": iteration,
                "tokens_before": tokens_before,
                "focus_topic": focus_topic or "(none)",
                "summary_chunks": len(chunks),
            },
            field="summary",
            value=summary,
            offload_kind=f"compact-summary-{iteration}",
        )
        self._emit("compact", {"tokens_before": tokens_before, "summary": summary[:200]})

        # Reconstruct: system + summary + acknowledge + preserved tail
        state_summary = self.memory.to_summary()
        compressed = f"[Conversation compressed — handoff summary. Transcript: {transcript_path}]\n\n{summary}"
        if verification_ledger:
            compressed += (
                "\n\n[Verified tool results from the compressed turns - do NOT "
                "re-run these tools, they are already verified]:\n"
                + verification_ledger
            )
        if state_summary and state_summary != "(empty state)":
            compressed += f"\n\nCurrent agent state:\n{state_summary}"

        messages.clear()
        messages.append(system_msg)
        messages.append({"role": "user", "content": f"{compressed}\n\n<system>Continue from the summary above.</system>"})
        messages.extend(tail)

        # Fix orphaned tool pairs in the reconstructed message list
        _fix_tool_pairs(messages)
        self._unblock_lost_readonly_results(messages, readable_before)

    def _emit(self, event_type: str, data: Dict[str, Any]) -> None:
        """Fire an event via the callback."""
        if self._event_callback:
            try:
                self._event_callback(event_type, data)
            except Exception:
                pass


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
