"""Shoonya period map must not silently collapse 4h/1H/1w/1M to daily."""

from __future__ import annotations

from src.trading.connectors.shoonya import sdk as sh


class _FakeApi:
    def __init__(self) -> None:
        self.daily_calls: list[dict] = []
        self.time_calls: list[dict] = []

    def get_daily_price_series(self, **kwargs):
        self.daily_calls.append(kwargs)
        return []

    def get_time_price_series(self, **kwargs):
        self.time_calls.append(kwargs)
        return []


def _cfg() -> sh.ShoonyaConfig:
    return sh.ShoonyaConfig(
        user_id="u", password="p", vendor_code="v", api_secret="s", totp_secret="t",
    )


def test_interval_map_covers_documented_hour_tokens() -> None:
    assert sh._INTERVAL_MAP["1H"] == "60"
    assert sh._INTERVAL_MAP["4h"] == "240"
    assert sh._INTERVAL_MAP["4H"] == "240"
    assert sh._INTERVAL_MAP["1h"] == "60"
    assert sh._INTERVAL_MAP["1d"] == "D"
    assert "1w" not in sh._INTERVAL_MAP
    assert "1M" not in sh._INTERVAL_MAP


def test_history_4h_uses_minute_series_not_daily(monkeypatch) -> None:
    fake = _FakeApi()
    monkeypatch.setattr(sh, "_login", lambda cfg: fake)
    out = sh.get_historical_bars("RELIANCE", config=_cfg(), period="4h", limit=10)
    assert out["status"] == "ok"
    assert fake.daily_calls == []
    assert fake.time_calls[-1]["interval"] == "240"


def test_history_1H_maps_to_60_not_daily(monkeypatch) -> None:
    fake = _FakeApi()
    monkeypatch.setattr(sh, "_login", lambda cfg: fake)
    out = sh.get_historical_bars("RELIANCE", config=_cfg(), period="1H", limit=10)
    assert out["status"] == "ok"
    assert fake.daily_calls == []
    assert fake.time_calls[-1]["interval"] == "60"


def test_history_1w_rejected_not_silent_daily(monkeypatch) -> None:
    fake = _FakeApi()
    monkeypatch.setattr(sh, "_login", lambda cfg: fake)
    out = sh.get_historical_bars("RELIANCE", config=_cfg(), period="1w", limit=10)
    assert out["status"] == "error"
    assert "unsupported period" in out["error"]
    assert fake.daily_calls == []
    assert fake.time_calls == []


def test_history_1M_rejected_not_silent_daily(monkeypatch) -> None:
    fake = _FakeApi()
    monkeypatch.setattr(sh, "_login", lambda cfg: fake)
    out = sh.get_historical_bars("RELIANCE", config=_cfg(), period="1M", limit=10)
    assert out["status"] == "error"
    assert "unsupported period" in out["error"]
    assert fake.daily_calls == []
    assert fake.time_calls == []
