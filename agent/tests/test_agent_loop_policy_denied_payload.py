"""Agent loop policy-denied payload parsing regressions."""

from __future__ import annotations

import pytest

from src.agent.loop import _is_tool_success


def test_policy_denied_payload_malformed_does_not_allow_execution() -> None:
    malformed_payload = "{status: policy_denied, reason: R5 shell blocked"

    assert _is_tool_success(malformed_payload) is False


def test_policy_denied_payload_parser_does_not_swallow_base_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_keyboard_interrupt(_value: str):  # noqa: ANN001
        raise KeyboardInterrupt

    monkeypatch.setattr("src.agent.loop.json.loads", raise_keyboard_interrupt)

    with pytest.raises(KeyboardInterrupt):
        _is_tool_success('{"status": "ok"}')

