from __future__ import annotations

import pandas as pd

from src.reliability.quant.factor_eval import (
    DEFAULT_IC_HORIZONS,
    build_ic_horizon_report,
    resolve_ic_horizons,
)
from src.research_protocol.model import EvaluationPlan


def test_ic_default_horizons_1_5_20() -> None:
    assert DEFAULT_IC_HORIZONS == [1, 5, 20]
    assert resolve_ic_horizons(None) == [1, 5, 20]


def test_ic_horizons_can_come_from_research_protocol_evaluation_plan() -> None:
    plan = EvaluationPlan(metrics=["ic"], ic_horizons=[1, 10, 20])

    assert resolve_ic_horizons(plan) == [1, 10, 20]


def test_all_ic_outputs_carry_horizon() -> None:
    report, warnings = build_ic_horizon_report({1: 0.03, 5: 0.02, 20: 0.01})

    assert not warnings
    assert [item.horizon for item in report] == [1, 5, 20]
    assert all(item.horizon in {1, 5, 20} for item in report)


def test_ic_decay_denominator_near_zero_warns() -> None:
    report, warnings = build_ic_horizon_report({1: 0.0001, 5: 0.02, 20: 0.01})

    assert [item.decay_to_1d for item in report] == [None, None, None]
    assert any(
        issue.code == "QUANT_IC_DECAY_DENOMINATOR_NEAR_ZERO"
        for issue in warnings
    )


def test_compute_ic_horizon_report_from_factor_and_close_prices() -> None:
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    columns = [f"S{i}" for i in range(6)]
    close = pd.DataFrame(
        {column: range(index + 1, index + 31) for index, column in enumerate(columns)},
        index=dates,
    )
    factor = close.pct_change().fillna(0.0)

    report, _warnings = build_ic_horizon_report.from_prices(factor, close, horizons=[1, 5])

    assert [item.horizon for item in report] == [1, 5]
