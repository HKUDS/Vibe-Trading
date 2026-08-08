"""Tests for BaseEngine shared logic: _align, _close_position, _calc_equity.

Uses ChinaAEngine as a concrete implementation since BaseEngine is abstract.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pytest

from backtest.engines.base import BaseEngine, _align, _load_optimizer
from backtest.engines.china_a import ChinaAEngine
from backtest.models import Position

_ENTRY_TS = pd.Timestamp("2026-01-02")
_ADJUST_TS = pd.Timestamp("2026-01-03")


class _AdjustmentEngine(BaseEngine):
    def __init__(self, **overrides):
        config = {"initial_cash": 1_000.0, "leverage": 1.0, "position_adjustment": "rebalance"}
        config.update(overrides)
        super().__init__(config)
        self.bar_positions: list[dict[str, Position]] = []
        self.bar_capitals: list[float] = []
        self.adjustment_events: list[dict] = []

    def can_execute(self, symbol, direction, bar):
        return True

    def round_size(self, raw_size, price):
        return round(max(raw_size, 0.0), 6)

    def calc_commission(self, size, price, direction, is_open):
        return size * price * float(self.config.get("fee_rate", 0.0))

    def apply_slippage(self, price, direction):
        return price * (1 + direction * float(self.config.get("slippage", 0.0)))

    def after_position_adjustment(self, **event):
        self.adjustment_events.append(event)

    def after_rebalance_bar(self, timestamp, data_map, codes):
        self.bar_positions.append(dict(self.positions))
        self.bar_capitals.append(self.capital)
        return False


class _ChangingLeverageAdjustmentEngine(_AdjustmentEngine):
    def _leverage_for_symbol(self, symbol):
        return 1.0 if self._bar_idx == 0 else 2.0


class _SymbolRulesAdjustmentEngine(_AdjustmentEngine):
    def round_size(self, raw_size, price):
        lot = {"A": 1.0, "B": 0.25}[self._active_symbol]
        return int(max(raw_size, 0.0) / lot) * lot

    def calc_commission(self, size, price, direction, is_open):
        return size * price * {"A": 0.01, "B": 0.02}[self._active_symbol]


class _ForcedFillAdjustmentEngine(_AdjustmentEngine):
    def apply_slippage(self, price, direction):
        forced = self.config.get("forced_fill_price")
        return super().apply_slippage(price, direction) if forced is None else forced


def _run_adjustments(
    engine: _AdjustmentEngine,
    weights: dict[str, list[float]],
    *,
    execution_prices: dict[str, list[float]] | None = None,
    codes: list[str] | None = None,
) -> None:
    dates = pd.date_range("2026-01-02", periods=len(next(iter(weights.values()))))
    prices = {symbol: (execution_prices or {}).get(symbol, [100.0] * len(dates)) for symbol in weights}
    data_map = {symbol: pd.DataFrame({"open": values, "close": values}, index=dates) for symbol, values in prices.items()}
    engine._execute_bars(
        dates,
        data_map,
        pd.DataFrame(prices, index=dates),
        pd.DataFrame(weights, index=dates),
        codes or list(weights),
    )


def _position(direction=1, size=5.0):
    return Position("A", direction, 100.0, _ENTRY_TS, size)


def _rebalance_once(engine, target_weight, raw_price=100.0):
    frame = pd.DataFrame({"open": [raw_price], "close": [100.0]}, index=[_ADJUST_TS])
    engine._execute_target_rebalance({"A": target_weight}, {"A": frame}, _ADJUST_TS, 1_000.0, ["A"])


def _assert_unchanged(engine, positions=None):
    assert engine.capital == 1_000.0
    assert engine.positions == ({} if positions is None else positions)
    assert engine.trades == []
    assert engine.adjustment_events == []


def _run_both_code_orders(engine_type, weights):
    first, second = engine_type(), engine_type()
    _run_adjustments(first, weights, codes=["A", "B"])
    _run_adjustments(second, weights, codes=["B", "A"])
    return first, second


def _sizes(state):
    return {symbol: position.size for symbol, position in state.items()}


def test_position_adjustment_rejects_unknown_mode():
    with pytest.raises(ValueError, match="position_adjustment"):
        _AdjustmentEngine(position_adjustment="resize")


def test_hold_mode_keeps_same_direction_size():
    engine = _AdjustmentEngine(position_adjustment="hold")
    _run_adjustments(engine, {"A": [0.25, 0.50, 0.20]})
    assert [state["A"].size for state in engine.bar_positions] == [2.5, 2.5, 2.5]


def test_hold_mode_preserves_legacy_negative_open_support():
    engine = _AdjustmentEngine(position_adjustment="hold", allow_nonpositive_prices=True)
    _run_adjustments(engine, {"A": [0.50]}, execution_prices={"A": [-100.0]})
    assert engine.bar_positions[0]["A"].entry_price == -100.0


@pytest.mark.parametrize(
    ("existing", "target_weight"), [(False, 0.50), (True, 0.0), (True, -0.50), (True, 0.80), (True, 0.20)],
    ids=("initial-open", "full-close", "reversal", "increase", "reduction"))
@pytest.mark.parametrize(
    ("raw_price", "forced_fill"),
    [(0.0, None), (-1.0, None), (np.nan, None), (np.inf, None), (100.0, 0.0), (100.0, -1.0), (100.0, np.nan), (100.0, np.inf)],
    ids=("zero-raw", "negative-raw", "nan-raw", "infinite-raw", "zero-fill", "negative-fill", "nan-fill", "infinite-fill"),
)
def test_rebalance_rejects_invalid_execution_prices_before_mutation(
    existing, target_weight, raw_price, forced_fill
):
    engine = _ForcedFillAdjustmentEngine(
        allow_nonpositive_prices=True, forced_fill_price=forced_fill
    )
    if existing:
        engine.positions["A"] = _position()
    positions = dict(engine.positions)

    with pytest.raises(ValueError, match="positive execution price"):
        _rebalance_once(engine, target_weight, raw_price)
    _assert_unchanged(engine, positions)


def test_rebalance_empty_zero_target_ignores_invalid_price():
    engine = _ForcedFillAdjustmentEngine(
        allow_nonpositive_prices=True, forced_fill_price=0.0
    )
    _rebalance_once(engine, 0.0, raw_price=0.0)
    _assert_unchanged(engine)


def test_rebalance_increases_then_reduces_same_direction_position():
    engine = _AdjustmentEngine()
    _run_adjustments(engine, {"A": [0.25, 0.50, 0.20]})
    assert [state["A"].size for state in engine.bar_positions] == [2.5, 5.0, 2.0]
    partial = next(t for t in engine.trades if t.exit_reason == "target_rebalance")
    assert partial.size == 3.0
    assert partial.entry_margin == 300.0
    assert partial.pnl == 0.0


def test_rebalance_persists_immutable_fill_deltas_and_weighted_holding():
    engine = _AdjustmentEngine()
    _run_adjustments(engine, {"A": [0.25, 0.50, 0.20]})

    assert [fill.action for fill in engine.fill_records] == [
        "open",
        "increase",
        "reduce",
        "close",
    ]
    assert [fill.signed_quantity for fill in engine.fill_records] == pytest.approx(
        [2.5, 2.5, -3.0, -2.0]
    )
    assert [fill.notional for fill in engine.fill_records] == pytest.approx(
        [250.0, 250.0, 300.0, 200.0]
    )
    assert [fill.margin for fill in engine.fill_records] == pytest.approx(
        [250.0, 250.0, 300.0, 200.0]
    )
    assert [fill.execution_price for fill in engine.fill_records] == pytest.approx(
        [100.0, 100.0, 100.0, 100.0]
    )
    assert [fill.fee for fill in engine.fill_records] == pytest.approx([0.0] * 4)
    assert [fill.holding_bars for fill in engine.fill_records] == [None, None, 1.5, 1.5]
    assert [trade.holding_bars for trade in engine.trades] == pytest.approx([1.5, 1.5])

    with pytest.raises(FrozenInstanceError):
        engine.fill_records[0].fee = 1.0  # type: ignore[misc]


def test_fill_delta_artifact_is_jsonl_and_exposes_weighted_holding(tmp_path):
    engine = _AdjustmentEngine()
    weights = {"A": [0.25, 0.50, 0.20]}
    _run_adjustments(engine, weights)
    dates = pd.date_range("2026-01-02", periods=3)
    prices = pd.DataFrame({"open": 100.0, "close": 100.0}, index=dates)
    equity = pd.Series(
        [snapshot.equity for snapshot in engine.equity_snapshots], index=dates
    )
    engine._write_artifacts(
        tmp_path,
        {"A": prices},
        dates,
        equity,
        pd.Series(1_000.0, index=dates),
        pd.Series(0.0, index=dates),
        pd.DataFrame(weights, index=dates),
        {},
        ["A"],
    )

    rows = [
        json.loads(line)
        for line in (tmp_path / "artifacts" / "fills.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert [row["action"] for row in rows] == ["open", "increase", "reduce", "close"]
    assert rows[2]["holding_bars"] == pytest.approx(1.5)

    trades = pd.read_csv(tmp_path / "artifacts" / "trades.csv")
    exits = trades[trades["pnl"].notna() & (trades["reason"] != "signal")]
    assert exits["holding_bars"].tolist() == pytest.approx([1.5, 1.5])


def test_partial_reduction_allocates_nonzero_entry_and_exit_fees():
    engine = _AdjustmentEngine(fee_rate=0.01)
    _run_adjustments(engine, {"A": [0.50, 0.20]})

    partial = next(t for t in engine.trades if t.exit_reason == "target_rebalance")
    event = next(e for e in engine.adjustment_events if e["action"] == "partial_reduction")
    remaining = engine.bar_positions[1]["A"]
    allocated_entry_fee = event["before"].entry_commission - remaining.entry_commission
    assert (allocated_entry_fee, event["trading_fee"]) == pytest.approx((3.01, 3.01))
    assert (partial.commission, remaining.entry_commission) == pytest.approx((6.02, 1.99))
    assert engine.bar_capitals[1] == pytest.approx(792.99)


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
    assert engine.bar_positions == [{"A": _position(size=2.5)}]


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


@pytest.mark.parametrize(
    ("direction", "target_weight", "expected_size", "expected_price", "action"),
    [(1, 0.80, 7.272727, 110.0, "increase"), (-1, -0.80, 8.888889, 90.0, "increase"), (1, 0.20, 2.222222, 90.0, "partial_reduction"), (-1, -0.20, 1.818182, 110.0, "partial_reduction")])
def test_existing_rebalance_sizes_target_at_action_fill(
    direction, target_weight, expected_size, expected_price, action
):
    engine = _AdjustmentEngine(slippage=0.10)
    engine.positions["A"] = _position(direction)
    _rebalance_once(engine, target_weight)

    assert engine.positions["A"].size == expected_size
    assert engine.adjustment_events[-1]["action"] == action
    assert engine.adjustment_events[-1]["execution_price"] == pytest.approx(expected_price)


@pytest.mark.parametrize("direction", [1, -1])
def test_existing_rebalance_does_not_churn_inside_slippage_band(direction):
    engine = _AdjustmentEngine(slippage=0.10)
    before = _position(direction)
    engine.positions["A"] = before
    _rebalance_once(engine, direction * 0.50)
    _assert_unchanged(engine, {"A": before})


def test_rebalance_insufficient_capital_is_atomic():
    engine = _AdjustmentEngine(fee_rate=0.10)
    with pytest.raises(ValueError, match="insufficient capital"):
        _run_adjustments(engine, {"A": [1.0]})
    _assert_unchanged(engine)


def test_existing_multi_symbol_rebalance_failure_is_atomic():
    engine = _AdjustmentEngine(fee_rate=0.01)

    with pytest.raises(ValueError, match="insufficient capital"):
        _run_adjustments(engine, {"A": [0.25, 0.10], "B": [0.25, 0.90]})

    assert engine.capital == engine.bar_capitals[0] == 495.0
    assert engine.positions == engine.bar_positions[0]
    assert engine.trades == []
    assert engine.adjustment_events == []
    assert len(engine.bar_positions) == 1


@pytest.mark.parametrize(
    ("target_weight", "expected_position", "bar_capital", "trade_fees"),
    [(0.0, None, 990.0, [10.0]), (-0.50, (-1, 4.975, 4.975), 487.525, [10.0, 9.95])])
def test_rebalance_full_zero_and_reversal_allocate_nonzero_fees(
    target_weight, expected_position, bar_capital, trade_fees
):
    engine = _AdjustmentEngine(fee_rate=0.01)

    _run_adjustments(engine, {"A": [0.50, target_weight]})

    position = engine.bar_positions[1].get("A")
    actual_position = None if position is None else (position.direction, position.size, position.entry_commission)
    assert actual_position == expected_position
    assert engine.bar_capitals[1] == pytest.approx(bar_capital)
    assert [trade.commission for trade in engine.trades] == pytest.approx(trade_fees)
    assert engine.trades[0].exit_reason == "signal"


def test_rebalance_basket_is_independent_of_input_code_order():
    weights = {"A": [0.50], "B": [0.50]}
    first, second = _run_both_code_orders(_AdjustmentEngine, weights)
    assert _sizes(first.bar_positions[0]) == {"A": 5.0, "B": 5.0}
    assert first.bar_positions == second.bar_positions
    assert [snapshot.capital for snapshot in first.equity_snapshots] == [
        snapshot.capital for snapshot in second.equity_snapshots
    ]


def test_existing_rebalance_uses_each_symbol_rules_independent_of_code_order():
    weights = {"A": [0.20, 0.35], "B": [0.20, 0.15]}
    first, second = _run_both_code_orders(_SymbolRulesAdjustmentEngine, weights)
    expected = [{"A": 2.0, "B": 2.0}, {"A": 3.0, "B": 1.25}]
    assert [_sizes(state) for state in first.bar_positions] == expected
    assert first.bar_positions == second.bar_positions
    assert first.bar_capitals == pytest.approx([594.0, 566.5])
    assert first.bar_capitals == second.bar_capitals


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
