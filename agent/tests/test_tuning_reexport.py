"""Contract tests for the tuning helpers extracted from the agent loop."""

import pytest

import src.agent.loop as loop_module
import src.agent.tuning as tuning_module

MOVED_NAMES = (
    "TOKEN_THRESHOLD",
    "_override",
    "_token_threshold",
    "_heartbeat_interval_s",
    "_reasoning_delta_min_interval_s",
    "_stream_retry_delay_s",
    "_stream_retry_max_delay_s",
    "_stream_retry_backoff_s",
    "_tool_timeout_seconds",
    "_llm_timeout_seconds",
    "_goal_max_continuations",
    "_stall_timeout_seconds",
)


@pytest.mark.parametrize("name", MOVED_NAMES)
def test_tuning_helpers_are_reexported_by_loop(name: str) -> None:
    assert getattr(loop_module, name) is getattr(tuning_module, name)


def test_token_threshold_override_must_target_tuning_module(monkeypatch) -> None:
    default = tuning_module._token_threshold()
    monkeypatch.setattr(loop_module, "TOKEN_THRESHOLD", 123)
    assert tuning_module._token_threshold() == default
    monkeypatch.setattr(tuning_module, "TOKEN_THRESHOLD", 321)
    assert tuning_module._token_threshold() == 321
