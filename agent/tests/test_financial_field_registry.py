"""Tests for the A-share financial field registry."""

from __future__ import annotations

import pytest

from backtest.financials.ashare.field_registry import (
    AmbiguousFinancialFieldError,
    SUPPORTED_FINANCIAL_TABLES,
    UnknownFinancialFieldError,
    build_financial_query_plan,
    get_field_tables,
    get_financial_field_registry,
    get_table_metadata,
)


class TestFinancialFieldRegistry:
    def test_loads_all_supported_tables(self) -> None:
        registry = get_financial_field_registry()

        assert set(registry.tables) == set(SUPPORTED_FINANCIAL_TABLES)

    def test_income_metadata_contains_vip_and_points(self) -> None:
        income = get_table_metadata("income")

        assert income.api_name == "income"
        assert income.vip_api_name == "income_vip"
        assert income.min_points == 2000
        assert income.vip_min_points == 5000
        assert income.supports_cross_sectional_query is True
        assert income.mcp_read_file_path == "skills/tushare/references/股票数据/财务数据/利润表.md"
        assert income.key_columns[:3] == ("ts_code", "ann_date", "f_ann_date")

    def test_field_ownership_supports_unique_and_shared_fields(self) -> None:
        assert get_field_tables("grossprofit_margin") == ("fina_indicator",)
        assert get_field_tables("n_cashflow_act") == ("cashflow",)
        assert get_field_tables("revenue") == ("income", "express")
        assert get_field_tables("total_assets") == ("balancesheet", "express")

    def test_unknown_field_returns_empty_owner_tuple(self) -> None:
        assert get_field_tables("not_a_real_financial_field") == ()

    def test_assesses_cross_sectional_capability_for_query_plan(self) -> None:
        registry = get_financial_field_registry()
        plan = build_financial_query_plan(
            ["revenue"],
            preferred_tables={"revenue": "income"},
        )

        capability = registry.assess_cross_sectional_query(plan)

        assert capability.supported is True
        assert capability.supported_tables == ("income",)
        assert capability.unsupported_tables == ()
        assert capability.required_points_by_table == {"income": 5000}
        assert capability.required_points == 5000


class TestFinancialQueryPlan:
    def test_groups_unique_fields_and_auto_adds_keys(self) -> None:
        plan = build_financial_query_plan([
            "grossprofit_margin",
            "n_cashflow_act",
            "ocfps",
        ])

        assert plan.requested_fields == {
            "fina_indicator": ("grossprofit_margin", "ocfps"),
            "cashflow": ("n_cashflow_act",),
        }
        assert plan.auto_included_keys["fina_indicator"] == ("ts_code", "ann_date", "end_date")
        assert plan.auto_included_keys["cashflow"][:3] == ("ts_code", "ann_date", "f_ann_date")
        assert plan.query_fields["fina_indicator"][:3] == ("ts_code", "ann_date", "end_date")

    def test_ambiguous_field_raises_without_preference(self) -> None:
        with pytest.raises(AmbiguousFinancialFieldError):
            build_financial_query_plan(["revenue"])

    def test_preferred_table_resolves_ambiguous_field(self) -> None:
        plan = build_financial_query_plan(
            ["revenue", "total_assets"],
            preferred_tables={
                "revenue": "express",
                "total_assets": "balancesheet",
            },
        )

        assert plan.requested_fields == {
            "express": ("revenue",),
            "balancesheet": ("total_assets",),
        }

    def test_unknown_field_raises_in_strict_mode(self) -> None:
        with pytest.raises(UnknownFinancialFieldError):
            build_financial_query_plan(["grossprofit_margin", "not_a_real_financial_field"])

    def test_unknown_and_ambiguous_fields_are_reported_in_non_strict_mode(self) -> None:
        plan = build_financial_query_plan(
            ["revenue", "not_a_real_financial_field", "grossprofit_margin"],
            strict=False,
        )

        assert plan.requested_fields == {"fina_indicator": ("grossprofit_margin",)}
        assert plan.ambiguous_fields == {"revenue": ("income", "express")}
        assert plan.unknown_fields == ("not_a_real_financial_field",)