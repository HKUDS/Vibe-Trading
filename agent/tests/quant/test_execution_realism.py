from __future__ import annotations

from src.reliability.quant.execution import build_execution_realism_report
from src.reliability.quant.scorecard import ExecutionTimestampSet


def test_execution_realism_distinguishes_all_required_timestamps() -> None:
    report = build_execution_realism_report(
        ExecutionTimestampSet(
            signal_time=True,
            decision_time=True,
            order_time=True,
            fill_time=False,
            price_time=True,
        )
    )

    assert report.required_fields == [
        "signal_time",
        "decision_time",
        "order_time",
        "fill_time",
        "price_time",
    ]
    assert report.missing_fields == ["fill_time"]
    assert report.passed is False
