"""Binance history must map project-style 1H/4H tokens to ccxt timeframes."""

from __future__ import annotations

from src.trading.connectors.binance import sdk as bn


class _FakeEx:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def fetch_ohlcv(self, symbol, timeframe="1d", limit=90):
        self.calls.append({"symbol": symbol, "timeframe": timeframe, "limit": limit})
        return []


def test_timeframe_map_covers_hour_tokens() -> None:
    assert bn._TIMEFRAME_MAP["1H"] == "1h"
    assert bn._TIMEFRAME_MAP["1h"] == "1h"
    assert bn._TIMEFRAME_MAP["4H"] == "4h"
    assert bn._TIMEFRAME_MAP["4h"] == "4h"


def test_history_1H_uses_hour_timeframe(monkeypatch) -> None:
    fake = _FakeEx()
    cfg = bn.BinanceConfig(api_key="k", api_secret="s", profile="paper")
    monkeypatch.setattr(bn, "_assert_host", lambda c: None)
    monkeypatch.setattr(bn, "_exchange", lambda c: fake)
    monkeypatch.setattr(bn, "normalize_symbol", lambda s: "BTC/USDT")
    out = bn.get_historical_bars("BTC/USDT", config=cfg, period="1H", limit=10)
    assert out["status"] == "ok"
    assert fake.calls[0]["timeframe"] == "1h"


def test_history_4H_uses_four_hour_timeframe(monkeypatch) -> None:
    fake = _FakeEx()
    cfg = bn.BinanceConfig(api_key="k", api_secret="s", profile="paper")
    monkeypatch.setattr(bn, "_assert_host", lambda c: None)
    monkeypatch.setattr(bn, "_exchange", lambda c: fake)
    monkeypatch.setattr(bn, "normalize_symbol", lambda s: "BTC/USDT")
    bn.get_historical_bars("BTC/USDT", config=cfg, period="4H", limit=10)
    assert fake.calls[0]["timeframe"] == "4h"
