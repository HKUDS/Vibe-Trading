"""Regression tests for the ``gross_profit`` revenue-minus-cogs fallback.

``RAW_FIELDS["gross_profit"]`` declares ``compute = revenue - cogs`` so that
filers who report revenue and cogs separately (without a literal
``GrossProfit`` XBRL concept) still get a gross profit and, transitively, a
``gross_profitability``. These tests pin that fallback at the loader level,
including PIT anchoring and the preference for the directly reported concept.

No test touches a live endpoint: ``cik_for`` / ``get_company_facts`` are
monkeypatched on the loader's SEC client module.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.loaders import fundamentals_loader


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


_QUARTER_END = "2024-03-31"
_FILED = "2024-04-20"


def test_gross_profit_falls_back_to_revenue_minus_cogs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_sec(
        monkeypatch,
        {
            "AAA": _facts(
                {
                    "Revenues": [_fact_row(_QUARTER_END, _FILED, 100.0)],
                    "CostOfRevenue": [_fact_row(_QUARTER_END, _FILED, 60.0)],
                    "Assets": [_fact_row(_QUARTER_END, _FILED, 1000.0)],
                }
            )
        },
    )
    index = pd.date_range("2024-04-01", "2024-05-01", freq="D")
    panel = fundamentals_loader.load_fundamental_panel(
        ["AAA"],
        ["gross_profit", "gross_profitability"],
        "2024-04-01",
        "2024-05-01",
        freq="quarterly",
        index=index,
    )

    gross_profit = panel["gross_profit"]["AAA"]
    # PIT: nothing visible before the filing date, fallback value after.
    assert pd.isna(gross_profit.loc["2024-04-19"])
    assert gross_profit.loc["2024-04-20"] == 40.0
    assert gross_profit.loc["2024-05-01"] == 40.0

    profitability = panel["gross_profitability"]["AAA"]
    assert pd.isna(profitability.loc["2024-04-19"])
    assert profitability.loc["2024-04-20"] == pytest.approx(0.04)


def test_gross_profit_prefers_direct_concept_over_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_sec(
        monkeypatch,
        {
            "AAA": _facts(
                {
                    "GrossProfit": [_fact_row(_QUARTER_END, _FILED, 45.0)],
                    "Revenues": [_fact_row(_QUARTER_END, _FILED, 100.0)],
                    "CostOfRevenue": [_fact_row(_QUARTER_END, _FILED, 60.0)],
                    "Assets": [_fact_row(_QUARTER_END, _FILED, 1000.0)],
                }
            )
        },
    )
    index = pd.date_range("2024-04-01", "2024-05-01", freq="D")

    panel = fundamentals_loader.load_fundamental_panel(
        ["AAA"],
        ["gross_profit", "gross_profitability"],
        "2024-04-01",
        "2024-05-01",
        freq="quarterly",
        index=index,
    )

    assert panel["gross_profit"]["AAA"].loc["2024-04-20"] == 45.0
    assert panel["gross_profitability"]["AAA"].loc["2024-04-20"] == pytest.approx(0.045)


def test_gross_profit_stays_null_without_either_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_sec(
        monkeypatch,
        {
            "AAA": _facts(
                {
                    # revenue present but cogs absent: fallback cannot fire and
                    # must not fabricate a gross profit from revenue alone.
                    "Revenues": [_fact_row(_QUARTER_END, _FILED, 100.0)],
                    "Assets": [_fact_row(_QUARTER_END, _FILED, 1000.0)],
                }
            )
        },
    )
    index = pd.date_range("2024-04-01", "2024-05-01", freq="D")

    panel = fundamentals_loader.load_fundamental_panel(
        ["AAA"],
        ["gross_profit", "gross_profitability"],
        "2024-04-01",
        "2024-05-01",
        freq="quarterly",
        index=index,
    )

    assert pd.isna(panel["gross_profit"]["AAA"].loc["2024-05-01"])
    assert pd.isna(panel["gross_profitability"]["AAA"].loc["2024-05-01"])


def test_gross_profit_direct_concept_is_ttm_summed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_sec(
        monkeypatch,
        {
            "AAA": _facts(
                {
                    "GrossProfit": [
                        _fact_row("2023-06-30", "2023-07-20", 10.0),
                        _fact_row("2023-09-30", "2023-10-20", 20.0),
                        _fact_row("2023-12-31", "2024-01-20", 30.0),
                        _fact_row("2024-03-31", "2024-04-20", 40.0),
                    ]
                }
            )
        },
    )
    index = pd.date_range("2024-04-01", "2024-05-01", freq="D")

    panel = fundamentals_loader.load_fundamental_panel(
        ["AAA"],
        ["gross_profit"],
        "2024-04-01",
        "2024-05-01",
        freq="ttm",
        index=index,
    )

    gross_profit = panel["gross_profit"]["AAA"]
    # TTM must be the rolling four-quarter sum, not the latest quarter.
    assert gross_profit.loc["2024-05-01"] == 100.0


def test_gross_profit_direct_concept_excludes_annual_span_from_quarterly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_sec(
        monkeypatch,
        {
            "AAA": _facts(
                {
                    "GrossProfit": [
                        _fact_row("2023-06-30", "2023-07-20", 10.0),
                        _fact_row("2023-09-30", "2023-10-20", 20.0),
                        _fact_row("2023-12-31", "2024-01-20", 30.0),
                        _fact_row(
                            "2024-03-31",
                            "2024-02-20",
                            100.0,
                            form="10-K",
                            start="2023-03-31",
                        ),
                    ]
                }
            )
        },
    )
    index = pd.date_range("2024-02-01", "2024-03-10", freq="D")

    panel = fundamentals_loader.load_fundamental_panel(
        ["AAA"],
        ["gross_profit"],
        "2024-02-01",
        "2024-03-10",
        freq="quarterly",
        index=index,
    )

    gross_profit = panel["gross_profit"]["AAA"]
    # The 10-K row is an annual span: quarterly cadence must synthesize fiscal
    # Q4 (100 - 10 - 20 - 30), never surface the full-year value.
    assert gross_profit.loc["2024-02-19"] == 30.0
    assert gross_profit.loc["2024-02-20"] == 40.0
