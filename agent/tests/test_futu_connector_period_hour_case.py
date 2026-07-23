"""Futu connector period map must treat project-style 1H/4H as hour bars."""

from __future__ import annotations

from src.trading.connectors.futu import sdk as futu_sdk


def test_kltype_map_accepts_project_hour_tokens() -> None:
    assert futu_sdk._KLTYPE_MAP["1H"] == "K_60M"
    assert futu_sdk._KLTYPE_MAP["4H"] == "K_240M"
    assert futu_sdk._KLTYPE_MAP["1h"] == "K_60M"
    assert futu_sdk._KLTYPE_MAP["4h"] == "K_240M"
    assert futu_sdk._KLTYPE_MAP["1m"] == "K_1M"
    assert futu_sdk._KLTYPE_MAP["1M"] == "K_MON"
    assert futu_sdk._KLTYPE_MAP["1D"] == "K_DAY"


def test_history_1H_does_not_collapse_to_day(monkeypatch) -> None:
    calls: list[object] = []

    class _KLType:
        K_60M = "K_60M"
        K_240M = "K_240M"
        K_DAY = "K_DAY"

    class _Futu:
        KLType = _KLType

    class _QuoteCtx:
        def request_history_kline(self, code, ktype=None, max_count=None):
            calls.append(ktype)
            return 0, None

    monkeypatch.setattr(futu_sdk, "_require_futu", lambda: _Futu)
    monkeypatch.setattr(futu_sdk, "_quote_ctx", lambda cfg: _QuoteCtx())
    monkeypatch.setattr(futu_sdk, "_close", lambda ctx: None)
    monkeypatch.setattr(futu_sdk, "_unwrap", lambda result: result)
    monkeypatch.setattr(futu_sdk, "_records", lambda data: [])
    cfg = futu_sdk.FutuConfig(host="127.0.0.1", port=11111, profile="paper")
    futu_sdk.get_historical_bars("US.AAPL", config=cfg, period="1H", limit=24)
    assert calls[-1] == "K_60M"


def test_history_4H_uses_240m_not_60m(monkeypatch) -> None:
    calls: list[object] = []

    class _KLType:
        K_60M = "K_60M"
        K_240M = "K_240M"
        K_DAY = "K_DAY"

    class _Futu:
        KLType = _KLType

    class _QuoteCtx:
        def request_history_kline(self, code, ktype=None, max_count=None):
            calls.append(ktype)
            return 0, None

    monkeypatch.setattr(futu_sdk, "_require_futu", lambda: _Futu)
    monkeypatch.setattr(futu_sdk, "_quote_ctx", lambda cfg: _QuoteCtx())
    monkeypatch.setattr(futu_sdk, "_close", lambda ctx: None)
    monkeypatch.setattr(futu_sdk, "_unwrap", lambda result: result)
    monkeypatch.setattr(futu_sdk, "_records", lambda data: [])
    cfg = futu_sdk.FutuConfig(host="127.0.0.1", port=11111, profile="paper")
    futu_sdk.get_historical_bars("US.AAPL", config=cfg, period="4H", limit=24)
    assert calls[-1] == "K_240M"
