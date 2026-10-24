"""trading_orders reads a JSON-string include_executions flag by its value."""

from __future__ import annotations

import json
from typing import Any

import pytest

import src.tools.trading_connector_tool as tool_mod


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    calls: list[bool] = []

    def fake_get_open_orders(_conn: Any, *, include_executions: bool, **_kw: Any) -> dict:
        calls.append(include_executions)
        return {"status": "ok", "orders": []}

    monkeypatch.setattr(tool_mod, "_connection", lambda name: name)
    monkeypatch.setattr(tool_mod, "get_open_orders", fake_get_open_orders)
    return calls


@pytest.mark.parametrize("flag", ["false", "False", "0", "no", ""])
def test_string_false_does_not_request_executions(seen: list[bool], flag: str) -> None:
    out = json.loads(tool_mod.TradingOrdersTool().execute(include_executions=flag))
    assert out["status"] == "ok"
    assert seen == [False]


@pytest.mark.parametrize("flag", ["true", True])
def test_true_requests_executions(seen: list[bool], flag: Any) -> None:
    tool_mod.TradingOrdersTool().execute(include_executions=flag)
    assert seen == [True]
