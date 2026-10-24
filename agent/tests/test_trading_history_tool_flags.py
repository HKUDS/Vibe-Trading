"""trading_history reads a JSON-string use_rth flag by its value."""

from __future__ import annotations

import json
from typing import Any

import pytest

import src.tools.trading_connector_tool as tool_mod


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    calls: list[bool] = []

    def fake_get_history(_symbol: str, _conn: Any, *, use_rth: bool, **_kw: Any) -> dict:
        calls.append(use_rth)
        return {"status": "ok", "bars": []}

    monkeypatch.setattr(tool_mod, "_connection", lambda name: name)
    monkeypatch.setattr(tool_mod, "get_history", fake_get_history)
    return calls


@pytest.mark.parametrize("flag", ["false", "False", "0", "no"])
def test_string_false_requests_all_sessions(seen: list[bool], flag: str) -> None:
    out = json.loads(tool_mod.TradingHistoryTool().execute(symbol="AAPL", use_rth=flag))
    assert out["status"] == "ok"
    assert seen == [False]


@pytest.mark.parametrize("kwargs", [{}, {"use_rth": "true"}, {"use_rth": True}])
def test_default_and_true_keep_regular_hours(seen: list[bool], kwargs: dict) -> None:
    tool_mod.TradingHistoryTool().execute(symbol="AAPL", **kwargs)
    assert seen == [True]
