"""Phase 7 end-to-end acceptance against a fixed historical SPY fixture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest.engines.global_equity import GlobalEquityEngine


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "spy_phase7_2024.csv"
SYMBOL = "SPY.US"
STARTING_CAPITAL = 100_000.0
FIXTURE_SHA256 = "925caa4dbce36342cf89bf66a7dd88096439896565ad3931cac5978119df424d"


class HistoricalFixtureLoader:
    """Offline loader for immutable, real SPY OHLCV observations."""

    name = "fixed-historical-spy-yfinance-cache"

    def __init__(self) -> None:
        frame = pd.read_csv(FIXTURE_PATH, parse_dates=["trade_date"])
        frame = frame.set_index("trade_date").sort_index()
        frame.index.name = "trade_date"
        self.frame = frame

    def fetch(self, codes, start_date, end_date, **kwargs):
        start = pd.Timestamp(start_date) if start_date else self.frame.index[0]
        end = pd.Timestamp(end_date) if end_date else self.frame.index[-1]
        sliced = self.frame.loc[start:end].copy()
        return {code: sliced.copy() for code in codes if code == SYMBOL}


class TwoCycleSignal:
    """Two deterministic long/cash cycles; no parameter fitting involved."""

    def generate(self, data_map):
        signals = {}
        for symbol, frame in data_map.items():
            values = np.zeros(len(frame), dtype=float)
            values[1:12] = 1.0
            values[18:31] = 1.0
            signals[symbol] = pd.Series(values, index=frame.index)
        return signals


class ConstantLongSignal:
    def generate(self, data_map):
        return {
            symbol: pd.Series(1.0, index=frame.index)
            for symbol, frame in data_map.items()
        }


class CostedUSEquityEngine(GlobalEquityEngine):
    """US equity engine with an explicit one-basis-point commission."""

    def calc_commission(
        self,
        size: float,
        price: float,
        direction: int,
        is_open: bool,
    ) -> float:
        return abs(float(size) * float(price)) * 0.0001


def _base_config() -> dict:
    return {
        "codes": [SYMBOL],
        "start_date": "2024-01-02",
        "end_date": "2024-02-29",
        "interval": "1D",
        "source": "fixed-historical-spy-yfinance-cache",
        "engine": "global_equity",
        "initial_cash": STARTING_CAPITAL,
        "slippage_us": 0.0005,
    }


def _prepare_run_directory(run_dir: Path, config: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "code").mkdir(exist_ok=True)
    (run_dir / "config.json").write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "code" / "signal_engine.py").write_text(
        "# Fixed two-cycle acceptance signal; see test_phase7_execution_acceptance.py\n",
        encoding="utf-8",
    )


def test_phase7_historical_execution_and_artifact_reconciliation(
    tmp_path: Path,
) -> None:
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == FIXTURE_SHA256
    config = {
        **_base_config(),
        "order_type": "limit",
        "limit_price_offset_bps": 5.0,
        "time_in_force": "GTC",
        "execution_latency_bars": 1,
        "order_expiry_bars": 5,
        "max_unfilled_bars": 3,
        "volume_participation_rate": 0.000001,
        "validation": {
            "monte_carlo": {"n_simulations": 50, "seed": 7},
            "bootstrap": {"n_bootstrap": 50, "confidence": 0.95, "seed": 7},
            "walk_forward": {"n_windows": 4},
        },
    }
    run_dir = tmp_path / "phase7_spy_acceptance"
    _prepare_run_directory(run_dir, config)
    engine = CostedUSEquityEngine(config, market="us")
    loader = HistoricalFixtureLoader()
    assert len(loader.frame) == 41
    assert loader.frame.index[0] == pd.Timestamp("2024-01-02")
    assert loader.frame.index[-1] == pd.Timestamp("2024-02-29")
    assert (loader.frame["volume"] > 0.0).all()

    metrics = engine.run_backtest(
        config,
        loader,
        TwoCycleSignal(),
        run_dir,
        bars_per_year=252,
    )

    artifacts = run_dir / "artifacts"
    expected_artifacts = {
        f"ohlcv_{SYMBOL}.csv",
        "equity.csv",
        "positions.csv",
        "executed_positions.csv",
        "fills.csv",
        "orders.csv",
        "trades.csv",
        "metrics.csv",
        "daily_accounting.csv",
        "performance_summary.json",
        "performance_summary.csv",
        "monthly_returns.csv",
        "drawdown_periods.csv",
        "asset_attribution.csv",
        "cost_reconciliation.csv",
        "concentration.csv",
        "performance_report.md",
        "validation.json",
    }
    assert expected_artifacts.issubset({path.name for path in artifacts.iterdir()})
    assert (run_dir / "run_card.json").is_file()
    assert (run_dir / "run_card.md").is_file()

    fills = pd.read_csv(artifacts / "fills.csv")
    orders = pd.read_csv(artifacts / "orders.csv")
    trades = pd.read_csv(artifacts / "trades.csv")
    accounting = pd.read_csv(artifacts / "daily_accounting.csv")
    reconciliation = pd.read_csv(artifacts / "cost_reconciliation.csv").iloc[0]
    summary = json.loads(
        (artifacts / "performance_summary.json").read_text(encoding="utf-8")
    )
    validation = json.loads(
        (artifacts / "validation.json").read_text(encoding="utf-8")
    )
    run_card = json.loads((run_dir / "run_card.json").read_text(encoding="utf-8"))

    assert not fills.empty
    assert not orders.empty
    assert not trades.empty
    assert set(validation) == {"monte_carlo", "bootstrap", "walk_forward"}
    assert run_card["data_sources"] == [HistoricalFixtureLoader.name]
    assert run_card["backtest"]["initial_cash"] == STARTING_CAPITAL

    order_ids = set(orders["order_id"])
    assert fills["order_id"].notna().all()
    assert set(fills["order_id"]).issubset(order_ids)
    assert set(fills["symbol"]) == {SYMBOL}
    assert set(orders["symbol"]) == {SYMBOL}
    assert set(orders["status"]).issubset({
        "filled", "cancelled", "expired", "rejected",
    })

    lifecycle_total = (
        orders["filled_quantity"]
        + orders["remaining_quantity"]
        + orders["cancelled_quantity"]
    )
    assert np.allclose(
        orders["requested_quantity"], lifecycle_total, rtol=0.0, atol=1e-8,
    )
    filled_by_order = fills.groupby("order_id")["quantity"].sum()
    for row in orders.itertuples(index=False):
        assert filled_by_order.get(row.order_id, 0.0) == pytest.approx(
            row.filled_quantity,
            abs=1e-8,
        )

    entry_quantity = fills.loc[fills["event_type"] == "entry", "quantity"].sum()
    exit_quantity = fills.loc[fills["event_type"] == "exit", "quantity"].sum()
    completed_size = trades.loc[trades["pnl"] != 0.0, "qty"].sum()
    assert entry_quantity == pytest.approx(completed_size, abs=1e-6)
    assert exit_quantity == pytest.approx(completed_size, abs=1e-6)

    for trade in engine.trades:
        trade_fills = fills[
            (fills["symbol"] == trade.symbol)
            & (pd.to_datetime(fills["timestamp"]) >= trade.entry_time)
            & (pd.to_datetime(fills["timestamp"]) <= trade.exit_time)
        ]
        assert trade_fills.loc[
            trade_fills["event_type"] == "entry", "quantity"
        ].sum() == pytest.approx(trade.size, abs=1e-6)
        assert trade_fills.loc[
            trade_fills["event_type"] == "exit", "quantity"
        ].sum() == pytest.approx(trade.size, abs=1e-6)

    assert reconciliation["reconciliation_status"] == "reconciled"
    assert reconciliation["difference"] == pytest.approx(0.0, abs=1e-8)
    assert reconciliation["commission_difference"] == pytest.approx(
        0.0, abs=1e-8,
    )
    assert reconciliation["slippage_difference"] == pytest.approx(
        0.0, abs=1e-8,
    )
    assert engine.capital == pytest.approx(
        STARTING_CAPITAL + sum(float(trade.net_pnl) for trade in engine.trades),
        abs=1e-6,
    )
    assert accounting.iloc[-1]["equity"] == pytest.approx(engine.capital, abs=1e-6)
    assert summary["ending_capital"] == pytest.approx(engine.capital, abs=1e-6)
    assert metrics["total_commission"] == pytest.approx(
        fills["commission"].sum(), abs=1e-8,
    )
    assert metrics["total_slippage_cost"] == pytest.approx(
        fills["slippage_cost"].sum(), abs=1e-8,
    )
    assert metrics["total_commission"] > 0.0

    # Golden execution outputs freeze this exact fixture/config combination.
    assert metrics["final_value"] == pytest.approx(
        102_911.49884971681, abs=1e-8,
    )
    assert metrics["total_return"] == pytest.approx(
        0.029114988497167982, abs=1e-12,
    )
    assert metrics["trade_count"] == 1
    assert metrics["order_count"] == pytest.approx(4.0)
    assert metrics["filled_order_count"] == pytest.approx(2.0)
    assert metrics["cancelled_order_count"] == pytest.approx(2.0)
    assert metrics["partial_fill_order_count"] == pytest.approx(2.0)
    assert metrics["limit_fill_count"] == pytest.approx(7.0)
    assert metrics["total_filled_quantity"] == pytest.approx(421.58, abs=1e-8)
    assert metrics["total_commission"] == pytest.approx(
        20.25495447950127, abs=1e-8,
    )
    assert metrics["total_slippage_cost"] == pytest.approx(
        62.6819572363223, abs=1e-8,
    )

    normal_fills = fills[~fills["volume_limit_exempt"].astype(bool)]
    capacity_by_bar = normal_fills.groupby(["timestamp", "symbol"]).agg(
        quantity=("quantity", "sum"),
        capacity=("bar_volume_capacity", "max"),
    )
    assert (capacity_by_bar["quantity"] <= capacity_by_bar["capacity"] + 1e-8).all()
    assert metrics["volume_limit_violation_count"] == pytest.approx(0.0)
    assert metrics["limit_price_violation_count"] == pytest.approx(0.0)
    assert metrics["execution_before_eligibility_count"] == pytest.approx(0.0)
    assert metrics["unlinked_fill_count"] == pytest.approx(0.0)
    assert metrics["orphan_fill_count"] == pytest.approx(0.0)
    assert metrics["fill_quantity_mismatch_count"] == pytest.approx(0.0)
    assert metrics["order_lifecycle_violation_count"] == pytest.approx(0.0)
    assert not engine.positions
    assert not engine.pending_orders
    assert engine.equity_snapshots[-1].positions == 0


def test_phase7_default_no_participation_preserves_full_fill(
    tmp_path: Path,
) -> None:
    config = _base_config()
    run_dir = tmp_path / "phase7_default_execution"
    _prepare_run_directory(run_dir, config)
    engine = CostedUSEquityEngine(config, market="us")

    metrics = engine.run_backtest(
        config,
        HistoricalFixtureLoader(),
        ConstantLongSignal(),
        run_dir,
        bars_per_year=252,
    )

    entry_orders = [order for order in engine.orders if order.event_type == "entry"]
    entry_fills = [fill for fill in engine.fills if fill.event_type == "entry"]
    assert len(entry_orders) == 1
    assert len(entry_fills) == 1
    assert entry_orders[0].status == "filled"
    assert entry_orders[0].filled_quantity == pytest.approx(
        entry_orders[0].requested_quantity
    )
    assert not entry_orders[0].volume_constrained
    assert entry_fills[0].participation_rate is None
    assert metrics["partial_fill_order_count"] == pytest.approx(0.0)
    assert metrics["volume_constrained_order_count"] == pytest.approx(0.0)
    assert metrics["order_lifecycle_violation_count"] == pytest.approx(0.0)
