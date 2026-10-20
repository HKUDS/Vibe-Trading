"""A Vietnamese order fills at most a share of the session's traded volume.

The Vietnam engine used to fill every order in full at the open, whatever the
session traded, so a backtest of thin names could buy more shares in one
session than the whole market traded that day. An order now fills at most
``vn_volume_cap`` (10%) of the session's volume and the rest keeps working on
the following sessions. An order the band or the T+2 hold blocks keeps working
the same way instead of waiting for the strategy's next decision. These tests
pin the limit, the working order in each execution mode, and the defaults that
leave other markets as they were.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd
import pytest

from backtest.engines.base import BaseEngine
from backtest.engines.composite import CompositeEngine
from backtest.engines.vietnam_equity import VietnamEquityEngine

CODE = "AAA.VN"
DATES = pd.bdate_range("2026-03-02", periods=8)
DAYS = [str(day.date()) for day in DATES]
# A flat 20,000 VND: buys fill at 20,050 and sells at 19,950 (slippage on
# HOSE's 50 VND grid), so half of 1 billion VND is 24,900 shares.
FLAT = [20_000.0] * 8


def _bars(opens: list[float], volumes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {"open": opens, "high": opens, "low": opens, "close": opens, "volume": volumes},
        index=DATES[: len(opens)],
    )


class _Loader:
    name = "local"

    def __init__(self, bars: pd.DataFrame) -> None:
        self.bars = bars

    def fetch(self, codes, start_date, end_date, fields=None, interval="1D"):
        return {CODE: self.bars.copy()}


class _Weights:
    """One target weight per bar; the engine trades each on the next bar."""

    def __init__(self, weights: list[float]) -> None:
        self.weights = weights

    def generate(self, data_map):
        return {CODE: pd.Series(self.weights, index=data_map[CODE].index)}


class _NoCarry(VietnamEquityEngine):
    """The engine with its orders no longer kept working."""

    def carries_unfilled_orders(self, symbol: str) -> bool:
        return False


class _AnyMarket(BaseEngine):
    """A market that sets no volume limit: BaseEngine's defaults."""

    def can_execute(self, symbol, direction, bar):
        return True

    def round_size(self, raw_size, price):
        return float(int(raw_size))

    def calc_commission(self, size, price, direction, is_open):
        return 0.0

    def apply_slippage(self, price, direction):
        return price


def _run(
    run_dir: Path,
    bars: pd.DataFrame,
    weights: list[float],
    engine_cls: type[BaseEngine] = VietnamEquityEngine,
    **overrides,
) -> tuple[BaseEngine, dict, dict]:
    config = {
        "codes": [CODE],
        "start_date": DAYS[0],
        "end_date": DAYS[-1],
        "source": "local",
        "initial_cash": 1_000_000_000,
        "position_adjustment": "rebalance",
        **overrides,
    }
    engine = engine_cls(config)
    metrics = engine.run_backtest(config, _Loader(bars), _Weights(weights), run_dir)
    card = json.loads((run_dir / "run_card.json").read_text(encoding="utf-8"))
    return engine, metrics, card


def _fills(engine: BaseEngine) -> list[tuple[int, str, float]]:
    """(bar, action, signed shares) of each fill before the end-of-run sale."""
    return [
        (fill.bar_idx, fill.action, fill.signed_quantity)
        for fill in engine.fill_records
        if fill.reason != "end_of_backtest"
    ]


