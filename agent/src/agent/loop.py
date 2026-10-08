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

import concurrent.futures
import contextvars
import copy
import json
import logging
import queue
import sys
import threading
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from src.agent.context import ContextBuilder
from src.agent.grounding import GroundingLedger
from src.agent.grounding.release import MAX_GROUNDING_REVISIONS
from src.agent.memory import WorkspaceMemory
from src.agent.progress import HeartbeatTimer, ProgressEvent, _set_emitter
from src.agent.context_budget import (
    MIN_CONVERSATION_TOKENS,
    CompactionBudget,
    ContextMeter,
    is_context_overflow,
    parse_context_limit,
    resolve_window,
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
    compute_content_filter_warnings,
)
from src.config.accessor import get_env_config
from src.config.paths import get_runs_dir, get_sessions_dir
from src.tools.background_tools import get_background_manager
from src.config.limits import truncate_tool_result
from src.tools.redaction import redact_payload, redact_tool_result

RUNS_DIR = get_runs_dir()
SESSIONS_DIR = get_sessions_dir()

# Compaction helpers split to ``loop_compaction.py`` (#1624). Re-exported here
# so every existing ``from src.agent.loop import ...`` (callers and tests)
# keeps resolving; import from ``loop_compaction`` in new code.
from src.agent.loop_compaction import (  # noqa: E402,F401
    COLLAPSE_HEAD,
    COLLAPSE_PRESERVE_RECENT,
    COLLAPSE_TAIL,
    COLLAPSE_TEXT_MIN,
    KEEP_RECENT,
    SUMMARY_CHUNK_CHARS,
    TAIL_TOKEN_BUDGET,
    _STUB_RESULT_CONTENT,
    _attach_tool_call_thought_signatures,
    _cleared_text,
    _context_collapse,
    _fix_tool_pairs,
    _format_timeout,
    _is_cleared,
    _microcompact,
    _msg_estimate_chars,
    _replay_context_result,
    _result_data_gone,
    _summary_chunks,
    _tail_cut_index,
    _verification_ledger,
    estimate_tokens,
)

LLM_USAGE_ARTIFACT = "llm_usage.json"

# An LLM may return a transient empty completion (no text, no tool calls);
# retry once with a nudge before failing the run on a second consecutive one.
MAX_CONSECUTIVE_EMPTY_RESPONSE_SKIPS = 1

# Compaction recovery is a bounded reliability aid, not an alternate research
# loop: a run restores at most this many lost readonly payloads from its replay
# cache. Past the cap a lost call runs again as it does without replay, so the
# model is never told to use a result it can no longer see, and a loop of
# identical re-runs still ends at the no-progress limit.
MAX_READONLY_REPLAY_RECOVERIES = 6


#: Test hook only: set it (monkeypatch) to run the three compaction layers on
#: the pre-2026-09-29 estimated-token thresholds. A real attribute on purpose:
#: while it was resolved lazily by the module ``__getattr__``, monkeypatch read
#: the lazy 40000 before patching and wrote it back as a real attribute on
#: undo, silently switching every later test in the process to the old path.
TOKEN_THRESHOLD: Optional[int] = None


def _override(name: str):
    """Return a monkeypatched module-level override if present."""
    mod = sys.modules.get(__name__)
    if mod is not None and name in mod.__dict__:
        return mod.__dict__[name]
    return None


def _token_threshold() -> int:
    ov = _override("TOKEN_THRESHOLD")
    if ov is not None:
        return ov
    from src.config.accessor import get_env_config
    return get_env_config().agent_tuning.token_threshold


def _heartbeat_interval_s() -> float:
    ov = _override("HEARTBEAT_INTERVAL_S")
    if ov is not None:
        return ov
    from src.config.accessor import get_env_config
    return get_env_config().agent_tuning.vt_heartbeat_interval_s


def _reasoning_delta_min_interval_s() -> float:
    ov = _override("REASONING_DELTA_MIN_INTERVAL_S")
    if ov is not None:
        return ov
    from src.config.accessor import get_env_config
    return get_env_config().agent_tuning.vt_reasoning_delta_min_interval_s


def _stream_retry_delay_s() -> float:
    ov = _override("STREAM_RETRY_DELAY_S")
    if ov is not None:
        return ov
    from src.config.accessor import get_env_config
    return get_env_config().agent_tuning.vt_stream_retry_delay_s


def _stream_retry_max_delay_s() -> float:
    ov = _override("STREAM_RETRY_MAX_DELAY_S")
    if ov is not None:
        return ov
    from src.config.accessor import get_env_config
    return get_env_config().agent_tuning.vt_stream_retry_max_delay_s


def _stream_retry_backoff_s(streak: int) -> float:
    """Return the capped exponential delay for the one-based failure streak.

    Doubles per consecutive retryable stream failure (1.0s, 2.0s, 4.0s, ...)
    so a sustained provider outage backs off instead of burning the retry
    budget at a constant cadence. The exponent is clamped at 62 (mirroring
    ``src/swarm/runtime.py``'s worker-level backoff) and the result is capped
    at ``_stream_retry_max_delay_s()``.

    Args:
        streak: Number of consecutive retryable stream failures including the
            current one; values below 1 are treated as 1.

    Returns:
        Seconds to sleep before the stream retry, never negative.
    """
    ceiling = min(
        _stream_retry_delay_s() * (2 ** min(max(streak, 1) - 1, 62)),
        _stream_retry_max_delay_s(),
    )
    return max(ceiling, 0.0)


def _tool_timeout_seconds() -> float:
    ov = _override("TOOL_TIMEOUT_SECONDS")
    if ov is not None:
        return ov
    from src.config.accessor import get_env_config
    return get_env_config().agent_tuning.vibe_trading_tool_timeout_seconds


def _llm_timeout_seconds() -> float:
    """Return the per-call LLM timeout in seconds (0/negative disables).

    A silent provider stall otherwise hangs the ReAct loop or the
    auto-compact summary call indefinitely - no chunk arrives, so the
    per-chunk cancel check never runs. Bounding the call lets the run fail
    (or degrade compaction) instead of freezing mid-task.
    """
    ov = _override("LLM_TIMEOUT_SECONDS")
    if ov is not None:
        return ov
    from src.config.accessor import get_env_config
    return get_env_config().agent_tuning.vibe_trading_llm_timeout_seconds


def _goal_max_continuations() -> int:
    ov = _override("GOAL_MAX_CONTINUATIONS")
    if ov is not None:
        return ov
    from src.config.accessor import get_env_config
    return get_env_config().agent_tuning.vibe_trading_goal_max_continuations


def _stall_timeout_seconds() -> float:
    """Return the run-stall watchdog timeout in seconds (0/negative disables).

    A run that makes no forward progress (no LLM completion, no tool result)
    for this long is treated as a zombie and failed explicitly with a clear
    reason instead of staying "running" forever with no state.json
    (recurring 2026-08 zombie runs). Heartbeats do NOT count as progress: a
    hung tool keeps emitting heartbeats, which is exactly the case the
    watchdog must catch.
    """
    ov = _override("STALL_TIMEOUT_SECONDS")
    if ov is not None:
        return ov
    from src.config.accessor import get_env_config
    return get_env_config().agent_tuning.vibe_trading_run_stall_timeout_seconds

logger = logging.getLogger(__name__)


