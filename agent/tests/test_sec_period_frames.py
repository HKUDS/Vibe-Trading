"""Regression tests for SEC XBRL period-frame selection.

SEC ``companyfacts`` files the true quarter and the year-to-date frame for the
same ``end`` date under the same ``fy``/``fp``/``form``/``accn``, so a consumer
keying on anything narrower than the ``(start, end)`` span silently lets one
overwrite the other. Reproduced live on AAPL before the fix: 36 of 81 revenue
keys collided, ``period="annual"`` returned 64,698,000,000 for FY2020 against a
filed 274,515,000,000, and ``period="quarter"`` served the full-year figure in
every fiscal-Q4 slot.

All HTTP is mocked; no test touches a live endpoint.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from backtest.loaders import sec_frames
from src.tools.financial_statements_tool import FinancialStatementsTool
from src.tools.sec_filings_tool import _parse_metric


def _row(start, end, val, *, fy, fp, form, accn, filed):
    """Build one companyfacts unit row; ``start=None`` makes it an instant fact."""
    row = {
        "end": end,
        "val": val,
        "fy": fy,
        "fp": fp,
        "form": form,
        "accn": accn,
        "filed": filed,
    }
    if start is not None:
        row["start"] = start
    return row


def _facts(rows, concept="Revenues"):
    """Wrap unit rows in the companyfacts envelope shape."""
    return {"facts": {"us-gaap": {concept: {"label": concept, "units": {"USD": rows}}}}}


def _fetch(facts, *, statement="income", period="annual", code="AAPL.US"):
    """Run the tool against a mocked companyfacts payload and return its periods."""
    with patch(
        "src.tools.financial_statements_tool.cik_for", return_value="0000320193"
    ), patch(
        "src.tools.financial_statements_tool.get_company_facts", return_value=facts
    ):
        text = FinancialStatementsTool().execute(
            code=code, statement=statement, period=period
        )
    payload = json.loads(text)
    assert payload["ok"] is True
    return payload["data"][code]["periods"]


# The shape that caused the defect: one 10-Q carrying a 272-day year-to-date
# frame and the 90-day quarter it contains, identical in every other field.
_TENQ_COLLISION = [
    _row("2025-09-28", "2026-06-27", 364_357, fy=2026, fp="Q3", form="10-Q",
         accn="q3", filed="2026-07-31"),
    _row("2026-03-29", "2026-06-27", 109_417, fy=2026, fp="Q3", form="10-Q",
         accn="q3", filed="2026-07-31"),
]

# The same shape on a 10-K: the full year and a Q4 duration frame share an end.
_TENK_COLLISION = [
    _row("2019-09-29", "2020-09-26", 274_515, fy=2020, fp="FY", form="10-K",
         accn="k20", filed="2020-10-30"),
    _row("2020-06-28", "2020-09-26", 64_698, fy=2020, fp="FY", form="10-K",
         accn="k20", filed="2020-10-30"),
]


class TestSpanPrimitives:
    """The shared span helpers are the single definition of the thresholds."""

    def test_span_days_measures_a_duration_fact(self):
        assert sec_frames.span_days({"start": "2026-03-29", "end": "2026-06-27"}) == 90

    def test_span_days_is_none_for_an_instant_fact(self):
        assert sec_frames.span_days({"end": "2026-06-27"}) is None

    def test_classify_span_separates_the_four_kinds(self):
        assert sec_frames.classify_span(None) == sec_frames.INSTANT
        assert sec_frames.classify_span(90) == sec_frames.QUARTER
        assert sec_frames.classify_span(363) == sec_frames.ANNUAL
        assert sec_frames.classify_span(272) == sec_frames.YTD
        assert sec_frames.classify_span(181) == sec_frames.YTD

    def test_frame_key_separates_a_ytd_frame_from_its_quarter(self):
        ytd, quarter = _TENQ_COLLISION
        assert sec_frames.frame_key(ytd) != sec_frames.frame_key(quarter)

    def test_matches_cadence_rejects_year_to_date_at_both_cadences(self):
        ytd, quarter = _TENQ_COLLISION
        assert sec_frames.matches_cadence(ytd, "quarter") is False
        assert sec_frames.matches_cadence(ytd, "annual") is False
        assert sec_frames.matches_cadence(quarter, "quarter") is True
        assert sec_frames.matches_cadence(quarter, "annual") is False


class TestQuarterCadence:
    """A quarterly series carries true quarters and nothing else."""

    def test_year_to_date_frame_never_replaces_the_quarter(self):
        periods = _fetch(_facts(_TENQ_COLLISION), period="quarter")
        assert [p["Revenues"] for p in periods] == [109_417]
        assert periods[0]["PERIOD_DAYS"] == 90
        assert periods[0]["PERIOD_TYPE"] == sec_frames.QUARTER

    def test_full_year_frame_is_not_served_as_a_quarter(self):
        periods = _fetch(_facts(_TENK_COLLISION), period="quarter")
        assert 274_515 not in [p.get("Revenues") for p in periods]
        assert [p["Revenues"] for p in periods] == [64_698]


class TestAnnualCadence:
    """An annual series carries full-year frames and nothing else."""

    def test_quarter_frame_never_overwrites_the_full_year(self):
        periods = _fetch(_facts(_TENK_COLLISION), period="annual")
        assert [p["Revenues"] for p in periods] == [274_515]
        assert periods[0]["PERIOD_DAYS"] == 363

    def test_year_to_date_frame_is_excluded(self):
        periods = _fetch(_facts(_TENQ_COLLISION), period="annual")
        assert periods == []


class TestFiscalQ4Synthesis:
    """Q4 flows are filed only inside the 10-K, so they must be derived."""

    _NO_Q4_FILED = [
        _row("2023-10-01", "2024-09-28", 400, fy=2024, fp="FY", form="10-K",
             accn="k24", filed="2024-11-01"),
        _row("2023-10-01", "2023-12-30", 120, fy=2024, fp="Q1", form="10-Q",
             accn="q1", filed="2024-02-02"),
        _row("2023-12-31", "2024-03-30", 90, fy=2024, fp="Q2", form="10-Q",
             accn="q2", filed="2024-05-03"),
        _row("2024-03-31", "2024-06-29", 85, fy=2024, fp="Q3", form="10-Q",
             accn="q3", filed="2024-08-02"),
    ]

    def test_missing_q4_is_derived_from_the_full_year(self):
        periods = _fetch(_facts(self._NO_Q4_FILED), period="quarter")
        by_end = {p["REPORT_DATE"]: p for p in periods}
        q4 = by_end["2024-09-28"]
        assert q4["Revenues"] == 400 - (120 + 90 + 85)
        assert q4["FISCAL_PERIOD"] == "Q4"

    def test_a_derived_quarter_is_labelled_as_derived(self):
        periods = _fetch(_facts(self._NO_Q4_FILED), period="quarter")
        q4 = next(p for p in periods if p["REPORT_DATE"] == "2024-09-28")
        assert q4["DERIVED"] == "FY - (Q1 + Q2 + Q3)"

    def test_a_filed_q4_is_not_overwritten_by_a_derived_one(self):
        periods = _fetch(_facts(_TENK_COLLISION), period="quarter")
        q4 = next(p for p in periods if p["REPORT_DATE"] == "2020-09-26")
        assert q4["Revenues"] == 64_698
        assert "DERIVED" not in q4


class TestComparativeVintages:
    """One period repeated across filings is one row, not one row per filing."""

    _RESTATED = [
        _row("2022-10-02", "2023-09-30", 383_285, fy=2023, fp="FY", form="10-K",
             accn="k23", filed="2023-11-03"),
        _row("2022-10-02", "2023-09-30", 383_290, fy=2024, fp="FY", form="10-K",
             accn="k24", filed="2024-11-01"),
        _row("2022-10-02", "2023-09-30", 383_290, fy=2025, fp="FY", form="10-K",
             accn="k25", filed="2025-10-31"),
    ]

    def test_one_period_yields_one_row(self):
        periods = _fetch(_facts(self._RESTATED), period="annual")
        assert len(periods) == 1

    def test_the_restated_value_wins_and_both_dates_are_visible(self):
        period = _fetch(_facts(self._RESTATED), period="annual")[0]
        assert period["Revenues"] == 383_290
        assert period["FILED"] == "2023-11-03"
        assert period["LAST_FILED"] == "2025-10-31"

    def test_the_originating_filing_supplies_the_fiscal_label(self):
        period = _fetch(_facts(self._RESTATED), period="annual")[0]
        assert period["FISCAL_YEAR"] == 2023


class TestInstantAndDurationMerge:
    """``indicators`` mixes balance-sheet instants with income-statement flows."""

    def test_one_period_carries_both_kinds_of_concept(self):
        facts = {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "label": "Revenues",
                        "units": {
                            "USD": [
                                _row("2023-10-01", "2024-09-28", 400, fy=2024,
                                     fp="FY", form="10-K", accn="k24",
                                     filed="2024-11-01")
                            ]
                        },
                    },
                    "Assets": {
                        "label": "Assets",
                        "units": {
                            "USD": [
                                _row(None, "2024-09-28", 365_000, fy=2024,
                                     fp="FY", form="10-K", accn="k24",
                                     filed="2024-11-01")
                            ]
                        },
                    },
                }
            }
        }
        periods = _fetch(facts, statement="indicators", period="annual")
        assert len(periods) == 1
        assert periods[0]["Revenues"] == 400
        assert periods[0]["Assets"] == 365_000


class TestSecFilingsMetricPoints:
    """Raw metric points keep every frame but must never be ambiguous."""

    def test_each_point_carries_its_span_and_kind(self):
        points = _parse_metric(_facts(_TENQ_COLLISION), "Revenues", 10)["points"]
        by_val = {p["val"]: p for p in points}
        assert by_val[364_357]["period_type"] == sec_frames.YTD
        assert by_val[364_357]["period_days"] == 272
        assert by_val[109_417]["period_type"] == sec_frames.QUARTER
        assert by_val[109_417]["period_days"] == 90

    def test_repeated_vintages_of_one_period_collapse(self):
        rows = TestComparativeVintages._RESTATED
        points = _parse_metric(_facts(rows), "Revenues", 10)["points"]
        assert len(points) == 1
        assert points[0]["val"] == 383_290

    def test_points_are_ordered_oldest_first(self):
        points = _parse_metric(_facts(_TENQ_COLLISION + _TENK_COLLISION),
                               "Revenues", 10)["points"]
        ends = [p["end"] for p in points]
        assert ends == sorted(ends)
