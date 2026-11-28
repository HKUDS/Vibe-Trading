"""Offline coverage for reading one SEC primary document through the filing tool."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from backtest.loaders import sec_edgar_client as client
from src.config.limits import TOOL_RESULT_LIMIT
from src.tools import sec_filings_tool as tool
from src.tools._sec_filing_text import extract_excerpts

ACCESSION = "0000320193-23-000106"
URL = "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm"
HTML = (Path(__file__).parent / "fixtures/sec_edgar/primary_document.htm").read_text()


@pytest.fixture
def index(monkeypatch):
    # Put the selected accession beyond the normal 40-row listing, and use
    # an earlier unrelated row so selection cannot silently fall back to it.
    rows = {
        "form": ["8-K"] * 41 + ["10-K"],
        "accessionNumber": [f"0000320193-23-{i:06}" for i in range(41)] + [ACCESSION],
        "primaryDocument": ["other.htm"] * 41 + ["aapl-20230930.htm"],
        "filingDate": ["2023-11-08"] * 41 + ["2023-11-03"],
    }
    monkeypatch.setattr(tool, "cik_for", lambda ticker: "0000320193")
    monkeypatch.setattr(
        tool, "get_submissions", lambda cik: {"filings": {"recent": rows}}
    )
    return rows


def test_tool_selects_exact_filing_and_reads_body_in_order(index):
    with patch.object(tool, "get_primary_document", return_value=HTML) as fetch:
        result = json.loads(
            tool.SecFilingsTool().execute(
                ticker="AAPL", accession_number=ACCESSION, item="Item 1a"
            )
        )
    fetch.assert_called_once_with(URL)
    assert result["ok"]
    assert result["data"] == {
        "ticker": "AAPL",
        "cik": "0000320193",
        "item": "1A",
        "filing": {
            "form": "10-K",
            "filing_date": "2023-11-03",
            "accession_number": ACCESSION,
            "document_url": URL,
        },
        "excerpts": [
            {
                "heading": "Item 1A. Risk Factors",
                "text": "A delayed shipment affected operating revenue.",
            },
            {
                "heading": "Liquidity",
                "text": "Credit terms & cash collections changed.",
            },
        ],
        "truncated": False,
    }


def test_output_is_bounded_and_discloses_truncation(index):
    html = "<p>" + '"\\' * 2000 + "</p>" + "<p>later passage</p>" * 6
    with patch.object(tool, "get_primary_document", return_value=html):
        raw = tool.SecFilingsTool().execute(ticker="AAPL", accession_number=ACCESSION)
    assert len(raw) <= TOOL_RESULT_LIMIT
    data = json.loads(raw)["data"]
    assert data["truncated"]
    assert len(data["excerpts"]) == 4
    assert len(data["excerpts"][0]["text"]) == 700


@pytest.mark.parametrize(
    "kwargs",
    [
        {"accession_number": "not-an-accession"},
        {"item": "1A"},
        {"accession_number": ACCESSION, "item": "any section"},
        {"accession_number": ACCESSION, "metric": "Revenues"},
        {"accession_number": "1111111111-23-000000"},
        {"accession_number": ACCESSION, "form": "10-Q"},
    ],
)
def test_invalid_or_unmatched_selection_never_fetches_a_document(index, kwargs):
    with patch.object(tool, "get_primary_document") as fetch:
        assert not json.loads(tool.SecFilingsTool().execute(ticker="AAPL", **kwargs))[
            "ok"
        ]
    fetch.assert_not_called()


def test_missing_document_or_text_is_explicit_and_preserves_citation(index):
    with patch.object(
        tool, "get_primary_document", return_value="<ix:hidden>only fact</ix:hidden>"
    ) as fetch:
        result = json.loads(
            tool.SecFilingsTool().execute(ticker="AAPL", accession_number=ACCESSION)
        )
        assert not result["ok"] and "no readable" in result["error"]
        assert result["data"]["filing"]["document_url"] == URL
        index["primaryDocument"][-1] = ""
        result = json.loads(
            tool.SecFilingsTool().execute(ticker="AAPL", accession_number=ACCESSION)
        )
        assert not result["ok"] and "no primary document" in result["error"]
    fetch.assert_called_once()


def test_missing_item_does_not_silently_return_the_cover():
    with pytest.raises(ValueError, match="Could not locate Item 7"):
        extract_excerpts(HTML, "7")


def test_unlinked_contents_row_and_inline_item_reference_are_not_body_headings():
    html = (
        "<table><tr><td><div>Item 1A.</div></td><td>Risk Factors</td><td>12</td></tr></table>"
        "<p>Cover.</p><h2>Item 1A. Risk Factors</h2>"
        "<p>Item 7 of this report provides more detail.</p><p>Actual exposure.</p>"
        "<h2>Item 1B. Staff Comments</h2><p>Later.</p>"
    )
    result = extract_excerpts(html, "1A")
    assert [e["text"] for e in result["excerpts"]] == [
        "Item 7 of this report provides more detail.",
        "Actual exposure.",
    ]


def test_missing_date_does_not_produce_an_uncitable_excerpt(index):
    index["filingDate"][-1] = ""
    with patch.object(tool, "get_primary_document") as fetch:
        result = json.loads(
            tool.SecFilingsTool().execute(ticker="AAPL", accession_number=ACCESSION)
        )
    assert not result["ok"] and "filing date" in result["error"]
    fetch.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        URL.replace("www.sec.gov", "example.org"),
        URL.replace("/Archives/edgar/data/", "/files/"),
        URL.replace("aapl-20230930.htm", "../other.htm"),
        URL.replace("aapl-20230930.htm", "%2e%2e/other.htm"),
        URL.replace(".htm", ".pdf"),
    ],
)
def test_only_official_archive_html_is_requested(url):
    with (
        patch.object(client, "throttled_get") as get,
        pytest.raises(ValueError, match="SEC Archives"),
    ):
        client.get_primary_document(url)
    get.assert_not_called()


@pytest.fixture
def response(monkeypatch):
    response = MagicMock(spec=requests.Response)
    response.__enter__.return_value = response
    response.status_code = 200
    response.headers = {"Content-Type": "text/html"}
    response.iter_content.return_value = [b"<p>filing ", b"text</p>"]
    get = MagicMock(return_value=response)
    monkeypatch.setattr(client, "throttled_get", get)
    return response, get


def test_download_uses_the_shared_sec_policy_and_closes_the_stream(response):
    stream, get = response
    assert client.get_primary_document(URL) == "<p>filing text</p>"
    get.assert_called_once_with(
        URL,
        host_key="sec",
        min_interval=client._min_interval(),
        headers={
            "User-Agent": client._user_agent(),
            "Accept": "text/html, application/xhtml+xml",
        },
        allow_redirects=False,
        stream=True,
    )
    stream.__exit__.assert_called_once()


def test_redirect_and_non_html_are_rejected_before_reading_the_body(response):
    stream, _ = response
    stream.status_code = 302
    with pytest.raises(ValueError, match="redirect"):
        client.get_primary_document(URL)
    stream.status_code = 200
    stream.headers = {"Content-Type": "application/pdf"}
    with pytest.raises(ValueError, match="did not return HTML"):
        client.get_primary_document(URL)
    stream.iter_content.assert_not_called()


def test_download_limit_applies_to_the_streamed_body(response, monkeypatch):
    stream, _ = response
    monkeypatch.setattr(client, "_MAX_DOCUMENT_BYTES", 10)
    with pytest.raises(ValueError, match="download limit"):
        client.get_primary_document(URL)
    stream.__exit__.assert_called_once()
