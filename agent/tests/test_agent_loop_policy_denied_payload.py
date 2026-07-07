from __future__ import annotations

import pytest

from src.agent import loop as agent_loop


def test_policy_denied_payload_handles_value_error(monkeypatch) -> None:
    def raise_value_error(_result: str):
        raise ValueError("decoder rejected payload")

    monkeypatch.setattr(agent_loop.json, "loads", raise_value_error)

    assert agent_loop._policy_denied_payload("{bad json}") is None


def test_policy_denied_payload_does_not_swallow_keyboard_interrupt(monkeypatch) -> None:
    def raise_keyboard_interrupt(_result: str):
        raise KeyboardInterrupt

    monkeypatch.setattr(agent_loop.json, "loads", raise_keyboard_interrupt)

    with pytest.raises(KeyboardInterrupt):
        agent_loop._policy_denied_payload("{}")


def test_policy_denied_payload_does_not_swallow_system_exit(monkeypatch) -> None:
    def raise_system_exit(_result: str):
        raise SystemExit(2)

    monkeypatch.setattr(agent_loop.json, "loads", raise_system_exit)

    with pytest.raises(SystemExit):
        agent_loop._policy_denied_payload("{}")
