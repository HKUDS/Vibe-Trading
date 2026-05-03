"""Tests for the raw Tushare financial statement loader."""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from backtest.financials.ashare.field_registry import build_financial_query_plan
from backtest.financials.ashare.tushare_loader import TushareFinancialLoader


def _stub_income_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_code": ["600519.SH"],
            "ann_date": ["20240430"],
            "f_ann_date": ["20240430"],
            "end_date": ["20240331"],
            "report_type": [1],
            "comp_type": [1],
            "end_type": ["Q1"],
            "revenue": [123.0],
        }
    )


def _stub_fina_indicator_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_code": ["600519.SH"],
            "ann_date": ["20240430"],
            "end_date": ["20240331"],
            "grossprofit_margin": [91.5],
        }
    )


class TestFetchTable:
    def test_fetch_table_uses_ordinary_api_with_ts_code(self) -> None:
        api = MagicMock()
        api.income.return_value = _stub_income_frame()
        loader = TushareFinancialLoader(api=api)

        frame = loader.fetch_table(
            "income",
            ts_code="600519.SH",
            fields=["ts_code", "ann_date", "revenue"],
            start_date="2024-01-01",
            end_date="2024-06-01",
        )

        api.income.assert_called_once_with(
            ts_code="600519.SH",
            start_date="20240101",
            end_date="20240601",
            fields="ts_code,ann_date,revenue",
        )
        assert list(frame.columns) == list(_stub_income_frame().columns)

    def test_fetch_table_uses_vip_api_for_cross_section(self) -> None:
        api = MagicMock()
        api.income_vip.return_value = _stub_income_frame()
        loader = TushareFinancialLoader(api=api)

        loader.fetch_table(
            "income",
            period="2024-03-31",
            fields=["ts_code", "ann_date", "revenue"],
            use_vip=True,
        )

        api.income_vip.assert_called_once_with(
            period="20240331",
            fields="ts_code,ann_date,revenue",
        )

    def test_fetch_table_rejects_foreign_fields(self) -> None:
        loader = TushareFinancialLoader(api=MagicMock())
        with pytest.raises(ValueError, match="do not belong"):
            loader.fetch_table("income", ts_code="600519.SH", fields=["grossprofit_margin"])

    def test_fetch_table_rejects_reserved_extra_params(self) -> None:
        api = MagicMock()
        loader = TushareFinancialLoader(api=api)

        with pytest.raises(ValueError, match="reserved financial query keys"):
            loader.fetch_table(
                "income",
                ts_code="600519.SH",
                fields=["ts_code", "ann_date", "revenue"],
                extra_params={"fields": "revenue", "ts_code": "000001.SZ"},
            )

        api.income.assert_not_called()


class TestFetchByPlan:
    def test_fetch_for_codes_groups_by_table_and_concatenates(self) -> None:
        api = MagicMock()
        api.income.return_value = _stub_income_frame()
        api.fina_indicator.return_value = _stub_fina_indicator_frame()
        loader = TushareFinancialLoader(api=api)
        plan = build_financial_query_plan(
            ["revenue", "grossprofit_margin"],
            preferred_tables={"revenue": "income"},
        )

        result = loader.fetch_for_codes(
            plan,
            codes=["600519.SH"],
            start_date="2024-01-01",
            end_date="2024-06-01",
        )

        assert set(result) == {"income", "fina_indicator"}
        assert api.income.call_count == 1
        assert api.fina_indicator.call_count == 1
        assert "revenue" in result["income"].columns
        assert "grossprofit_margin" in result["fina_indicator"].columns

    def test_fetch_for_period_uses_vip_endpoints(self) -> None:
        api = MagicMock()
        api.income_vip.return_value = _stub_income_frame()
        api.fina_indicator_vip.return_value = _stub_fina_indicator_frame()
        loader = TushareFinancialLoader(api=api)
        plan = build_financial_query_plan(
            ["revenue", "grossprofit_margin"],
            preferred_tables={"revenue": "income"},
        )

        result = loader.fetch_for_period(plan, period="2024-03-31")

        assert set(result) == {"income", "fina_indicator"}
        api.income_vip.assert_called_once()
        api.fina_indicator_vip.assert_called_once()