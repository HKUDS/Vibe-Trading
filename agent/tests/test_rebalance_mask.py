"""Calendar/explicit-date execution mask for partial portfolio rebalancing."""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.engines.base import BaseEngine
from backtest.runner import BacktestConfigSchema


class _MaskEngine(BaseEngine):
    """Frictionless engine exposing execution-mask behavior."""

    def __init__(self, **overrides):
        config = {
            "initial_cash": 1_000.0,
            "position_adjustment": "rebalance",
        }
        config.update(overrides)
        super().__init__(config)
        self.bar_sizes: list[float | None] = []

    def can_execute(self, symbol, direction, bar):
        return True

    def round_size(self, raw_size, price):
        return raw_size

    def calc_commission(self, size, price, direction, is_open):
        return 0.0

    def apply_slippage(self, price, direction):
        return price

    def after_rebalance_bar(self, timestamp, data_map, codes):
        position = self.positions.get("AAPL.US")
        self.bar_sizes.append(None if position is None else position.size)
        return False


def _run_masked(
    engine: _MaskEngine,
    weights: list[float],
    *,
    dates: pd.DatetimeIndex | None = None,
) -> pd.DatetimeIndex:
    if dates is None:
        dates = pd.bdate_range("2026-01-02", periods=len(weights))
    bars = pd.DataFrame({"open": 100.0, "close": 100.0}, index=dates)
    engine._execute_bars(
        dates,
        {"AAPL.US": bars},
        pd.DataFrame({"AAPL.US": 100.0}, index=dates),
        pd.DataFrame({"AAPL.US": weights}, index=dates),
        ["AAPL.US"],
    )
    return dates


def test_mask_false_bar_keeps_position_quantity_unchanged() -> None:
    engine = _MaskEngine(rebalance_mask=["2026-01-02"])

    _run_masked(engine, [0.2, 0.8, 0.2])

    assert engine.bar_sizes == pytest.approx([2.0, 2.0, 2.0])
    assert [fill.action for fill in engine.fill_records[:-1]] == ["open"]


def test_mask_true_bar_partially_resizes_same_direction_position() -> None:
    engine = _MaskEngine(
        rebalance_mask=["2026-01-02", "2026-01-05"],
    )

    _run_masked(engine, [0.2, 0.8, 0.2])

    assert engine.bar_sizes == pytest.approx([2.0, 8.0, 8.0])
    assert [fill.action for fill in engine.fill_records[:-1]] == ["open", "increase"]


def test_mask_true_zero_target_explicitly_exits_position() -> None:
    engine = _MaskEngine(
        rebalance_mask=["2026-01-02", "2026-01-05"],
    )

    _run_masked(engine, [0.5, 0.0, 0.0])

    assert engine.bar_sizes == [5.0, None, None]
    assert [fill.action for fill in engine.fill_records] == ["open", "close"]


def test_off_mask_zero_target_keeps_position_open() -> None:
    engine = _MaskEngine(rebalance_mask=["2026-01-02"])

    _run_masked(engine, [0.5, 0.0, 0.0])

    assert engine.bar_sizes == pytest.approx([5.0, 5.0, 5.0])
    assert [fill.action for fill in engine.fill_records[:-1]] == ["open"]


def test_missing_mask_preserves_every_bar_legacy_rebalance() -> None:
    engine = _MaskEngine()

    _run_masked(engine, [0.2, 0.8, 0.2])

    assert engine.bar_sizes == pytest.approx([2.0, 8.0, 2.0])
    assert [fill.action for fill in engine.fill_records[:-1]] == [
        "open",
        "increase",
        "reduce",
    ]


def test_mask_is_rejected_with_hold_mode() -> None:
    with pytest.raises(ValueError, match="rebalance_mask.*position_adjustment"):
        _MaskEngine(
            position_adjustment="hold",
            rebalance_mask=["2026-01-02"],
        )


def test_monthly_alias_executes_first_trading_bar_of_each_month() -> None:
    dates = pd.DatetimeIndex(
        [
            pd.Timestamp("2026-01-30"),
            pd.Timestamp("2026-02-02"),
            pd.Timestamp("2026-02-03"),
        ]
    )
    engine = _MaskEngine(rebalance_mask="MS")

    _run_masked(engine, [0.2, 0.8, 0.2], dates=dates)

    assert engine.bar_sizes == pytest.approx([2.0, 8.0, 8.0])


def test_mask_without_trading_date_intersection_is_rejected() -> None:
    engine = _MaskEngine(rebalance_mask=["2030-01-01"])

    with pytest.raises(ValueError, match="rebalance_mask.*intersect"):
        _run_masked(engine, [0.2, 0.8, 0.2])


def test_invalid_mask_alias_is_rejected() -> None:
    with pytest.raises(ValueError, match="rebalance_mask"):
        _MaskEngine(rebalance_mask="monthly")


@pytest.mark.parametrize("alias", ["h", "bh"])
def test_alias_finer_than_aligned_bar_spacing_is_rejected(alias: str) -> None:
    dates = pd.bdate_range("2026-01-02", periods=3)
    engine = _MaskEngine(rebalance_mask=alias)

    with pytest.raises(ValueError, match="rebalance_mask.*finer"):
        _run_masked(engine, [0.2, 0.8, 0.2], dates=dates)


@pytest.mark.parametrize(
    ("mask", "position_adjustment"),
    [
        ("MS", "rebalance"),
        (["2026-01-02"], "rebalance"),
        (None, "hold"),
    ],
)
def test_schema_accepts_supported_mask_combinations(
    mask: str | list[str] | None,
    position_adjustment: str,
) -> None:
    config = BacktestConfigSchema.model_validate(
        {
            "codes": ["AAPL.US"],
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "source": "yfinance",
            "position_adjustment": position_adjustment,
            "rebalance_mask": mask,
        }
    )

    assert config.rebalance_mask == mask


@pytest.mark.parametrize(
    "overrides",
    [
        {"position_adjustment": "hold", "rebalance_mask": "MS"},
        {"position_adjustment": "rebalance", "rebalance_mask": "monthly"},
    ],
)
def test_schema_rejects_ambiguous_or_invalid_mask(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="rebalance_mask"):
        BacktestConfigSchema.model_validate(
            {
                "codes": ["AAPL.US"],
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "source": "yfinance",
                **overrides,
            }
        )
