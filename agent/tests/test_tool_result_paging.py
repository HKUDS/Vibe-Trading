"""Regression: an oversized tool result must be paged, and any cut declared.

A tool result is capped at ``TOOL_RESULT_LIMIT`` characters and the cut used to
be silent. For a JSON envelope it also lands mid-structure, so the model got a
broken fragment and read the records that survived as the whole answer.
Measured live before this landed:

* ``get_financial_statements("AAPL.US", statement="income", period="quarter")``
  serialized to 28,498 characters for 40 periods and delivered roughly 12 — and
  a parser-level cap of 40 put the other 32 quarters out of reach of any request.
* ``get_sec_filings(ticker="AAPL")`` with no options at all serialized to 12,190
  characters, i.e. the default call already overflowed.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.config.limits import TOOL_RESULT_LIMIT, truncate_tool_result
from src.tools._result_paging import fit_records
from src.tools.financial_statements_tool import FinancialStatementsTool


class TestTruncationNotice:
    """The generic backstop for tools that cannot page."""

    def test_a_short_result_is_untouched(self):
        assert truncate_tool_result("short") == "short"

    def test_a_result_at_the_limit_is_untouched(self):
        exact = "x" * TOOL_RESULT_LIMIT
        assert truncate_tool_result(exact) == exact

    def test_an_oversized_result_still_fits_the_budget(self):
        assert len(truncate_tool_result("x" * 50_000)) <= TOOL_RESULT_LIMIT

    def test_an_oversized_result_says_it_was_cut(self):
        out = truncate_tool_result("x" * 50_000)

        assert "TRUNCATED" in out
        assert "50000" in out

    def test_the_notice_survives_an_absurdly_small_budget(self):
        out = truncate_tool_result("x" * 500, limit=40)

        assert len(out) <= 40
        assert "TRUNCATED" in out


class TestFitRecords:
    """Records are paged whole; a page is never a partial record."""

    def _build(self, page, paging):
        return {"paging": paging, "rows": page}

    def test_everything_fits_in_one_page_when_small(self):
        payload = json.loads(fit_records([{"a": 1}, {"a": 2}], 0, self._build))

        assert payload["paging"]["complete"] is True
        assert payload["paging"]["next_offset"] is None
        assert len(payload["rows"]) == 2

    def test_a_large_set_pages_and_reports_the_total(self):
        records = [{"i": i, "pad": "y" * 400} for i in range(100)]

        payload = json.loads(fit_records(records, 0, self._build))

        assert payload["paging"]["total"] == 100
        assert payload["paging"]["complete"] is False
        assert 0 < payload["paging"]["returned"] < 100

    def test_every_page_stays_within_the_budget(self):
        records = [{"i": i, "pad": "y" * 400} for i in range(100)]
        offset, seen, guard = 0, 0, 0
        while True:
            raw = fit_records(records, offset, self._build)
            assert len(raw) <= TOOL_RESULT_LIMIT
            paging = json.loads(raw)["paging"]
            seen += paging["returned"]
            guard += 1
            assert guard < 200
            if paging["complete"]:
                break
            offset = paging["next_offset"]

        assert seen == 100

    def test_records_are_never_split(self):
        records = [{"i": i, "pad": "y" * 400} for i in range(100)]

        rows = json.loads(fit_records(records, 0, self._build))["rows"]

        assert all(set(row) == {"i", "pad"} for row in rows)

    def test_a_single_oversized_record_is_still_emitted(self):
        # One page must always carry at least one record, or paging deadlocks.
        payload = json.loads(fit_records([{"pad": "y" * 50_000}], 0, self._build))

        assert payload["paging"]["returned"] == 1

    def test_max_records_caps_a_page_below_the_budget(self):
        records = [{"i": i} for i in range(100)]

        payload = json.loads(fit_records(records, 0, self._build, max_records=7))

        assert payload["paging"]["returned"] == 7


def _sec_facts(period_count: int) -> dict:
    rows = []
    for i in range(period_count):
        year = 2000 + i // 4
        month = 3 * (i % 4) + 3
        end = f"{year}-{month:02d}-28"
        start = f"{year}-{month - 2:02d}-01"
        rows.append(
            {
                "start": start,
                "end": end,
                "val": 1_000_000 + i,
                "fy": year,
                "fp": f"Q{i % 4 + 1}",
                "form": "10-Q",
                "accn": f"a{i}",
                "filed": f"{year}-{month:02d}-30",
            }
        )
    return {"facts": {"us-gaap": {"Revenues": {"label": "Revenues", "units": {"USD": rows}}}}}


class TestFinancialStatementsPaging:
    """The analyst-facing statement tool must expose its whole history."""

    def _run(self, offset: int, period_count: int = 120):
        with patch(
            "src.tools.financial_statements_tool.cik_for", return_value="0000320193"
        ), patch(
            "src.tools.financial_statements_tool.get_company_facts",
            return_value=_sec_facts(period_count),
        ):
            raw = FinancialStatementsTool().execute(
                code="AAPL.US", statement="income", period="quarter", offset=offset
            )
        return raw, json.loads(raw)

    def test_the_first_page_reports_the_full_period_count(self):
        _, payload = self._run(0)

        assert payload["paging"]["total"] == 120
        assert payload["paging"]["returned"] < 120

    def test_every_page_stays_within_the_budget(self):
        offset, guard = 0, 0
        while True:
            raw, payload = self._run(offset)
            assert len(raw) <= TOOL_RESULT_LIMIT
            guard += 1
            assert guard < 100
            if payload["paging"]["complete"]:
                break
            offset = payload["paging"]["next_offset"]

    def test_paging_reaches_every_period_exactly_once(self):
        offset, ends = 0, []
        while True:
            _, payload = self._run(offset)
            ends.extend(
                row["REPORT_DATE"] for row in payload["data"]["AAPL.US"]["periods"]
            )
            if payload["paging"]["complete"]:
                break
            offset = payload["paging"]["next_offset"]

        assert len(ends) == 120
        assert len(set(ends)) == 120

    def test_a_non_integer_offset_is_rejected(self):
        with patch(
            "src.tools.financial_statements_tool.cik_for", return_value="0000320193"
        ), patch(
            "src.tools.financial_statements_tool.get_company_facts",
            return_value=_sec_facts(8),
        ):
            payload = json.loads(
                FinancialStatementsTool().execute(code="AAPL.US", offset="banana")
            )

        assert payload["ok"] is False

    def test_a_short_history_is_complete_in_one_call(self):
        _, payload = self._run(0, period_count=4)

        assert payload["paging"]["complete"] is True
        assert payload["paging"]["next_offset"] is None
