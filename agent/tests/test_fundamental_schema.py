from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from backtest.loaders._fundamental_schema import (
    DERIVED_FIELDS,
    RAW_FIELDS,
    SEC_CONCEPT_MAP,
    list_supported_fields,
    resolve_field,
)


EXPECTED_RAW_FIELDS = {
    "revenue",
    "cogs",
    "gross_profit",
    "operating_income",
    "net_income",
    "total_assets",
    "total_equity",
    "total_debt",
    "cash",
    "shares_diluted",
    "cfo",
    "capex",
}


def test_raw_field_schema_and_sec_map_cover_all_raw_fields() -> None:
    assert set(RAW_FIELDS) == EXPECTED_RAW_FIELDS
    assert set(SEC_CONCEPT_MAP) == EXPECTED_RAW_FIELDS

    for field, spec in RAW_FIELDS.items():
        assert spec["statement"]
        assert spec["description"]
        assert SEC_CONCEPT_MAP[field], field


def test_revenue_concept_priority_keeps_new_standard_first() -> None:
    assert SEC_CONCEPT_MAP["revenue"][:4] == [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ]


def test_sec_revenue_fixture_shapes_cover_new_and_old_standard() -> None:
    fixture_dir = Path(__file__).parent / "fixtures" / "sec"
    aapl_like = json.loads((fixture_dir / "aapl_like_companyfacts.json").read_text())
    old_standard = json.loads((fixture_dir / "old_standard_companyfacts.json").read_text())

    aapl_concepts = aapl_like["facts"]["us-gaap"]
    old_concepts = old_standard["facts"]["us-gaap"]

    assert "RevenueFromContractWithCustomerExcludingAssessedTax" in aapl_concepts
    assert "Revenues" not in aapl_concepts
    assert "Revenues" in old_concepts
    assert "RevenueFromContractWithCustomerExcludingAssessedTax" not in old_concepts


def test_shares_diluted_does_not_alias_basic_shares() -> None:
    assert "WeightedAverageNumberOfSharesOutstandingBasic" not in SEC_CONCEPT_MAP["shares_diluted"]


def test_derived_formulas_are_numerically_correct() -> None:
    idx = pd.to_datetime(["2022-12-31", "2023-12-31"])
    data = {
        "gross_profit": pd.Series([40.0, 60.0], index=idx),
        "net_income": pd.Series([10.0, 15.0], index=idx),
        "revenue": pd.Series([100.0, 120.0], index=idx),
        "total_assets": pd.Series([200.0, 250.0], index=idx),
        "total_equity": pd.Series([50.0, 75.0], index=idx),
        "total_debt": pd.Series([100.0, 125.0], index=idx),
        "cfo": pd.Series([7.0, 12.0], index=idx),
    }

    expected = {
        "roe": pd.Series([0.2, 0.2], index=idx),
        "roa": pd.Series([0.05, 0.06], index=idx),
        "gross_profitability": pd.Series([0.2, 0.24], index=idx),
        "accruals": pd.Series([0.015, 0.012], index=idx),
        "leverage": pd.Series([2.0, 125.0 / 75.0], index=idx),
        "revenue_growth": pd.Series([float("nan"), 0.2], index=idx),
        "earnings_growth": pd.Series([float("nan"), 0.5], index=idx),
    }

    for field, expected_series in expected.items():
        result = DERIVED_FIELDS[field]["compute"](data)
        pd.testing.assert_series_equal(result, expected_series, check_names=False)


def test_asset_growth_uses_annual_period_over_period_semantics() -> None:
    idx = pd.to_datetime(["2021-12-31", "2022-12-31", "2023-12-31"])
    data = {"total_assets": pd.Series([100.0, 120.0, 90.0], index=idx)}

    result = DERIVED_FIELDS["asset_growth"]["compute"](data)
    expected = pd.Series([float("nan"), 0.2, -0.25], index=idx)

    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_asset_growth_reads_a_year_ahead_on_a_daily_densified_panel() -> None:
    # load_fundamental_panel densifies every dependency to the daily price
    # index before a derived field runs (backtest.runner passes index=
    # panel["close"].index), so total_assets arrives here as a forward-filled
    # daily series, never one row per annual period_end. A row-positional
    # shift(1) then compares yesterday to today (flat 0% every ordinary day,
    # a spurious one-day spike on a filing update) instead of this year to
    # last -- the growth reading must stay at the true year-over-year value
    # across the whole year following a step, not just on the step's own day.
    dates = pd.date_range("2024-01-01", "2025-12-31", freq="D")
    total_assets = pd.Series(100.0, index=dates)
    total_assets.loc["2024-07-01":] = 110.0
    data = {"total_assets": pd.DataFrame({"AAPL": total_assets})}

    result = DERIVED_FIELDS["asset_growth"]["compute"](data)

    assert result.loc["2025-01-15", "AAPL"] == pytest.approx(0.10)
    assert result.loc["2025-06-25", "AAPL"] == pytest.approx(0.10)