def _coerce_usage_int(value: Any) -> int:
    """Coerce provider token counts to non-negative ints."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _normalize_llm_usage(usage: Any) -> dict[str, int] | None:
    """Normalize provider-reported usage metadata without estimating tokens."""
    if usage is None:
        return None
    if not isinstance(usage, dict):
        try:
            usage = dict(usage)
        except (TypeError, ValueError):
            return None

    input_tokens = _coerce_usage_int(usage.get("input_tokens"))
    output_tokens = _coerce_usage_int(usage.get("output_tokens"))
    total_tokens = _coerce_usage_int(usage.get("total_tokens"))
    if total_tokens == 0 and (input_tokens or output_tokens):
        total_tokens = input_tokens + output_tokens
    if not (input_tokens or output_tokens or total_tokens):
        return None
    normalized: dict[str, int] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }
    details = usage.get("input_token_details")
    if isinstance(details, dict):
        if details.get("cache_read") is not None:
            normalized["cache_read_tokens"] = _coerce_usage_int(details["cache_read"])
        creation_keys = ("cache_creation", "ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")
        if any(details.get(key) is not None for key in creation_keys):
            normalized["cache_creation_tokens"] = sum(
                _coerce_usage_int(details.get(key)) for key in creation_keys
            )
    return normalized


def _new_llm_usage_summary(llm: Any) -> dict[str, Any]:
    """Create the run-scoped provider usage accumulator."""
    from src.config.accessor import get_env_config
    cfg = get_env_config()
    provider = cfg.llm.langchain_provider.strip() or "openai"
    model = getattr(llm, "model_name", None) or cfg.llm.langchain_model_name.strip()
    return {
        "provider": provider,
        "model": model,
        "totals": {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "calls": 0,
        },
        "per_iteration": [],
    }


def _record_llm_usage(
    run_dir: Path,
    summary: dict[str, Any],
    usage: Any,
    iteration: int,
) -> dict[str, int] | None:
    """Accumulate and persist one provider-reported usage event."""
    normalized = _normalize_llm_usage(usage)
    if normalized is None:
        return None

    totals = summary.setdefault("totals", {})
    totals["input_tokens"] = int(totals.get("input_tokens") or 0) + normalized["input_tokens"]
    totals["output_tokens"] = int(totals.get("output_tokens") or 0) + normalized["output_tokens"]
    totals["total_tokens"] = int(totals.get("total_tokens") or 0) + normalized["total_tokens"]
    totals["calls"] = int(totals.get("calls") or 0) + 1
    for key in ("cache_read_tokens", "cache_creation_tokens"):
        if key in normalized:
            totals[key] = int(totals.get(key) or 0) + normalized[key]
    summary.setdefault("per_iteration", []).append({"iter": iteration, **normalized})
    summary["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    try:
        path = run_dir / LLM_USAGE_ARTIFACT
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except OSError as exc:
        logger.debug("LLM usage artifact write skipped: %s", exc)

    return normalized


_STRUCTURED_SUMMARY_PROMPT = """\
Summarize this conversation for handoff to a fresh context window.
This summary is the ONLY context available — omitted information is lost.

Use EXACTLY this structure:

## Goal
What the user is trying to accomplish.

## Constraints & Preferences
User-stated requirements: risk tolerance, strategy parameters, asset preferences.

## Progress
### Done
- Completed steps with key results and specific numbers.
### In Progress
- Current work when compression triggered.

## Key Decisions
Choices made and rationale.

## Resolved Questions
Questions already answered — do NOT re-answer these.

## Pending User Asks
Unfinished requests still needing action.

## Relevant Files
File paths, run_dir, signal engines, artifact locations.

## Remaining Work
What still needs to be done (background reference, NOT active instructions).

## Critical Context
Specific numbers, parameters, error messages, configuration values.

## Tools & Patterns
Which tools worked, what failed, effective approaches.

IMPORTANT: This is a handoff — background reference, NOT active instructions.
Preserve ALL specific numbers, file paths, and parameter values.
{focus_section}
Conversation to summarize:
"""

_FOCUS_SECTION = """
FOCUS TOPIC: {topic}
Allocate 60-70% of the summary budget to content related to this topic.
Aggressively compress unrelated content to make room.
"""

_ITERATIVE_UPDATE_PROMPT = """\
Update the existing summary with new conversation turns.

PREVIOUS SUMMARY:
{previous_summary}

NEW TURNS TO INCORPORATE:
{new_turns}

