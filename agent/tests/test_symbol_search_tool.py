"""Tests for the search_symbol tool.

All HTTP is mocked at the client functions the tool imports
(``eastmoney_client.get_json``, ``yahoo_client.search``,
``sec_edgar_client.cik_for``), so no test ever reaches a live endpoint.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from src.tools import symbol_search_tool as ss


def _eastmoney_payload() -> dict:
    """A suggest payload spanning A-share, HK, and US markets."""
    return {
        "QuotationCodeTable": {
            "Data": [
                {
                    "QuoteID": "1.600519",
                    "Code": "600519",
                    "Name": "贵州茅台",
                    "MktNum": "1",
                    "SecurityTypeName": "沪A",
                },
                {
                    "QuoteID": "116.00700",
                    "Code": "00700",
                    "Name": "腾讯控股",
                    "MktNum": "116",
                    "SecurityTypeName": "港股",
                },
                {
                    "QuoteID": "105.AAPL",
                    "Code": "AAPL",
                    "Name": "苹果",
                    "MktNum": "105",
                    "SecurityTypeName": "美股",
                },
                {
                    # Unmappable market (e.g. a fund/board) -> dropped, not fatal.
                    "QuoteID": "90.BK0001",
                    "Code": "BK0001",
                    "Name": "板块",
                    "MktNum": "90",
                    "SecurityTypeName": "板块",
                },
            ]
        }
    }


def _yahoo_quotes() -> list:
    return [
        {
            "symbol": "AAPL",
            "shortname": "Apple Inc.",
            "exchange": "NMS",
            "quoteType": "EQUITY",
        },
        {
            "symbol": "0700.HK",
            "shortname": "TENCENT",
            "exchange": "HKG",
            "quoteType": "EQUITY",
        },
        {
            "symbol": "BTC-USD",
            "shortname": "Bitcoin USD",
            "exchange": "CCC",
            "quoteType": "CRYPTOCURRENCY",
        },
        {
            "symbol": "TD.TO",
            "shortname": "Toronto-Dominion Bank",
            "exchange": "TOR",
            "quoteType": "EQUITY",
        },
        {
            "symbol": "PNG.V",
            "shortname": "Kraken Robotics Inc.",
            "exchange": "VAN",
            "quoteType": "EQUITY",
        },
        {"symbol": "", "shortname": "no symbol"},  # dropped
    ]


class TestSymbolSearchSuccess:
    """Happy-path fan-out, normalization, merge, and CIK enrichment."""

    def test_merges_and_normalizes_across_sources(self):
        with patch.object(
            ss.eastmoney_client, "get_json", return_value=_eastmoney_payload()
        ), patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ), patch.object(
            ss.sec_edgar_client, "cik_for", return_value="0000320193"
        ):
            out = ss.SymbolSearchTool().execute(query="apple", limit=10)

        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["market"] == "multi"
        assert payload["source"] == "symbol_search"

        data = payload["data"]
        assert data["query"] == "apple"
        assert data["sources"]["eastmoney"] == "ok"
        assert data["sources"]["yahoo"] == "ok"
        assert data["sources"]["sec_edgar"] == "ok"

        by_symbol = {c["symbol"]: c for c in data["candidates"]}

        assert by_symbol["TD.TO"]["market"] == "ca"
        assert by_symbol["PNG.V"]["market"] == "ca"

        # A-share secid -> 600519.SH, market cn.
        assert by_symbol["600519.SH"]["market"] == "cn"
        assert by_symbol["600519.SH"]["name"] == "贵州茅台"

        # HK code zero-padded to 5 digits from both Eastmoney and Yahoo, merged.
        assert "00700.HK" in by_symbol
        assert by_symbol["00700.HK"]["market"] == "hk"
        assert "yahoo" in by_symbol["00700.HK"].get("also_from", [])

        # US equity: Eastmoney + Yahoo merge, SEC CIK attached.
        aapl = by_symbol["AAPL.US"]
        assert aapl["market"] == "us"
        assert aapl["cik"] == "0000320193"
        assert "yahoo" in aapl.get("also_from", [])

        # Crypto keeps its native Yahoo symbol and a global market label.
        assert by_symbol["BTC-USD"]["market"] == "global"

        # Unmappable Eastmoney market dropped; empty Yahoo symbol dropped.
        assert "BK0001" not in by_symbol
        assert data["count"] == len(data["candidates"])

    def test_limit_clamped_and_applied(self):
        with patch.object(
            ss.eastmoney_client, "get_json", return_value=_eastmoney_payload()
        ), patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ), patch.object(
            ss.sec_edgar_client, "cik_for", return_value=None
        ):
            out = ss.SymbolSearchTool().execute(query="x", limit=2)
        payload = json.loads(out)
        assert payload["data"]["count"] == 2

    def test_no_us_candidate_omits_sec_source(self):
        em = {
            "QuotationCodeTable": {
                "Data": [
                    {
                        "QuoteID": "1.600519",
                        "Code": "600519",
                        "Name": "贵州茅台",
                        "MktNum": "1",
                    }
                ]
            }
        }
        with patch.object(
            ss.eastmoney_client, "get_json", return_value=em
        ), patch.object(
            ss.yahoo_client, "search", return_value=[]
        ), patch.object(
            ss.sec_edgar_client, "cik_for"
        ) as mock_cik:
            out = ss.SymbolSearchTool().execute(query="茅台")
        payload = json.loads(out)
        assert "sec_edgar" not in payload["data"]["sources"]
        mock_cik.assert_not_called()

    def test_canadian_query_skips_eastmoney_endpoint(self):
        """A Canadian .V/.TO query fails fast: eastmoney is never contacted."""
        with patch.object(
            ss.eastmoney_client, "get_json"
        ) as mock_em, patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ):
            out = ss.SymbolSearchTool().execute(query="BYN.V")

        mock_em.assert_not_called()
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["data"]["sources"]["eastmoney"] == (
            "skipped: eastmoney has no Canada coverage"
        )

    def test_canadian_query_drops_us_otc_aliases(self):
        """Yahoo OTC aliases (BYAGF.US) of a Canadian name are filtered out."""
        quotes = [
            {
                "symbol": "BYN.V",
                "shortname": "Banyan Gold Corp.",
                "exchange": "VAN",
                "quoteType": "EQUITY",
            },
            {
                "symbol": "BYAGF.US",
                "shortname": "Banyan Gold Corp.",
                "exchange": "PNK",
                "quoteType": "EQUITY",
            },
        ]
        with patch.object(
            ss.eastmoney_client, "get_json"
        ), patch.object(ss.yahoo_client, "search", return_value=quotes):
            out = ss.SymbolSearchTool().execute(query="BYN.V")

        payload = json.loads(out)
        symbols = {c["symbol"] for c in payload["data"]["candidates"]}
        assert symbols == {"BYN.V"}
        assert "BYAGF.US" not in symbols

    def test_canadian_query_drops_us_otc_aliases_cert(self):
        """CERT.V OTC alias (CERT.US) is filtered for a Canadian query."""
        quotes = [
            {
                "symbol": "CERT.V",
                "shortname": "Cerrado Gold Inc.",
                "exchange": "VAN",
                "quoteType": "EQUITY",
            },
            {
                "symbol": "CERT.US",
                "shortname": "Cerrado Gold Inc.",
                "exchange": "PNK",
                "quoteType": "EQUITY",
            },
        ]
        with patch.object(
            ss.eastmoney_client, "get_json"
        ), patch.object(ss.yahoo_client, "search", return_value=quotes):
            out = ss.SymbolSearchTool().execute(query="CERT.V")

        payload = json.loads(out)
        symbols = {c["symbol"] for c in payload["data"]["candidates"]}
        assert symbols == {"CERT.V"}

    def test_canadian_tsx_to_query_keeps_to_only(self):
        """A .TO (TSX) query keeps only the .TO candidate, not a US alias."""
        quotes = [
            {
                "symbol": "PDI.TO",
                "shortname": "Predictive Discovery",
                "exchange": "TOR",
                "quoteType": "EQUITY",
            },
            {
                "symbol": "PDIYF.US",
                "shortname": "Predictive Discovery ADR",
                "exchange": "PNK",
                "quoteType": "EQUITY",
            },
        ]
        with patch.object(
            ss.eastmoney_client, "get_json"
        ), patch.object(ss.yahoo_client, "search", return_value=quotes):
            out = ss.SymbolSearchTool().execute(query="PDI.TO")

        payload = json.loads(out)
        symbols = {c["symbol"] for c in payload["data"]["candidates"]}
        assert symbols == {"PDI.TO"}

    def test_canadian_ticker_with_name_text_skips_eastmoney(self):
        """A "TICKER.TO <name>" query (e.g. "BTO.TO B2Gold") still fails fast.

        The model commonly searches the suffixed ticker plus a name hint; the
        leading .TO/.V suffix is unambiguous Canada, so Eastmoney (no Canada
        coverage) must not be contacted.
        """
        with patch.object(
            ss.eastmoney_client, "get_json"
        ) as mock_em, patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ):
            out = ss.SymbolSearchTool().execute(query="BTO.TO B2Gold")

        mock_em.assert_not_called()
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["data"]["sources"]["eastmoney"] == (
            "skipped: eastmoney has no Canada coverage"
        )

    def test_canadian_v_ticker_with_name_text_skips_eastmoney(self):
        """"SGML.V Sigma Lithium Vancouver" fails fast on the leading .V suffix."""
        with patch.object(
            ss.eastmoney_client, "get_json"
        ) as mock_em, patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ):
            out = ss.SymbolSearchTool().execute(query="SGML.V Sigma Lithium Vancouver")

        mock_em.assert_not_called()
        payload = json.loads(out)
        assert payload["data"]["sources"]["eastmoney"] == (
            "skipped: eastmoney has no Canada coverage"
        )

    def test_bare_name_without_suffix_still_hits_eastmoney(self):
        """A bare name (no .TO/.V) is NOT fail-fast — venue is ambiguous.

        This preserves the documented design: bare names like "B2Gold BTO" or
        "BTO" may be legit non-Canadian lookups, so Eastmoney fan-out stays.
        """
        with patch.object(
            ss.eastmoney_client, "get_json", return_value=_eastmoney_payload()
        ) as mock_em, patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ):
            out = ss.SymbolSearchTool().execute(query="B2Gold BTO")

        mock_em.assert_called_once()
        payload = json.loads(out)
        assert payload["data"]["sources"]["eastmoney"] == "ok"


class TestSymbolSearchErrors:
    """Error envelopes and per-source resilience."""

    def test_missing_query_returns_error_envelope(self):
        out = ss.SymbolSearchTool().execute(query="   ")
        payload = json.loads(out)
        assert payload["ok"] is False
        assert "required" in payload["error"]

    def test_one_source_failure_does_not_abort_others(self):
        with patch.object(
            ss.eastmoney_client,
            "get_json",
            side_effect=RuntimeError("HTTP 429 banned"),
        ), patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ), patch.object(
            ss.sec_edgar_client, "cik_for", return_value="0000320193"
        ):
            out = ss.SymbolSearchTool().execute(query="apple")

        payload = json.loads(out)
        # Overall call still succeeds with the surviving source's hits.
        assert payload["ok"] is True
        sources = payload["data"]["sources"]
        assert "eastmoney search failed" in sources["eastmoney"]
        assert "429" in sources["eastmoney"]
        assert sources["yahoo"] == "ok"
        symbols = {c["symbol"] for c in payload["data"]["candidates"]}
        assert "AAPL.US" in symbols

    def test_sec_lookup_failure_recorded_not_fatal(self):
        with patch.object(
            ss.eastmoney_client, "get_json", return_value=_eastmoney_payload()
        ), patch.object(
            ss.yahoo_client, "search", return_value=[]
        ), patch.object(
            ss.sec_edgar_client,
            "cik_for",
            side_effect=RuntimeError("tickers fetch failed"),
        ):
            out = ss.SymbolSearchTool().execute(query="apple")
        payload = json.loads(out)
        assert payload["ok"] is True
        assert "sec lookup failed" in payload["data"]["sources"]["sec_edgar"]
        # The US candidate still appears, just without a CIK.
        aapl = next(c for c in payload["data"]["candidates"] if c["symbol"] == "AAPL.US")
        assert "cik" not in aapl


class TestShanghaiAliasAndUnsupportedQueries:
    """The two resolver defects that made Shanghai and Chinese queries unusable."""

    def test_yahoo_shanghai_suffix_folds_onto_the_project_convention(self):
        """Yahoo's ``.SS`` and Eastmoney's ``.SH`` must merge into one candidate.

        Emitted separately they became two rival candidates for one listing,
        which no downstream tie-break could resolve, so every Shanghai query
        dead-ended before any market tool could run.
        """
        with patch.object(
            ss.eastmoney_client, "get_json", return_value=_eastmoney_payload()
        ), patch.object(
            ss.yahoo_client,
            "search",
            return_value=[
                {
                    "symbol": "600519.SS",
                    "shortname": "Kweichow Moutai Co Ltd",
                    "exchange": "SHH",
                    "quoteType": "EQUITY",
                }
            ],
        ):
            data = json.loads(ss.SymbolSearchTool().execute(query="600519"))["data"]

        by_symbol = {c["symbol"]: c for c in data["candidates"]}
        assert "600519.SS" not in by_symbol
        assert by_symbol["600519.SH"]["market"] == "cn"
        assert "yahoo" in by_symbol["600519.SH"].get("also_from", [])

    def test_non_ascii_query_skips_yahoo_without_calling_it(self):
        """A source that cannot serve a query shape is skipped, not failed.

        Yahoo answers any non-ASCII query with HTTP 400. Recording that as a
        source failure made "this entity is not listed" indistinguishable from
        "a source is down" for every Chinese query.
        """
        with patch.object(
            ss.eastmoney_client, "get_json", return_value=_eastmoney_payload()
        ), patch.object(ss.yahoo_client, "search") as search, patch.object(
            ss.sec_edgar_client, "cik_for", return_value="0000320193"
        ):
            data = json.loads(ss.SymbolSearchTool().execute(query="贵州茅台"))["data"]

        search.assert_not_called()
        assert data["sources"]["yahoo"].startswith("skipped:")
        assert data["sources"]["eastmoney"] == "ok"

    def test_ascii_query_still_reaches_yahoo(self):
        """The skip is keyed on the query shape, not switched on permanently."""
        with patch.object(
            ss.eastmoney_client, "get_json", return_value=_eastmoney_payload()
        ), patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ) as search, patch.object(
            ss.sec_edgar_client, "cik_for", return_value="0000320193"
        ):
            data = json.loads(ss.SymbolSearchTool().execute(query="apple"))["data"]

        search.assert_called_once()
        assert data["sources"]["yahoo"] == "ok"


class TestTickerNameQueryYahooSkip:
    """A ticker+name query Yahoo cannot serve must be skipped, not "ok".

    Yahoo's search endpoint answers a multi-token query whose first token is a
    bare all-caps ticker ("XOM ExxonMobil") with zero quotes. Recording that as
    "ok" counted a second clean source, so a caller deciding whether an entity
    exists read "not listed" as two corroborating "not found" answers; the
    unsupported shape must read as "skipped" instead, mirroring the non-ASCII
    guard. Eastmoney is NOT skipped for this shape — it can serve multi-token
    queries — only the Yahoo path relabels.
    """

    def test_ticker_name_query_skips_yahoo_without_ok_status(self):
        """Yahoo returns zero quotes for the shape and is relabeled "skipped"."""
        with patch.object(
            ss.eastmoney_client,
            "get_json",
            return_value={"QuotationCodeTable": {"Data": []}},
        ), patch.object(
            ss.yahoo_client, "search", return_value=[]
        ) as search, patch.object(
            ss.sec_edgar_client, "cik_for", return_value=None
        ):
            data = json.loads(
                ss.SymbolSearchTool().execute(query="XOM ExxonMobil")
            )["data"]

        # Post-response relabel, not a pre-call skip: Yahoo is still consulted.
        search.assert_called_once()
        assert data["sources"]["yahoo"].startswith("skipped:")
        assert data["sources"]["eastmoney"] == "ok"
        assert data["count"] == 0

    def test_ticker_name_query_with_matching_quotes_stays_ok(self):
        """The relabel must NOT fire when Yahoo can actually serve the shape."""
        quotes = [
            {
                "symbol": "XOM",
                "shortname": "Exxon Mobil Corp.",
                "exchange": "NYQ",
                "quoteType": "EQUITY",
            }
        ]
        with patch.object(
            ss.eastmoney_client,
            "get_json",
            return_value={"QuotationCodeTable": {"Data": []}},
        ), patch.object(
            ss.yahoo_client, "search", return_value=quotes
        ) as search, patch.object(
            ss.sec_edgar_client, "cik_for", return_value="0000034088"
        ):
            data = json.loads(
                ss.SymbolSearchTool().execute(query="XOM ExxonMobil")
            )["data"]

        search.assert_called_once()
        assert data["sources"]["yahoo"] == "ok"
        assert data["count"] == 1

    def test_multi_word_name_query_still_reaches_yahoo(self):
        """A multi-word NAME ("Exxon Mobil") is not a ticker+name shape."""
        with patch.object(
            ss.eastmoney_client,
            "get_json",
            return_value={"QuotationCodeTable": {"Data": []}},
        ), patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ) as search, patch.object(
            ss.sec_edgar_client, "cik_for", return_value="0000320193"
        ):
            data = json.loads(ss.SymbolSearchTool().execute(query="Exxon Mobil"))["data"]

        search.assert_called_once()
        assert data["sources"]["yahoo"] == "ok"

    def test_single_token_query_still_reaches_yahoo(self):
        """A bare single-token ticker ("XOM") is not a ticker+name shape."""
        with patch.object(
            ss.eastmoney_client,
            "get_json",
            return_value={"QuotationCodeTable": {"Data": []}},
        ), patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ) as search, patch.object(
            ss.sec_edgar_client, "cik_for", return_value="0000320193"
        ):
            data = json.loads(ss.SymbolSearchTool().execute(query="XOM"))["data"]

        search.assert_called_once()
        assert data["sources"]["yahoo"] == "ok"

    def test_suffixed_ticker_with_name_still_reaches_yahoo(self):
        """The bare-ticker clause must not fire on suffixed Canadian tickers."""
        with patch.object(
            ss.eastmoney_client,
            "get_json",
            return_value={"QuotationCodeTable": {"Data": []}},
        ), patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ) as search:
            data = json.loads(
                ss.SymbolSearchTool().execute(query="BTO.TO B2Gold")
            )["data"]

        search.assert_called_once()
        assert data["sources"]["yahoo"] == "ok"

    def test_single_token_ascii_empty_result_stays_ok(self):
        """A bare single token Yahoo cannot match is "not listed", not "skipped".

        The relabel is shape-specific: only a multi-token ticker+name query is
        unsupported. A single token (e.g. a bogus ticker) that returns zero
        quotes is an authoritative "not listed" and must stay "ok", otherwise
        every genuinely-absent entity would read as an unsupported shape.
        """
        with patch.object(
            ss.eastmoney_client,
            "get_json",
            return_value={"QuotationCodeTable": {"Data": []}},
        ), patch.object(
            ss.yahoo_client, "search", return_value=[]
        ) as search:
            data = json.loads(
                ss.SymbolSearchTool().execute(query="XOMZZZ")
            )["data"]

        search.assert_called_once()
        assert data["sources"]["yahoo"] == "ok"

    def test_multi_word_name_empty_result_stays_ok(self):
        """A multi-word NAME ("Exxon Mobil") with zero quotes is "not listed".

        The shape classifier keys on a bare all-caps FIRST token ("XOM
        ExxonMobil"). A name-led query ("Exxon Mobil") is a shape Yahoo can
        serve, so its empty answer is an authoritative "not listed" and must
        not be relabeled to "skipped".
        """
        with patch.object(
            ss.eastmoney_client,
            "get_json",
            return_value={"QuotationCodeTable": {"Data": []}},
        ), patch.object(
            ss.yahoo_client, "search", return_value=[]
        ) as search:
            data = json.loads(
                ss.SymbolSearchTool().execute(query="Exxon Mobil")
            )["data"]

        search.assert_called_once()
        assert data["sources"]["yahoo"] == "ok"