def test_revenue_growth_uses_annual_period_over_period_semantics() -> None:
    idx = pd.to_datetime(["2021-12-31", "2022-12-31", "2023-12-31"])
    data = {"revenue": pd.Series([100.0, 120.0, 90.0], index=idx)}

    result = DERIVED_FIELDS["revenue_growth"]["compute"](data)
    expected = pd.Series([float("nan"), 0.2, -0.25], index=idx)

    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_earnings_growth_is_sign_safe_with_negative_prior_year() -> None:
    idx = pd.to_datetime(["2022-12-31", "2023-12-31"])
    data = {"net_income": pd.Series([-10.0, 5.0], index=idx)}

    result = DERIVED_FIELDS["earnings_growth"]["compute"](data)
    expected = pd.Series([float("nan"), 1.5], index=idx)

    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_growth_fields_zero_or_missing_lag_is_nan() -> None:
    idx = pd.to_datetime(["2021-12-31", "2022-12-31", "2023-12-31"])
    net_income = pd.Series([0.0, 8.0, 4.0], index=idx)
    revenue = pd.Series([float("nan"), 100.0, 110.0], index=idx)

    earnings_growth = DERIVED_FIELDS["earnings_growth"]["compute"]({"net_income": net_income})
    assert pd.isna(earnings_growth.loc["2021-12-31"])
    assert pd.isna(earnings_growth.loc["2022-12-31"])
    assert earnings_growth.loc["2023-12-31"] == pytest.approx(-0.5)

    revenue_growth = DERIVED_FIELDS["revenue_growth"]["compute"]({"revenue": revenue})
    assert pd.isna(revenue_growth.loc["2021-12-31"])
    assert pd.isna(revenue_growth.loc["2022-12-31"])
    assert revenue_growth.loc["2023-12-31"] == pytest.approx(0.10)


def test_growth_fields_read_a_year_ahead_on_a_daily_densified_panel() -> None:
    # Same daily-densification contract as the asset_growth panel test: a
    # row-positional shift(1) would compare yesterday to today, so the YoY
    # reading must hold across the whole year following a mid-year step.
    dates = pd.date_range("2024-01-01", "2025-12-31", freq="D")
    revenue = pd.Series(100.0, index=dates)
    revenue.loc["2024-07-01":] = 110.0
    net_income = pd.Series(-10.0, index=dates)
    net_income.loc["2024-07-01":] = 5.0

    revenue_growth = DERIVED_FIELDS["revenue_growth"]["compute"](
        {"revenue": pd.DataFrame({"AAPL": revenue})}
    )
    earnings_growth = DERIVED_FIELDS["earnings_growth"]["compute"](
        {"net_income": pd.DataFrame({"AAPL": net_income})}
    )

    assert revenue_growth.loc["2025-01-15", "AAPL"] == pytest.approx(0.10)
    assert revenue_growth.loc["2025-06-25", "AAPL"] == pytest.approx(0.10)
    assert earnings_growth.loc["2025-01-15", "AAPL"] == pytest.approx(1.5)
    assert earnings_growth.loc["2025-06-25", "AAPL"] == pytest.approx(1.5)


def test_resolve_field_and_list_supported_fields() -> None:
    kind, raw_spec = resolve_field("revenue")
    assert kind == "raw"
    assert raw_spec is RAW_FIELDS["revenue"]

    kind, derived_spec = resolve_field("roe")
    assert kind == "derived"
    assert derived_spec is DERIVED_FIELDS["roe"]

    supported = list_supported_fields()
    assert supported == sorted(set(RAW_FIELDS) | set(DERIVED_FIELDS))

    with pytest.raises(ValueError, match="unknown fundamental field"):
        resolve_field("earnings_yield")
