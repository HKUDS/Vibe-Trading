"""three_scenario must not report 0% upside against a zero price, or 0 years for -3."""

from __future__ import annotations

import json

import pytest

from src.tools.financial_rigor_tool import FinancialRigorTool, three_scenario_valuation


def _valuation(price, years=3):
    return three_scenario_valuation(
        current_price=price, current_eps=5, shares_billion=1,
        growth_optimistic=0.2, growth_neutral=0.1, growth_pessimistic=0.0,
        pe_optimistic=20, pe_neutral=15, pe_pessimistic=10, years=years,
    )


@pytest.mark.parametrize("price", [0, -10])
def test_non_positive_price_reports_null_upside(price) -> None:
    out = _valuation(price)
    assert [s["upside_pct"] for s in out["scenarios"]] == [None, None, None]
    assert out["scenarios"][2]["target_price"] == 50.0
    json.dumps(out, allow_nan=False)


def test_positive_price_keeps_its_upside() -> None:
    out = _valuation(50)
    assert [s["upside_pct"] for s in out["scenarios"]] == [245.6, 99.65, 0.0]


def test_negative_years_is_an_error_envelope() -> None:
    with pytest.raises(ValueError, match="years"):
        _valuation(50, years=-3)
    payload = json.loads(
        FinancialRigorTool().execute(
            command="three_scenario", price=50, eps=5, shares=1,
            growth=[0.2, 0.1, 0.0], pe=[20, 15, 10], years=-3,
        )
    )
    assert payload["status"] == "error"
    assert "years" in payload["error"]


def test_zero_years_is_still_allowed() -> None:
    out = _valuation(50, years=0)
    assert out["scenarios"][1]["future_eps"] == 5.0
