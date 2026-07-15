"""Causality and ordering regressions for the shared execution loop."""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.engines.base import BaseEngine
from backtest.engines.china_a import ChinaAEngine
from backtest.engines.china_futures import ChinaFuturesEngine
from backtest.engines.composite import CompositeEngine
from backtest.engines.crypto import CryptoEngine
from backtest.engines.forex import ForexEngine
from backtest.engines.global_equity import GlobalEquityEngine
from backtest.engines.global_futures import GlobalFuturesEngine
from backtest.engines.india_equity import IndiaEquityEngine


class _FrictionlessEngine(BaseEngine):
    def can_execute(self, symbol, direction, bar):
        return True

    def round_size(self, raw_size, price):
        return raw_size

    def calc_commission(self, size, price, direction, is_open):
        return 0.0

    def apply_slippage(self, price, direction):
        return price


def _rotation_run(*, last_close_a: float = 100.0, code_order=None):
    dates = pd.bdate_range("2026-01-05", periods=2)
    bars_a = pd.DataFrame(
        {"open": [100.0, 100.0], "close": [100.0, last_close_a]},
        index=dates,
    )
    bars_b = pd.DataFrame(
        {"open": [100.0, 100.0], "close": [100.0, 100.0]},
        index=dates,
    )
    data_map = {"A": bars_a, "B": bars_b}
    close_df = pd.DataFrame(
        {"A": bars_a["close"], "B": bars_b["close"]},
        index=dates,
    )
    target_pos = pd.DataFrame(
        {"A": [0.5, 0.0], "B": [0.0, 0.5]},
        index=dates,
    )
    engine = _FrictionlessEngine({"initial_cash": 100_000.0})
    engine._execute_bars(
        dates,
        data_map,
        close_df,
        target_pos,
        code_order or ["A", "B"],
    )
    return engine


def test_decision_bar_close_cannot_change_open_position_size() -> None:
    baseline = _rotation_run(last_close_a=100.0)
    shocked = _rotation_run(last_close_a=200.0)

    baseline_b = next(t for t in baseline.trades if t.symbol == "B")
    shocked_b = next(t for t in shocked.trades if t.symbol == "B")

    assert baseline_b.size == 500.0
    assert shocked_b.size == baseline_b.size


def test_rotation_is_independent_of_close_open_symbol_order() -> None:
    a_first = _rotation_run(code_order=["A", "B"])
    b_first = _rotation_run(code_order=["B", "A"])

    a_first_trades = [(t.symbol, t.size, t.exit_reason) for t in a_first.trades]
    b_first_trades = [(t.symbol, t.size, t.exit_reason) for t in b_first.trades]

    assert a_first_trades == b_first_trades
    assert [symbol for symbol, _, _ in a_first_trades] == ["A", "B"]


def test_open_signal_exit_precedes_close_based_liquidation() -> None:
    dates = pd.date_range("2026-01-05", periods=2, freq="D")
    bars = pd.DataFrame(
        {
            "open": [100.0, 100.0],
            "high": [100.0, 100.0],
            "low": [100.0, 10.0],
            "close": [100.0, 10.0],
        },
        index=dates,
    )
    symbol = "BTC-USDT"
    close_df = pd.DataFrame({symbol: bars["close"]}, index=dates)
    target_pos = pd.DataFrame({symbol: [1.0, 0.0]}, index=dates)
    engine = CryptoEngine(
        {
            "initial_cash": 1_000.0,
            "leverage": 10.0,
            "maker_rate": 0.0,
            "taker_rate": 0.0,
            "slippage": 0.0,
            "funding_rate": 0.0,
        }
    )

    engine._execute_bars(
        dates,
        {symbol: bars},
        close_df,
        target_pos,
        [symbol],
    )

    assert len(engine.trades) == 1
    assert engine.trades[0].exit_reason == "signal"
    assert engine.trades[0].exit_price == 100.0
    assert engine.capital == 1_000.0


