"""Regression coverage for the dedicated Binance crypto fallback."""

from __future__ import annotations

import pandas as pd

from backtest.loaders.registry import FALLBACK_CHAINS
from src import market_data


def test_market_data_falls_back_from_okx_to_binance() -> None:
    calls: list[str] = []

    def resolver(source: str):
        calls.append(source)

        class FailedLoader:
            def fetch(self, *_args, **_kwargs):
                raise RuntimeError(f"{source} unavailable")

        class BinanceLoader:
            def fetch(self, codes, *_args, **_kwargs):
                frame = pd.DataFrame(
                    {"close": [1.0]}, index=pd.to_datetime(["2026-01-01"])
                )
                frame.index.name = "trade_date"
                return {codes[0]: frame}

        return BinanceLoader if source == "binance" else FailedLoader

    result = market_data.fetch_market_data(
        codes=["BTC-USDT"],
        start_date="2026-01-01",
        end_date="2026-01-02",
        source="okx",
        loader_resolver=resolver,
        fallback_chain_provider=lambda _source: FALLBACK_CHAINS["crypto"],
    )

    assert calls[:2] == ["okx", "binance"]
    assert "BTC-USDT" in result
def test_binance_loader_canonical_frame_uses_shared_contract(monkeypatch):
    import pandas as pd

    from backtest.loaders.binance_loader import DataLoader
    from tests.loader_contract import assert_loader_contract

    class Exchange:
        def fetch_ohlcv(self, symbol, timeframe, **_kwargs):
            assert (symbol, timeframe) == ("BTC/USDT", "1d")
            day = 86_400_000
            start = int(pd.Timestamp("2026-10-01", tz="UTC").timestamp() * 1000)
            return [[start + i * day, 100 + i, 102 + i, 99 + i, 101 + i, 20] for i in range(3)]

    monkeypatch.setenv("VIBE_TRADING_DATA_CACHE", "0")
    monkeypatch.setattr(DataLoader, "_get_exchange", lambda *_args: Exchange())
    result = DataLoader().fetch(["BTC-USDT"], "2026-10-01", "2026-10-03")
    assert_loader_contract(result["BTC-USDT"], context="binance daily")
