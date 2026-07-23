"""Longbridge connector period map must treat 1H/4H like the loader."""

from __future__ import annotations

from src.trading.connectors.longbridge import sdk as lb


def test_period_map_accepts_project_hour_tokens() -> None:
    assert lb._PERIOD_MAP["1H"] == "Min_60"
    assert lb._PERIOD_MAP["4H"] == "Min_60"
    assert lb._PERIOD_MAP["1h"] == "Min_60"
    assert lb._PERIOD_MAP["4h"] == "Min_60"
    assert lb._PERIOD_MAP["1m"] == "Min_1"
    assert lb._PERIOD_MAP["1M"] == "Month"


def test_candlestick_enums_1H_not_day(monkeypatch) -> None:
    class _Period:
        Min_60 = "Min_60"
        Day = "Day"

    class _Adjust:
        NoAdjust = "NoAdjust"

    class _OpenApi:
        Period = _Period
        AdjustType = _Adjust

    monkeypatch.setattr(lb, "_require_openapi", lambda: _OpenApi)
    period_enum, _ = lb._candlestick_enums("1H")
    assert period_enum == "Min_60"
