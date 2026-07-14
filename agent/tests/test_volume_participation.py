"""Adversarial tests for Phase 6A bar-volume participation limits."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest.engines.base import BaseEngine
from backtest.metrics import calc_execution_metrics
from backtest.models import FillRecord
from backtest.reporting import build_reporting_outputs


class VolumeParticipationEngine(BaseEngine):
    """Minimal deterministic engine for execution-cap tests."""

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        return True

    def round_size(self, raw_size: float, price: float) -> float:
        return round(max(float(raw_size), 0.0), 8)

    def calc_commission(
        self,
        size: float,
        price: float,
        direction: int,
        is_open: bool,
    ) -> float:
        return 0.0

    def apply_slippage(self, price: float, direction: int) -> float:
        return float(price)


class NearestCentSizeEngine(VolumeParticipationEngine):
    """Round to nearest hundredth to exercise post-rounding cap safety."""

    def round_size(self, raw_size: float, price: float) -> float:
        return round(max(float(raw_size), 0.0), 2)


class StaticLoader:
    def __init__(self, data_map: dict[str, pd.DataFrame]):
        self.data_map = data_map
        self.name = "test"

    def fetch(self, *args, **kwargs):
        return {symbol: frame.copy() for symbol, frame in self.data_map.items()}


class ConstantLongSignal:
    def generate(self, data_map):
        return {
            symbol: pd.Series(1.0, index=frame.index)
            for symbol, frame in data_map.items()
        }


def _bar(price: float = 10.0, volume: object = 100.0) -> pd.Series:
    return pd.Series({"open": price, "close": price, "volume": volume})


def _entry_order(
    engine: BaseEngine,
    symbol: str,
    quantity: float,
    timestamp: pd.Timestamp,
    *,
    direction: int = 1,
):
    return engine._create_order(
        symbol=symbol,
        event_type="entry",
        direction=direction,
        quantity=quantity,
        timestamp=timestamp,
        decision_price=10.0,
        reason="signal",
        signal_time=timestamp - pd.Timedelta(days=1),
    )


def test_default_configuration_preserves_legacy_full_fill() -> None:
    engine = VolumeParticipationEngine({"initial_cash": 100_000.0})
    timestamp = pd.Timestamp("2025-01-01")
    order = _entry_order(engine, "X", 25.0, timestamp)

    executed = engine._process_order(order, _bar(volume=1.0), timestamp)

    assert executed == pytest.approx(25.0)
    assert order.status == "filled"
    assert order.volume_constrained is False
    assert engine.fills[0].participation_rate is None


def test_global_participation_limit_fills_across_bars_and_preserves_lifecycle() -> None:
    engine = VolumeParticipationEngine({
        "initial_cash": 100_000.0,
        "volume_participation_rate": 0.10,
    })
    dates = pd.date_range("2025-02-01", periods=3, freq="D")
    order = _entry_order(engine, "X", 25.0, dates[0])

    executed = [
        engine._process_order(order, _bar(volume=100.0), timestamp)
        for timestamp in dates
    ]

    assert executed == pytest.approx([10.0, 10.0, 5.0])
    assert order.status == "filled"
    assert order.volume_constrained is True
    assert order.volume_constrained_bars == 2
    assert order.requested_quantity == pytest.approx(
        order.filled_quantity
        + float(order.remaining_quantity or 0.0)
        + order.cancelled_quantity
    )
    assert all(fill.bar_volume == pytest.approx(100.0) for fill in engine.fills)
    assert all(fill.participation_rate == pytest.approx(0.10) for fill in engine.fills)
    assert all(fill.bar_volume_capacity == pytest.approx(10.0) for fill in engine.fills)

    metrics = calc_execution_metrics(
        pd.DataFrame(), engine.fills, 3, orders=engine.orders,
    )
    assert metrics["volume_constrained_order_count"] == pytest.approx(1.0)
    assert metrics["volume_constraint_event_count"] == pytest.approx(2.0)
    assert metrics["volume_participation_fill_quantity"] == pytest.approx(25.0)
    assert metrics["max_observed_volume_participation"] == pytest.approx(0.10)
    assert metrics["volume_limit_violation_count"] == pytest.approx(0.0)


def test_symbol_specific_rates_and_default_are_independent() -> None:
    engine = VolumeParticipationEngine({
        "initial_cash": 100_000.0,
        "volume_participation_rate": {"A": 0.10, "B": 0.25, "default": 0.05},
    })
    timestamp = pd.Timestamp("2025-03-01")

    quantities = {}
    for symbol in ("A", "B", "C"):
        order = _entry_order(engine, symbol, 50.0, timestamp)
        quantities[symbol] = engine._process_order(
            order, _bar(volume=100.0), timestamp,
        )

    assert quantities == pytest.approx({"A": 10.0, "B": 25.0, "C": 5.0})
    assert {fill.symbol: fill.participation_rate for fill in engine.fills} == pytest.approx({
        "A": 0.10,
        "B": 0.25,
        "C": 0.05,
    })


def test_multiple_fills_share_one_symbol_bar_capacity_budget() -> None:
    engine = VolumeParticipationEngine({
        "initial_cash": 100_000.0,
        "volume_participation_rate": 0.10,
    })
    timestamp = pd.Timestamp("2025-04-01")
    entry = _entry_order(engine, "X", 6.0, timestamp)
    engine._process_order(entry, _bar(volume=100.0), timestamp)

    exit_order = engine._create_order(
        symbol="X",
        event_type="exit",
        direction=1,
        quantity=6.0,
        timestamp=timestamp,
        decision_price=10.0,
        reason="signal",
    )
    executed_exit = engine._process_order(
        exit_order, _bar(volume=100.0), timestamp,
    )

    assert executed_exit == pytest.approx(4.0)
    assert exit_order.status == "partially_filled"
    assert engine.positions["X"].size == pytest.approx(2.0)
    same_bar_quantity = sum(
        fill.quantity
        for fill in engine.fills
        if fill.symbol == "X" and fill.timestamp == timestamp
    )
    assert same_bar_quantity == pytest.approx(10.0)


@pytest.mark.parametrize(
    "bar",
    [
        pd.Series({"open": 10.0, "close": 10.0}),
        _bar(volume=0.0),
        _bar(volume=np.nan),
        _bar(volume="invalid"),
    ],
    ids=["missing", "zero", "nan", "invalid"],
)
def test_missing_or_invalid_volume_has_zero_capacity(bar: pd.Series) -> None:
    engine = VolumeParticipationEngine({
        "initial_cash": 100_000.0,
        "volume_participation_rate": 0.10,
    })
    timestamp = pd.Timestamp("2025-05-01")
    order = _entry_order(engine, "X", 5.0, timestamp)

    assert engine._process_order(order, bar, timestamp) == pytest.approx(0.0)
    assert order.status == "open"
    assert order.volume_constrained is True
    assert not engine.fills
    assert not engine.positions
    assert engine.capital == pytest.approx(engine.initial_capital)


@pytest.mark.parametrize("rate", [-0.01, 1.01, np.nan, np.inf, True, "bad"])
def test_invalid_participation_rates_are_rejected(rate: object) -> None:
    with pytest.raises(ValueError, match="volume_participation_rate"):
        VolumeParticipationEngine({"volume_participation_rate": rate})


def test_zero_participation_rate_is_valid_and_prevents_fills() -> None:
    engine = VolumeParticipationEngine({
        "initial_cash": 100_000.0,
        "volume_participation_rate": 0.0,
    })
    timestamp = pd.Timestamp("2025-06-01")
    order = _entry_order(engine, "X", 1.0, timestamp)

    assert engine._process_order(order, _bar(volume=1_000.0), timestamp) == 0.0
    assert order.volume_constrained is True
    assert not engine.fills


def test_market_rounding_cannot_push_fill_above_capacity() -> None:
    engine = NearestCentSizeEngine({
        "initial_cash": 100_000.0,
        "volume_participation_rate": 0.005,
    })
    timestamp = pd.Timestamp("2025-07-01")
    order = _entry_order(engine, "X", 1.0, timestamp)

    executed = engine._process_order(order, _bar(volume=1.0), timestamp)

    assert executed <= 0.005 + 1e-12
    assert not engine.fills
    assert order.status == "open"


def test_forced_terminal_close_is_explicitly_exempt_and_finishes_flat() -> None:
    engine = VolumeParticipationEngine({
        "initial_cash": 100_000.0,
        "volume_participation_rate": 0.10,
    })
    dates = pd.date_range("2025-08-01", periods=2, freq="D")
    entry = _entry_order(engine, "X", 5.0, dates[0])
    engine._process_order(entry, _bar(volume=100.0), dates[0])

    engine._bar_idx = 1
    engine._close_position(
        "X", 11.0, dates[1], "end_of_backtest", exit_decision_price=11.0,
    )

    assert not engine.positions
    assert len(engine.trades) == 1
    assert engine.fills[-1].volume_limit_exempt is True
    metrics = calc_execution_metrics(
        pd.DataFrame(), engine.fills, 2, orders=engine.orders,
    )
    assert metrics["volume_limit_exempt_fill_count"] == pytest.approx(1.0)
    assert metrics["volume_limit_violation_count"] == pytest.approx(0.0)


def test_metrics_detect_aggregate_capacity_violation() -> None:
    timestamp = pd.Timestamp("2025-09-01")
    fills = [
        FillRecord(
            timestamp, "X", "buy", "entry", 1, quantity, 10.0, 10.0,
            quantity * 10.0, 0.0, 0.0, "signal",
            order_id=f"order-{index}", bar_volume=100.0,
            participation_rate=0.10, bar_volume_capacity=10.0,
        )
        for index, quantity in enumerate((6.0, 5.0), start=1)
    ]

    metrics = calc_execution_metrics(pd.DataFrame(), fills, 1)

    assert metrics["max_observed_volume_participation"] == pytest.approx(0.11)
    assert metrics["volume_limit_violation_count"] == pytest.approx(1.0)


def test_volume_fields_are_written_to_artifacts_and_report(
    tmp_path: Path,
) -> None:
    engine = VolumeParticipationEngine({
        "initial_cash": 100_000.0,
        "volume_participation_rate": 0.10,
    })
    timestamp = pd.Timestamp("2025-10-01")
    order = _entry_order(engine, "X", 15.0, timestamp)
    engine._process_order(order, _bar(volume=100.0), timestamp)

    dates = pd.DatetimeIndex([timestamp])
    data_map = {
        "X": pd.DataFrame(
            {"open": [10.0], "close": [10.0], "volume": [100.0]},
            index=dates,
        )
    }
    equity = pd.Series([100_000.0], index=dates)
    engine._write_artifacts(
        tmp_path,
        data_map,
        dates,
        equity,
        equity,
        pd.Series([0.0], index=dates),
        pd.DataFrame({"X": [0.0]}, index=dates),
        {},
        ["X"],
    )

    fills = pd.read_csv(tmp_path / "artifacts" / "fills.csv")
    orders = pd.read_csv(tmp_path / "artifacts" / "orders.csv")
    assert fills.loc[0, "bar_volume"] == pytest.approx(100.0)
    assert fills.loc[0, "participation_rate"] == pytest.approx(0.10)
    assert fills.loc[0, "bar_volume_capacity"] == pytest.approx(10.0)
    assert not bool(fills.loc[0, "volume_limit_exempt"])
    assert bool(orders.loc[0, "volume_constrained"])
    assert orders.loc[0, "volume_constrained_bars"] == 1

    outputs = build_reporting_outputs(
        daily_accounting=pd.DataFrame(),
        executed_positions=pd.DataFrame(),
        trades=[],
        fills=engine.fills,
        orders=engine.orders,
        scalar_metrics={},
        starting_capital=engine.initial_capital,
        bars_per_year=252,
    )
    summary = outputs["performance_summary"]
    assert summary["volume_constrained_order_count"] == 1
    assert summary["max_observed_volume_participation"] == pytest.approx(0.10)
    assert summary["volume_limit_violation_count"] == 0
    assert "Volume-constrained orders: 1" in outputs["performance_report"]


def test_full_backtest_enforces_cap_and_reconciles_terminal_state(
    tmp_path: Path,
) -> None:
    dates = pd.date_range("2025-11-01", periods=4, freq="D")
    data_map = {
        "X": pd.DataFrame({
            "open": [10.0, 10.0, 10.0, 10.0],
            "high": [10.0, 10.0, 10.0, 10.0],
            "low": [10.0, 10.0, 10.0, 10.0],
            "close": [10.0, 10.0, 10.0, 10.0],
            "volume": [100.0, 100.0, 100.0, 100.0],
        }, index=dates),
    }
    config = {
        "codes": ["X"],
        "start_date": str(dates[0].date()),
        "end_date": str(dates[-1].date()),
        "source": "test",
        "initial_cash": 100_000.0,
        "volume_participation_rate": 0.10,
    }
    engine = VolumeParticipationEngine(config)

    metrics = engine.run_backtest(
        config,
        StaticLoader(data_map),
        ConstantLongSignal(),
        tmp_path,
        bars_per_year=252,
    )

    normal_fills = [fill for fill in engine.fills if not fill.volume_limit_exempt]
    quantity_by_bar: dict[tuple[pd.Timestamp, str], float] = {}
    for fill in normal_fills:
        key = (fill.timestamp, fill.symbol)
        quantity_by_bar[key] = quantity_by_bar.get(key, 0.0) + fill.quantity
    assert quantity_by_bar
    assert all(quantity <= 10.0 + 1e-9 for quantity in quantity_by_bar.values())
    assert metrics["volume_limit_violation_count"] == pytest.approx(0.0)
    assert metrics["max_observed_volume_participation"] <= 0.10 + 1e-12
    assert not engine.positions
    assert engine.equity_snapshots[-1].positions == 0
    assert engine.equity_snapshots[-1].unrealized == pytest.approx(0.0)
    assert any(fill.volume_limit_exempt for fill in engine.fills)
    for order in engine.orders:
        assert order.requested_quantity == pytest.approx(
            order.filled_quantity
            + float(order.remaining_quantity or 0.0)
            + order.cancelled_quantity
        )

    artifact_fills = pd.read_csv(tmp_path / "artifacts" / "fills.csv")
    assert artifact_fills["volume_limit_exempt"].sum() == 1
    assert artifact_fills.loc[
        ~artifact_fills["volume_limit_exempt"], "quantity"
    ].max() <= 10.0 + 1e-9
