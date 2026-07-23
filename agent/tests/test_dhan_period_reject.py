"""Dhan history must reject unsupported periods instead of serving daily bars."""

from __future__ import annotations

from src.trading.connectors.dhan import sdk as dhan_sdk


class _FakeDhanClient:
    def __init__(self) -> None:
        self.daily_calls = 0
        self.intraday_calls = 0

    def historical_daily_candle_data(self, **kwargs):
        self.daily_calls += 1
        return {"data": {"candles": []}}

    def intraday_daily_candle_data(self, **kwargs):
        self.intraday_calls += 1
        return {"data": {"candles": []}}


def test_dhan_rejects_hour_period_instead_of_daily(monkeypatch) -> None:
    fake = _FakeDhanClient()
    monkeypatch.setattr(dhan_sdk, "_dhan_client", lambda cfg: fake)
    cfg = dhan_sdk.DhanConfig(client_id="x", access_token="y", profile="paper")
    out = dhan_sdk.get_historical_bars("RELIANCE", config=cfg, period="1H", limit=24)
    assert out["status"] == "error"
    assert "unsupported period" in out["error"]
    assert fake.daily_calls == 0
    assert fake.intraday_calls == 0


def test_dhan_keeps_supported_daily_and_intraday(monkeypatch) -> None:
    fake = _FakeDhanClient()
    monkeypatch.setattr(dhan_sdk, "_dhan_client", lambda cfg: fake)
    cfg = dhan_sdk.DhanConfig(client_id="x", access_token="y", profile="paper")
    daily = dhan_sdk.get_historical_bars("RELIANCE", config=cfg, period="1D", limit=10)
    assert daily["status"] == "ok"
    assert fake.daily_calls == 1
    minute = dhan_sdk.get_historical_bars("RELIANCE", config=cfg, period="5m", limit=10)
    assert minute["status"] == "ok"
    assert fake.intraday_calls == 1
