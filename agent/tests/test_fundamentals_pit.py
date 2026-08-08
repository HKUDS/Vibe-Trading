from __future__ import annotations

import sys
from types import ModuleType

import pandas as pd
import pytest

from backtest.loaders import fundamentals_loader


def _install_schema_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    schema = ModuleType("backtest.loaders._fundamental_schema")
    schema.SEC_CONCEPT_MAP = {
        "revenue": [
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
        ],
        "net_income": ["NetIncomeLoss"],
    }
    schema.DERIVED_FIELDS = {}
    schema.resolve_field = lambda field: field.removeprefix("fund:")
    monkeypatch.setitem(sys.modules, "backtest.loaders._fundamental_schema", schema)


def _facts(concept_rows: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    return {
        "facts": {
            "us-gaap": {
                concept: {"units": {"USD": rows}}
                for concept, rows in concept_rows.items()
            }
        }
    }


def _fact_row(
    end: str,
    filed: str,
    value: float,
    *,
    form: str = "10-Q",
    start: str | None = None,
) -> dict[str, object]:
    if start is None:
        # Default to a true-quarter duration so flow-concept frames survive
        # the loader's start/end span filter.
        start = (pd.Timestamp(end) - pd.Timedelta(days=91)).strftime("%Y-%m-%d")
    return {"start": start, "end": end, "filed": filed, "val": value, "form": form}


def _patch_sec(
    monkeypatch: pytest.MonkeyPatch,
    facts_by_symbol: dict[str, dict[str, object]],
) -> None:
    def cik_for(symbol: str) -> str | None:
        return f"CIK-{symbol}" if symbol in facts_by_symbol else None

    def get_company_facts(cik: str) -> dict[str, object]:
        symbol = cik.removeprefix("CIK-")
        return facts_by_symbol[symbol]

    monkeypatch.setattr(fundamentals_loader.sec_edgar_client, "cik_for", cik_for)
    monkeypatch.setattr(
        fundamentals_loader.sec_edgar_client,
        "get_company_facts",
        get_company_facts,
    )


def test_filed_at_t_plus_30_does_not_appear_before_filed_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_schema_stub(monkeypatch)
    _patch_sec(
        monkeypatch,
        {
            "AAA": _facts(
                {
                    "Revenues": [
                        _fact_row("2023-12-31", "2024-01-30", 100.0),
                    ]
                }
            )
        },
    )
    index = pd.date_range("2024-01-01", "2024-02-05", freq="D")

    panel = fundamentals_loader.load_fundamental_panel(
        ["AAA"],
        ["revenue"],
        "2024-01-01",
        "2024-02-05",
        freq="quarterly",
        index=index,
    )

    revenue = panel["revenue"]["AAA"]
    assert pd.isna(revenue.loc["2024-01-29"])
    assert revenue.loc["2024-01-30"] == 100.0
    assert revenue.loc["2024-02-05"] == 100.0


def test_restatement_first_filed_is_pit_and_latest_filed_is_research_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_schema_stub(monkeypatch)
    _patch_sec(
        monkeypatch,
        {
            "AAA": _facts(
                {
                    "Revenues": [
                        _fact_row("2023-12-31", "2024-01-15", 100.0),
                        _fact_row("2023-12-31", "2024-07-15", 120.0),
                    ]
                }
            )
        },
    )
    index = pd.date_range("2024-01-10", "2024-07-20", freq="D")

    pit_panel = fundamentals_loader.load_fundamental_panel(
        ["AAA"],
        ["revenue"],
        "2024-01-10",
        "2024-07-20",
        freq="quarterly",
        pit=True,
        index=index,
    )
    research_panel = fundamentals_loader.load_fundamental_panel(
        ["AAA"],
        ["revenue"],
        "2024-01-10",
        "2024-07-20",
        freq="quarterly",
        pit=False,
        index=index,
    )

    assert pit_panel["revenue"].loc["2024-07-20", "AAA"] == 100.0
    assert research_panel["revenue"].loc["2024-07-14", "AAA"] != 120.0
    assert research_panel["revenue"].loc["2024-07-15", "AAA"] == 120.0


def test_ffill_anchors_on_filed_date_not_period_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_schema_stub(monkeypatch)
    _patch_sec(
        monkeypatch,
        {
            "AAA": _facts(
                {
                    "Revenues": [
                        _fact_row("2024-03-31", "2024-05-01", 77.0),
                    ]
                }
            )
        },
    )
    index = pd.to_datetime(["2024-04-15", "2024-05-01"])

    panel = fundamentals_loader.load_fundamental_panel(
        ["AAA"],
        ["revenue"],
        "2024-04-15",
        "2024-05-01",
        freq="quarterly",
        index=index,
    )

    assert pd.isna(panel["revenue"].loc[pd.Timestamp("2024-04-15"), "AAA"])
    assert panel["revenue"].loc[pd.Timestamp("2024-05-01"), "AAA"] == 77.0


def test_concept_alias_union_resolves_new_standard_revenue_concept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_schema_stub(monkeypatch)
    _patch_sec(
        monkeypatch,
        {
            "AAA": _facts(
                {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": [
                        _fact_row("2024-03-31", "2024-04-25", 150.0),
                    ]
                }
            )
        },
    )
    index = pd.to_datetime(["2024-04-24", "2024-04-25"])

    panel = fundamentals_loader.load_fundamental_panel(
        ["AAA"],
        ["revenue"],
        "2024-04-24",
        "2024-04-25",
        freq="quarterly",
        index=index,
    )

    assert pd.isna(panel["revenue"].loc[pd.Timestamp("2024-04-24"), "AAA"])
    assert panel["revenue"].loc[pd.Timestamp("2024-04-25"), "AAA"] == 150.0


