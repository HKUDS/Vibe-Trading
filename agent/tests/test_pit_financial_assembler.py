"""Tests for point-in-time financial field assembly."""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.financials.ashare.field_registry import build_financial_query_plan
from backtest.financials.ashare.pit_assembler import (
    assemble_pit_frame,
    canonicalize_financial_rows,
    enrich_data_map_with_financials,
)


def _trade_index() -> pd.DatetimeIndex:
    return pd.DatetimeIndex(
        [
            "2024-05-02",
            "2024-05-03",
            "2024-05-06",
            "2024-05-07",
        ],
        name="trade_date",
    )


def _price_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"close": [1.0, 1.0, 1.0, 1.0]},
        index=_trade_index(),
    )


class TestAssemblePitFrame:
    def test_ann_date_becomes_visible_next_trade_day(self) -> None:
        records = pd.DataFrame(
            {
                "ts_code": ["600519.SH", "600519.SH"],
                "ann_date": ["20240502", "20240505"],
                "f_ann_date": ["20240502", "20240505"],
                "end_date": ["20240331", "20240630"],
                "revenue": [100.0, 120.0],
            }
        )

        pit = assemble_pit_frame(_trade_index(), records, fields=["revenue"])

        assert pd.isna(pit.loc[pd.Timestamp("2024-05-02"), "revenue"])
        assert pit.loc[pd.Timestamp("2024-05-03"), "revenue"] == 100.0
        assert pit.loc[pd.Timestamp("2024-05-06"), "revenue"] == 120.0
        assert pit.loc[pd.Timestamp("2024-05-07"), "revenue"] == 120.0

    def test_canonicalize_keeps_distinct_revisions_but_dedups_same_cycle(self) -> None:
        records = pd.DataFrame(
            {
                "ts_code": ["600519.SH", "600519.SH", "600519.SH"],
                "ann_date": ["20240430", "20240430", "20240510"],
                "f_ann_date": ["20240430", "20240501", "20240510"],
                "end_date": ["20240331", "20240331", "20240331"],
                "report_type": [1, 1, 1],
                "revenue": [100.0, 101.0, 110.0],
            }
        )

        canonical = canonicalize_financial_rows(records)

        assert len(canonical) == 2
        assert canonical.iloc[0]["revenue"] == 101.0
        assert canonical.iloc[1]["revenue"] == 110.0

    def test_report_type_priority_breaks_same_cycle_tie(self) -> None:
        records = pd.DataFrame(
            {
                "ts_code": ["600519.SH", "600519.SH"],
                "ann_date": ["20240430", "20240430"],
                "f_ann_date": ["20240430", "20240430"],
                "end_date": ["20240331", "20240331"],
                "report_type": [1, 2],
                "grossprofit_margin": [88.0, 91.5],
            }
        )

        canonical = canonicalize_financial_rows(records, report_type_priority={1: 0, 2: 10})

        assert len(canonical) == 1
        assert canonical.iloc[0]["grossprofit_margin"] == 91.5

    def test_default_priority_is_order_independent(self) -> None:
        records = pd.DataFrame(
            {
                "ts_code": ["600519.SH", "600519.SH"],
                "ann_date": ["20240430", "20240430"],
                "f_ann_date": ["20240430", "20240430"],
                "end_date": ["20240331", "20240331"],
                "report_type": [1, 2],
                "grossprofit_margin": [88.0, 91.5],
            }
        )

        forward = canonicalize_financial_rows(records)
        reversed_rows = canonicalize_financial_rows(records.iloc[::-1].reset_index(drop=True))

        assert len(forward) == 1
        assert len(reversed_rows) == 1
        assert forward.iloc[0]["report_type"] == 1
        assert reversed_rows.iloc[0]["report_type"] == 1
        assert forward.iloc[0]["grossprofit_margin"] == 88.0
        assert reversed_rows.iloc[0]["grossprofit_margin"] == 88.0


class TestEnrichDataMap:
    def test_per_stock_visibility_dates_remain_independent(self) -> None:
        data_map = {
            "600519.SH": _price_frame(),
            "000001.SZ": _price_frame(),
        }
        raw_tables = {
            "income": pd.DataFrame(
                {
                    "ts_code": ["600519.SH", "000001.SZ"],
                    "ann_date": ["20240502", "20240506"],
                    "f_ann_date": ["20240502", "20240506"],
                    "end_date": ["20240331", "20240331"],
                    "revenue": [100.0, 200.0],
                }
            )
        }
        plan = build_financial_query_plan(["revenue"], preferred_tables={"revenue": "income"})

        enriched = enrich_data_map_with_financials(data_map, raw_tables, plan)

        assert enriched["600519.SH"].loc[pd.Timestamp("2024-05-03"), "revenue"] == 100.0
        assert pd.isna(enriched["000001.SZ"].loc[pd.Timestamp("2024-05-03"), "revenue"])
        assert enriched["000001.SZ"].loc[pd.Timestamp("2024-05-07"), "revenue"] == 200.0

    def test_rejects_invalid_raw_table_schema(self) -> None:
        data_map = {"600519.SH": _price_frame()}
        raw_tables = {
            "income": pd.DataFrame(
                {
                    "ann_date": ["20240502"],
                    "end_date": ["20240331"],
                    "revenue": [100.0],
                }
            )
        }
        plan = build_financial_query_plan(["revenue"], preferred_tables={"revenue": "income"})

        with pytest.raises(ValueError, match="missing key columns") as exc_info:
            enrich_data_map_with_financials(data_map, raw_tables, plan)

        assert "financial table 'income' has invalid schema" in str(exc_info.value)