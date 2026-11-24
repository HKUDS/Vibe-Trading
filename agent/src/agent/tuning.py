"""Tuning and configuration helpers for the agent loop."""

from typing import Optional


# A concrete None lets monkeypatch restore the default compaction path.
TOKEN_THRESHOLD: Optional[int] = None


def _override(name: str):
    """Return a monkeypatched module-level override if present."""
    return globals().get(name)


def _setting(override_name: str, config_name: str, *, nonnegative: bool = False):
    override = _override(override_name)
    if override is not None:
        return max(int(override), 0) if nonnegative else override
    from src.config.accessor import get_env_config

    return getattr(get_env_config().agent_tuning, config_name)


def _token_threshold() -> int:
    return _setting("TOKEN_THRESHOLD", "token_threshold")


def _heartbeat_interval_s() -> float:
    return _setting("HEARTBEAT_INTERVAL_S", "vt_heartbeat_interval_s")


def _reasoning_delta_min_interval_s() -> float:
    return _setting("REASONING_DELTA_MIN_INTERVAL_S", "vt_reasoning_delta_min_interval_s")


def _stream_retry_delay_s() -> float:
    return _setting("STREAM_RETRY_DELAY_S", "vt_stream_retry_delay_s")


def _stream_retry_max_delay_s() -> float:
    return _setting("STREAM_RETRY_MAX_DELAY_S", "vt_stream_retry_max_delay_s")


def _stream_retry_backoff_s(streak: int) -> float:
    """Return the capped exponential delay for the one-based failure streak."""
    ceiling = min(
        _stream_retry_delay_s() * (2 ** min(max(streak, 1) - 1, 62)),
        _stream_retry_max_delay_s(),
    )
    return max(ceiling, 0.0)


def _tool_timeout_seconds() -> float:
    return _setting("TOOL_TIMEOUT_SECONDS", "vibe_trading_tool_timeout_seconds")


def _llm_timeout_seconds() -> float:
    """Return the per-call LLM timeout in seconds (0/negative disables)."""
    return _setting("LLM_TIMEOUT_SECONDS", "vibe_trading_llm_timeout_seconds")


def _goal_max_continuations() -> int:
    return _setting("GOAL_MAX_CONTINUATIONS", "vibe_trading_goal_max_continuations")


def _stall_timeout_seconds() -> float:
    """Return the run-stall watchdog timeout in seconds (0/negative disables)."""
    return _setting("STALL_TIMEOUT_SECONDS", "vibe_trading_run_stall_timeout_seconds")


def _mid_turn_nudge_rounds() -> int:
    """Return the configured no-commentary pacing nudge threshold."""
    return _setting("MID_TURN_NUDGE_ROUNDS", "vibe_trading_mid_turn_nudge_rounds", nonnegative=True)


def _wrap_up_nudge_remaining() -> int:
    """Return the configured number of iterations reserved for a wrap-up nudge."""
    return _setting("WRAP_UP_NUDGE_REMAINING", "vibe_trading_wrap_up_nudge_remaining", nonnegative=True)
