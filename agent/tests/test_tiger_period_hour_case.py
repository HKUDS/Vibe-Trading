"""Tiger period map must treat project-style 1H/4H as hour bars, not day."""

from __future__ import annotations

from src.trading.connectors.tiger import sdk as tg


class _FakeTigerQuote:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_bars(self, symbols, period=None, limit=None):
        self.calls.append({"period": period, "limit": limit})
        return []


def test_tiger_period_map_accepts_project_hour_tokens() -> None:
    assert tg._PERIOD_MAP["1H"] == "60min"
    assert tg._PERIOD_MAP["4H"] == "60min"
    assert tg._PERIOD_MAP["1h"] == "60min"
    assert tg._PERIOD_MAP["1m"] == "1min"
    assert tg._PERIOD_MAP["1M"] == "month"


def test_tiger_history_1H_does_not_collapse_to_day(monkeypatch) -> None:
    fake = _FakeTigerQuote()
    monkeypatch.setattr(tg, "_quote_client", lambda cfg: fake)
    monkeypatch.setattr(tg, "_assert_profile", lambda cfg: None)
    cfg = tg.TigerConfig(
        tiger_id="x",
        private_key_path="x",
        account="20191106192858300",
        profile="paper",
    )
    tg.get_historical_bars("AAPL", config=cfg, period="1H", limit=24)
    assert fake.calls[-1]["period"] == "60min"
