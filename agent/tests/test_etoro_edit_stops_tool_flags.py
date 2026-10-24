"""etoro_edit_position_stops reads JSON-string stop flags by their value."""

from __future__ import annotations

import json
from typing import Any

import pytest

import src.tools.trading_connector_tool as tool_mod


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    box: dict[str, Any] = {}

    def fake_edit(position_id: str, _conn: Any, **kw: Any) -> dict:
        box.update(kw, position_id=position_id)
        return {"status": "ok"}

    monkeypatch.setattr(tool_mod, "edit_position_stops", fake_edit)
    return box


@pytest.mark.parametrize("flag", ["false", "False", "0", "no"])
def test_string_false_keeps_stops_and_fixed_type(seen: dict[str, Any], flag: str) -> None:
    out = json.loads(
        tool_mod.EtoroEditPositionStopsTool().execute(
            position_id="123",
            take_profit=110.0,
            clear_stop_loss=flag,
            clear_take_profit=flag,
            trailing_stop_loss=flag,
        )
    )
    assert out["status"] == "ok"
    assert seen["clear_stop_loss"] is False
    assert seen["clear_take_profit"] is False
    assert seen["trailing_stop_loss"] is False


def test_string_true_and_omitted_flags(seen: dict[str, Any]) -> None:
    tool_mod.EtoroEditPositionStopsTool().execute(position_id="123", clear_stop_loss="true")
    assert seen["clear_stop_loss"] is True
    assert seen["clear_take_profit"] is False
    assert seen["trailing_stop_loss"] is None
