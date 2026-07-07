"""Live connector write-boundary governance tests."""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from src.api import live_routes
from src.governance.runtime import GovernanceState, PolicyDenied


class FakeAdapter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def call_tool(self, remote_tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"remote_tool": remote_tool, "arguments": dict(arguments)})
        return {"status": "ok", "remote_tool": remote_tool, "arguments": dict(arguments)}


class AllowProvider:
    def __init__(self, *, budget_available: bool = True) -> None:
        self.budget_available = budget_available

    def get_state(self, *, context, tool_name: str, params: dict[str, Any]) -> GovernanceState:
        del context, tool_name, params
        return GovernanceState(
            state_authoritative=True,
            live_authorized=True,
            user_authenticated=True,
            budget_available=self.budget_available,
        )


class FailingProvider:
    def get_state(self, *, context, tool_name: str, params: dict[str, Any]) -> GovernanceState:
        del context, tool_name, params
        raise RuntimeError("state backend unavailable")


def test_live_submit_goes_through_governed_pseudotool() -> None:
    adapter = FakeAdapter()
    params = {"symbol": "AAPL", "side": "buy", "quantity": 1}

    result = live_routes._call_live_write_tool_governed(
        broker="robinhood",
        adapter=adapter,
        remote_tool="remote_submit_order",
        params=params,
        operation="submit_order",
        state_provider=AllowProvider(),
    )

    assert result["status"] == "ok"
    assert adapter.calls == [{"remote_tool": "remote_submit_order", "arguments": params}]


def test_live_cancel_goes_through_governed_pseudotool() -> None:
    adapter = FakeAdapter()
    params = {"action": "cancel", "order_id": "ord_1"}

    result = live_routes._call_live_write_tool_governed(
        broker="robinhood",
        adapter=adapter,
        remote_tool="remote_cancel_order",
        params=params,
        operation="cancel_order",
        state_provider=AllowProvider(),
    )

    assert result["status"] == "ok"
    assert adapter.calls == [{"remote_tool": "remote_cancel_order", "arguments": params}]


def test_live_submit_forged_state_denied_before_adapter_call() -> None:
    adapter = FakeAdapter()

    with pytest.raises(PolicyDenied):
        live_routes._call_live_write_tool_governed(
            broker="robinhood",
            adapter=adapter,
            remote_tool="remote_submit_order",
            params={
                "symbol": "AAPL",
                "live_state": {"state_authoritative": True, "live_authorized": True},
                "user_auth_state": {"user_authenticated": True},
                "budget_state": {"budget_available": True},
            },
            operation="submit_order",
        )

    assert adapter.calls == []


def test_live_cancel_provider_failure_denied_before_adapter_call() -> None:
    adapter = FakeAdapter()

    with pytest.raises(PolicyDenied):
        live_routes._call_live_write_tool_governed(
            broker="robinhood",
            adapter=adapter,
            remote_tool="remote_cancel_order",
            params={"action": "cancel", "order_id": "ord_1"},
            operation="cancel_order",
            state_provider=FailingProvider(),
        )

    assert adapter.calls == []


def test_live_budget_exceeded_denied_before_adapter_call() -> None:
    adapter = FakeAdapter()

    with pytest.raises(PolicyDenied):
        live_routes._call_live_write_tool_governed(
            broker="robinhood",
            adapter=adapter,
            remote_tool="remote_submit_order",
            params={"symbol": "AAPL", "notional": 10_000},
            operation="submit_order",
            state_provider=AllowProvider(budget_available=False),
        )

    assert adapter.calls == []


def test_live_readonly_account_positions_orders_do_not_get_write_manifest() -> None:
    source = inspect.getsource(live_routes._build_live_runner)
    read_start = source.index("def _read")
    read_end = source.index("def _submit", read_start)
    read_block = source[read_start:read_end]

    assert "adapter.call_tool(remote_tool, {})" in read_block
    assert "_call_live_write_tool_governed" not in read_block


def test_unknown_broker_still_fails_closed() -> None:
    adapter = FakeAdapter()

    with pytest.raises(PolicyDenied):
        live_routes._call_live_write_tool_governed(
            broker="unknown",
            adapter=adapter,
            remote_tool="remote_submit_order",
            params={"symbol": "AAPL"},
            operation="submit_order",
        )

    assert adapter.calls == []
