"""Tests that yfinance-loaded crypto routes to CryptoEngine.

The yfinance branch used to hand every symbol to GlobalEquityEngine, whose
fee keys (slippage_us / hk_commission) never read the CryptoEngine keys
(taker_rate / maker_rate / slippage), so an explicit fee config was silently
ignored and two runs with different fees produced byte-identical metrics.
"""

from __future__ import annotations

from backtest.engines.crypto import CryptoEngine
from backtest.engines.global_equity import GlobalEquityEngine
from backtest.runner import _create_market_engine


class TestYfinanceCryptoRouting:
    def test_usdt_pair_routes_to_crypto_engine(self) -> None:
        engine = _create_market_engine("yfinance", {"initial_cash": 100_000}, ["BTC-USDT"])
        assert isinstance(engine, CryptoEngine)

    def test_usd_pair_routes_to_crypto_engine(self) -> None:
        # yfinance's native crypto spelling
        engine = _create_market_engine("yfinance", {"initial_cash": 100_000}, ["BTC-USD"])
        assert isinstance(engine, CryptoEngine)

    def test_us_equity_still_routes_to_global_equity_engine(self) -> None:
        engine = _create_market_engine("yfinance", {"initial_cash": 100_000}, ["AAPL.US"])
        assert isinstance(engine, GlobalEquityEngine)

    def test_fee_keys_reach_the_engine(self) -> None:
        engine = _create_market_engine(
            "yfinance",
            {
                "initial_cash": 100_000,
                "taker_rate": 0.001,
                "maker_rate": 0.001,
                "slippage": 0.001,
            },
            ["ETH-USDT"],
        )
        assert isinstance(engine, CryptoEngine)
        assert engine.taker_rate == 0.001
        assert engine.maker_rate == 0.001
        assert engine.slippage_rate == 0.001