class TestTheLimit:
    def test_an_order_fills_at_most_a_tenth_of_the_volume(self) -> None:
        engine = VietnamEquityEngine({})
        bar = pd.Series({"volume": 123_456.0})
        assert engine.fill_cap(CODE, bar) == pytest.approx(12_345.6)

    def test_the_share_is_configurable(self) -> None:
        engine = VietnamEquityEngine({"vn_volume_cap": 0.25})
        assert engine.fill_cap(CODE, pd.Series({"volume": 100_000.0})) == 25_000.0

    @pytest.mark.parametrize("off", [0, 0.0, None])
    def test_zero_or_none_turns_it_off(self, off) -> None:
        engine = VietnamEquityEngine({"vn_volume_cap": off})
        assert engine.fill_cap(CODE, pd.Series({"volume": 100_000.0})) is None

    @pytest.mark.parametrize(
        "bar", [pd.Series({"open": 20_000.0}), pd.Series({"volume": float("nan")})]
    )
    def test_a_bar_without_volume_sets_no_limit(self, bar) -> None:
        assert VietnamEquityEngine({}).fill_cap(CODE, bar) is None

    @pytest.mark.parametrize("bad", [-0.1, 1.5, float("nan"), float("inf")])
    def test_a_share_outside_zero_to_one_is_refused(self, bad) -> None:
        with pytest.raises(ValueError, match="vn_volume_cap"):
            VietnamEquityEngine({"vn_volume_cap": bad})

    def test_other_markets_set_no_limit_and_keep_no_orders(
        self, tmp_path: Path
    ) -> None:
        engine, metrics, _ = _run(
            tmp_path, _bars(FLAT, [100.0] * 8), [0.5] * 8, _AnyMarket
        )

        assert engine.fill_cap(CODE, pd.Series({"volume": 100.0})) is None
        assert engine.carries_unfilled_orders(CODE) is False
        assert _fills(engine) == [(1, "open", 25_000.0)]
        assert "volume_capped_orders" not in metrics

    def test_a_composite_limits_its_vietnamese_symbols_only(self) -> None:
        codes = [CODE, "AAPL.US"]
        engine = CompositeEngine({"initial_cash": 1_000_000_000, "codes": codes}, codes)
        bar = pd.Series({"volume": 100_000.0})

        assert engine.fill_cap(CODE, bar) == 10_000.0
        assert engine.fill_cap("AAPL.US", bar) is None
        assert engine.carries_unfilled_orders(CODE) is True
        assert engine.carries_unfilled_orders("AAPL.US") is False


