"""The run card must say when a run's trading did not follow its targets.

Both execution modes can give a periodic strategy a normal-looking report that
the strategy did not produce. ``position_adjustment="hold"`` drops every
same-direction resize (#918) and until now said so only in the log.
``position_adjustment="rebalance"`` with no drift band and no execution
calendar re-pins constant targets on every bar: a quarterly VN30 backtest with
27 requested target changes made 8,022 resize fills, 7,951 of them on targets
that had not changed, and its run card carried no warning. The warnings go
where a reader of the result looks, the run card.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from backtest.engines.base import BaseEngine
from backtest.engines.vietnam_equity import VietnamEquityEngine


class _Engine(BaseEngine):
    def can_execute(self, symbol, direction, bar):
        return True

    def round_size(self, raw_size, price):
        return float(int(raw_size))

    def calc_commission(self, size, price, direction, is_open):
        return 0.0

    def apply_slippage(self, price, direction):
        return price * (1 + 0.0005 * direction)


class _StubLoader:
    name = "local"

    def __init__(self, prices: list[float]):
        self.prices = prices

    def fetch(self, codes, start_date, end_date, fields=None, interval="1D"):
        dates = pd.bdate_range("2026-01-05", periods=len(self.prices))
        return {
            code: pd.DataFrame(
                {
                    "open": self.prices,
                    "close": self.prices,
                    "high": self.prices,
                    "low": self.prices,
                },
                index=dates,
            )
            for code in codes
        }


class _WeightSignal:
    """Replay a fixed target-weight path for ``A``, one weight per bar."""

    def __init__(self, weights: list[float]) -> None:
        self._weights = weights

    def generate(self, data_map):
        dates = next(iter(data_map.values())).index
        return {"A": pd.Series(self._weights, index=dates)}


def _run_pipeline(
    tmp_path: Path, prices: list[float], weights: list[float], **config_overrides
) -> tuple[_Engine, dict, dict]:
    config = {
        "codes": ["A"],
        "start_date": "2026-01-05",
        "end_date": "2026-01-30",
        "initial_cash": 100_000.0,
        **config_overrides,
    }
    engine = _Engine(config)
    metrics = engine.run_backtest(
        config, _StubLoader(prices), _WeightSignal(weights), tmp_path, bars_per_year=252
    )
    card = json.loads((tmp_path / "run_card.json").read_text(encoding="utf-8"))
    return engine, metrics, card


def _rebalance_fills(engine: BaseEngine) -> int:
    return sum(fill.reason == "target_rebalance" for fill in engine.fill_records)


def test_dropped_hold_resizes_reach_the_run_card(tmp_path: Path) -> None:
    """The strategy asked for 0.20 -> 0.60 -> 0.30; the card says it got none."""
    _, metrics, card = _run_pipeline(
        tmp_path, [100.0] * 8, [0.20, 0.20, 0.60, 0.60, 0.30, 0.30, 0.30, 0.30]
    )

    assert metrics["position_adjustment"] == "hold"
    assert metrics["dropped_target_adjustment_count"] == 2
    assert len(card["warnings"]) == 1
    assert card["warnings"][0].startswith(
        "position_adjustment='hold' dropped 2 target change(s) across 1 symbol(s)"
    )
    markdown = (tmp_path / "run_card.md").read_text(encoding="utf-8")
    assert "## Warnings" in markdown
    assert "position_adjustment='hold' dropped 2 target change(s)" in markdown


def test_drift_trading_without_a_band_or_calendar_reaches_the_run_card(
    tmp_path: Path,
) -> None:
    """A constant 40% target on a rising series: every resize trades drift."""
    prices = [100.0 * (1.01**i) for i in range(8)]
    engine, metrics, card = _run_pipeline(
        tmp_path, prices, [0.0, 0.0] + [0.4] * 6, position_adjustment="rebalance"
    )

    assert metrics["target_change_count"] == 1
    assert metrics["rebalance_executed_fills"] > 1
    assert (
        metrics["rebalance_unchanged_target_fills"]
        == metrics["rebalance_executed_fills"]
    )
    assert card["metrics"]["rebalance_unchanged_target_fills"] == (
        metrics["rebalance_unchanged_target_fills"]
    )
    assert len(card["warnings"]) == 1
    assert card["warnings"][0].startswith(
        "position_adjustment='rebalance' with rebalance_tolerance=0 and no rebalance_mask: "
        f"{metrics['rebalance_executed_fills']} of {metrics['rebalance_executed_fills']} "
        "rebalance fill(s)"
    )
    assert engine.dropped_target_adjustments == []


def test_a_run_that_follows_its_targets_carries_no_warning(tmp_path: Path) -> None:
    """Flat prices, so the only trades are the ones the targets asked for."""
    _, metrics, card = _run_pipeline(
        tmp_path, [100.0] * 8, [0.0] + [0.4] * 7, position_adjustment="rebalance"
    )

    assert metrics["rebalance_unchanged_target_fills"] == 0
    assert card["warnings"] == []
    markdown = (tmp_path / "run_card.md").read_text(encoding="utf-8")
    assert "## Warnings" not in markdown


_DRIFT_BARS = 12


def _execute_constant_target(**config_overrides) -> _Engine:
    """A constant 40% target on a series rising 5% a bar, executed directly."""
    dates = pd.bdate_range("2026-01-05", periods=_DRIFT_BARS)
    prices = [100.0 * (1.05**i) for i in range(_DRIFT_BARS)]
    bars = pd.DataFrame({"open": prices, "close": prices}, index=dates)
    close_df = pd.DataFrame({"A": bars["close"]}, index=dates)
    targets = pd.DataFrame({"A": [0.4] * _DRIFT_BARS}, index=dates)
    engine = _Engine(
        {
            "initial_cash": 1_000_000.0,
            "position_adjustment": "rebalance",
            **config_overrides,
        }
    )
    engine._execute_bars(dates, {"A": bars}, close_df, targets, ["A"])
    return engine


def test_unconfigured_drift_trading_is_warned() -> None:
    """The control for the case below: same data, no band, no calendar."""
    engine = _execute_constant_target()

    fills = _rebalance_fills(engine)
    assert fills > 1
    assert engine.rebalance_unchanged_target_fills == fills
    warnings = engine._position_adjustment_warnings(fills)
    assert len(warnings) == 1
    assert "most rebalance trading followed price drift" in warnings[0]


@pytest.mark.parametrize(
    "config_overrides",
    [
        {"rebalance_tolerance": 0.05},
        {"rebalance_mask": ["2026-01-05", "2026-01-09", "2026-01-15"]},
    ],
    ids=["drift_band", "execution_calendar"],
)
def test_a_band_or_a_calendar_makes_drift_fills_intended(
    config_overrides: dict,
) -> None:
    """Re-pinning on a band breach or a calendar date is what was configured.

    The fills still re-size an unchanged target, so the count reports them,
    but they are not a warning.
    """
    engine = _execute_constant_target(**config_overrides)

    fills = _rebalance_fills(engine)
    assert fills > 0
    assert engine.rebalance_unchanged_target_fills == fills
    assert engine._position_adjustment_warnings(fills) == []


def test_changed_targets_are_not_counted_as_drift() -> None:
    """Every resize here executes a new target, so none of it is drift."""
    dates = pd.bdate_range("2026-01-05", periods=6)
    bars = pd.DataFrame({"open": [100.0] * 6, "close": [100.0] * 6}, index=dates)
    close_df = pd.DataFrame({"A": bars["close"]}, index=dates)
    targets = pd.DataFrame({"A": [0.20, 0.30, 0.40, 0.50, 0.40, 0.30]}, index=dates)
    engine = _Engine({"initial_cash": 100_000.0, "position_adjustment": "rebalance"})

    engine._execute_bars(dates, {"A": bars}, close_df, targets, ["A"])

    fills = _rebalance_fills(engine)
    assert fills == 5
    assert engine.rebalance_unchanged_target_fills == 0
    assert engine._position_adjustment_warnings(fills) == []


_VN_CODE = "VIC.VN"
_VN_BASE = 24_250.0
_VN_BARS = pd.DataFrame(
    {
        "open": [_VN_BASE + 50 * i for i in range(9)],
        "high": [_VN_BASE + 50 * i + 150 for i in range(9)],
        "low": [_VN_BASE + 50 * i - 150 for i in range(9)],
        "close": [_VN_BASE + 50 * i + 50 for i in range(9)],
        "volume": [1_000_000] * 9,
    },
    index=pd.bdate_range("2026-03-02", periods=9),
)


class _VnLoader:
    def fetch(self, *args, **kwargs):
        return {_VN_CODE: _VN_BARS.copy()}


class _VnWeightSignal:
    def __init__(self, weights: list[float]) -> None:
        self._weights = weights

    def generate(self, data_map):
        return {_VN_CODE: pd.Series(self._weights, index=data_map[_VN_CODE].index)}


def test_a_vietnam_re_weighting_dropped_by_the_default_mode_is_on_the_card(
    tmp_path: Path,
) -> None:
    """The vietnam-equity skill's example config leaves the mode at "hold".

    A re-weighting from 30% to 50% of a name already held is then dropped,
    and the card must say so rather than report the 30% run as the strategy.
    """
    config = {
        "codes": [_VN_CODE],
        "start_date": "2026-03-02",
        "end_date": "2026-03-20",
        "source": "auto",
        "initial_cash": 1_000_000_000,
    }
    engine = VietnamEquityEngine(config)
    engine.run_backtest(
        config, _VnLoader(), _VnWeightSignal([0.3] * 4 + [0.5] * 5), tmp_path
    )

    assert engine.position_adjustment == "hold"
    assert [fill.action for fill in engine.fill_records].count("increase") == 0
    card = json.loads((tmp_path / "run_card.json").read_text(encoding="utf-8"))
    assert len(card["warnings"]) == 1
    assert card["warnings"][0].startswith(
        "position_adjustment='hold' dropped 1 target change(s) across 1 symbol(s)"
    )
