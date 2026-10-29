"""Spot fees and funding reconcile through the real execution loop (#2088)."""

import pandas as pd
import pytest

from backtest.engines.composite import CompositeEngine
from backtest.engines.crypto import CryptoEngine
from backtest.models import Position
from backtest.runner import _create_market_engine


@pytest.mark.parametrize("source", ["okx", "ccxt", "yfinance", "local"])
def test_spot_runner_preserves_commission_without_default_funding(source):
    config = {"initial_cash": 10000, "commission": 0.001, "slippage": 0.0}
    engine = _create_market_engine(source, config, ["BTC-USDT"])
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    bars = pd.DataFrame({k: [100.0] * 4 for k in ("open", "high", "low", "close")}, index=dates)
    engine._execute_bars(dates, {"BTC-USDT": bars}, pd.DataFrame({"BTC-USDT": bars["close"]}),
                         pd.DataFrame({"BTC-USDT": [0.5, 0.5, 0.5, 0]}, index=dates), ["BTC-USDT"])
    assert engine.capital == pytest.approx(9990.0)
    assert sum(t.commission for t in engine.trades) == pytest.approx(10.0)
    assert engine._engine_diagnostics()["crypto_funding_pnl"] == 0.0


@pytest.mark.parametrize("symbol", ["BTC-USDT-PERP", "BTC-USDT-SWAP", "BTC/USDT:USDT"])
def test_perpetual_default_funding_remains_active(symbol):
    engine = CryptoEngine({"initial_cash": 10000, "interval": "1H"})
    timestamp = pd.Timestamp("2026-01-01 08:00")
    engine.positions[symbol] = Position(symbol=symbol, direction=1, size=1.0, entry_price=100.0,
                                        entry_time=timestamp - pd.Timedelta(hours=1))
    engine.on_bar(symbol, pd.Series({"open": 100.0, "close": 100.0}), timestamp)
    assert engine.capital == pytest.approx(9999.99)
    assert engine._engine_diagnostics()["crypto_funding_pnl"] == pytest.approx(-0.01)


def test_explicit_crypto_fee_side_overrides_only_its_commission_fallback():
    engine = CryptoEngine({"commission": 0.001, "maker_rate": 0.0003})
    assert engine.calc_commission(1, 100, 1, True) == pytest.approx(0.1)
    assert engine.calc_commission(1, 100, 1, False) == pytest.approx(0.03)


def test_composite_spot_has_no_default_funding():
    engine = CompositeEngine({"initial_cash": 10000}, ["BTC-USDT", "AAPL.US"])
    timestamp = pd.Timestamp("2026-01-01")
    engine.positions["BTC-USDT"] = Position(symbol="BTC-USDT", direction=1, size=1.0, entry_price=100.0,
                                            entry_time=timestamp - pd.Timedelta(days=1))
    engine.on_bar("BTC-USDT", pd.Series({"open": 100.0, "close": 100.0, "funding_rate": 0.1}), timestamp)
    assert engine.capital == 10000
    assert engine._engine_diagnostics()["crypto_funding_pnl"] == 0
