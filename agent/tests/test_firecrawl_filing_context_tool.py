"""Tests for get_filing_context: SEC EDGAR first, optional Firecrawl filing text.

All HTTP is mocked. The SEC client functions are patched on the
``sec_filings_tool`` module and ``throttled_post_json`` on the Firecrawl tool
module, so no test reaches sec.gov or api.firecrawl.dev. Responses come from the
redacted fixture in ``tests/fixtures/firecrawl/aapl_filing_context.json``.
"""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest
import requests

import src.data_gateway as data_gateway
from src.config.limits import TOOL_RESULT_LIMIT
from src.data_gateway.config import Config
from src.data_gateway.service import MarketDataGateway
from src.tools import firecrawl_filing_context_tool as fct
from src.tools import sec_filings_tool as sft
from src.tools.firecrawl_filing_context_tool import DISABLED_NOTE, FirecrawlFilingContextTool
from src.tools.sec_filings_tool import SecFilingsTool

_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "firecrawl" / "aapl_filing_context.json").read_text(encoding="utf-8")
)
_KEY = "fc-test-key"


def _use_sec_fixture(monkeypatch, submissions: Dict[str, Any] | None = None) -> None:
    monkeypatch.setattr(sft, "cik_for", lambda ticker: _FIXTURE["cik"])
    monkeypatch.setattr(sft, "get_submissions", lambda cik: copy.deepcopy(submissions or _FIXTURE["sec_submissions"]))


def _many_filings(count: int) -> Dict[str, Any]:
    """A long 8-K index with a distinct accession number and document per row."""
    rows: Dict[str, List[Any]] = {
        "form": [],
        "accessionNumber": [],
        "filingDate": [],
        "reportDate": [],
        "primaryDocument": [],
        "primaryDocDescription": [],
    }
    for i in range(count):
        rows["form"].append("8-K")
        rows["accessionNumber"].append(f"0000320193-26-{i:06d}")
        rows["filingDate"].append(f"2026-{12 - i // 28:02d}-{28 - i % 28:02d}")
        rows["reportDate"].append("")
        rows["primaryDocument"].append(f"doc{i}.htm")
        rows["primaryDocDescription"].append("8-K")
    return {"cik": "320193", "filings": {"recent": rows}}


def _scrape_response(url: str) -> Dict[str, Any]:
    """The fixture response, tagged with the requested URL so each filing's text differs."""
    response = copy.deepcopy(_FIXTURE["firecrawl_scrape"])
    response["data"]["markdown"] = f"Document {url}\n\n" + response["data"]["markdown"]
    response["data"]["metadata"]["sourceURL"] = url
    return response


def _record_scrapes(monkeypatch, responses: List[Any] | None = None) -> List[Dict]:
    """Patch the HTTP helper; each queued entry is a response dict or an exception."""
    calls: List[Dict] = []
    queue = list(responses or [])

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        outcome = queue.pop(0) if queue else _scrape_response(kwargs["json_body"]["url"])
        if isinstance(outcome, Exception):
            raise outcome
        return copy.deepcopy(outcome)

    monkeypatch.setattr(fct, "throttled_post_json", fake_post)
    return calls


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status} error", response=response)


def _wide_filings(count: int, width: int) -> Dict[str, Any]:
    """An index whose rows carry a long description, so few of them fill the budget."""
    submissions = _many_filings(count)
    submissions["filings"]["recent"]["primaryDocDescription"] = ["x" * width] * count
    return submissions


def _assert_items_belong_to_page(out: Dict[str, Any]) -> None:
    on_page = {filing["accession_number"] for filing in out["data"]["filings"]}
    for item in out["firecrawl_context"]["items"]:
        assert item["accession_number"] in on_page
        assert item["excerpt"]


def _run(**kwargs) -> Dict[str, Any]:
    raw = FirecrawlFilingContextTool().execute(**kwargs)
    assert len(raw) <= TOOL_RESULT_LIMIT
    return json.loads(raw)


def _sec(**kwargs) -> Dict[str, Any]:
    return json.loads(SecFilingsTool().execute(**kwargs))