class TestWorkingOrders:
    def test_ample_volume_fills_in_one_session(self, tmp_path: Path) -> None:
        engine, metrics, card = _run(
            tmp_path, _bars(FLAT, [1_000_000.0] * 8), [0.5] * 8
        )

        assert _fills(engine) == [(1, "open", 24_900.0)]
        assert "volume_capped_orders" not in metrics
        assert not card["warnings"]

    def test_a_large_order_fills_over_several_sessions(self, tmp_path: Path) -> None:
        engine, metrics, card = _run(tmp_path, _bars(FLAT, [100_000.0] * 8), [0.5] * 8)

        # 10,000 shares a session; the last fill is sized on that session's
        # equity, which fees and the spread have lowered.
        assert _fills(engine) == [
            (1, "open", 10_000.0),
            (2, "increase", 10_000.0),
            (3, "increase", 4_800.0),
        ]
        assert metrics["volume_capped_orders"] == 2
        assert metrics["unfinished_orders_at_end"] == 0
        assert any("volume limit cut 2 order(s)" in w for w in card["warnings"])

    def test_finishing_an_order_is_not_counted_as_drift(self, tmp_path: Path) -> None:
        _, metrics, _ = _run(tmp_path, _bars(FLAT, [100_000.0] * 8), [0.5] * 8)
        assert metrics["rebalance_unchanged_target_fills"] == 0

    def test_the_order_keeps_working_on_sessions_the_calendar_skips(
        self, tmp_path: Path
    ) -> None:
        bars = _bars(FLAT, [100_000.0] * 8)
        engine, metrics, _ = _run(
            tmp_path / "carry", bars, [0.5] * 8, rebalance_mask=[DAYS[1]]
        )
        assert [fill[:2] for fill in _fills(engine)] == [
            (1, "open"),
            (2, "increase"),
            (3, "increase"),
        ]
        assert metrics["rebalance_bars_executed"] == 1

        # Without working orders the rest waited for a decision that never came.
        engine, _, _ = _run(
            tmp_path / "wait", bars, [0.5] * 8, _NoCarry, rebalance_mask=[DAYS[1]]
        )
        assert _fills(engine) == [(1, "open", 10_000.0)]

    def test_a_working_order_finishes_inside_the_drift_band(
        self, tmp_path: Path
    ) -> None:
        bars = _bars(FLAT, [100_000.0] * 8)
        engine, _, _ = _run(
            tmp_path / "carry", bars, [0.5] * 8, rebalance_tolerance=0.5
        )
        assert engine.positions == {}
        assert engine.fill_records[-1].signed_quantity == -24_800.0

        # Without it, 20,000 shares sat inside the band around the 24,800
        # wanted, and the order stopped there.
        engine, _, _ = _run(
            tmp_path / "band", bars, [0.5] * 8, _NoCarry, rebalance_tolerance=0.5
        )
        assert engine.fill_records[-1].signed_quantity == -20_000.0

    def test_hold_mode_completes_a_cut_opening_order(self, tmp_path: Path) -> None:
        engine, _, _ = _run(
            tmp_path,
            _bars(FLAT, [100_000.0] * 8),
            [0.5] * 8,
            position_adjustment="hold",
        )
        assert _fills(engine) == [
            (1, "open", 10_000.0),
            (2, "increase", 10_000.0),
            (3, "increase", 4_800.0),
        ]

    @pytest.mark.parametrize("mode", ["rebalance", "hold"])
    def test_an_exit_sells_over_several_sessions(
        self, tmp_path: Path, mode: str
    ) -> None:
        bars = _bars(FLAT, [1_000_000.0] * 3 + [100_000.0] * 5)
        engine, _, _ = _run(
            tmp_path, bars, [0.5] * 3 + [0.0] * 5, position_adjustment=mode
        )

        assert _fills(engine) == [
            (1, "open", 24_900.0),
            (4, "reduce", -10_000.0),
            (5, "reduce", -10_000.0),
            (6, "close", -4_900.0),
        ]
        assert engine.fill_records[-1].reason == "signal"

    def test_a_new_target_replaces_the_working_order(self, tmp_path: Path) -> None:
        # Decisions on bars 1 (buy half) and 3 (sell all). The buy is still
        # working on bar 3, and the shares it bought on bar 2 settle on bar 4,
        # a session the calendar skips.
        engine, _, _ = _run(
            tmp_path,
            _bars(FLAT, [100_000.0] * 8),
            [0.5, 0.5] + [0.0] * 6,
            rebalance_mask=[DAYS[1], DAYS[3]],
        )
        assert _fills(engine) == [
            (1, "open", 10_000.0),
            (2, "increase", 10_000.0),
            (4, "reduce", -10_000.0),
            (5, "close", -10_000.0),
        ]

    def test_a_sale_blocked_at_the_floor_fills_once_it_can(
        self, tmp_path: Path
    ) -> None:
        # Bars 4 and 5 open at the floor, with no bid to sell into.
        opens = [20_000.0] * 4 + [18_600.0, 17_300.0, 17_500.0, 17_500.0]
        bars = _bars(opens, [1_000_000.0] * 8)
        weights = [0.5] * 3 + [0.0] * 5
        calendar = [DAYS[1], DAYS[4]]

        engine, _, _ = _run(tmp_path / "carry", bars, weights, rebalance_mask=calendar)
        assert _fills(engine) == [(1, "open", 24_900.0), (6, "close", -24_900.0)]

        engine, _, _ = _run(
            tmp_path / "wait", bars, weights, _NoCarry, rebalance_mask=calendar
        )
        assert _fills(engine) == [(1, "open", 24_900.0)]

    def test_a_session_without_trades_fills_nothing(self, tmp_path: Path) -> None:
        volumes = [100_000.0, 0.0] + [100_000.0] * 6
        engine, metrics, _ = _run(
            tmp_path, _bars(FLAT, volumes), [0.5] * 8, rebalance_mask=[DAYS[1]]
        )

        assert [fill[:2] for fill in _fills(engine)] == [
            (2, "open"),
            (3, "increase"),
            (4, "increase"),
        ]
        assert metrics["unfilled_plan_rejections_by_symbol"] == {
            CODE: {"volume_cap": 1}
        }

    def test_data_without_any_volume_is_not_limited(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # The local loader writes a zero volume column for a file without one.
        with caplog.at_level(logging.WARNING):
            engine, _, _ = _run(tmp_path, _bars(FLAT, [0.0] * 8), [0.5] * 8)

        assert _fills(engine) == [(1, "open", 24_900.0)]
        assert "no traded volume on any bar" in caplog.text

    def test_an_order_still_working_at_the_end_is_reported(
        self, tmp_path: Path
    ) -> None:
        engine, metrics, card = _run(tmp_path, _bars(FLAT, [20_000.0] * 8), [0.5] * 8)

        assert {quantity for _, _, quantity in _fills(engine)} == {2_000.0}
        assert metrics["unfinished_orders_at_end"] == 1
        assert any(
            "1 order(s) were still working when the run ended" in w
            for w in card["warnings"]
        )
