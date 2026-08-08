"""Tests for CryptoEngine market rules.

Validates:
  - 24/7 execution (no direction/time restrictions)
  - Fractional position sizing
  - Maker/Taker fee separation
  - Funding fee settlement (every 8 hours)
  - Forced liquidation (maintenance margin check)
  - Tiered maintenance margin rates
"""

from __future__ import annotations

import json
import math

import pandas as pd
import pytest

from backtest.engines.crypto import CryptoEngine
from backtest.engines._market_hooks import (
    FUNDING_HOURS as _FUNDING_HOURS,
    _maintenance_rate,
)
from backtest.models import Position

_BRACKETS = (
    '[{"bracket_tier":1,"notional_cap":1000000.0,'
    '"maintenance_rate":0.004,"cumulative_maintenance_amount":0.0}]'
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bar(close: float = 60000.0, open_: float | None = None) -> pd.Series:
    return pd.Series({"close": close, "open": open_ or close})


def _make_engine(**overrides) -> CryptoEngine:
    config = {
        "initial_cash": 100_000,
        "leverage": 10.0,
        "maker_rate": 0.0002,
        "taker_rate": 0.0005,
        "funding_rate": 0.0001,
    }
    config.update(overrides)
    return CryptoEngine(config)


def _strict_engine(**overrides) -> CryptoEngine:
    config = {
        "initial_cash": 1_000.0,
        "leverage": 10.0,
        "maker_rate": 0.0002,
        "taker_rate": 0.0005,
        "slippage": 0.0,
        "perpetual_strict": True,
        "funding_mode": "data",
        "margin_mode": "isolated",
    }
    config.update(overrides)
    return CryptoEngine(config)


def _strict_frame(
    dates: pd.DatetimeIndex,
    *,
    price: float = 100.0,
    mark: list[float] | None = None,
    execution_open: list[float] | None = None,
    mark_open: list[float] | None = None,
    mark_high: list[float] | None = None,
    mark_low: list[float] | None = None,
    mark_close: list[float] | None = None,
    funding_rate: list[float] | None = None,
    settlements: list[pd.Timestamp | None] | None = None,
) -> pd.DataFrame:
    base = [price] * len(dates)
    marks = mark or base
    return pd.DataFrame(
        {
            "execution_open": execution_open or base,
            "mark_open": mark_open or marks,
            "mark_high": mark_high or marks,
            "mark_low": mark_low or marks,
            "mark_close": mark_close or marks,
            "funding_rate": funding_rate or [0.0] * len(dates),
            "funding_settlement_time": settlements or [pd.NaT] * len(dates),
            "maintenance_brackets": [_BRACKETS] * len(dates),
            "maintenance_bracket_version": ["fixture-v1"] * len(dates),
        },
        index=dates,
    )


def _run_strict(
    engine: CryptoEngine,
    data_map: dict[str, pd.DataFrame],
    targets: dict[str, list[float]],
) -> None:
    dates = next(iter(data_map.values())).index
    codes = list(data_map)
    engine._execute_bars(
        dates,
        data_map,
        pd.DataFrame(index=dates),
        pd.DataFrame(targets, index=dates),
        codes,
    )


def _write_strict_artifacts(
    engine: CryptoEngine,
    data_map: dict[str, pd.DataFrame],
    targets: dict[str, list[float]],
    run_dir,
) -> dict:
    dates = next(iter(data_map.values())).index
    equity = pd.Series(
        [snapshot.equity for snapshot in engine.equity_snapshots],
        index=[snapshot.timestamp for snapshot in engine.equity_snapshots],
    )
    benchmark_return = pd.Series(0.0, index=dates)
    metrics: dict = {}
    engine._write_artifacts(
        run_dir,
        data_map,
        dates,
        equity,
        pd.Series(engine.initial_capital, index=dates),
        benchmark_return,
        pd.DataFrame(targets, index=dates),
        metrics,
        list(data_map),
    )
    return metrics


def _read_strict_evidence(run_dir) -> tuple[list[dict], dict]:
    artifacts = run_dir / "artifacts"
    events = [
        json.loads(line)
        for line in (artifacts / "perpetual_events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    summary = json.loads(
        (artifacts / "perpetual_summary.json").read_text(encoding="utf-8")
    )
    return events, summary


def _run_liquidation_case(margin_mode: str):
    dates = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
    frames = {
        symbol: _strict_frame(dates, mark_low=[100.0, low])
        for symbol, low in (
            ("BTC-USDT-PERP", 80.0),
            ("ETH-USDT-PERP", 100.0),
        )
    }
    engine = _strict_engine(
        initial_cash=2_000.0,
        interval="1H",
        taker_rate=0.0,
        maker_rate=0.0,
        liquidation_fee_rate=0.01,
        margin_mode=margin_mode,
    )
    targets = {symbol: [0.5, 0.5] for symbol in frames}
    _run_strict(engine, frames, targets)
    return engine, frames, targets


# ---------------------------------------------------------------------------
# can_execute: no restrictions
# ---------------------------------------------------------------------------


class TestCanExecute:
    def test_long_allowed(self) -> None:
        engine = _make_engine()
        assert engine.can_execute("BTC-USDT", 1, _make_bar()) is True

    def test_short_allowed(self) -> None:
        engine = _make_engine()
        assert engine.can_execute("BTC-USDT", -1, _make_bar()) is True

    def test_close_allowed(self) -> None:
        engine = _make_engine()
        assert engine.can_execute("BTC-USDT", 0, _make_bar()) is True


# ---------------------------------------------------------------------------
# round_size: fractional
# ---------------------------------------------------------------------------


class TestRoundSize:
    def test_fractional_preserved(self) -> None:
        engine = _make_engine()
        assert engine.round_size(0.123456, 60000.0) == 0.123456

    def test_six_decimal_precision(self) -> None:
        engine = _make_engine()
        assert engine.round_size(0.1234567890, 60000.0) == pytest.approx(0.123457, abs=1e-7)

    def test_negative_clamps_to_zero(self) -> None:
        engine = _make_engine()
        assert engine.round_size(-0.5, 60000.0) == 0.0


# ---------------------------------------------------------------------------
# calc_commission: maker/taker
# ---------------------------------------------------------------------------


class TestCommission:
    def test_open_uses_taker(self) -> None:
        engine = _make_engine(taker_rate=0.0005, maker_rate=0.0002)
        comm = engine.calc_commission(1.0, 60000.0, 1, is_open=True)
        # 1 BTC × $60000 × 0.0005 = $30
        assert comm == pytest.approx(30.0)

    def test_close_uses_maker(self) -> None:
        engine = _make_engine(taker_rate=0.0005, maker_rate=0.0002)
        comm = engine.calc_commission(1.0, 60000.0, 1, is_open=False)
        # 1 BTC × $60000 × 0.0002 = $12
        assert comm == pytest.approx(12.0)

    def test_taker_higher_than_maker(self) -> None:
        engine = _make_engine()
        open_comm = engine.calc_commission(1.0, 60000.0, 1, is_open=True)
        close_comm = engine.calc_commission(1.0, 60000.0, 1, is_open=False)
        assert open_comm > close_comm


# ---------------------------------------------------------------------------
# apply_slippage
# ---------------------------------------------------------------------------


class TestSlippage:
    def test_long_slippage_increases_price(self) -> None:
        engine = _make_engine(slippage=0.001)
        assert engine.apply_slippage(60000.0, 1) == pytest.approx(60060.0)

    def test_short_slippage_decreases_price(self) -> None:
        engine = _make_engine(slippage=0.001)
        assert engine.apply_slippage(60000.0, -1) == pytest.approx(59940.0)


# ---------------------------------------------------------------------------
# Funding fee
# ---------------------------------------------------------------------------


class TestFundingFee:
    def test_funding_deducted_at_settlement_hour(self) -> None:
        engine = _make_engine(funding_rate=0.0001)
        engine.positions["BTC-USDT"] = Position(
            "BTC-USDT", 1, 60000.0, pd.Timestamp("2025-01-01"), 1.0, leverage=10.0,
        )
        initial_capital = engine.capital
        bar = _make_bar(close=60000.0)
        ts = pd.Timestamp("2025-01-01 08:00:00")  # settlement hour
        engine.on_bar("BTC-USDT", bar, ts)
        # Long pays: 1.0 × 60000 × 0.0001 × 1(long) = $6
        assert engine.capital == pytest.approx(initial_capital - 6.0)

    def test_non_settlement_hour_applies_daily_fallback(self) -> None:
        """Non-settlement hour still applies funding once per day (daily bar support)."""
        engine = _make_engine(funding_rate=0.0001)
        engine.positions["BTC-USDT"] = Position(
            "BTC-USDT", 1, 60000.0, pd.Timestamp("2025-01-01"), 1.0, leverage=10.0,
        )
        initial_capital = engine.capital
        bar = _make_bar(close=60000.0)
        ts = pd.Timestamp("2025-01-01 05:00:00")  # not settlement hour
        engine.on_bar("BTC-USDT", bar, ts)
        # Daily fallback: applies once even at non-settlement hour
        assert engine.capital == pytest.approx(initial_capital - 6.0)

    def test_short_receives_funding(self) -> None:
        engine = _make_engine(funding_rate=0.0001)
        engine.positions["BTC-USDT"] = Position(
            "BTC-USDT", -1, 60000.0, pd.Timestamp("2025-01-01"), 1.0, leverage=10.0,
        )
        initial_capital = engine.capital
        bar = _make_bar(close=60000.0)
        ts = pd.Timestamp("2025-01-01 08:00:00")
        engine.on_bar("BTC-USDT", bar, ts)
        # Short: direction=-1, fee = notional × rate × direction = negative → capital increases
        assert engine.capital > initial_capital

    def test_no_double_settlement(self) -> None:
        engine = _make_engine(funding_rate=0.0001)
        engine.positions["BTC-USDT"] = Position(
            "BTC-USDT", 1, 60000.0, pd.Timestamp("2025-01-01"), 1.0, leverage=10.0,
        )
        bar = _make_bar(close=60000.0)
        ts = pd.Timestamp("2025-01-01 08:00:00")
        engine.on_bar("BTC-USDT", bar, ts)
        capital_after_first = engine.capital
        # Call again at same hour — should not deduct again
        engine.on_bar("BTC-USDT", bar, ts)
        assert engine.capital == capital_after_first

    def test_no_funding_without_position(self) -> None:
        engine = _make_engine()
        initial_capital = engine.capital
        bar = _make_bar()
        ts = pd.Timestamp("2025-01-01 08:00:00")
        engine.on_bar("BTC-USDT", bar, ts)
        assert engine.capital == initial_capital

    def test_daily_bars_apply_each_day(self) -> None:
        """Regression: daily bars (all hour=0) must apply funding every day, not just day 1."""
        engine = _make_engine(funding_rate=0.0001)
        engine.positions["BTC-USDT"] = Position(
            "BTC-USDT", 1, 60000.0, pd.Timestamp("2025-01-01"), 1.0, leverage=10.0,
        )
        bar = _make_bar(close=60000.0)
        initial = engine.capital

        # Day 1
        engine.on_bar("BTC-USDT", bar, pd.Timestamp("2025-01-01"))
        after_day1 = engine.capital
        assert after_day1 < initial  # fee deducted

        # Day 2 (same hour=0, different date)
        engine.on_bar("BTC-USDT", bar, pd.Timestamp("2025-01-02"))
        after_day2 = engine.capital
        assert after_day2 < after_day1  # fee deducted again

        # Day 3
        engine.on_bar("BTC-USDT", bar, pd.Timestamp("2025-01-03"))
        after_day3 = engine.capital
        assert after_day3 < after_day2  # fee deducted again

        # Each day: 1 × 60000 × 0.0001 = $6
        assert initial - after_day3 == pytest.approx(18.0)

    def test_multi_symbol_funding(self) -> None:
        """Each symbol gets independent funding settlement."""
        engine = _make_engine(funding_rate=0.0001)
        engine.positions["BTC-USDT"] = Position(
            "BTC-USDT", 1, 60000.0, pd.Timestamp("2025-01-01"), 1.0, leverage=10.0,
        )
        engine.positions["ETH-USDT"] = Position(
            "ETH-USDT", 1, 3000.0, pd.Timestamp("2025-01-01"), 10.0, leverage=10.0,
        )
        initial = engine.capital
        bar_btc = _make_bar(close=60000.0)
        bar_eth = _make_bar(close=3000.0)
        ts = pd.Timestamp("2025-01-01 08:00:00")

        engine.on_bar("BTC-USDT", bar_btc, ts)
        after_btc = engine.capital
        engine.on_bar("ETH-USDT", bar_eth, ts)
        after_both = engine.capital

        # BTC: 1 × 60000 × 0.0001 = $6
        # ETH: 10 × 3000 × 0.0001 = $3
        assert initial - after_btc == pytest.approx(6.0)
        assert initial - after_both == pytest.approx(9.0)

    def test_funding_hours_correct(self) -> None:
        assert _FUNDING_HOURS == {0, 8, 16}


# ---------------------------------------------------------------------------
# Liquidation
# ---------------------------------------------------------------------------


class TestLiquidation:
    def test_liquidation_on_large_loss(self) -> None:
        """Position wiped when equity drops below maintenance margin."""
        engine = _make_engine(leverage=10.0)
        engine.positions["BTC-USDT"] = Position(
            "BTC-USDT", 1, 60000.0, pd.Timestamp("2025-01-01"), 1.0, leverage=10.0,
        )
        # Margin = 1.0 × 60000 / 10 = $6000
        # If price drops to 54500: unrealized = 1 × (54500 - 60000) = -$5500
        # equity_in_pos = 6000 + (-5500) = $500
        # Notional = 1 × 54500 = 54500, maint_rate(54500) = 0.004
        # Maint margin = 54500 × 0.004 = $218
        # $500 > $218 → no liquidation

        # But if price drops to 54000:
        # unrealized = -6000, equity = 0 → clearly liquidated
        bar = _make_bar(close=54000.0)
        ts = pd.Timestamp("2025-01-02")
        engine.on_bar("BTC-USDT", bar, ts)
        assert "BTC-USDT" not in engine.positions
        assert len(engine.trades) == 1
        assert engine.trades[0].exit_reason == "liquidation"

    def test_no_liquidation_when_profitable(self) -> None:
        engine = _make_engine(leverage=10.0)
        engine.positions["BTC-USDT"] = Position(
            "BTC-USDT", 1, 60000.0, pd.Timestamp("2025-01-01"), 1.0, leverage=10.0,
        )
        bar = _make_bar(close=65000.0)
        ts = pd.Timestamp("2025-01-02")
        engine.on_bar("BTC-USDT", bar, ts)
        assert "BTC-USDT" in engine.positions

    def test_no_liquidation_for_spot(self) -> None:
        """Spot (leverage=1) should never get liquidated."""
        engine = _make_engine(leverage=1.0)
        engine.positions["BTC-USDT"] = Position(
            "BTC-USDT", 1, 60000.0, pd.Timestamp("2025-01-01"), 1.0, leverage=1.0,
        )
        bar = _make_bar(close=30000.0)  # 50% drop
        ts = pd.Timestamp("2025-01-02")
        engine.on_bar("BTC-USDT", bar, ts)
        assert "BTC-USDT" in engine.positions

    def test_short_liquidation(self) -> None:
        """Short position liquidated when price rises sharply."""
        engine = _make_engine(leverage=10.0)
        engine.positions["BTC-USDT"] = Position(
            "BTC-USDT", -1, 60000.0, pd.Timestamp("2025-01-01"), 1.0, leverage=10.0,
        )
        # Margin = $6000, unrealized = -1 × 1 × (66500 - 60000) = -$6500
        # equity_in_pos = 6000 - 6500 = -$500 < 0 → liquidated
        bar = _make_bar(close=66500.0)
        ts = pd.Timestamp("2025-01-02")
        engine.on_bar("BTC-USDT", bar, ts)
        assert "BTC-USDT" not in engine.positions


# ---------------------------------------------------------------------------
# Tiered maintenance margin
# ---------------------------------------------------------------------------


class TestMaintenanceRate:
    def test_small_position(self) -> None:
        assert _maintenance_rate(50_000) == 0.004

    def test_medium_position(self) -> None:
        assert _maintenance_rate(300_000) == 0.006

    def test_large_position(self) -> None:
        assert _maintenance_rate(2_000_000) == 0.02

    def test_tier_boundaries(self) -> None:
        assert _maintenance_rate(100_000) == 0.004
        assert _maintenance_rate(100_001) == 0.006

    def test_maximum_tier(self) -> None:
        assert _maintenance_rate(100_000_000) == 0.10


class TestHistoricalFundingRate:
    def test_bar_funding_rate_overrides_fixed_rate(self) -> None:
        """A bar carrying a historical ``funding_rate`` column (USD-M perp
        data) must be charged at that rate, not the fixed config rate."""
        engine = _make_engine(funding_rate=0.0001)
        engine.positions["BTC-USDT-PERP"] = Position(
            "BTC-USDT-PERP", 1, 60000.0, pd.Timestamp("2025-01-01"), 1.0, leverage=10.0,
        )
        initial_capital = engine.capital
        bar = pd.Series({"close": 60000.0, "open": 60000.0, "funding_rate": 0.0005})
        ts = pd.Timestamp("2025-01-01 08:00:00")
        engine.on_bar("BTC-USDT-PERP", bar, ts)
        # Historical rate: 1.0 × 60000 × 0.0005 = $30 (not $6 from the fixed rate)
        assert engine.capital == pytest.approx(initial_capital - 30.0)

    def test_negative_historical_funding_pays_longs(self) -> None:
        engine = _make_engine(funding_rate=0.0001)
        engine.positions["BTC-USDT-PERP"] = Position(
            "BTC-USDT-PERP", 1, 60000.0, pd.Timestamp("2025-01-01"), 1.0, leverage=10.0,
        )
        initial_capital = engine.capital
        bar = pd.Series({"close": 60000.0, "open": 60000.0, "funding_rate": -0.0002})
        ts = pd.Timestamp("2025-01-01 08:00:00")
        engine.on_bar("BTC-USDT-PERP", bar, ts)
        # Negative funding: longs receive
        assert engine.capital == pytest.approx(initial_capital + 12.0)

    def test_nan_funding_rate_falls_back_to_fixed(self) -> None:
        """Non-settlement bars carry NaN funding_rate — must fall back to
        the fixed config rate (daily-fallback path), not charge NaN."""
        engine = _make_engine(funding_rate=0.0001)
        engine.positions["BTC-USDT-PERP"] = Position(
            "BTC-USDT-PERP", 1, 60000.0, pd.Timestamp("2025-01-01"), 1.0, leverage=10.0,
        )
        initial_capital = engine.capital
        bar = pd.Series({"close": 60000.0, "open": 60000.0, "funding_rate": float("nan")})
        ts = pd.Timestamp("2025-01-01 08:00:00")
        engine.on_bar("BTC-USDT-PERP", bar, ts)
        assert engine.capital == pytest.approx(initial_capital - 6.0)


class TestStrictPerpetualLifecycle:
    @pytest.mark.parametrize("interval", ["3m", "60m", "4H", "1D"])
    def test_strict_100x_rejects_unsupported_or_coarse_intervals(
        self, interval: str
    ) -> None:
        with pytest.raises(ValueError, match="resolution boundary"):
            _strict_engine(leverage=100.0, interval=interval)

    @pytest.mark.parametrize("interval", ["1m", "30m", "1H"])
    def test_strict_100x_accepts_at_most_one_hour(self, interval: str) -> None:
        engine = _strict_engine(leverage=100.0, interval=interval)
        assert engine.default_leverage == 100.0

    def test_strict_100x_revalidates_run_config_before_loading(
        self, tmp_path
    ) -> None:
        class LoaderThatMustNotRun:
            def fetch(self, *args, **kwargs):
                raise AssertionError("loader ran before strict interval validation")

        engine = _strict_engine(leverage=100.0, interval="1H")
        run_config = {
            **engine.config,
            "codes": ["BTC-USDT-PERP"],
            "interval": "1D",
        }

        with pytest.raises(ValueError, match="resolution boundary"):
            engine.run_backtest(run_config, LoaderThatMustNotRun(), object(), tmp_path)

    def test_market_fills_use_execution_open_and_taker_rate(self) -> None:
        dates = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
        frame = _strict_frame(
            dates,
            execution_open=[60_123.0, 60_234.0],
            mark_open=[60_000.0, 60_100.0],
            mark_high=[60_200.0, 60_300.0],
            mark_low=[59_900.0, 60_000.0],
            mark_close=[60_100.0, 60_200.0],
        )
        engine = _strict_engine()

        _run_strict(engine, {"BTC-USDT-PERP": frame}, {"BTC-USDT-PERP": [1.0, 0.0]})

        trade = engine.trades[0]
        assert trade.entry_price == 60_123.0
        assert trade.exit_price == 60_234.0
        assert trade.commission == pytest.approx(
            trade.size * (trade.entry_price + trade.exit_price) * engine.taker_rate
        )

    def test_funding_applies_only_to_position_open_before_settlement(self) -> None:
        dates = pd.date_range("2026-01-01", periods=2, freq="8h", tz="UTC")
        frame = _strict_frame(
            dates,
            price=60_000.0,
            funding_rate=[0.001, 0.001],
            settlements=list(dates),
        )
        engine = _strict_engine(taker_rate=0.0, maker_rate=0.0)

        _run_strict(engine, {"BTC-USDT-PERP": frame}, {"BTC-USDT-PERP": [1.0, 0.0]})

        assert engine.capital == pytest.approx(990.0, abs=0.001)

    def test_isolated_liquidation_closes_only_breached_position(self) -> None:
        dates = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
        btc = _strict_frame(
            dates,
            mark_low=[90.0, 100.0],
            mark_close=[95.0, 100.0],
        )
        eth = _strict_frame(dates)
        engine = _strict_engine(
            initial_cash=2_000.0,
            taker_rate=0.0,
            maker_rate=0.0,
            liquidation_fee_rate=0.01,
        )

        _run_strict(
            engine,
            {"BTC-USDT-PERP": btc, "ETH-USDT-PERP": eth},
            {"BTC-USDT-PERP": [0.5, 0.0], "ETH-USDT-PERP": [0.5, 0.5]},
        )

        reasons = {trade.symbol: trade.exit_reason for trade in engine.trades}
        assert reasons == {
            "BTC-USDT-PERP": "position_liquidation",
            "ETH-USDT-PERP": "end_of_backtest",
        }
        assert engine.terminal_status == "completed"
        assert engine.capital == pytest.approx(910.0)

    def test_open_mark_liquidation_blocks_same_bar_reopen(self) -> None:
        dates = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
        frame = _strict_frame(
            dates,
            mark=[100.0, 90.0],
        )
        engine = _strict_engine(taker_rate=0.0, maker_rate=0.0)

        _run_strict(engine, {"BTC-USDT-PERP": frame}, {"BTC-USDT-PERP": [1.0, 1.0]})

        assert [trade.exit_reason for trade in engine.trades] == [
            "position_liquidation"
        ]
        assert not engine.positions

    def test_cross_liquidation_closes_account_and_stops_later_bars(self) -> None:
        dates = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
        frames = {
            symbol: _strict_frame(
                dates,
                mark_low=[100.0, low, 100.0],
            )
            for symbol, low in (
                ("BTC-USDT-PERP", 80.0),
                ("ETH-USDT-PERP", 100.0),
            )
        }
        engine = _strict_engine(
            initial_cash=2_000.0,
            taker_rate=0.0,
            maker_rate=0.0,
            margin_mode="cross",
        )

        _run_strict(
            engine,
            frames,
            {symbol: [0.5] * 3 for symbol in frames},
        )

        assert {trade.exit_reason for trade in engine.trades} == {
            "account_liquidation"
        }
        assert engine.terminal_status == "account_liquidation"
        assert len(engine.equity_snapshots) == 2
        assert engine.equity_snapshots[-1].timestamp == dates[1]

    def test_evidence_records_funding_before_fill_and_separate_fee_totals(
        self, tmp_path
    ) -> None:
        dates = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
        frame = _strict_frame(
            dates,
            funding_rate=[0.0, 0.001, 0.0],
            settlements=[None, dates[1], None],
        )
        engine = _strict_engine(
            interval="1H",
            taker_rate=0.001,
            liquidation_fee_rate=0.02,
        )
        targets = {"BTC-USDT-PERP": [0.5, 0.0, 0.0]}

        _run_strict(engine, {"BTC-USDT-PERP": frame}, targets)
        metrics = _write_strict_artifacts(
            engine, {"BTC-USDT-PERP": frame}, targets, tmp_path
        )

        events, summary = _read_strict_evidence(tmp_path)
        settlement = next(
            event for event in events if event["event_type"] == "funding_settlement"
        )
        close_fill = next(
            event
            for event in events
            if event["event_type"] == "market_fill" and event["action"] == "close"
        )
        assert settlement["timestamp"] == dates[1].isoformat()
        assert settlement["funding_pnl"] == pytest.approx(-5.0)
        assert settlement["sequence"] < close_fill["sequence"]
        assert close_fill["execution_price_source"] == "execution_open"

        assert summary["funding_settlement_count"] == 1
        assert summary["total_funding_pnl"] == pytest.approx(-5.0)
        assert summary["total_trading_fee"] == pytest.approx(10.0)
        assert summary["total_liquidation_fee"] == 0.0
        assert summary["leverage"] == 10.0
        assert summary["taker_rate"] == 0.001
        assert summary["liquidation_fee_rate"] == 0.02
        assert summary["fee_model"] == {
            "market_fill_rate": "taker_rate",
            "maker_rate_used": False,
            "funding_separate": True,
            "liquidation_separate": True,
        }
        assert metrics["perpetual_funding_pnl"] == pytest.approx(-5.0)
        assert metrics["perpetual_trading_fees"] == pytest.approx(10.0)

    def test_evidence_records_cross_liquidation_and_intrabar_limitation(
        self, tmp_path
    ) -> None:
        engine, frames, targets = _run_liquidation_case("cross")
        metrics = _write_strict_artifacts(engine, frames, targets, tmp_path)

        events, summary = _read_strict_evidence(tmp_path)
        liquidation = next(
            event for event in events if event["event_type"] == "account_liquidation"
        )
        assert liquidation["symbols"] == ["BTC-USDT-PERP", "ETH-USDT-PERP"]
        assert liquidation["price_source"] == "adverse_mark_extrema"
        assert liquidation["liquidation_fee"] == pytest.approx(180.0)

        assert summary["terminal_status"] == "account_liquidation"
        assert summary["liquidation_event_count"] == 1
        assert summary["liquidated_position_count"] == 2
        assert summary["total_liquidation_fee"] == pytest.approx(180.0)
        assert summary["maintenance_bracket_versions"] == {
            "BTC-USDT-PERP": "fixture-v1",
            "ETH-USDT-PERP": "fixture-v1",
        }
        assert summary["fidelity_flags"] == ["conservative_intrabar_assumption"]
        assert "not guaranteed" in summary["resolution_limitation"]
        assert metrics["perpetual_liquidation_events"] == 1
        assert metrics["perpetual_liquidation_fees"] == pytest.approx(180.0)

    def test_evidence_keeps_isolated_liquidation_position_scoped(
        self, tmp_path
    ) -> None:
        engine, frames, targets = _run_liquidation_case("isolated")
        _write_strict_artifacts(engine, frames, targets, tmp_path)

        events, _ = _read_strict_evidence(tmp_path)
        liquidations = [
            event
            for event in events
            if event["event_type"]
            in {
                "position_liquidation",
                "account_liquidation",
            }
        ]
        assert [event["event_type"] for event in liquidations] == [
            "position_liquidation"
        ]
        assert liquidations[0]["symbol"] == "BTC-USDT-PERP"
        assert liquidations[0]["liquidation_fee"] == pytest.approx(80.0)
        assert engine.terminal_status == "completed"
        assert {trade.symbol: trade.exit_reason for trade in engine.trades} == {
            "BTC-USDT-PERP": "position_liquidation",
            "ETH-USDT-PERP": "end_of_backtest",
        }

    @pytest.mark.parametrize("margin_mode", ["isolated", "cross"])
    def test_rebalance_matches_hand_computed_collateral_and_fill_accounting(
        self, margin_mode: str
    ) -> None:
        class StateCaptureEngine(CryptoEngine):
            def __init__(self, config: dict) -> None:
                super().__init__(config)
                self.states: list[dict] = []

            def after_rebalance_bar(self, timestamp, data_map, codes) -> bool:
                stop = super().after_rebalance_bar(timestamp, data_map, codes)
                position = self.positions["BTC-USDT-PERP"]
                account = self._account_state()
                self.states.append(
                    {
                        "size": position.size,
                        "entry_price": position.entry_price,
                        "entry_fee": position.entry_commission,
                        "capital": self.capital,
                        "isolated_margin": self._isolated_margins.get(position.symbol),
                        "wallet_balance": account.wallet_balance,
                    }
                )
                return stop

        dates = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
        engine = StateCaptureEngine(
            {
                "initial_cash": 1_000.0,
                "leverage": 10.0,
                "maker_rate": 0.0002,
                "taker_rate": 0.001,
                "slippage": 0.0,
                "perpetual_strict": True,
                "funding_mode": "data",
                "margin_mode": margin_mode,
                "position_adjustment": "rebalance",
            }
        )

        _run_strict(
            engine,
            {"BTC-USDT-PERP": _strict_frame(dates)},
            {"BTC-USDT-PERP": [0.25, 0.50, 0.20]},
        )

        assert [state["size"] for state in engine.states] == pytest.approx(
            [25.0, 49.875, 19.90025]
        )
        assert [state["entry_price"] for state in engine.states] == pytest.approx(
            [100.0, 100.0, 100.0]
        )
        assert [state["entry_fee"] for state in engine.states] == pytest.approx(
            [2.5, 4.9875, 1.990025]
        )
        assert [state["capital"] for state in engine.states] == pytest.approx(
            [747.5, 496.2625, 793.012525]
        )
        assert [state["wallet_balance"] for state in engine.states] == pytest.approx(
            [997.5, 995.0125, 992.015025]
        )
        isolated_margins = [state["isolated_margin"] for state in engine.states]
        if margin_mode == "isolated":
            assert isolated_margins == pytest.approx([250.0, 498.75, 199.0025])
        else:
            assert isolated_margins == [None, None, None]

        fills = [
            event
            for event in engine._perpetual_events
            if event["event_type"] == "market_fill"
        ]
        assert [event["action"] for event in fills] == [
            "open",
            "increase",
            "reduce",
            "close",
        ]
        assert [event["signed_quantity"] for event in fills[:3]] == pytest.approx(
            [25.0, 24.875, -29.97475]
        )
        assert [event["trading_fee"] for event in fills[:3]] == pytest.approx(
            [2.5, 2.4875, 2.997475]
        )
        assert fills[2]["realized_pnl"] == pytest.approx(0.0)
        assert fills[2]["released_margin"] == pytest.approx(299.7475)

    def test_rebalance_funding_precedes_increase_at_preincrease_size(self) -> None:
        dates = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
        engine = _strict_engine(position_adjustment="rebalance", taker_rate=0.001)
        frame = _strict_frame(
            dates,
            funding_rate=[0.0, 0.001, 0.0],
            settlements=[None, dates[1], None],
        )

        _run_strict(
            engine,
            {"BTC-USDT-PERP": frame},
            {"BTC-USDT-PERP": [0.25, 0.50, 0.20]},
        )

        funding = next(
            event
            for event in engine._perpetual_events
            if event["event_type"] == "funding_settlement"
        )
        increase = next(
            event
            for event in engine._perpetual_events
            if event["event_type"] == "market_fill" and event["action"] == "increase"
        )
        assert funding["signed_quantity"] == pytest.approx(25.0)
        assert funding["sequence"] < increase["sequence"]

    def test_isolated_reduction_keeps_funding_pnl_and_collateral_consistent(
        self,
    ) -> None:
        class StateCaptureEngine(CryptoEngine):
            def __init__(self, config: dict) -> None:
                super().__init__(config)
                self.states: list[dict] = []

            def after_rebalance_bar(self, timestamp, data_map, codes) -> bool:
                stop = super().after_rebalance_bar(timestamp, data_map, codes)
                position = self.positions["BTC-USDT-PERP"]
                self.states.append(
                    {
                        "capital": self.capital,
                        "wallet_balance": self._account_state().wallet_balance,
                        "isolated_margin": self._isolated_margins[position.symbol],
                        "size": position.size,
                    }
                )
                return stop

        dates = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
        engine = StateCaptureEngine(
            {
                **_strict_engine(
                    position_adjustment="rebalance",
                    taker_rate=0.001,
                ).config
            }
        )
        frame = _strict_frame(
            dates,
            execution_open=[100.0, 100.0, 110.0],
            mark=[100.0, 100.0, 110.0],
            funding_rate=[0.0, 0.001, 0.0],
            settlements=[None, dates[1], None],
        )

        _run_strict(
            engine,
            {"BTC-USDT-PERP": frame},
            {"BTC-USDT-PERP": [0.25, 0.50, 0.20]},
        )

        after_increase, after_reduction = engine.states[1:]
        assert after_increase == pytest.approx(
            {
                "capital": 495.025,
                "wallet_balance": 992.525,
                "isolated_margin": 495.0,
                "size": 49.75,
            }
        )
        assert after_reduction == pytest.approx(
            {
                "capital": 945.7052772727273,
                "wallet_balance": 1216.6189136363636,
                "isolated_margin": 269.5522613065327,
                "size": 27.0913636363636,
            }
        )
        reduction = next(
            event
            for event in engine._perpetual_events
            if event["event_type"] == "market_fill" and event["action"] == "reduce"
        )
        assert reduction["realized_pnl"] == pytest.approx(226.5863636363636)
        assert reduction["released_margin"] == pytest.approx(226.5863636363636)
        assert reduction["trading_fee"] == pytest.approx(2.49245)
        assert after_reduction["wallet_balance"] == pytest.approx(
            1_000.0
            - 2.5  # opening fee
            - 2.5  # funding paid before the increase
            - 2.475  # increase fee
            + reduction["realized_pnl"]
            - reduction["trading_fee"]
        )

    def test_cross_rebalance_reduces_before_addition_and_then_checks_risk(self) -> None:
        dates = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
        engine = _strict_engine(
            position_adjustment="rebalance",
            margin_mode="cross",
            taker_rate=0.0,
            maker_rate=0.0,
        )
        frames = {
            symbol: _strict_frame(dates)
            for symbol in ("BTC-USDT-PERP", "ETH-USDT-PERP")
        }

        _run_strict(
            engine,
            frames,
            {
                "BTC-USDT-PERP": [0.40, 0.10],
                "ETH-USDT-PERP": [0.40, 0.70],
            },
        )

        second_bar = [
            event
            for event in engine._perpetual_events
            if event["timestamp"] == dates[1].isoformat()
        ]
        reduce_event = next(event for event in second_bar if event.get("action") == "reduce")
        increase_event = next(
            event for event in second_bar if event.get("action") == "increase"
        )
        risk_events = [
            event
            for event in second_bar
            if event["event_type"] == "risk_snapshot" and event["phase"] == "post_fill"
        ]
        assert reduce_event["symbol"] == "BTC-USDT-PERP"
        assert increase_event["symbol"] == "ETH-USDT-PERP"
        assert len(risk_events) == 2
        assert (
            reduce_event["sequence"]
            < risk_events[0]["sequence"]
            < increase_event["sequence"]
            < risk_events[1]["sequence"]
        )
        assert [event["status"] for event in risk_events] == ["healthy", "healthy"]

    def test_strict_100x_rebalance_stays_finite_without_breach(self) -> None:
        dates = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
        engine = _strict_engine(
            interval="1H",
            leverage=100.0,
            position_adjustment="rebalance",
            taker_rate=0.001,
        )

        _run_strict(
            engine,
            {"BTC-USDT-PERP": _strict_frame(dates)},
            {"BTC-USDT-PERP": [0.02, 0.03, 0.01]},
        )

        assert {
            event["action"]
            for event in engine._perpetual_events
            if event["event_type"] == "market_fill"
        } >= {"increase", "reduce"}
        assert all(
            math.isfinite(value)
            for snapshot in engine.equity_snapshots
            for value in (snapshot.equity, snapshot.capital)
        )
        assert all(
            math.isfinite(float(event[field]))
            for event in engine._perpetual_events
            if event["event_type"] == "risk_snapshot"
            for field in (
                "margin_balance",
                "initial_margin",
                "maintenance_margin",
                "available_balance",
            )
        )

    def test_strict_rebalance_fills_use_raw_execution_open(self) -> None:
        dates = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
        engine = _strict_engine(
            position_adjustment="rebalance",
            slippage=0.10,
            taker_rate=0.0,
            maker_rate=0.0,
        )
        frame = _strict_frame(
            dates,
            execution_open=[101.0, 102.0, 103.0],
            mark=[113.3, 113.3, 113.3],
        )

        _run_strict(
            engine,
            {"BTC-USDT-PERP": frame},
            {"BTC-USDT-PERP": [0.25, 0.50, 0.20]},
        )

        fills = {
            event["action"]: event["execution_price"]
            for event in engine._perpetual_events
            if event["event_type"] == "market_fill"
            and event["action"] in {"open", "increase", "reduce"}
        }
        assert fills == {"open": 101.0, "increase": 102.0, "reduce": 103.0}

    def test_strict_hold_keeps_configured_slippage_behavior(self) -> None:
        dates = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
        engine = _strict_engine(
            position_adjustment="hold",
            slippage=0.10,
            taker_rate=0.0,
            maker_rate=0.0,
        )

        _run_strict(
            engine,
            {"BTC-USDT-PERP": _strict_frame(dates)},
            {"BTC-USDT-PERP": [0.25, 0.25]},
        )

        fills = [
            event
            for event in engine._perpetual_events
            if event["event_type"] == "market_fill"
        ]
        assert [event["action"] for event in fills] == ["open", "close"]
        assert [event["execution_price"] for event in fills] == pytest.approx(
            [110.0, 90.0]
        )

    def test_cross_atomic_liquidation_stops_remaining_additions(self) -> None:
        dates = pd.date_range("2026-01-01", periods=1, freq="h", tz="UTC")
        engine = _strict_engine(
            position_adjustment="rebalance",
            margin_mode="cross",
            taker_rate=0.0,
            maker_rate=0.0,
        )
        frames = {
            "BTC-USDT-PERP": _strict_frame(dates, mark_low=[80.0]),
            "ETH-USDT-PERP": _strict_frame(dates),
        }

        _run_strict(
            engine,
            frames,
            {
                "BTC-USDT-PERP": [0.50],
                "ETH-USDT-PERP": [0.25],
            },
        )

        fills = [
            event
            for event in engine._perpetual_events
            if event["event_type"] == "market_fill" and event["action"] == "open"
        ]
        assert [event["symbol"] for event in fills] == ["BTC-USDT-PERP"]
        assert engine.terminal_status == "account_liquidation"
        assert not engine.positions

    def test_isolated_atomic_liquidation_allows_other_symbol_to_continue(self) -> None:
        dates = pd.date_range("2026-01-01", periods=1, freq="h", tz="UTC")
        engine = _strict_engine(
            position_adjustment="rebalance",
            margin_mode="isolated",
            taker_rate=0.0,
            maker_rate=0.0,
        )
        frames = {
            "BTC-USDT-PERP": _strict_frame(dates, mark_low=[90.0]),
            "ETH-USDT-PERP": _strict_frame(dates),
        }

        _run_strict(
            engine,
            frames,
            {
                "BTC-USDT-PERP": [0.50],
                "ETH-USDT-PERP": [0.25],
            },
        )

        fills = [
            event
            for event in engine._perpetual_events
            if event["event_type"] == "market_fill" and event["action"] == "open"
        ]
        assert [event["symbol"] for event in fills] == [
            "BTC-USDT-PERP",
            "ETH-USDT-PERP",
        ]
        liquidation = next(
            event
            for event in engine._perpetual_events
            if event["event_type"] == "position_liquidation"
        )
        assert liquidation["symbol"] == "BTC-USDT-PERP"
        assert engine.terminal_status == "completed"

    def test_isolated_liquidation_rejects_now_unfunded_addition(self) -> None:
        dates = pd.date_range("2026-01-01", periods=1, freq="h", tz="UTC")
        engine = _strict_engine(
            position_adjustment="rebalance",
            margin_mode="isolated",
            taker_rate=0.0,
            maker_rate=0.0,
        )
        frames = {
            "BTC-USDT-PERP": _strict_frame(dates, mark_low=[80.0]),
            "ETH-USDT-PERP": _strict_frame(dates),
        }

        _run_strict(
            engine,
            frames,
            {
                "BTC-USDT-PERP": [0.50],
                "ETH-USDT-PERP": [0.25],
            },
        )

        opens = [
            event
            for event in engine._perpetual_events
            if event["event_type"] == "market_fill" and event["action"] == "open"
        ]
        assert [event["symbol"] for event in opens] == ["BTC-USDT-PERP"]
        rejected = next(
            event
            for event in engine._perpetual_events
            if event["event_type"] == "order_rejected"
        )
        assert rejected["symbol"] == "ETH-USDT-PERP"
        assert rejected["reason"] == "insufficient_capital_after_liquidation"
        assert rejected["required_capital"] == pytest.approx(250.0)
        assert rejected["available_capital"] == pytest.approx(0.0)
        assert engine.terminal_status == "completed"

    def test_cross_rebalance_increase_precedes_adverse_account_liquidation(
        self,
    ) -> None:
        dates = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
        engine = _strict_engine(
            initial_cash=1_000.0,
            position_adjustment="rebalance",
            taker_rate=0.0,
            maker_rate=0.0,
            margin_mode="cross",
        )
        frame = _strict_frame(dates, mark_low=[100.0, 80.0])

        _run_strict(
            engine,
            {"BTC-USDT-PERP": frame},
            {"BTC-USDT-PERP": [0.25, 0.50]},
        )

        increase = next(
            event
            for event in engine._perpetual_events
            if event["event_type"] == "market_fill" and event["action"] == "increase"
        )
        liquidation = next(
            event
            for event in engine._perpetual_events
            if event["event_type"] == "account_liquidation"
        )
        assert increase["sequence"] < liquidation["sequence"]
        assert not engine.positions
        assert engine.terminal_status == "account_liquidation"

    def test_rebalance_evidence_artifacts_are_deterministic(self, tmp_path) -> None:
        dates = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
        frame = _strict_frame(dates)
        targets = {"BTC-USDT-PERP": [0.25, 0.50, 0.20]}

        results = []
        for run_name in ("first", "second"):
            engine = _strict_engine(
                position_adjustment="rebalance",
                taker_rate=0.001,
            )
            _run_strict(engine, {"BTC-USDT-PERP": frame}, targets)
            metrics = _write_strict_artifacts(
                engine,
                {"BTC-USDT-PERP": frame},
                targets,
                tmp_path / run_name,
            )
            events, summary = _read_strict_evidence(tmp_path / run_name)
            results.append((events, summary, metrics))

        first_events, first_summary, first_metrics = results[0]
        second_events, second_summary, second_metrics = results[1]
        assert first_events == second_events
        assert first_summary == second_summary
        assert first_metrics == second_metrics
        assert [
            event["action"]
            for event in first_events
            if event["event_type"] == "market_fill"
        ] == ["open", "increase", "reduce", "close"]
        assert first_summary["total_trading_fee"] == pytest.approx(9.975)
        assert first_metrics["perpetual_trading_fees"] == pytest.approx(9.975)