def test_panel_shape_aligns_to_given_index_and_missing_cik_is_nan(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _install_schema_stub(monkeypatch)
    _patch_sec(
        monkeypatch,
        {
            "AAA": _facts(
                {
                    "Revenues": [
                        _fact_row("2024-03-31", "2024-04-25", 150.0),
                    ]
                }
            )
        },
    )
    index = pd.to_datetime(["2024-04-20", "2024-04-25", "2024-04-30"])

    panel = fundamentals_loader.load_fundamental_panel(
        ["AAA", "MISS"],
        ["revenue"],
        "2024-04-01",
        "2024-04-30",
        freq="quarterly",
        index=index,
    )

    frame = panel["revenue"]
    assert frame.shape == (3, 2)
    assert list(frame.index) == list(index)
    assert list(frame.columns) == ["AAA", "MISS"]
    assert frame.loc[pd.Timestamp("2024-04-25"), "AAA"] == 150.0
    assert frame["MISS"].isna().all()
    assert "No SEC CIK for symbols: MISS" in caplog.text


def test_ttm_flow_fields_use_four_quarter_rolling_sum_on_latest_filed_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_schema_stub(monkeypatch)
    _patch_sec(
        monkeypatch,
        {
            "AAA": _facts(
                {
                    "Revenues": [
                        _fact_row("2023-03-31", "2023-04-25", 10.0),
                        _fact_row("2023-06-30", "2023-07-25", 20.0),
                        _fact_row("2023-09-30", "2023-10-25", 30.0),
                        _fact_row("2023-12-31", "2024-01-25", 40.0),
                    ]
                }
            )
        },
    )
    index = pd.to_datetime(["2024-01-24", "2024-01-25", "2024-01-26"])

    panel = fundamentals_loader.load_fundamental_panel(
        ["AAA"],
        ["revenue"],
        "2024-01-24",
        "2024-01-26",
        index=index,
    )

    assert pd.isna(panel["revenue"].loc[pd.Timestamp("2024-01-24"), "AAA"])
    assert panel["revenue"].loc[pd.Timestamp("2024-01-25"), "AAA"] == 100.0
    assert panel["revenue"].loc[pd.Timestamp("2024-01-26"), "AAA"] == 100.0


def test_ytd_and_full_year_frames_are_excluded_and_q4_is_synthesized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: SEC duration entries mix 3-month, YTD, and full-year frames.

    Live AAPL data produced a ~$1T "TTM revenue" because YTD frames sharing a
    quarter's end date were rolled into the four-quarter sum. Only true-quarter
    spans may enter the rolling sum, and the fiscal Q4 (reported only inside
    the 10-K full-year frame) must be synthesized as FY - (Q1 + Q2 + Q3),
    anchored on the 10-K filed date.
    """
    _install_schema_stub(monkeypatch)
    _patch_sec(
        monkeypatch,
        {
            "AAPL": _facts(
                {
                    "Revenues": [
                        # FY2023: three true quarters filed via 10-Qs...
                        _fact_row("2023-03-31", "2023-04-20", 10.0, start="2023-01-01"),
                        _fact_row("2023-06-30", "2023-07-20", 20.0, start="2023-04-01"),
                        # ...plus a YTD frame sharing the Q2 end date (must be ignored)
                        _fact_row("2023-06-30", "2023-07-20", 30.0, start="2023-01-01"),
                        _fact_row("2023-09-30", "2023-10-20", 30.0, start="2023-07-01"),
                        # 10-K: full-year frame only (no explicit Q4) => Q4 = 100-60 = 40
                        _fact_row("2023-12-31", "2024-02-01", 100.0, form="10-K", start="2023-01-01"),
                    ]
                }
            )
        },
    )
    index = pd.to_datetime(["2024-01-31", "2024-02-01", "2024-02-02"])
    panel = fundamentals_loader.load_fundamental_panel(
        ["AAPL"],
        ["revenue"],
        "2024-01-31",
        "2024-02-02",
        freq="ttm",
        pit=True,
        source="sec",
        index=index,
    )
    series = panel["revenue"]["AAPL"]
    # Before the 10-K filing there is no complete four-quarter window.
    assert pd.isna(series.loc[pd.Timestamp("2024-01-31")])
    # From the 10-K filed date: TTM = 10 + 20 + 30 + synthesized Q4 (40) = 100,
    # NOT values inflated by the 30.0 YTD frame or the 100.0 full-year frame.
    assert series.loc[pd.Timestamp("2024-02-01")] == 100.0
    assert series.loc[pd.Timestamp("2024-02-02")] == 100.0


def test_unresolvable_symbols_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A market this loader cannot serve must raise, not return an empty panel.

    ``get_fundamentals("600519.SH")`` used to answer ``ok: true`` with every
    value null, which reads as "this issuer reports nothing" rather than "this
    loader is US-only".
    """
    _install_schema_stub(monkeypatch)
    _patch_sec(monkeypatch, {})

    with pytest.raises(ValueError, match="no SEC CIK resolved"):
        fundamentals_loader.load_fundamental_panel(
            symbols=["600519.SH"],
            fields=["revenue"],
            start="2023-01-01",
            end="2023-03-01",
        )


def test_a_partially_resolvable_batch_still_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One unresolvable symbol must not sink the symbols that do resolve."""
    _install_schema_stub(monkeypatch)
    _patch_sec(
        monkeypatch,
        {"AAPL": _facts({"Revenues": [_fact_row("2023-12-31", "2024-01-30", 100.0)]})},
    )

    panel = fundamentals_loader.load_fundamental_panel(
        ["AAPL", "600519.SH"],
        ["revenue"],
        "2024-01-01",
        "2024-02-05",
        freq="quarterly",
    )
    assert panel["revenue"]["AAPL"].notna().any()
    assert panel["revenue"]["600519.SH"].isna().all()
