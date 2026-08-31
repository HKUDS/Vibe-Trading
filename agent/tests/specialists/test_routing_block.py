"""Routing-block tests: the delegation policy appears in the system prompt
exactly when the delegate tool is registered, and never otherwise."""

from __future__ import annotations

import pytest

from src.specialists.loader import load_specialists, reset_specialists_cache
from src.specialists.routing import specialist_routing_block


@pytest.fixture(autouse=True)
def _fresh_roster():
    reset_specialists_cache()
    yield
    reset_specialists_cache()


class _RegistryWith:
    def get(self, name: str):
        return object() if name == "delegate_to_specialist" else None


class _RegistryWithout:
    def get(self, name: str):
        return None


class _ExplodingRegistry:
    def get(self, name: str):
        raise RuntimeError("boom")


def test_block_present_when_tool_registered() -> None:
    block = specialist_routing_block(_RegistryWith())
    assert block
    assert "delegate_to_specialist" in block
    assert "self-contained brief" in block
    for name in load_specialists():
        assert f"`{name}`" in block


def test_block_absent_when_tool_missing() -> None:
    assert specialist_routing_block(_RegistryWithout()) == ""


def test_block_fails_safe_on_registry_errors() -> None:
    assert specialist_routing_block(_ExplodingRegistry()) == ""
    assert specialist_routing_block(None) == ""


def test_block_absent_when_roster_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.specialists.loader.load_specialists", lambda: {})
    assert specialist_routing_block(_RegistryWith()) == ""
