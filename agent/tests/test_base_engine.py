"""Tests for BaseEngine shared logic: _align, _close_position, _calc_equity.

Uses ChinaAEngine as a concrete implementation since BaseEngine is abstract.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.engines.base import BaseEngine, _align, _load_optimizer
from backtest.engines.china_a import ChinaAEngine
from backtest.models import Position


class _AdjustmentEngine(BaseEngine):
    def __init__(self, **overrides):
        config = {
            "initial_cash": 1_000.0,
            "leverage": 1.0,
            "position_adjustment": "rebalance",
        }
        config.update(overrides)
        super().__init__(config)
        self.bar_positions: list[dict[str, Position]] = []

    def can_execute(self, symbol, direction, bar):
        return True

    def round_size(self, raw_size, price):
        return round(max(raw_size, 0.0), 6)

    def calc_commission(self, size, price, direction, is_open):
        return size * price * float(self.config.get("fee_rate", 0.0))

    def apply_slippage(self, price, direction):
        return price

    def after_rebalance_bar(self, timestamp, data_map, codes):
        self.bar_positions.append(dict(self.positions))
        return False


class _ChangingLeverageAdjustmentEngine(_AdjustmentEngine):
    def _leverage_for_symbol(self, symbol):
        del symbol
        return 1.0 if self._bar_idx == 0 else 2.0


def _run_adjustments(
    engine: _AdjustmentEngine,
    weights: dict[str, list[float]],
    *,
    execution_prices: dict[str, list[float]] | None = None,
    codes: list[str] | None = None,
) -> None:
    dates = pd.date_range("2026-01-02", periods=len(next(iter(weights.values()))))
    codes = codes or list(weights)
    data_map = {}
    close_data = {}
    for symbol in weights:
        prices = (execution_prices or {}).get(symbol, [100.0] * len(dates))
        data_map[symbol] = pd.DataFrame({"open": prices, "close": prices}, index=dates)
        close_data[symbol] = prices
    engine._execute_bars(
        dates,
        data_map,
        pd.DataFrame(close_data, index=dates),
        pd.DataFrame(weights, index=dates),
        codes,
    )


def test_position_adjustment_rejects_unknown_mode():
    with pytest.raises(ValueError, match="position_adjustment"):
        _AdjustmentEngine(position_adjustment="resize")


def test_hold_mode_keeps_same_direction_size():
    engine = _AdjustmentEngine(position_adjustment="hold")
    _run_adjustments(engine, {"A": [0.25, 0.50, 0.20]})
    assert [state["A"].size for state in engine.bar_positions] == [2.5, 2.5, 2.5]


def test_rebalance_increases_then_reduces_same_direction_position():
    engine = _AdjustmentEngine()
    _run_adjustments(engine, {"A": [0.25, 0.50, 0.20]})
    assert [state["A"].size for state in engine.bar_positions] == [2.5, 5.0, 2.0]
    partial = next(t for t in engine.trades if t.exit_reason == "target_rebalance")
    assert partial.size == 3.0
    assert partial.entry_margin == 300.0
    assert partial.pnl == 0.0


def test_rebalance_scale_in_uses_weighted_average_entry():
    engine = _AdjustmentEngine()
    _run_adjustments(
        engine,
        {"A": [0.25, 0.50]},
        execution_prices={"A": [100.0, 120.0]},
    )
    assert engine.bar_positions[0]["A"].size == 2.5
    assert engine.bar_positions[1]["A"].size == 4.375
    assert engine.bar_positions[1]["A"].entry_price == pytest.approx(108.5714285714)


def test_rebalance_rejects_same_direction_adjustment_with_changed_leverage():
    engine = _ChangingLeverageAdjustmentEngine()
    with pytest.raises(ValueError, match="leverage"):
        _run_adjustments(engine, {"A": [0.25, 0.50]})
    assert engine.capital == 750.0
    assert engine.bar_positions == [
        {"A": Position("A", 1, 100.0, pd.Timestamp("2026-01-02"), 2.5)}
    ]


def test_rebalance_reduces_short_with_correct_signed_pnl():
    engine = _AdjustmentEngine()
    _run_adjustments(
        engine,
        {"A": [-0.50, -0.20]},
        execution_prices={"A": [100.0, 90.0]},
    )
    partial = next(t for t in engine.trades if t.exit_reason == "target_rebalance")
    assert partial.direction == -1
    assert partial.size == pytest.approx(2.666667)
    assert partial.pnl == pytest.approx(26.66667, rel=1e-5)


def test_rebalance_insufficient_capital_is_atomic():
    engine = _AdjustmentEngine(fee_rate=0.10)
    with pytest.raises(ValueError, match="insufficient capital"):
        _run_adjustments(engine, {"A": [1.0]})
    assert engine.capital == 1_000.0
    assert engine.positions == {}
    assert engine.trades == []


def test_rebalance_basket_is_independent_of_input_code_order():
    weights = {"A": [0.50], "B": [0.50]}
    first = _AdjustmentEngine()
    second = _AdjustmentEngine()
    _run_adjustments(first, weights, codes=["A", "B"])
    _run_adjustments(second, weights, codes=["B", "A"])
    assert {
        symbol: position.size for symbol, position in first.bar_positions[0].items()
    } == {"A": 5.0, "B": 5.0}
    assert first.bar_positions == second.bar_positions
    assert [snapshot.capital for snapshot in first.equity_snapshots] == [
        snapshot.capital for snapshot in second.equity_snapshots
    ]


class _LifecycleEngine(ChinaAEngine):
    def __init__(self, *, stop_before: bool = False):
        super().__init__({"initial_cash": 1_000_000.0})
        self.stop_before = stop_before
        self.lifecycle: list[str] = []

    def before_rebalance_bar(self, timestamp, data_map, codes):
        self.lifecycle.append("pre")
        return self.stop_before

    def after_rebalance_bar(self, timestamp, data_map, codes):
        self.lifecycle.append("post")
        return False

    def _execute_open_order(self, order, ts):
        self.lifecycle.append("fill")
        super()._execute_open_order(order, ts)


def _run_lifecycle(engine: _LifecycleEngine) -> None:
    dates = pd.DatetimeIndex([pd.Timestamp("2026-01-02")])
    frame = pd.DataFrame({"open": [100.0], "close": [100.0]}, index=dates)
    engine._execute_bars(
        dates,
        {"TEST": frame},
        frame[["close"]].rename(columns={"close": "TEST"}),
        pd.DataFrame({"TEST": [1.0]}, index=dates),
        ["TEST"],
    )


@pytest.mark.parametrize(("stop_before", "expected"), [
    (False, ["pre", "fill", "post"]), (True, ["pre"]),
])
def test_execute_bars_lifecycle_and_pre_fill_stop(
    stop_before: bool, expected: list[str]
) -> None:
    engine = _LifecycleEngine(stop_before=stop_before)
    _run_lifecycle(engine)
    assert engine.lifecycle == expected
    assert len(engine.equity_snapshots) == 1
    if stop_before:
        assert engine.trades == []


# ---------------------------------------------------------------------------
# _align: signal alignment and normalization
# ---------------------------------------------------------------------------


def _simple_data_and_signals():
    """Build minimal data_map and signal_map for alignment tests."""
    dates = pd.bdate_range("2025-01-01", periods=10)
    df_a = pd.DataFrame(
        {"close": np.linspace(10, 20, 10), "open": np.linspace(10, 20, 10)},
        index=dates,
    )
    df_b = pd.DataFrame(
        {"close": np.linspace(100, 110, 10), "open": np.linspace(100, 110, 10)},
        index=dates,
    )
    data_map = {"A": df_a, "B": df_b}

    sig_a = pd.Series(0.0, index=dates)
    sig_a.iloc[3:] = 1.0
    sig_b = pd.Series(0.0, index=dates)
    sig_b.iloc[5:] = 1.0
    signal_map = {"A": sig_a, "B": sig_b}

    return data_map, signal_map, dates


class TestAlign:
    def test_common_timezone_is_preserved(self) -> None:
        dates = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
        frame = pd.DataFrame({"open": [100.0] * 3, "close": [100.0] * 3}, index=dates)
        signals = pd.Series([0.0, 1.0, 0.0], index=dates)

        out_dates, close_df, pos_df, _ = _align(
            {"BTC-USDT-PERP": frame}, {"BTC-USDT-PERP": signals}, ["BTC-USDT-PERP"]
        )

        assert str(out_dates.tz) == "UTC"
        assert close_df.index.equals(dates)
        assert pos_df.index.equals(dates)

    def test_output_shapes(self) -> None:
        data_map, signal_map, dates = _simple_data_and_signals()
        out_dates, close_df, pos_df, ret_df = _align(data_map, signal_map, ["A", "B"])
        assert len(out_dates) == len(dates)
        assert close_df.shape == (len(dates), 2)
        assert pos_df.shape == (len(dates), 2)
        assert ret_df.shape == (len(dates), 2)

    def test_signal_shifted_by_one(self) -> None:
        """Signal at bar i should produce position at bar i+1 (next-bar-open)."""
        data_map, signal_map, dates = _simple_data_and_signals()
        _, _, pos_df, _ = _align(data_map, signal_map, ["A", "B"])
        # Signal A goes to 1.0 at index 3 → position should be 0 at index 3, non-zero at index 4
        assert pos_df.at[dates[3], "A"] == 0.0
        assert pos_df.at[dates[4], "A"] > 0.0

    def test_positions_normalized(self) -> None:
        """Sum of abs(weights) should be <= 1.0 per row."""
        data_map, signal_map, dates = _simple_data_and_signals()
        _, _, pos_df, _ = _align(data_map, signal_map, ["A", "B"])
        row_sums = pos_df.abs().sum(axis=1)
        assert (row_sums <= 1.0 + 1e-10).all()

    def test_signals_clipped(self) -> None:
        """Signals outside [-1, 1] should be clipped."""
        dates = pd.bdate_range("2025-01-01", periods=5)
        df = pd.DataFrame({"close": [100] * 5, "open": [100] * 5}, index=dates)
        sig = pd.Series([0, 0, 2.0, -3.0, 0.5], index=dates)
        data_map = {"X": df}
        signal_map = {"X": sig}
        _, _, pos_df, _ = _align(data_map, signal_map, ["X"])
        # After shift, clipped values show up at indices 3 and 4
        assert pos_df["X"].abs().max() <= 1.0 + 1e-10

    def test_nan_signals_filled_zero(self) -> None:
        dates = pd.bdate_range("2025-01-01", periods=5)
        df = pd.DataFrame({"close": [100] * 5, "open": [100] * 5}, index=dates)
        sig = pd.Series([np.nan, 1.0, np.nan, 0.5, np.nan], index=dates)
        data_map = {"X": df}
        signal_map = {"X": sig}
        _, _, pos_df, _ = _align(data_map, signal_map, ["X"])
        assert not pos_df.isna().any().any()

    def test_close_ffill_bfill(self) -> None:
        """Missing close prices should be forward/backward filled."""
        dates = pd.bdate_range("2025-01-01", periods=5)
        df = pd.DataFrame(
            {"close": [100, np.nan, np.nan, 110, 115], "open": [100] * 5},
            index=dates,
        )
        sig = pd.Series([0, 1, 1, 1, 0], index=dates)
        _, close_df, _, _ = _align({"X": df}, {"X": sig}, ["X"])
        assert not close_df.isna().any().any()

    def test_with_optimizer(self) -> None:
        """Optimizer callable gets applied."""
        data_map, signal_map, dates = _simple_data_and_signals()

        def dummy_optimizer(ret, pos, dates_arg):
            return pos * 0.5  # halve everything

        _, _, pos_df, _ = _align(data_map, signal_map, ["A", "B"], optimizer=dummy_optimizer)
        # Positions should be smaller due to optimizer
        _, _, pos_no_opt, _ = _align(data_map, signal_map, ["A", "B"])
        assert pos_df.abs().sum().sum() <= pos_no_opt.abs().sum().sum() + 1e-10


# ---------------------------------------------------------------------------
# _load_optimizer
# ---------------------------------------------------------------------------


class TestLoadOptimizer:
    def test_no_optimizer(self) -> None:
        assert _load_optimizer({}) is None
        assert _load_optimizer({"optimizer": ""}) is None

    def test_valid_optimizer(self) -> None:
        opt = _load_optimizer({"optimizer": "risk_parity"})
        assert opt is not None and callable(opt)

    def test_invalid_optimizer_returns_none(self) -> None:
        opt = _load_optimizer({"optimizer": "nonexistent_module_xyz"})
        assert opt is None


# ---------------------------------------------------------------------------
# _close_position: PnL calculation
# ---------------------------------------------------------------------------


class TestClosePosition:
    def test_profitable_long(self) -> None:
        engine = ChinaAEngine({"initial_cash": 1_000_000})
        engine._bar_idx = 5
        engine.positions["000001.SZ"] = Position(
            "000001.SZ", 1, 15.0, pd.Timestamp("2025-01-02"), 1000.0, entry_bar_idx=0,
        )
        engine.capital = 985_000.0  # after buying
        engine._close_position("000001.SZ", 16.0, pd.Timestamp("2025-01-10"), "signal")

        assert "000001.SZ" not in engine.positions
        assert len(engine.trades) == 1
        t = engine.trades[0]
        assert t.pnl == pytest.approx(1000.0)  # 1000 × (16 - 15) = +1000
        assert t.exit_reason == "signal"
        assert t.holding_bars == 5

    def test_losing_long(self) -> None:
        engine = ChinaAEngine({"initial_cash": 1_000_000})
        engine._bar_idx = 3
        engine.positions["600519.SH"] = Position(
            "600519.SH", 1, 1800.0, pd.Timestamp("2025-01-02"), 100.0, entry_bar_idx=0,
        )
        engine.capital = 820_000.0
        engine._close_position("600519.SH", 1750.0, pd.Timestamp("2025-01-06"), "signal")

        t = engine.trades[0]
        assert t.pnl == pytest.approx(-5000.0)  # 100 × (1750 - 1800) = -5000
        assert t.direction == 1

    def test_close_nonexistent_position_noop(self) -> None:
        engine = ChinaAEngine({"initial_cash": 1_000_000})
        engine._close_position("NOPE.SZ", 10.0, pd.Timestamp("2025-01-01"), "signal")
        assert len(engine.trades) == 0

    def test_capital_returned(self) -> None:
        engine = ChinaAEngine({"initial_cash": 1_000_000})
        engine._bar_idx = 1
        engine.positions["000001.SZ"] = Position(
            "000001.SZ", 1, 15.0, pd.Timestamp("2025-01-02"), 1000.0,
        )
        capital_before = 985_000.0
        engine.capital = capital_before
        engine._close_position("000001.SZ", 15.0, pd.Timestamp("2025-01-03"), "signal")
        # Margin returned + 0 PnL - exit commission
        assert engine.capital > capital_before  # margin returned exceeds commission


# ---------------------------------------------------------------------------
# _calc_equity
# ---------------------------------------------------------------------------


class TestCalcEquity:
    def test_no_positions(self) -> None:
        engine = ChinaAEngine({"initial_cash": 1_000_000})
        dates = pd.DatetimeIndex([pd.Timestamp("2025-01-02")])
        close_df = pd.DataFrame({"X": [15.0]}, index=dates)
        eq = engine._calc_equity(close_df, dates[0])
        assert eq == 1_000_000.0

    def test_with_unrealized_gain(self) -> None:
        engine = ChinaAEngine({"initial_cash": 1_000_000})
        engine.capital = 985_000.0
        engine.positions["X"] = Position("X", 1, 15.0, pd.Timestamp("2025-01-02"), 1000.0)
        dates = pd.DatetimeIndex([pd.Timestamp("2025-01-03")])
        close_df = pd.DataFrame({"X": [16.0]}, index=dates)
        eq = engine._calc_equity(close_df, dates[0])
        # capital + margin + unrealized = 985000 + (1000×15/1) + (1×1000×(16-15)) = 985000 + 15000 + 1000 = 1001000
        assert eq == pytest.approx(1_001_000.0)


# ---------------------------------------------------------------------------
# _safe_price
# ---------------------------------------------------------------------------


class TestSafePrice:
    def test_returns_close_price(self) -> None:
        dates = pd.DatetimeIndex([pd.Timestamp("2025-01-02")])
        close_df = pd.DataFrame({"X": [15.5]}, index=dates)
        assert BaseEngine._safe_price(close_df, dates[0], "X", 10.0) == 15.5

    def test_fallback_on_missing_symbol(self) -> None:
        dates = pd.DatetimeIndex([pd.Timestamp("2025-01-02")])
        close_df = pd.DataFrame({"X": [15.5]}, index=dates)
        assert BaseEngine._safe_price(close_df, dates[0], "MISSING", 10.0) == 10.0

    def test_fallback_on_missing_timestamp(self) -> None:
        dates = pd.DatetimeIndex([pd.Timestamp("2025-01-02")])
        close_df = pd.DataFrame({"X": [15.5]}, index=dates)
        assert BaseEngine._safe_price(close_df, pd.Timestamp("2025-06-01"), "X", 10.0) == 10.0

    def test_fallback_on_nan(self) -> None:
        dates = pd.DatetimeIndex([pd.Timestamp("2025-01-02")])
        close_df = pd.DataFrame({"X": [np.nan]}, index=dates)
        assert BaseEngine._safe_price(close_df, dates[0], "X", 10.0) == 10.0
