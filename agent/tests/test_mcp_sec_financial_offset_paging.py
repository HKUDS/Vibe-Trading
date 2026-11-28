"""get_sec_filings and get_financial_statements (MCP) must forward offset.

Both tools are paged internally via fit_records(), which returns a
paging.next_offset callers are expected to pass back in to continue reading.
The MCP wrappers dropped that parameter on the way in, the same drift class
PR #715 fixed for factor_analysis: a caller (including an LLM agent) that
follows paging.next_offset from the tool's own response gets a TypeError, and
otherwise has no way to reach anything past the first page.
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import patch

import mcp_server
from src.tools import sec_filings_tool as sft
from src.tools.financial_statements_tool import FinancialStatementsTool
from src.tools.sec_filings_tool import SecFilingsTool

_sec = getattr(mcp_server.get_sec_filings, "fn", None) or getattr(
    mcp_server.get_sec_filings, "__wrapped__", mcp_server.get_sec_filings
)
_fin = getattr(mcp_server.get_financial_statements, "fn", None) or getattr(
    mcp_server.get_financial_statements, "__wrapped__", mcp_server.get_financial_statements
)


def test_get_sec_filings_wrapper_matches_tool_contract():
    spec = SecFilingsTool.parameters
    sig = inspect.signature(_sec)
    missing = set(spec["properties"]) - set(sig.parameters)
    assert not missing, f"MCP wrapper is missing parameters the tool declares: {missing}"


def test_sec_document_selectors_reach_the_agent_tool():
    accession = "0000320193-23-000106"
    with patch.object(mcp_server, "_get_registry") as registry:
        _sec(ticker="AAPL", accession_number=accession, item="1A")
    registry.return_value.execute.assert_called_once_with(
        "get_sec_filings",
        {
            "ticker": "AAPL",
            "limit": 20,
            "offset": 0,
            "accession_number": accession,
            "item": "1A",
        },
    )


def test_get_financial_statements_wrapper_matches_tool_contract():
    spec = FinancialStatementsTool.parameters
    sig = inspect.signature(_fin)
    missing = set(spec["properties"]) - set(sig.parameters)
    assert not missing, f"MCP wrapper is missing parameters the tool declares: {missing}"


def _submissions_with_n_filings(n: int) -> dict:
    return {
        "cik": "320193",
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "form": ["10-K"] * n,
                "accessionNumber": [f"0000320193-23-{i:06d}" for i in range(n)],
                "filingDate": ["2023-11-03"] * n,
                "reportDate": ["2023-09-30"] * n,
                "primaryDocument": [f"aapl-{i}.htm" for i in range(n)],
                "primaryDocDescription": ["10-K"] * n,
            }
        },
    }


def test_mcp_get_sec_filings_offset_reaches_the_second_page():
    # SecFilingsTool caps the parsed filing pool at _MAX_LIMIT=40 regardless
    # of the requested limit, so 40 (not more) is the realistic total here.
    submissions = _submissions_with_n_filings(40)
    with (
        patch.object(sft, "cik_for", return_value="320193"),
        patch.object(sft, "get_submissions", return_value=submissions),
    ):
        page1 = json.loads(_sec(ticker="AAPL", limit=40))
        assert page1["ok"] is True
        assert page1["paging"]["complete"] is False, "40 filings must not fit in one page"
        next_offset = page1["paging"]["next_offset"]
        assert next_offset, "page 1 must report a next_offset when truncated"

        page2 = json.loads(_sec(ticker="AAPL", limit=40, offset=next_offset))

    combined_ids = {f["accession_number"] for f in page1["data"]["filings"]} | {
        f["accession_number"] for f in page2["data"]["filings"]
    }
    assert len(combined_ids) == 40, "paging through offset must recover every filing"