Rules:
- PRESERVE all existing information from the previous summary.
- ADD new progress, decisions, and findings.
- Move "In Progress" items to "Done" when completed.
- Move answered questions to "Resolved Questions".
- Keep the same section structure.
- Do NOT drop any critical context from the previous summary.
{focus_section}"""


# --- Tool-result helpers, moved to src.agent.tool_results (issue #1624) ---
# Re-exported here so existing ``from src.agent.loop import ...`` keeps working.
from src.agent.tool_results import (  # noqa: E402
    _FORCED_TEXT_TOOL_CALL_RE as _FORCED_TEXT_TOOL_CALL_RE,
    _DSML_BAR_TOOL_CALL_RE as _DSML_BAR_TOOL_CALL_RE,
    _TARGET_PATH_RE as _TARGET_PATH_RE,
    _TARGET_ACTION_RE,
    _failure_code,
    _is_tool_success,
    _looks_like_tool_call_syntax,
    _named_target_paths,
    _normalize_tool_run_dir,
    _previously_archived as _previously_archived,
    _archive_backtest_result,
)





class AgentLoop:
    """ReAct Agent core loop.

    Attributes:
        registry: Tool registry.
        llm: ChatLLM client.
        memory: Workspace memory.
        max_iterations: Maximum number of iterations.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        llm: ChatLLM,
        memory: Optional[WorkspaceMemory] = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        max_iterations: int = 50,
        persistent_memory: Optional[Any] = None,
    ) -> None:
        """Initialize AgentLoop.

        Args:
            registry: Tool registry.
            llm: ChatLLM client.
            memory: Workspace memory (created fresh if not provided).
            event_callback: Event callback (event_type, data).
            max_iterations: Maximum number of loop iterations.
            persistent_memory: PersistentMemory for cross-session recall.
        """
        self.registry = registry
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
        self._cancel_event = threading.Event()
        self._previous_summary: str = ""
        self._persistent_memory = persistent_memory
        self._run_iteration: int = 0
        self._has_run = False
        self._grounding: GroundingLedger | None = None
        self._released_fallback = False
        self._released_fallback_reason: str | None = None
        self._written_files: set[str] = set()
        self._stall_reason: str | None = None
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

    def cancel(self) -> None:
        """Cancel the current loop.

        Sets a thread-safe flag polled at every iteration boundary, per LLM
        stream chunk, and between tool batches, so a running turn stops at the
        next cooperative checkpoint instead of only at the next iteration.
        """
        self._cancel_event.set()

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
        try:
            return self._run_bound(user_message, history, session_id)
        finally:
            reset_llm_session_id(token)

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
        # Sent with every request and never compacted, so they count against
        # the window exactly like the system prompt.
        definitions = getattr(self.registry, "get_definitions", None)
        self._tool_schema_tokens = estimate_tokens(definitions()) if callable(definitions) else 0
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
        llm_usage_summary = _new_llm_usage_summary(self.llm)
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
        try:
            while iteration < self.max_iterations:
                if self._cancel_event.is_set():
                    trace.write({"type": "cancelled", "iter": self._run_iteration + 1})
                    logger.info("AgentLoop cancelled by user")
                    break

                iteration += 1
                self._run_iteration += 1
                current_iter = self._run_iteration

                # Inject background task notifications
                bg = get_background_manager()
                notifs = bg.drain_notifications()
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

                # Streaming output + collect thinking text
                thinking_chunks: List[str] = []
                reasoning_chars = 0
                reasoning_tail = ""
                last_reasoning_emit: float | None = None
                buffer_text_output = bool(
                    self._grounding and self._grounding.should_buffer_output
                )

                streamed_chars = 0
                stream_total = 0
                stream_frozen = False

                def _on_text_chunk(delta: str) -> None:
                    nonlocal streamed_chars, stream_total, stream_frozen
                    thinking_chunks.append(delta)
                    stream_total += len(delta)
                    if buffer_text_output or stream_frozen:
                        return
                    # Neither the figures block nor an unchecked measurement streams
                    # (see streamable_length). Only a fence character or a digit
                    # can hold text back, so any other chunk is emitted as it
                    # arrives instead of re-parsing the whole answer.
                    if streamed_chars + len(delta) == stream_total and not any(
                        char in "`~" or char.isdigit() for char in delta
                    ):
                        self._emit("text_delta", {"delta": delta, "iter": current_iter})
                        streamed_chars = stream_total
                        return
                    text = "".join(thinking_chunks)
                    safe = (
                        self._grounding.streamable_length(text)
                        if self._grounding is not None
                        else len(text)
                    )
                    if self._grounding is not None and safe < len(text):
                        # Held at a measurement: nothing after it streams this turn.
                        stream_frozen = self._grounding.measurement_start(text) == safe
                    if safe > streamed_chars:
                        self._emit(
                            "text_delta",
                            {"delta": text[streamed_chars:safe], "iter": current_iter},
                        )
                        streamed_chars = safe

                def _on_reasoning_chunk(delta: str) -> None:
                    # Throttled: long reasoning streams produce hundreds of
                    # chunks; emitting each one floods the SSE replay buffer
                    # and evicts tool_call/text_delta events. The first chunk
                    # of each iteration always emits immediately so the UI
                    # flips to "Reasoning…" without delay.
                    nonlocal reasoning_chars, reasoning_tail, last_reasoning_emit
                    reasoning_chars += len(delta)
                    # Rolling tail rides the already-throttled emit so the UI
                    # can whisper the current thought; a bounded window keeps
                    # replay-buffer pressure flat regardless of trace length.
                    reasoning_tail = (reasoning_tail + delta)[-600:]
                    now = _time.monotonic()
                    if (
                        last_reasoning_emit is not None
                        and now - last_reasoning_emit < _reasoning_delta_min_interval_s()
                    ):
                        return
                    last_reasoning_emit = now
                    reasoning_event = {
                        "iter": current_iter,
                        "chars": reasoning_chars,
                    }
                    if not buffer_text_output:
                        reasoning_event["tail"] = reasoning_tail
                    self._emit("reasoning_delta", reasoning_event)

                # The final iteration is always text-only. A grounding correction
                # whose validator requested no explicit recovery is text-only too:
                # the model must revise from evidence already gathered instead of
                # starting another research/refetch loop merely to reformat a draft.
                is_last_iteration = (iteration == self.max_iterations)
                correction_text_only = grounding_correction_text_only
                tool_defs = (
                    None
                    if is_last_iteration or correction_text_only
                    else self.registry.get_definitions()
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

                try:
                    response = self.llm.stream_chat(
                        messages,
                        tools=tool_defs,
                        on_text_chunk=_on_text_chunk,
                        on_reasoning_chunk=_on_reasoning_chunk,
                        timeout=llm_timeout,
                        idle_timeout_s=llm_timeout,
                        should_cancel=self._cancel_event.is_set,
                    )
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
                    thinking_chunks.clear()
                    streamed_chars = 0
                    stream_total = 0
                    stream_frozen = False
                    reasoning_chars = 0
                    last_reasoning_emit = None
                    # Wait on the cancel event, not time.sleep: the delay now
                    # escalates to the configured cap (30s by default) and a
                    # provider Retry-After can ask for that much on the first
                    # failure. A blocking sleep would make Stop take that long
                    # to be observed; the event returns the moment it is set.
                    self._cancel_event.wait(retry_delay_s)
                    if self._cancel_event.is_set():
                        break
                    response = self.llm.stream_chat(
                        messages,
                        tools=tool_defs,
                        on_text_chunk=_on_text_chunk,
                        on_reasoning_chunk=_on_reasoning_chunk,
                        timeout=llm_timeout,
                        idle_timeout_s=llm_timeout,
                        should_cancel=self._cancel_event.is_set,
                    )
                else:
                    stream_failure_streak = 0

                self._consume_readonly_replay_visibility(messages, trace, current_iter)

                # Cancelled mid-stream: discard this turn's partial response and
                # end the run now, without executing any of its tool calls.
                if self._cancel_event.is_set():
                    break

                # An LLM response arrived - real progress for the stall watchdog.
                self._last_activity_wall = _time.time()

                usage = getattr(response, "usage_metadata", None)
                current_response_model = getattr(response, "response_model", None)
                # `messages` is still exactly what this request sent.
                self._context_meter.observe(
                    usage.get("input_tokens") if isinstance(usage, dict) else None,
                    messages,
                )
                if current_response_model:
                    last_response_model = current_response_model
                usage_delta = _record_llm_usage(
                    run_dir,
                    llm_usage_summary,
                    usage,
                    current_iter,
                )
                if usage_delta:
                    self._emit(
                        "llm_usage",
                        {
                            **usage_delta,
                            "iter": current_iter,
                        },
                    )
                if active_goal_id and session_id:
                    token_delta = int(usage_delta.get("total_tokens") or 0) if usage_delta else 0
                    turn_delta = 0 if goal_turn_accounted else 1
                    if token_delta or turn_delta:
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
                            if snapshot is not None:
                                self._emit(
                                    "goal.updated",
                                    {"goal": snapshot["goal"], "snapshot": snapshot},
                                )
                        except Exception as exc:  # noqa: BLE001
                            logger.debug("Goal usage accounting skipped: %s", exc)

                thinking_text = "".join(thinking_chunks)
                if thinking_text:
                    trace.write_text_entry(
                        {"type": "thinking", "iter": current_iter},
                        field="content",
                        value=thinking_text,
                        offload_kind=f"thinking-{current_iter}",
                    )
                    if not buffer_text_output:
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
                    if streamed_chars:
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

                if forced_grounding_release or not response.has_tool_calls:
                    # At the cap, release the last actual draft through the
                    # existing gate. The forbidden call's text is not an answer.
                    final_content = pending_grounding_draft if forced_grounding_release else response.content or ""
                    syntax_fallback_emitted = False
                    if not final_content:
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
                    # That is not an answer: retry once with a plain-text instruction,
                    # and if no budget remains release a deterministic fallback instead
                    # of leaking the raw markup to the user.
                    if _looks_like_tool_call_syntax(final_content):
                        trace.write(
                            {
                                "type": "tool_call_syntax_in_answer",
                                "iter": current_iter,
                            }
                        )
                        messages.append(
                            {"role": "assistant", "content": final_content}
                        )
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
                        if iteration < self.max_iterations:
                            continue
                        # No budget left: never leak the raw markup. The
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
                    if self._grounding is not None:
                        validation = (
                            self._grounding.revalidate(final_content)
                            if forced_grounding_release
                            else self._grounding.validate_final_answer(final_content)
                        )
                        if not validation.valid:
                            # A draft whose only defect is a missing provenance
                            # word (source / currency / symbol suffix) gets the
                            # word appended, not another multi-minute model round.
                            repaired = self._grounding.repair_provenance(
                                final_content, validation
                            )
                            if repaired is not None:
                                # Non-recording: no model round produced this
                                # text, and ``validation_count`` is the
                                # rejected-draft number the user is shown.
                                recheck = self._grounding.revalidate(repaired)
                                if recheck.valid:
                                    trace.write(
                                        {
                                            "type": "answer_repaired",
                                            "iter": current_iter,
                                            "issues": validation.issues,
                                        }
                                    )
                                    react_trace.append(
                                        {"type": "answer_repaired", "issues": validation.issues}
                                    )
                                    final_content = repaired
                                    validation = recheck
                        if validation.valid:
                            # The figures block is the model's declaration to
                            # the gate, not answer text.
                            final_content = validation.released_text
                        if not validation.valid:
                            if not forced_grounding_release:
                                trace.write_text_entry(
                                    {
                                        "type": "answer_rejected",
                                        "iter": current_iter,
                                        "issues": validation.issues,
                                    },
                                    field="content",
                                    value=final_content,
                                    offload_kind=f"answer-rejected-{current_iter}",
                                )
                                if not buffer_text_output and streamed_chars:
                                    # The stream showed this draft up to its first unchecked
                                    # number; the next draft or the released answer replaces it.
                                    self._emit(
                                        "stream_reset",
                                        {"iter": current_iter, "reason": "grounding_rejected"},
                                    )
                                react_trace.append(
                                    {
                                        "type": "answer_rejected",
                                        "issues": validation.issues,
                                    }
                                )
                                messages.append(
                                    {"role": "assistant", "content": final_content}
                                )
                            recovery = self._grounding.recovery_action(validation)
                            if not forced_grounding_release and recovery is not None and iteration < self.max_iterations:
                                # Explicit bounded recovery is the one case where
                                # the next turn is allowed to research again.
                                grounding_correction_text_only = False
                                self._grounding.record_recovery(recovery)
                                trace.write(
                                    {
                                        "type": "grounding_recovery",
                                        "iter": current_iter,
                                        "action": recovery,
                                    }
                                )
                                react_trace.append(
                                    {"type": "grounding_recovery", "action": recovery}
                                )
                                messages.append(
                                    {
                                        "role": "user",
                                        "content": f"<system>{self._grounding.recovery_prompt(recovery, validation)}</system>",
                                    }
                                )
                                self._emit(
                                    "grounding_status",
                                    {
                                        "stage": "revising",
                                        "round": self._grounding.validation_count,
                                        "issues": len(validation.issues),
                                    },
                                )
                                final_content = ""
                                continue
                            if not forced_grounding_release:
                                messages.append(
                                    {
                                        "role": "user",
                                        "content": f"<system>{self._grounding.correction_prompt(validation)}</system>",
                                    }
                                )
                            rejected_draft = final_content
                            pending_grounding_draft = rejected_draft
                            final_content = ""
                            # The budget counts drafts rejected on this
                            # correction path; the last one is released with
                            # its figures cut. A draft that triggered bounded
                            # recovery is not counted (it re-fetches evidence
                            # rather than rewording), so a run that had to
                            # resolve its symbol first still gets a corrected
                            # draft.
                            if not forced_grounding_release:
                                grounding_revisions += 1
                            if (
                                not forced_grounding_release
                                and iteration < self.max_iterations
                                and grounding_revisions < MAX_GROUNDING_REVISIONS
                            ):
                                grounding_correction_text_only = True
                                self._emit(
                                    "grounding_status",
                                    {
                                        "stage": "revising",
                                        "round": self._grounding.validation_count,
                                        "issues": len(validation.issues),
                                    },
                                )
                                continue
                            # Out of revisions. The last draft is still the
                            # analysis the user waited minutes for; release it
                            # with the rejected figures cut out and re-checked
                            # by the same gate. The canned refusal is only for
                            # what cannot be cut: an identity finding, a run
                            # that never observed a price, or a cut that still
                            # fails validation.
                            rejected_drafts = self._grounding.validation_count
                            released = self._grounding.redacted_release(
                                rejected_draft, validation
                            )
                            if released is not None:
                                trace.write(
                                    {
                                        "type": "answer_released_redacted",
                                        "iter": current_iter,
                                        "issues": validation.issues,
                                    }
                                )
                                react_trace.append(
                                    {
                                        "type": "answer_released_redacted",
                                        "issues": validation.issues,
                                    }
                                )
                                final_content = released
                                self._emit(
                                    "grounding_status",
                                    {
                                        "stage": "released_redacted",
                                        "removed": self._grounding.figures_removed,
                                    },
                                )
                                self._released_fallback_reason = (
                                    "final answer released with unverified figures "
                                    f"redacted after {rejected_drafts} rejected drafts"
                                )
                            else:
                                final_content = self._grounding.safe_fallback()
                                # Captured HERE, beside the redacted branch's
                                # own count. Left unset, the reason was built
                                # lazily at the end of the run from a
                                # ``validation_count`` the release path's
                                # rechecks had already moved.
                                self._released_fallback_reason = (
                                    "final answer degraded to the deterministic "
                                    f"fallback after {rejected_drafts} rejected "
                                    "drafts could not be corrected within the "
                                    "iteration budget"
                                )
                            self._released_fallback = True
                            self._emit(
                                "text_delta",
                                {"delta": final_content, "iter": current_iter},
                            )
                        elif buffer_text_output and not syntax_fallback_emitted:
                            self._emit(
                                "text_delta",
                                {"delta": final_content, "iter": current_iter},
                            )
                        elif not self._released_fallback and not syntax_fallback_emitted:
                            # Flush a held-back last line that never became a
                            # figures fence; a stripped block leaves nothing.
                            shown = "".join(thinking_chunks)[:streamed_chars]
                            if not final_content.startswith(shown):
                                # Stripping the block also trims the blank lines
                                # the stream already showed before its fence.
                                shown = shown.rstrip()
                            if final_content.startswith(shown) and len(final_content) > len(shown):
                                self._emit(
                                    "text_delta",
                                    {"delta": final_content[len(shown):], "iter": current_iter},
                                )
                    # The correction has ended. A goal continuation is a new
                    # research turn and must regain its normal tool access.
                    grounding_correction_text_only = False
                    pending_grounding_draft = ""
                    should_continue_goal = False
                    continuation_snapshot = None
                    _max_cont = _goal_max_continuations()
                    if not forced_grounding_release and active_goal_id and session_id and _max_cont > 0:
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

                if not buffer_text_output and self._grounding is not None:
                    # The turn is over, so a held-back last line is complete: it is
                    # shown unless it opens a figures block.
                    turn_text = "".join(thinking_chunks)
                    safe = min(len(turn_text), self._grounding.streamable_length(turn_text + "\n"))
                    if safe > streamed_chars:
                        self._emit(
                            "text_delta",
                            {"delta": turn_text[streamed_chars:safe], "iter": current_iter},
                        )
                        streamed_chars = safe
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
        final_reason: str | None = None
        if self._stall_reason is not None:
            # The stall watchdog already wrote the failed state; keep this
            # run's terminal status honest instead of overwriting it.
            final_reason = self._stall_reason
            final_status = "failed"
        elif self._cancel_event.is_set():
            final_reason = "cancelled by user"
            state_store.mark_cancelled(run_dir, final_reason)
            final_status = "cancelled"
        elif no_progress_reason is not None:
            final_reason = no_progress_reason
            state_store.mark_failure(run_dir, final_reason)
            final_status = "failed"
        elif content_filter_circuit_breaker:
            final_reason = (
                f"content_filter_circuit_breaker: "
                f"{MAX_CONSECUTIVE_CONTENT_FILTER_SKIPS} consecutive LLM "
                "responses were blocked by content moderation"
            )
            state_store.mark_failure(run_dir, final_reason)
            final_status = "failed"
        elif (run_dir / "artifacts" / "metrics.csv").exists() or final_content:
            state_store.mark_success(run_dir)
            final_status = "success"
            if self._released_fallback:
                final_reason = self._released_fallback_reason or (
                    "final answer degraded to the deterministic fallback after "
                    f"{self._grounding.validation_count if self._grounding else 0} "
                    "rejected drafts could not be corrected within the iteration budget"
                )
            elif not self._released_fallback:
                pending_directive = self._pending_write_directive(
                    user_message, run_started_wall
                )
                if pending_directive:
                    final_reason = (
                        "run ended without writing the task target file(s): "
                        + pending_directive
                    )
                    self._released_fallback = True
        elif empty_model_response_iter is not None:
            provider = self._llm_runtime.provider
            model = self._llm_runtime.configured_model or "(unset)"
            final_reason = (
                "empty_model_response: "
                f"provider={provider} model={model} iteration {empty_model_response_iter} "
                "returned no content and no tool calls"
            )
            state_store.mark_failure(run_dir, final_reason)
            final_status = "failed"
        else:
            final_reason = (
                f"reached max iterations ({self.max_iterations}) without final answer"
            )
            state_store.mark_failure(run_dir, final_reason)
            final_status = "failed"

        end_event: dict[str, Any] = {
            "type": "end",
            "iter": self._run_iteration,
            "status": final_status,
            "iterations": iteration,
        }
        if self._released_fallback:
            end_event["degraded"] = True
        if final_reason is not None:
            end_event["reason"] = final_reason
        trace.write(end_event)
        trace.close()

        result: dict[str, Any] = {
            "status": final_status,
            "run_dir": str(run_dir),
            "run_id": run_dir.name,
            "content": final_content,
            "react_trace": react_trace,
            "iterations": iteration,
            "max_iterations": self.max_iterations,
        }
        if self._released_fallback:
            result["degraded"] = True
        configured_model = self._llm_runtime.configured_model
        result.update(
            {
                "provider": self._llm_runtime.provider,
                "configured_model": configured_model,
                "model": last_response_model or configured_model,
                "model_source": "provider_response" if last_response_model else "configured",
                "reasoning_effort": self._llm_runtime.reasoning_effort,
            }
        )
        if final_reason is not None:
            result["reason"] = final_reason

        self._run_done.set()

        cf_warnings = compute_content_filter_warnings(
            content_filter_count, max(1, iteration),
        )
        if cf_warnings:
            result["content_filter_warnings"] = cf_warnings

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

    # -- Tool execution with read/write batching --------------------------------

    def _process_tool_calls(
        self,
        tool_calls: list,
        context: ContextBuilder,
        messages: list,
        trace: TraceWriter,
        react_trace: list,
        iteration: int,
    ) -> tuple[bool, str]:
        """Pre-process tool calls: handle compact, filter duplicates, batch execute.

        Args:
            tool_calls: Raw tool calls from LLM response.
            context: ContextBuilder for formatting messages.
            messages: Conversation messages (appended in place).
            trace: TraceWriter.
            react_trace: React trace list.
            iteration: Current iteration number.

        Returns:
            Tuple of (compact_requested, focus_topic).
        """
        compact_requested = False
        focus_topic = ""
        execution_plan: list[tuple[Any, str | None]] = []
        batch_authorized_symbols = (
            set(self._grounding.authorized_symbols)
            if self._grounding is not None
            else set()
        )
        batch_identity_status = (
            self._grounding.identity_status
            if self._grounding is not None
            else "not_required"
        )

        # Cancelled before this turn's tools ran — skip execution entirely.
        if self._cancel_event.is_set():
            return compact_requested, focus_topic

        for tc in tool_calls:
            # Layer 4: compact tool — mark then defer execution
            if tc.name == "compact":
                self._tool_progress.note("compact", "compact")
                self._emit(
                    "tool_call",
                    {"tool": "compact", "arguments": {}, "iter": iteration, "call_id": tc.id},
                )
                budget = None if _override("TOKEN_THRESHOLD") is not None else self._context_budget(messages)
                tokens = self._prompt_tokens(messages) if budget is not None else 0
                if budget is not None and tokens <= budget.micro_at:
                    # Summarising a prompt this small only destroys evidence the
                    # model will then fetch again: decline, and say why.
                    declined = json.dumps({
                        "status": "ok",
                        "skipped": True,
                        "message": (
                            f"Compaction not needed: the prompt is {tokens} tokens, "
                            f"under the {budget.micro_at}-token threshold. Earlier "
                            "tool results are still in context; keep using them."
                        ),
                    })
                    messages.append(context.format_tool_result(tc.id, "compact", declined))
                    trace.write({"type": "compact_declined", "iter": iteration, "prompt_tokens": tokens})
                else:
                    compact_requested = True
                    focus_topic = tc.arguments.get("focus_topic", "")
                    messages.append(context.format_tool_result(tc.id, "compact", '{"status":"ok","message":"Compressing..."}'))
                    trace.write({"type": "compact_requested", "iter": iteration})
                self._emit(
                    "tool_result",
                    {"tool": "compact", "status": "ok", "elapsed_ms": 0, "call_id": tc.id},
                )
                continue

            tool_def = self.registry.get(tc.name)
            is_repeatable = tool_def.repeatable if tool_def else False
            # A None key means the arguments could not be canonicalised. The
            # deterministic cache treats that as 'never cache'; the blocking
            # gate must likewise treat it as 'never block', otherwise every
            # un-serialisable call would collapse into a single identity and
            # the second one would be skipped without ever running.
            dedup_key = self._identical_call_key(tc.name, tc.arguments)
            if dedup_key is not None and self._tool_progress.is_blocked(dedup_key):
                failed_result = json.dumps(
                    {
                        "status": "error",
                        "skipped": True,
                        "reason": "This exact call already failed repeatedly in this run. Change strategy or ask the user for help.",
                    }
                )
                self._record_blocked_tool_call(
                    tc,
                    failed_result,
                    context,
                    messages,
                    trace,
                    react_trace,
                    iteration,
                )
                continue
            if self._grounding is not None:
                authorization = self._grounding.authorize_tool_call(
                    tc.name,
                    tc.arguments,
                    batch_authorized_symbols=batch_authorized_symbols,
                    call_id=tc.id,
                    batch_identity_status=batch_identity_status,
                )
                if not authorization.allowed:
                    execution_plan.append(
                        (
                            tc,
                            authorization.error_payload(
                                tc.name,
                                self._grounding.identity_summary(),
                            ),
                        )
                    )
                    continue

            # A successful readonly call whose visible result was removed by
            # micro/auto-compaction can be replayed from this run's memory. This
            # extends the existing deterministic-cache pattern without declaring
            # mutable web resources deterministic. Fresh/no-cache calls bypass
            # this path, while repeatable calls must explicitly opt in.
            if (
                dedup_key is not None
                and dedup_key in self._readonly_replay_ready
                and self._readonly_replay_recoveries < MAX_READONLY_REPLAY_RECOVERIES
                and self._readonly_replay_allowed(tool_def, tc.arguments)
                and dedup_key in self._readonly_replay_cache
            ):
                cached = self._readonly_replay_cache[dedup_key]
                restored = _replay_context_result(cached)
                messages.append(
                    context.format_tool_result(
                        tc.id, tc.name, truncate_tool_result(restored)
                    )
                )
                self._readonly_replay_visibility_pending.add(tc.id)
                self._successful_call_keys[tc.id] = dedup_key
                self._called_ok.add(dedup_key)
                self._readonly_replay_ready.discard(dedup_key)
                self._readonly_replay_recoveries += 1
                # A repeatable tool would otherwise re-fetch on the very next
                # identical call; the restored payload is visible now, so that
                # call is refused until compaction removes it again.
                if getattr(tool_def, "repeatable", False):
                    self._readonly_replay_protected.add(dedup_key)
                # Restoring data that compaction removed is forward progress for
                # the working context, but not a new external observation.
                self._tool_progress.mark_context_restored()
                trace.write({
                    "type": "tool_result_replayed",
                    "iter": iteration,
                    "tool": tc.name,
                    "call_id": tc.id,
                    "recovery_count": self._readonly_replay_recoveries,
                    "recovery_limit": MAX_READONLY_REPLAY_RECOVERIES,
                })
                react_trace.append({"type": "tool_result_replayed", "tool": tc.name})
                self._tool_progress.note("replayed", tc.name)
                self._emit(
                    "tool_result",
                    {
                        "tool": tc.name,
                        "status": "ok",
                        "elapsed_ms": 0,
                        "preview": redact_tool_result(cached)[:200],
                        "call_id": tc.id,
                        "cached": True,
                        "replayed": True,
                    },
                )
                continue

            if (
                dedup_key is not None
                and dedup_key in self._called_ok
                and (
                    not is_repeatable
                    or dedup_key in self._readonly_replay_protected
                )
            ):
                logger.warning(f"Blocked duplicate call: {tc.name} (already succeeded)")
                replay_restored = dedup_key in self._readonly_replay_protected
                reason = (
                    f"{tc.name} was just restored from the run-scoped replay cache after "
                    "compaction. The payload is already visible in context; use that "
                    "result and continue the analysis instead of requesting the same "
                    "call again."
                    if replay_restored
                    else f"{tc.name} already completed successfully. Use the previous result."
                )
                skip_msg = json.dumps({"skipped": True, "reason": reason})
                messages.append(context.format_tool_result(tc.id, tc.name, skip_msg))
                trace.write({"type": "tool_skipped", "iter": iteration, "tool": tc.name})
                self._tool_progress.note("skipped", tc.name)
                react_trace.append({"type": "tool_skipped", "tool": tc.name})
                continue

            # Deterministic tools (e.g. financial_rigor calc) return the same
            # result for the same args. Checked AFTER authorization above so a
            # cached repeat can never bypass the identity gate. After auto-compact cleared earlier
            # tool outputs, the model used to re-run identical expressions
            # 5-9x each (2026-08-20 INTC run) to re-verify numbers it could
            # no longer see. Serve an identical prior call from cache instead.
            if tool_def is not None and getattr(tool_def, "deterministic", False):
                cache_key = self._identical_call_key(tc.name, tc.arguments)
                if cache_key is not None and cache_key in self._called_identical:
                    cached = self._called_identical[cache_key]
                    messages.append(context.format_tool_result(tc.id, tc.name, cached))
                    self._successful_call_keys[tc.id] = cache_key
                    self._called_ok.add(cache_key)
                    trace.write({
                        "type": "tool_result_cached",
                        "iter": iteration,
                        "tool": tc.name,
                        "call_id": tc.id,
                    })
                    react_trace.append({"type": "tool_result_cached", "tool": tc.name})
                    self._tool_progress.note("cached", tc.name)
                    self._emit(
                        "tool_result",
                        {
                            "tool": tc.name,
                            "status": "ok",
                            "elapsed_ms": 0,
                            "preview": cached[:200],
                            "call_id": tc.id,
                            "cached": True,
                        },
                    )
                    continue

            execution_plan.append((tc, None))

        if not execution_plan:
            return compact_requested, focus_topic

        # Preserve provider tool-result ordering. A synthetic blocked result
        # acts as a batch boundary, while adjacent authorized calls retain the
        # existing readonly-parallel/write-serial scheduler.
        authorized_segment: list[Any] = []

        def flush_authorized_segment() -> None:
            if not authorized_segment:
                return
            if len(authorized_segment) == 1:
                self._execute_single(
                    authorized_segment[0],
                    context,
                    messages,
                    trace,
                    react_trace,
                    iteration,
                )
            else:
                self._batch_execute(
                    authorized_segment,
                    context,
                    messages,
                    trace,
                    react_trace,
                    iteration,
                )
            authorized_segment.clear()

        for tc, blocked_result in execution_plan:
            if blocked_result is None:
                authorized_segment.append(tc)
                continue
            flush_authorized_segment()
            self._record_blocked_tool_call(
                tc,
                blocked_result,
                context,
                messages,
                trace,
                react_trace,
                iteration,
            )
        flush_authorized_segment()

        return compact_requested, focus_topic

    def _record_blocked_tool_call(
        self,
        tc: Any,
        result: str,
        context: ContextBuilder,
        messages: list,
        trace: TraceWriter,
        react_trace: list,
        iteration: int,
    ) -> None:
        """Record a blocked call without invoking its implementation.

        Args:
            tc: Provider tool-call object.
            result: Structured identity-gate error payload.
            context: Context builder.
            messages: Conversation messages.
            trace: Persistent trace writer.
            react_trace: Compact returned trace.
            iteration: Current iteration.
        """
        self._tool_progress.note("blocked", tc.name, _failure_code(result))
        args = _normalize_tool_run_dir(tc.arguments, self.memory.run_dir)
        redacted_args = redact_payload(args)
        event_args = {key: str(value)[:200] for key, value in redacted_args.items()}
        self._emit(
            "tool_call",
            {
                "tool": tc.name,
                "arguments": event_args,
                "iter": iteration,
                "call_id": tc.id,
                "blocked": True,
            },
        )
        trace.write(
            {
                "type": "tool_call",
                "iter": iteration,
                "tool": tc.name,
                "call_id": tc.id,
                "args": redacted_args,
                "blocked": True,
            }
        )
        self._finalize_tool_result(
            tc,
            result,
            0,
            context,
            messages,
            trace,
            react_trace,
            iteration,
            update_memory=False,
        )

    def _batch_execute(
        self,
        tool_calls: list,
        context: ContextBuilder,
        messages: list,
        trace: TraceWriter,
        react_trace: list,
        iteration: int,
    ) -> None:
        """Execute tools with read/write batching.

        Consecutive readonly tools run in parallel via ThreadPoolExecutor.
        Write tools run serially between readonly batches.

        Args:
            tool_calls: Tool calls to execute.
            context: ContextBuilder.
            messages: Conversation messages.
            trace: TraceWriter.
            react_trace: React trace list.
            iteration: Current iteration.
        """
        # Split into batches: consecutive readonly → parallel, write → serial
        batches: list[tuple[str, list]] = []
        current_ro: list = []

        for tc in tool_calls:
            tool_def = self.registry.get(tc.name)
            if tool_def and tool_def.is_readonly:
                current_ro.append(tc)
            else:
                if current_ro:
                    batches.append(("parallel", current_ro))
                    current_ro = []
                batches.append(("serial", [tc]))
        if current_ro:
            batches.append(("parallel", current_ro))

        for mode, batch in batches:
            # Stop launching further tool batches once cancelled — the current
            # batch (if any) finishes, but no new work starts.
            if self._cancel_event.is_set():
                break
            if mode == "parallel" and len(batch) > 1:
                self._execute_parallel(batch, context, messages, trace, react_trace, iteration)
            else:
                for tc in batch:
                    self._execute_single(tc, context, messages, trace, react_trace, iteration)

    def _execute_parallel(
        self,
        tool_calls: list,
        context: ContextBuilder,
        messages: list,
        trace: TraceWriter,
        react_trace: list,
        iteration: int,
    ) -> None:
        """Execute readonly tools in parallel using threads.

        Args:
            tool_calls: Readonly tool calls to execute in parallel.
            context: ContextBuilder.
            messages: Conversation messages.
            trace: TraceWriter.
            react_trace: React trace list.
            iteration: Current iteration.
        """
        # Prepare args + emit events
        runnable: list[tuple] = []
        for tc in tool_calls:
            args = _normalize_tool_run_dir(tc.arguments, self.memory.run_dir)
            redacted_args = redact_payload(args)
            event_args = {k: str(v)[:200] for k, v in redacted_args.items()}
            self._emit(
                "tool_call",
                {
                    "tool": tc.name,
                    "arguments": event_args,
                    "iter": iteration,
                    "call_id": tc.id,
                },
            )
            trace.write({"type": "tool_call", "iter": iteration, "tool": tc.name, "call_id": tc.id, "args": redacted_args})
            runnable.append((tc, args))

        # Execute in parallel — each worker gets its own heartbeat + progress emitter.
        def _run(tc_args: tuple) -> tuple:
            tc, args = tc_args
            result, elapsed_ms = self._invoke_tool(tc.name, args, call_id=tc.id)
            return tc, result, elapsed_ms

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(runnable), 8)) as pool:
            futures = [pool.submit(_run, item) for item in runnable]
            results = []
            for i, f in enumerate(futures):
                try:
                    results.append(f.result())
                except Exception as exc:
                    tc = runnable[i][0]
                    results.append((tc, json.dumps({"status": "error", "error": str(exc)}), 0))

        # Process results in order
        for tc, result, elapsed_ms in results:
            self._finalize_tool_result(tc, result, elapsed_ms, context, messages, trace, react_trace, iteration)

    def _execute_single(
        self,
        tc: Any,
        context: ContextBuilder,
        messages: list,
        trace: TraceWriter,
        react_trace: list,
        iteration: int,
    ) -> None:
        """Execute a single tool call.

        Args:
            tc: Tool call object.
            context: ContextBuilder.
            messages: Conversation messages.
            trace: TraceWriter.
            react_trace: React trace list.
            iteration: Current iteration.
        """
        args = _normalize_tool_run_dir(tc.arguments, self.memory.run_dir)

        redacted_args = redact_payload(args)
        event_args = {k: str(v)[:200] for k, v in redacted_args.items()}
        self._emit(
            "tool_call",
            {
                "tool": tc.name,
                "arguments": event_args,
                "iter": iteration,
                "call_id": tc.id,
            },
        )
        trace.write({"type": "tool_call", "iter": iteration, "tool": tc.name, "call_id": tc.id, "args": redacted_args})
        logger.info(f"Tool call: {tc.name}({list(args.keys())})")

        result, elapsed_ms = self._invoke_tool(tc.name, args, call_id=tc.id)

        self._finalize_tool_result(tc, result, elapsed_ms, context, messages, trace, react_trace, iteration)

    def _invoke_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        *,
        call_id: str,
    ) -> tuple[str, int]:
        """Execute a tool with heartbeat + structured progress emission.

        Installs a thread-local progress emitter so the tool may call
        ``emit_progress()`` without taking a callback parameter, and runs a
        background heartbeat timer that ticks every ``_heartbeat_interval_s()``
        seconds. Both event streams are forwarded through ``self._emit`` and
        therefore land in the same SSE bus and CLI dashboard as normal
        tool events.

        Args:
            tool_name: Tool name to execute.
            args: Tool arguments dict.
            call_id: Stable identity of this tool invocation.

        Returns:
            Tuple of (result_str, elapsed_ms).
        """
        readonly = self._is_tool_readonly(tool_name)
        timed_out = threading.Event()

        def _on_progress(event: ProgressEvent) -> None:
            if timed_out.is_set():
                return
            payload = event.to_dict()
            payload["tool"] = tool_name
            payload["call_id"] = call_id
            self._emit("tool_progress", payload)

        def _on_heartbeat(payload: Dict[str, Any]) -> None:
            if timed_out.is_set():
                return
            payload["call_id"] = call_id
            self._emit("tool_heartbeat", payload)

        t0 = _time.perf_counter()
        _tool_timeout = _tool_timeout_seconds()
        timeout = _tool_timeout if _tool_timeout > 0 else None
        timeout_label = _format_timeout(timeout) if timeout is not None else ""

        def _elapsed_ms() -> int:
            """Return milliseconds elapsed since tool start.

            Returns:
                Elapsed wall-clock time in milliseconds.
            """
            return int((_time.perf_counter() - t0) * 1000)

        def _heartbeat_timer() -> HeartbeatTimer:
            """Build the per-invocation heartbeat timer.

            Returns:
                HeartbeatTimer wired to this invocation's heartbeat emitter.
            """
            return HeartbeatTimer(
                tool_name=tool_name,
                interval=_heartbeat_interval_s(),
                emit=_on_heartbeat,
            )

        def _emit_timeout_progress(stage: str, message: str, **extra: Any) -> int:
            """Emit a timeout-related tool_progress event.

            Args:
                stage: Progress stage label ("timeout" or "timeout_warning").
                message: Human-readable timeout message.
                **extra: Additional payload fields.

            Returns:
                Elapsed milliseconds at emission time.
            """
            elapsed_ms = _elapsed_ms()
            payload: Dict[str, Any] = {
                "tool": tool_name,
                "call_id": call_id,
                "stage": stage,
                "message": message,
                "elapsed_s": round(elapsed_ms / 1000, 2),
            }
            payload.update(extra)
            self._emit("tool_progress", payload)
            return elapsed_ms

        if not readonly:
            # Write tools are never killed: a watchdog warns once past the
            # timeout, then the result is awaited to completion.
            finished = threading.Event()

            def _warn_if_stale() -> None:
                if timeout is None or finished.wait(timeout):
                    return
                _emit_timeout_progress(
                    "timeout_warning",
                    (
                        f"Write tool exceeded {timeout_label} timeout; "
                        "waiting for completion because it cannot be safely cancelled"
                    ),
                    readonly=False,
                )

            watchdog = threading.Thread(
                target=_warn_if_stale,
                name=f"tool-watchdog-{tool_name}",
                daemon=True,
            )
            watchdog.start()
            _set_emitter(_on_progress)
            try:
                with _heartbeat_timer():
                    result = self.registry.execute(tool_name, args)
            finally:
                finished.set()
                _set_emitter(None)
            return result or "", _elapsed_ms()

        # Readonly tools run in a worker thread so a hung tool becomes a
        # bounded error: late results are discarded and the emitters are
        # suppressed via the timed_out event.
        result_queue: queue.Queue[tuple[str | None, BaseException | None]] = queue.Queue(maxsize=1)

        def _worker() -> None:
            _set_emitter(_on_progress)
            try:
                result_queue.put((self.registry.execute(tool_name, args), None))
            except BaseException as exc:  # noqa: BLE001 - propagate through caller thread
                result_queue.put((None, exc))
            finally:
                _set_emitter(None)

        worker = threading.Thread(
            target=_worker,
            name=f"tool-{tool_name}",
            daemon=True,
        )
        worker.start()
        with _heartbeat_timer():
            try:
                result, exc = result_queue.get(timeout=timeout)
            except queue.Empty:
                timed_out.set()
                elapsed_ms = _emit_timeout_progress(
                    "timeout", f"Tool exceeded {timeout_label} timeout"
                )
                return (
                    json.dumps(
                        {
                            "status": "error",
                            "error_code": "tool_timeout",
                            "tool": tool_name,
                            "timeout_seconds": timeout,
                            "message": f"Tool exceeded {timeout_label} timeout",
                        },
                        ensure_ascii=False,
                    ),
                    elapsed_ms,
                )
        if exc is not None:
            raise exc
        return result or "", _elapsed_ms()

    def _is_tool_readonly(self, tool_name: str) -> bool:
        """Return whether a tool is known to be side-effect free."""
        get_tool = getattr(self.registry, "get", None)
        if not callable(get_tool):
            return False
        try:
            tool_def = get_tool(tool_name)
        except Exception:  # noqa: BLE001 - unknown classification is not readonly
            return False
        return bool(tool_def and getattr(tool_def, "is_readonly", False))

    def _readonly_replay_allowed(self, tool_def: Any, arguments: Mapping[str, Any]) -> bool:
        """Whether an exact readonly result may be restored after compaction.

        This is intentionally narrower than ``is_readonly``: deterministic
        calls already use the existing cache, and ``no_cache=True`` explicitly
        requests a fresh read. Repeatable calls require explicit opt-in because
        they may otherwise be intentionally refreshed.
        """
        if tool_def is None or not getattr(tool_def, "is_readonly", False):
            return False
        if getattr(tool_def, "deterministic", False):
            return False
        try:
            if bool((arguments or {}).get("no_cache")):
                return False
        except AttributeError:
            return False
        if getattr(tool_def, "repeatable", False):
            return bool(getattr(tool_def, "replay_after_compaction", False))
        return True

    def _record_written_target(self, arguments: Mapping[str, Any]) -> None:
        """Remember a file written by write_file/edit_file for completion checks."""
        raw = arguments.get("path") or arguments.get("file_path")
        if not raw:
            return
        p = Path(str(raw))
        if not p.is_absolute() and self.memory.run_dir:
            p = Path(self.memory.run_dir) / p
        try:
            resolved = p.resolve()
            self._written_files.add(str(resolved).casefold())
        except (OSError, ValueError):
            resolved = p
            self._written_files.add(str(p).casefold())

        if not self.memory.run_dir:
            return
        run_root = Path(self.memory.run_dir).resolve()
        try:
            relative = resolved.relative_to(run_root).as_posix()
        except ValueError:
            return
        if relative not in {"config.json", "code/signal_engine.py"}:
            return

        metadata_path = run_root / "strategy_provenance.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            files = {}
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "Could not read strategy model provenance; update skipped: %s",
                exc,
            )
            return
        else:
            if not isinstance(metadata, dict):
                logger.warning("Invalid strategy model provenance; update skipped.")
                return
            files = metadata.get("files", {})
            if not isinstance(files, dict):
                logger.warning("Invalid strategy model provenance files; update skipped.")
                return
        files[relative] = {
            "provider": self._llm_runtime.provider or None,
            "model_id": self._active_model_id or None,
            "model_source": self._active_model_source,
        }
        try:
            metadata_path.write_text(
                json.dumps({"files": files}, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Could not write strategy model provenance: %s", exc)

    def _pending_write_directive(
        self, user_message: str, run_started_wall: float
    ) -> str:
        """Return a directive naming task target files not yet written this run.

        Empty when the message names no .md targets, carries no create/update
        intent, or every named target has been written (directly via
        write_file/edit_file, or by any process whose mtime is newer than the
        run start - which covers the bash workaround).
        """
        if not _TARGET_ACTION_RE.search(user_message or ""):
            return ""
        targets = _named_target_paths(user_message)
        if not targets:
            return ""
        pending: list[str] = []
        # A bare target ("create X.md at the same folder") carries no directory;
        # resolve it against the folders of the absolute targets named in the
        # same message, or the run would never see the file the model wrote to
        # the intended folder and would report a false "not written".
        base_dirs = [p.parent for p in targets if p.parent != Path(".")]
        any_written = False
        for p in targets:
            candidates = [p]
            if not p.is_absolute() and p.parent == Path("."):
                candidates += [d / p.name for d in base_dirs]
            written = False
            for cand in candidates:
                try:
                    key = str(cand.resolve()).casefold()
                except (OSError, ValueError):
                    key = str(cand).casefold()
                if key in self._written_files:
                    written = True
                    break
                if not written:
                    try:
                        if cand.exists() and cand.stat().st_mtime >= run_started_wall:
                            written = True
                            break
                    except OSError:
                        pass
            if written:
                any_written = True
            else:
                pending.append(str(p))
        # If any named target was written this run, the create/update task is
        # addressed; reference files named alongside (e.g. "refer to A, create B")
        # are never "written" and must not trigger the directive.
        if any_written or not pending:
            return ""
        return (
            "[SYSTEM] The following task target file(s) have NOT been written "
            "yet in this run: " + ", ".join(pending) + ". Write them NOW using "
            "write_file/edit_file (or bash for file operations). If your task "
            "was to create or update a file, a plain-text answer without the "
            "file write is a failure."
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

    def _consume_readonly_replay_visibility(
        self, messages: list, trace: TraceWriter, iteration: int
    ) -> None:
        """Release replay leases once a successful model request carried them."""
        visible = {
            msg.get("tool_call_id")
            for msg in messages
            if msg.get("role") == "tool"
            and msg.get("tool_call_id") in self._readonly_replay_visibility_pending
            and not _result_data_gone(msg.get("content"))
        }
        for call_id in sorted(visible):
            self._readonly_replay_visibility_pending.discard(call_id)
            trace.write({"type": "replay_visibility_consumed", "iter": iteration, "call_id": call_id})

    def _readable_success_keys(self, messages: list) -> set[tuple[str, str]]:
        """Identify surviving successful results, not synthetic skip/stub calls."""
        return {
            self._successful_call_keys[msg["tool_call_id"]]
            for msg in messages
            if msg.get("role") == "tool"
            and msg.get("tool_call_id") in self._successful_call_keys
            and not _result_data_gone(msg.get("content"))
        }

    def _unblock_lost_readonly_results(
        self, messages: list, readable_before: set[tuple[str, str]]
    ) -> list[str]:
        """Recover only lost exact queries; context loss cannot replay writes."""
        lost = readable_before - self._readable_success_keys(messages)
        reopened = {
            key for key in lost & self._called_ok if self._is_tool_readonly(key[0])
        }
        self._called_ok.difference_update(reopened)
        # Every lost call reopens, as before replay existed; the replay budget
        # only decides, at call time, whether it is restored or run again.
        self._readonly_replay_protected.difference_update(reopened)
        self._readonly_replay_ready.update(
            key for key in reopened if key in self._readonly_replay_cache
        )
        return sorted({key[0] for key in reopened})

    def _identical_call_key(self, tool_name: str, arguments: Mapping[str, Any]) -> tuple[str, str] | None:
        """Build a stable key identifying a deterministic tool invocation.

        Args:
            tool_name: Tool name.
            arguments: Tool arguments.

        Returns:
            Tuple of (tool_name, canonical JSON of the args) usable as a
            dict key, or None when the args cannot be serialized.
        """
        try:
            normalized = _normalize_tool_run_dir(dict(arguments or {}), self.memory.run_dir)
            canonical = json.dumps(normalized, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001 - un-serializable args are never cached
            return None
        return (tool_name, canonical)

    def _finalize_tool_result(
        self,
        tc: Any,
        result: str,
        elapsed_ms: int,
        context: ContextBuilder,
        messages: list,
        trace: TraceWriter,
        react_trace: list,
        iteration: int,
        *,
        update_memory: bool = True,
    ) -> None:
        """Record a tool result: update memory, append message, write trace, emit event.

        Args:
            tc: Tool call object.
            result: Raw tool result string.
            elapsed_ms: Execution time in milliseconds.
            context: ContextBuilder.
            messages: Conversation messages.
            trace: TraceWriter.
            react_trace: React trace list.
            iteration: Current iteration.
            update_memory: Whether this call reached the tool implementation.
        """
        if update_memory:
            self._update_memory(tc.name)

        # A tool completed - real progress for the stall watchdog.
        self._last_activity_wall = _time.time()

        success = _is_tool_success(result)
        if update_memory:
            self._tool_progress.record(
                tc.name,
                self._identical_call_key(tc.name, tc.arguments),
                result,
                success=success,
                is_readonly=self._is_tool_readonly(tc.name),
            )
        if success:
            recorded_key = self._identical_call_key(tc.name, tc.arguments)
            if recorded_key is not None:
                self._called_ok.add(recorded_key)
                self._successful_call_keys[tc.id] = recorded_key
            if tc.name == "backtest":
                try:
                    _archive_backtest_result(result, self.memory.run_dir, source_call_id=tc.id)
                except OSError as exc:
                    logger.warning("Could not archive backtest output into active run: %s", exc)
            if tc.name in {"write_file", "edit_file"}:
                self._record_written_target(tc.arguments)

        if self._grounding is not None:
            self._grounding.ingest_tool_result(
                tool_name=tc.name,
                arguments=_normalize_tool_run_dir(tc.arguments, self.memory.run_dir),
                result=result,
                call_id=tc.id,
                success=success,
            )
            if tc.name == "search_symbol":
                trace.write(
                    {
                        "type": "identity_state",
                        "iter": iteration,
                        "call_id": tc.id,
                        "identity": self._grounding.identity_summary(),
                    }
                )

        # Cache successful deterministic results so an identical later call is
        # served without re-execution (regression: repeated financial_rigor
        # calcs after compaction, 2026-08-20 INTC run). Readonly results use a
        # separate run-scoped replay cache: it is only consulted after
        # compaction has made that exact result unreadable, and only for tools
        # whose replay policy allows it.
        if success:
            try:
                tool_def = self.registry.get(tc.name)
            except Exception:  # noqa: BLE001
                tool_def = None
            cache_key = self._identical_call_key(tc.name, tc.arguments)
            if tool_def is not None and getattr(tool_def, "deterministic", False):
                if cache_key is not None:
                    self._called_identical[cache_key] = result
            elif (
                cache_key is not None
                and self._readonly_replay_allowed(tool_def, tc.arguments)
            ):
                self._readonly_replay_cache[cache_key] = result
            # Its payload is visible again, so nothing is waiting to be restored.
            self._readonly_replay_ready.discard(cache_key)
            # A write can change what a readonly call reads (a factor file, a
            # config), so no result cached before it may be replayed after it.
            if update_memory and not self._is_tool_readonly(tc.name):
                self._readonly_replay_cache.clear()
                self._readonly_replay_ready.clear()
                self._readonly_replay_protected.clear()

        status = "ok" if success else "error"
        truncated = truncate_tool_result(result)
        messages.append(context.format_tool_result(tc.id, tc.name, truncated))

        # One redaction feeds every subscriber below: the persisted trace
        # record, the react trace, and the SSE preview.
        trace_result = redact_tool_result(result)
        trace.write_tool_result(
            call_id=tc.id,
            result=trace_result,
            tool_name=tc.name,
            status=status,
            elapsed_ms=elapsed_ms,
            iteration=iteration,
        )
        preview = trace_result[:200]
        artifact = None
        if status == "ok" and tc.name in {"write_file", "render_shadow_report"}:
            try:
                payload = json.loads(trace_result)
                from src.tools.report_artifacts import report_path
                report_id = payload.get("report_id", "")
                path = report_path(report_id) if isinstance(report_id, str) else None
                if path is not None:
                    artifact = {"report_id": report_id, "filename": path.name,
                                "download_url": f"/api/reports/{report_id}"}
            except (ValueError, TypeError, AttributeError, OSError):
                pass
        react_trace.append({"type": "tool_call", "tool": tc.name, "result_preview": preview})
        self._emit(
            "tool_result",
            {
                "tool": tc.name,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "preview": preview,
                "call_id": tc.id,
                **({"artifact": artifact} if artifact else {}),
            },
        )

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
        del run_dir
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
                    break
                if _compact_error:
                    logger.warning(
                        "Auto compact LLM call failed (%s); degrading compaction",
                        _compact_error[0],
                    )
                    degraded_compact = True
                    break
                summary_resp = _compact_result[0]
            else:
                summary_resp = self.llm.chat([{"role": "user", "content": prompt}])
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

    def _update_memory(self, tool_name: str) -> None:
        """Update workspace memory counters after tool execution."""
        self.memory.increment(tool_name)


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
