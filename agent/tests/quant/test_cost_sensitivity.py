from __future__ import annotations

from src.reliability.quant.cost import COST_BPS_GRID, build_cost_sensitivity_report


def test_cost_sensitivity_bps_grid() -> None:
    report = build_cost_sensitivity_report(gross_edge_bps=25.0)

    assert COST_BPS_GRID == [0, 5, 10, 25, 50, 100]
    assert [scenario.bps for scenario in report.scenarios] == [0, 5, 10, 25, 50, 100]
    assert report.cost_breakeven_bps == 25.0


def test_cost_sensitivity_warns_when_10bps_invalidates_edge() -> None:
    report = build_cost_sensitivity_report(gross_edge_bps=8.0)

    assert any(issue.code == "QUANT_COST_SENSITIVE_10BPS_FAIL" for issue in report.warnings)
