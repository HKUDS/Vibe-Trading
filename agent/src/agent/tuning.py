"""Tuning and configuration helpers for the agent loop."""

import sys
from typing import Optional


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