class TestAvailability:
    def test_unavailable_without_key(self, monkeypatch):
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        assert FirecrawlFilingContextTool.check_available() is False

    def test_available_with_key(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", _KEY)
        assert FirecrawlFilingContextTool.check_available() is True

    def test_metadata(self):
        assert FirecrawlFilingContextTool.name == "get_filing_context"
        assert FirecrawlFilingContextTool().is_readonly is True


class TestKeyAbsent:
    def test_returns_sec_envelope_unchanged_with_note_and_no_request(self, monkeypatch):
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        _use_sec_fixture(monkeypatch)
        calls = _record_scrapes(monkeypatch)

        out = _run(ticker="AAPL", form="8-K")
        context = out.pop("firecrawl_context")

        assert calls == []
        assert out == _sec(ticker="AAPL", form="8-K")
        assert context == {"enabled": False, "note": DISABLED_NOTE, "items": [], "skipped": []}

    def test_full_sec_page_plus_note_stays_valid_json_within_budget(self, monkeypatch):
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        _use_sec_fixture(monkeypatch, _many_filings(40))
        _record_scrapes(monkeypatch)

        out = _run(ticker="AAPL", form="8-K")
        sec = _sec(ticker="AAPL", form="8-K")

        assert out["firecrawl_context"]["note"] == DISABLED_NOTE
        assert out["data"]["filings"] == sec["data"]["filings"][: out["paging"]["returned"]]
        assert out["paging"]["next_offset"] == out["paging"]["returned"]


class TestSuccess:
    def test_every_item_carries_filing_url_and_date(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", _KEY)
        _use_sec_fixture(monkeypatch)
        calls = _record_scrapes(monkeypatch)

        out = _run(ticker="AAPL", form="8-K", max_filings=3)
        filings = out["data"]["filings"]
        items = out["firecrawl_context"]["items"]

        assert out["ok"] is True and out["source"] == "sec_edgar"
        assert len(items) == 2
        for item, filing in zip(items, filings):
            assert item["source"] == "firecrawl"
            assert item["filing_url"] == filing["document_url"]
            assert item["filing_url"].startswith("https://www.sec.gov/Archives/edgar/data/320193/")
            assert item["filing_date"] == filing["filing_date"]
            assert item["form"] == "8-K"
            assert item["accession_number"] == filing["accession_number"]
            assert item["excerpt"].startswith(f"Document {filing['document_url']}")
        assert out["firecrawl_context"]["skipped"] == [
            {"accession_number": "0000000000-00-000000", "reason": "SEC index row has no filing URL or filing date"}
        ]
        assert "error" not in out["firecrawl_context"]
        assert [call["json_body"]["url"] for call in calls] == [i["filing_url"] for i in items]
        assert calls[0]["url"] == "https://api.firecrawl.dev/v2/scrape"
        assert calls[0]["headers"] == {"Authorization": f"Bearer {_KEY}"}
        assert 0 < calls[0]["timeout"] <= 30
        assert calls[0]["json_body"]["timeout"] == int(calls[0]["timeout"] * 1000)
        assert _KEY not in json.dumps(out)

    def test_row_without_filing_date_is_skipped_not_scraped(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", _KEY)
        submissions = copy.deepcopy(_FIXTURE["sec_submissions"])
        submissions["filings"]["recent"]["filingDate"][0] = ""
        _use_sec_fixture(monkeypatch, submissions)
        calls = _record_scrapes(monkeypatch)

        out = _run(ticker="AAPL", form="8-K", max_filings=1)

        assert calls == []
        assert out["firecrawl_context"]["items"] == []
        assert out["firecrawl_context"]["skipped"][0]["accession_number"] == "0001140361-26-042798"

    def test_query_excerpt_contains_the_match(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", _KEY)
        _use_sec_fixture(monkeypatch)
        _record_scrapes(monkeypatch)

        item = _run(ticker="AAPL", form="8-K", query="item 8.01")["firecrawl_context"]["items"][0]

        assert item["query_found"] is True
        assert "Item 8.01 Other Events" in item["excerpt"]
        assert "](" not in item["excerpt"]

    def test_query_not_found_is_flagged(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", _KEY)
        _use_sec_fixture(monkeypatch)
        _record_scrapes(monkeypatch)

        item = _run(ticker="AAPL", form="8-K", query="no such phrase")["firecrawl_context"]["items"][0]

        assert item["query_found"] is False


class TestFailureFallback:
    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (requests.Timeout("read timed out"), "Firecrawl request timed out after"),
            (_http_error(429), "Firecrawl returned HTTP 429 (rate limited)"),
            (_http_error(401), "Firecrawl returned HTTP 401"),
            (_http_error(502), "Firecrawl returned HTTP 502"),
            (requests.ConnectionError("refused"), "Firecrawl request failed (ConnectionError)"),
        ],
    )
    def test_request_failure_returns_sec_data_with_error(self, monkeypatch, error, expected):
        monkeypatch.setenv("FIRECRAWL_API_KEY", _KEY)
        _use_sec_fixture(monkeypatch)
        calls = _record_scrapes(monkeypatch, [error])

        out = _run(ticker="AAPL", form="8-K", max_filings=3)

        assert len(calls) == 1
        assert out["ok"] is True
        assert out["data"] == _sec(ticker="AAPL", form="8-K")["data"]
        assert out["firecrawl_context"]["items"] == []
        assert out["firecrawl_context"]["error"].startswith(expected)
        assert out["firecrawl_context"]["error"].endswith("scraped 0 of 3 requested filings")

    def test_error_text_never_echoes_the_key(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", _KEY)
        _use_sec_fixture(monkeypatch)
        _record_scrapes(monkeypatch, [requests.exceptions.InvalidHeader(f"Invalid header value b'Bearer {_KEY}'")])

        raw = FirecrawlFilingContextTool().execute(ticker="AAPL", form="8-K")

        assert _KEY not in raw
        assert "Firecrawl request failed (InvalidHeader)" in json.loads(raw)["firecrawl_context"]["error"]

    def test_partial_failure_keeps_fetched_items_and_names_the_failed_filing(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", _KEY)
        _use_sec_fixture(monkeypatch, _many_filings(3))
        first_url = "https://www.sec.gov/Archives/edgar/data/320193/000032019326000000/doc0.htm"
        _record_scrapes(monkeypatch, [_scrape_response(first_url), _http_error(429)])

        context = _run(ticker="AAPL", form="8-K", max_filings=3)["firecrawl_context"]

        assert [item["accession_number"] for item in context["items"]] == ["0000320193-26-000000"]
        assert context["error"] == (
            "Firecrawl returned HTTP 429 (rate limited) for 0000320193-26-000001; scraped 1 of 3 requested filings"
        )

    @pytest.mark.parametrize(
        ("response", "expected"),
        [
            ({"success": False, "error": "Insufficient credits"}, "did not include scraped content"),
            ({"success": True, "data": {"markdown": "", "metadata": {"statusCode": 200}}}, "no readable text"),
            ({"success": True, "data": {"markdown": "![logo](a.jpg) | --- |", "metadata": {}}}, "no readable text"),
            ({"success": True, "data": {"markdown": "Forbidden", "metadata": {"statusCode": 403}}}, "HTTP 403"),
        ],
    )
    def test_unusable_response_is_reported_not_raised(self, monkeypatch, response, expected):
        monkeypatch.setenv("FIRECRAWL_API_KEY", _KEY)
        _use_sec_fixture(monkeypatch)
        _record_scrapes(monkeypatch, [response])

        out = _run(ticker="AAPL", form="8-K")

        assert out["ok"] is True
        assert out["firecrawl_context"]["items"] == []
        assert expected in out["firecrawl_context"]["error"]

    def test_exhausted_time_budget_skips_scraping(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", _KEY)
        _use_sec_fixture(monkeypatch)
        calls = _record_scrapes(monkeypatch)
        monkeypatch.setattr(fct, "_request_budget", lambda: 0.4)

        out = _run(ticker="AAPL", form="8-K")

        assert calls == []
        assert out["ok"] is True
        assert out["firecrawl_context"]["error"].startswith("not enough request time left")

    def test_request_timeout_stays_inside_the_gateway_deadline(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", _KEY)
        _use_sec_fixture(monkeypatch)
        budgets: List[float] = []
        calls = _record_scrapes(monkeypatch)
        real_budget = fct._request_budget
        monkeypatch.setattr(fct, "_request_budget", lambda: budgets.append(real_budget()) or budgets[-1])

        _run(ticker="AAPL", form="8-K")

        assert calls[0]["timeout"] == budgets[0]
        assert budgets[0] < 30 - fct._DEADLINE_MARGIN_S

    def test_stalled_response_ends_at_the_gateway_deadline_and_keeps_sec_data(self, monkeypatch, tmp_path):
        import backtest.loaders._http as http

        gateway = MarketDataGateway(Config(cache_dir=tmp_path / "gateway", source_timeout=2.5))
        monkeypatch.setattr(data_gateway, "_instance", gateway)
        monkeypatch.setenv("FIRECRAWL_API_KEY", _KEY)
        _use_sec_fixture(monkeypatch)

        class TrickleSession:
            def post(self, url, **kwargs):
                for _ in range(8):
                    time.sleep(0.4)
                raise AssertionError("the gateway deadline should have ended this request")

        monkeypatch.setattr(http, "_session_for", lambda bucket: TrickleSession())
        try:
            started = time.monotonic()
            out = _run(ticker="AAPL", form="8-K")
            elapsed = time.monotonic() - started
        finally:
            gateway.close()

        assert elapsed < 3.2
        assert out["ok"] is True
        assert out["data"] == _sec(ticker="AAPL", form="8-K")["data"]
        assert out["firecrawl_context"]["error"].startswith("Firecrawl request timed out")

    def test_sec_failure_is_returned_as_is_without_firecrawl(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", _KEY)
        monkeypatch.setattr(sft, "cik_for", lambda ticker: None)
        calls = _record_scrapes(monkeypatch)

        out = FirecrawlFilingContextTool().execute(ticker="NOPE")

        assert calls == []
        assert out == SecFilingsTool().execute(ticker="NOPE")


class TestSourceOrder:
    def test_sec_envelope_comes_first_and_context_is_appended(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", _KEY)
        _use_sec_fixture(monkeypatch)
        _record_scrapes(monkeypatch)

        out = _run(ticker="AAPL", form="8-K", max_filings=2)
        sec = _sec(ticker="AAPL", form="8-K")

        assert list(out) == list(sec) + ["firecrawl_context"]
        assert out["source"] == "sec_edgar"
        assert out["data"]["filings"] == sec["data"]["filings"]
        assert [i["accession_number"] for i in out["firecrawl_context"]["items"]] == [
            f["accession_number"] for f in sec["data"]["filings"][:2]
        ]

    def test_long_list_keeps_a_prefix_of_the_sec_page_within_budget(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", _KEY)
        _use_sec_fixture(monkeypatch, _many_filings(40))
        _record_scrapes(monkeypatch)

        out = _run(ticker="AAPL", form="8-K", max_filings=3, max_chars=3000)
        sec = _sec(ticker="AAPL", form="8-K")
        paging = out["paging"]

        assert len(out["firecrawl_context"]["items"]) == 3
        assert paging["returned"] >= 3
        assert out["data"]["filings"] == sec["data"]["filings"][: paging["returned"]]
        assert paging["total"] == 40 and paging["offset"] == 0
        assert paging["next_offset"] == paging["returned"] and paging["complete"] is False

    def test_offset_continues_the_sec_list(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", _KEY)
        _use_sec_fixture(monkeypatch, _many_filings(40))
        _record_scrapes(monkeypatch)

        first = _run(ticker="AAPL", form="8-K", max_filings=1)
        second = _run(ticker="AAPL", form="8-K", max_filings=1, offset=first["paging"]["next_offset"])
        sec_second = _sec(ticker="AAPL", form="8-K", offset=first["paging"]["next_offset"])

        assert second["paging"]["offset"] == first["paging"]["next_offset"]
        assert second["data"]["filings"] == sec_second["data"]["filings"][: second["paging"]["returned"]]
        first_item = first["firecrawl_context"]["items"][0]["accession_number"]
        second_item = second["firecrawl_context"]["items"][0]["accession_number"]
        assert first_item == "0000320193-26-000000"
        assert second_item == sec_second["data"]["filings"][0]["accession_number"] != first_item

    @pytest.mark.parametrize(("count", "width"), [(3, 2600), (1, 9300)])
    def test_wide_sec_rows_drop_excerpts_before_breaking_the_budget(self, monkeypatch, count, width):
        monkeypatch.setenv("FIRECRAWL_API_KEY", _KEY)
        _use_sec_fixture(monkeypatch, _wide_filings(count, width))
        _record_scrapes(monkeypatch)

        out = _run(ticker="AAPL", form="8-K", max_filings=3)
        sec = _sec(ticker="AAPL", form="8-K")

        assert out["data"]["filings"] == sec["data"]["filings"][: len(out["data"]["filings"])]
        if "firecrawl_context" in out:
            _assert_items_belong_to_page(out)

    def test_quote_heavy_excerpts_still_fit(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", _KEY)
        _use_sec_fixture(monkeypatch, _many_filings(40))
        heavy = {"success": True, "data": {"markdown": '"\\' * 5000, "metadata": {"statusCode": 200}}}
        _record_scrapes(monkeypatch, [heavy, heavy, heavy])

        out = _run(ticker="AAPL", form="8-K", max_filings=3, max_chars=3000)

        assert len(out["firecrawl_context"]["items"]) == 3
        assert out["paging"]["returned"] >= 3