class _FeeEngine(_FrictionlessEngine):
    def calc_commission(self, size, price, direction, is_open):
        return 10.0


def test_capital_constrained_open_basket_is_proportional_and_order_independent() -> None:
    dates = pd.DatetimeIndex(["2026-01-05"])
    data_map = {
        code: pd.DataFrame({"open": [100.0], "close": [100.0]}, index=dates)
        for code in ("A", "B")
    }
    close_df = pd.DataFrame({code: frame["close"] for code, frame in data_map.items()})
    targets = pd.DataFrame({"A": [0.6], "B": [0.6]}, index=dates)

    results = []
    for codes in (["A", "B"], ["B", "A"]):
        engine = _FeeEngine({"initial_cash": 1_000.0})
        engine._execute_bars(dates, data_map, close_df, targets, codes)
        results.append({trade.symbol: trade.size for trade in engine.trades})

    assert results[0] == results[1]
    assert results[0]["A"] == pytest.approx(results[0]["B"])
    assert results[0]["A"] == pytest.approx(4.9)


def _engine_case(name: str, codes: list[str], reverse: bool) -> tuple[BaseEngine, list[str]]:
    ordered = list(reversed(codes)) if reverse else codes
    config = {
        "initial_cash": 1_000_000.0,
        "codes": ordered,
        "slippage": 0.0,
        "slippage_us": 0.0,
        "commission_override": 0.0,
        "commission_per_contract": 0.0,
        "maker_rate": 0.0,
        "taker_rate": 0.0,
        "funding_rate": 0.0,
    }
    factories = {
        "china_a": lambda: ChinaAEngine(config),
        "global_equity": lambda: GlobalEquityEngine(config, market="us"),
        "crypto": lambda: CryptoEngine(config),
        "china_futures": lambda: ChinaFuturesEngine(config),
        "global_futures": lambda: GlobalFuturesEngine(config),
        "forex": lambda: ForexEngine(config),
        "india_equity": lambda: IndiaEquityEngine(config),
        "composite": lambda: CompositeEngine(config, ordered),
    }
    return factories[name](), ordered


@pytest.mark.parametrize(
    ("name", "codes"),
    [
        ("china_a", ["000001.SZ", "000002.SZ"]),
        ("global_equity", ["AAPL.US", "MSFT.US"]),
        ("crypto", ["BTC-USDT", "ETH-USDT"]),
        ("china_futures", ["IF2406.CFFEX", "IF2407.CFFEX"]),
        ("global_futures", ["ESZ4", "ESH5"]),
        ("forex", ["EUR/USD", "GBP/USD"]),
        ("india_equity", ["RELIANCE.NS", "TCS.NS"]),
        ("composite", ["AAPL.US", "BTC-USDT"]),
    ],
)
def test_engine_family_execution_is_code_order_independent(
    name: str, codes: list[str]
) -> None:
    dates = pd.DatetimeIndex(["2026-01-05"])
    data_map = {
        code: pd.DataFrame(
            {
                "open": [100.0],
                "high": [100.0],
                "low": [100.0],
                "close": [100.0],
                "pre_close": [100.0],
                "volume": [1_000_000.0],
            },
            index=dates,
        )
        for code in codes
    }
    close_df = pd.DataFrame({code: frame["close"] for code, frame in data_map.items()})
    targets = pd.DataFrame({code: [0.3] for code in codes}, index=dates)
    signatures = []

    for reverse in (False, True):
        engine, ordered = _engine_case(name, codes, reverse)
        engine._execute_bars(dates, data_map, close_df, targets, ordered)
        signatures.append(
            sorted(
                (
                    trade.symbol,
                    round(trade.size, 8),
                    round(trade.entry_price, 8),
                    round(trade.commission, 8),
                )
                for trade in engine.trades
            )
        )

    assert signatures[0] == signatures[1]
