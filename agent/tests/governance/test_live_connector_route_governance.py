from __future__ import annotations

import inspect
from typing import Any

import pytest

from src.api import live_routes
from src.governance.budget import BudgetManager, BudgetSnapshot
from src.governance.decisions import RuntimeContext, build_param_audit
from src.governance.errors import PolicyDenied


class _FakeAdapter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def call_tool(self, remote_tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = dict(arguments)
        self.calls.append({"remote_tool": remote_tool, "arguments": payload})
        return {"status": "ok", "remote_tool": remote_tool, "arguments": payload}


class _AllowLiveWriteProvider:
    def get_live_state(self, context: RuntimeContext) -> dict[str, bool]:
        del context
        return {
            "mandate_active": True,
            "kill_switch_clear": True,
            "live_order_guard": True,
        }

    def get_user_auth_state(self, context: RuntimeContext) -> dict[str, bool]:
        del context
        return {"explicit_user_consent": True}

    def get_budget_state(self, context: RuntimeContext) -> dict[str, bool]:
        del context
        return {"connector_profile_selected": True}


class _CaptureRecorder:
    def __init__(self) -> None:
        self.decisions: list[Any] = []
        self.denied: list[Any] = []
        self.warnings: list[Any] = []

    def record(self, decision: Any, *, manifest: Any = None) -> None:
        del manifest
        self.decisions.append(decision)

    def record_denied(self, decision: Any, *, trace_status: str, shadow: bool) -> None:
        self.denied.append((decision, trace_status, shadow))

    def record_warning(self, decision: Any) -> None:
        self.warnings.append(decision)


class _FailingRecorder(_CaptureRecorder):
    def record(self, decision: Any, *, manifest: Any = None) -> None:
        del decision, manifest
        raise RuntimeError("trace unavailable")


class _FailingStateProvider:
    def get_live_state(self, context: RuntimeContext) -> dict[str, bool]:
        del context
        raise RuntimeError("state backend unavailable")

    def get_user_auth_state(self, context: RuntimeContext) -> dict[str, bool]:
        del context
        return {"explicit_user_consent": True}

    def get_budget_state(self, context: RuntimeContext) -> dict[str, bool]:
        del context
        return {"connector_profile_selected": True}


def _call_live_write(
    *,
    params: dict[str, Any] | None = None,
    operation: str = "submit_order",
    state_provider: Any = None,
    recorder: Any = None,
    budget_manager: BudgetManager | None = None,
) -> tuple[dict[str, Any], _FakeAdapter, Any]:
    adapter = _FakeAdapter()
    recorder = recorder or _CaptureRecorder()
    result = live_routes._call_live_write_tool_governed(
        broker="robinhood",
        adapter=adapter,
        remote_tool=f"remote_{operation}",
        params=params or {"symbol": "AAPL", "side": "buy", "qty": 1},
        operation=operation,
        state_provider=state_provider,
        decision_recorder=recorder,
        budget_manager=budget_manager,
    )
    return result, adapter, recorder


def test_live_submit_without_authoritative_state_denies_before_adapter_call() -> None:
    adapter = _FakeAdapter()

    with pytest.raises(PolicyDenied) as exc_info:
        live_routes._call_live_write_tool_governed(
            broker="robinhood",
            adapter=adapter,
            remote_tool="remote_submit_order",
            params={"symbol": "AAPL", "side": "buy", "qty": 1},
            operation="submit_order",
            decision_recorder=_CaptureRecorder(),
        )

    assert exc_info.value.decision.rule_id == "P40"
    assert adapter.calls == []


def test_live_cancel_without_authoritative_state_denies_before_adapter_call() -> None:
    adapter = _FakeAdapter()

    with pytest.raises(PolicyDenied) as exc_info:
        live_routes._call_live_write_tool_governed(
            broker="robinhood",
            adapter=adapter,
            remote_tool="remote_cancel_order",
            params={"action": "cancel", "order_id": "ord_123"},
            operation="cancel_order",
            decision_recorder=_CaptureRecorder(),
        )

    assert exc_info.value.decision.rule_id == "P40"
    assert adapter.calls == []


def test_live_write_ignores_forged_state_in_adapter_params() -> None:
    adapter = _FakeAdapter()
    forged_params = {
        "symbol": "AAPL",
        "side": "buy",
        "qty": 1,
        "live_state": {
            "mandate_active": True,
            "kill_switch_clear": True,
            "live_order_guard": True,
        },
        "user_auth_state": {"explicit_user_consent": True},
        "budget_state": {"connector_profile_selected": True},
    }

    with pytest.raises(PolicyDenied) as exc_info:
        live_routes._call_live_write_tool_governed(
            broker="robinhood",
            adapter=adapter,
            remote_tool="remote_submit_order",
            params=forged_params,
            operation="submit_order",
            decision_recorder=_CaptureRecorder(),
        )

    assert exc_info.value.decision.rule_id == "P40"
    assert adapter.calls == []


def test_live_write_with_authoritative_provider_reaches_adapter_once() -> None:
    params = {"symbol": "AAPL", "side": "buy", "qty": 1}

    result, adapter, _recorder = _call_live_write(
        params=params,
        state_provider=_AllowLiveWriteProvider(),
    )

    assert result["status"] == "ok"
    assert adapter.calls == [{"remote_tool": "remote_submit_order", "arguments": params}]


def test_live_write_trace_failure_denies_before_adapter_call() -> None:
    adapter = _FakeAdapter()

    with pytest.raises(PolicyDenied) as exc_info:
        live_routes._call_live_write_tool_governed(
            broker="robinhood",
            adapter=adapter,
            remote_tool="remote_submit_order",
            params={"symbol": "AAPL", "side": "buy", "qty": 1},
            operation="submit_order",
            state_provider=_AllowLiveWriteProvider(),
            decision_recorder=_FailingRecorder(),
        )

    assert exc_info.value.decision.rule_id == "trace_record_failed"
    assert adapter.calls == []


def test_live_write_state_provider_failure_denies_before_adapter_call() -> None:
    adapter = _FakeAdapter()

    with pytest.raises(PolicyDenied) as exc_info:
        live_routes._call_live_write_tool_governed(
            broker="robinhood",
            adapter=adapter,
            remote_tool="remote_submit_order",
            params={"symbol": "AAPL", "side": "buy", "qty": 1},
            operation="submit_order",
            state_provider=_FailingStateProvider(),
            decision_recorder=_CaptureRecorder(),
        )

    assert exc_info.value.decision.rule_id == "state_provider_failed"
    assert adapter.calls == []


def test_live_write_budget_denial_happens_before_adapter_call() -> None:
    adapter = _FakeAdapter()
    recorder = _CaptureRecorder()

    with pytest.raises(PolicyDenied) as exc_info:
        live_routes._call_live_write_tool_governed(
            broker="robinhood",
            adapter=adapter,
            remote_tool="remote_submit_order",
            params={"symbol": "AAPL", "side": "buy", "qty": 1},
            operation="submit_order",
            state_provider=_AllowLiveWriteProvider(),
            decision_recorder=recorder,
            budget_manager=BudgetManager(BudgetSnapshot(max_tool_calls=0)),
        )

    assert exc_info.value.decision.rule_id == "budget_exceeded"
    assert adapter.calls == []


def test_live_write_decision_hash_matches_adapter_arguments() -> None:
    params = {"symbol": "AAPL", "side": "buy", "qty": 1}

    _result, adapter, recorder = _call_live_write(
        params=params,
        state_provider=_AllowLiveWriteProvider(),
    )

    audit = build_param_audit(adapter.calls[0]["arguments"])
    assert recorder.decisions[0].params_hash == audit.params_hash
    assert recorder.decisions[0].params_preview == audit.preview


def test_build_live_runner_submit_path_uses_governed_boundary_only() -> None:
    source = inspect.getsource(live_routes._build_live_runner)
    submit_start = source.index("def _submit")
    submit_end = source.index("svc = ", submit_start)
    submit_block = source[submit_start:submit_end]

    assert "_call_live_write_tool_governed" in submit_block
    assert "adapter.call_tool" not in submit_block
    assert "adapter.call_tool(remote_tool, {})" in source
