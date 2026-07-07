from __future__ import annotations

from src.reliability.quant.cost import (
    ADV_PARTICIPATION_GRID,
    build_capacity_report,
)


def test_capacity_adv_caps() -> None:
    report = build_capacity_report(
        order_notional_by_symbol={"000001.SZ": 1_000_000.0},
        adv_notional_by_symbol={"000001.SZ": 20_000_000.0},
    )

    assert ADV_PARTICIPATION_GRID == [0.05, 0.10, 0.20]
    assert [item.participation for item in report.participation] == [0.05, 0.10, 0.20]
    assert report.max_participation_used == 0.05


def test_capacity_missing_adv_warns_and_caps() -> None:
    report = build_capacity_report(
        order_notional_by_symbol={"000001.SZ": 1_000_000.0},
        adv_notional_by_symbol=None,
    )

    assert report.conclusion_cap == "research_candidate"
    assert any(issue.code == "QUANT_ADV_UNAVAILABLE" for issue in report.warnings)
