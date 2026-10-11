"""Tests for sec_edgar_client: ticker->CIK mapping, CIK padding, payload parse.

All HTTP is fully mocked by patching ``throttled_get_json`` in the client
module — no test makes a real SEC request.
"""
from unittest.mock import patch

import pytest
import requests

from backtest.loaders import sec_edgar_client as sec


_TICKERS_PAYLOAD = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
    # lower-case ticker + already-int CIK to exercise normalization
    "2": {"cik_str": 1318605, "ticker": "tsla", "title": "Tesla, Inc."},
}


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset the memoized ticker map before and after every test."""
    sec._reset_ticker_cache_for_tests()
    yield
    sec._reset_ticker_cache_for_tests()


class TestCikFor:
    """Ticker -> zero-padded 10-digit CIK resolution."""

    def test_resolves_and_pads_cik(self):
        with patch.object(sec, "throttled_get_json", return_value=_TICKERS_PAYLOAD):
            assert sec.cik_for("AAPL") == "0000320193"

    def test_case_insensitive(self):
        with patch.object(sec, "throttled_get_json", return_value=_TICKERS_PAYLOAD):
            assert sec.cik_for("aapl") == "0000320193"
            assert sec.cik_for("Tsla") == "0001318605"

    def test_unknown_ticker_returns_none(self):
        with patch.object(sec, "throttled_get_json", return_value=_TICKERS_PAYLOAD):
            assert sec.cik_for("NOPE") is None

    def test_empty_ticker_returns_none_without_fetch(self):
        with patch.object(sec, "throttled_get_json") as mock_get:
            assert sec.cik_for("") is None
            assert sec.cik_for("   ") is None
            mock_get.assert_not_called()

    def test_map_is_fetched_once_and_memoized(self):
        with patch.object(
            sec, "throttled_get_json", return_value=_TICKERS_PAYLOAD
        ) as mock_get:
            assert sec.cik_for("AAPL") == "0000320193"
            assert sec.cik_for("MSFT") == "0000789019"
            assert mock_get.call_count == 1

    def test_malformed_rows_skipped(self):
        payload = {
            "0": {"cik_str": 320193, "ticker": "AAPL"},
            "1": {"ticker": "NOCIK"},          # missing cik
            "2": {"cik_str": 5},               # missing ticker
            "3": "garbage",                    # not a dict
        }
        with patch.object(sec, "throttled_get_json", return_value=payload):
            assert sec.cik_for("AAPL") == "0000320193"
            assert sec.cik_for("NOCIK") is None


class TestSymbolSuffixes:
    """The SEC table carries bare tickers with dashes and no dots at all.

    ``get_fundamentals("AAPL.US")`` — the tool's own documented example — used to
    return ``ok: true`` with an all-null panel because the ``.US`` market suffix
    was passed through to the lookup verbatim.
    """

    _PAYLOAD = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 1067983, "ticker": "BRK-B", "title": "Berkshire B"},
    }

    def test_us_market_suffix_is_stripped(self):
        with patch.object(sec, "throttled_get_json", return_value=self._PAYLOAD):
            assert sec.cik_for("AAPL.US") == "0000320193"
            assert sec.cik_for("aapl.us") == "0000320193"

    def test_share_class_written_with_a_dot_resolves(self):
        with patch.object(sec, "throttled_get_json", return_value=self._PAYLOAD):
            assert sec.cik_for("BRK.B") == "0001067983"
            assert sec.cik_for("BRK-B") == "0001067983"

    def test_share_class_and_market_suffix_together_resolve(self):
        with patch.object(sec, "throttled_get_json", return_value=self._PAYLOAD):
            assert sec.cik_for("BRK.B.US") == "0001067983"

    def test_a_non_us_market_suffix_is_not_stripped(self):
        with patch.object(sec, "throttled_get_json", return_value=self._PAYLOAD):
            assert sec.cik_for("600519.SH") is None
            assert sec.cik_for("00700.HK") is None


class TestTickerCikOverrides:
    """Verified ticker->CIK pins win over the SEC ticker table.

    SEC's company_tickers.json re-pointed XOM at CIK 2115436 ("ExxonMobil
    Holdings Corp"), a holding registrant whose first 10-Q was filed 2026-08
    and whose companyfacts carries no period before 2025 — every 2017-2024
    fundamental panel column came back NaN. The operating filer with the full
    XBRL history is CIK 34088 ("Exxon Mobil Corporation").
    """

    _PAYLOAD_WITH_SHELL = {
        "0": {"cik_str": 2115436, "ticker": "XOM", "title": "ExxonMobil Holdings Corp"},
        "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    }

    def test_override_wins_over_table_entry(self):
        with patch.object(sec, "throttled_get_json", return_value=self._PAYLOAD_WITH_SHELL):
            assert sec.cik_for("XOM") == "0000034088"

    def test_override_applies_to_market_suffix_and_case_variants(self):
        with patch.object(sec, "throttled_get_json", return_value=self._PAYLOAD_WITH_SHELL):
            assert sec.cik_for("XOM.US") == "0000034088"
            assert sec.cik_for("xom.us") == "0000034088"

    def test_override_resolves_without_fetching_the_table(self):
        with patch.object(sec, "throttled_get_json") as mock_get:
            assert sec.cik_for("XOM.US") == "0000034088"
            mock_get.assert_not_called()

    def test_non_overridden_tickers_still_resolve_from_table(self):
        with patch.object(sec, "throttled_get_json", return_value=self._PAYLOAD_WITH_SHELL):
            assert sec.cik_for("AAPL") == "0000320193"

    def test_override_values_are_padded_ten_digit_ciks(self):
        for cik in sec._TICKER_CIK_OVERRIDES.values():
            assert len(cik) == 10 and cik.isdigit()


class TestBacVerifiedCorrectWithoutOverride:
    """BAC resolves through the SEC table — live-verified correct on 2026-10-11.

    An audit of the 50-name sp500 bench fallback universe flagged BAC because
    the companyfacts payload for CIK 70858 stamps its top-level ``entityName``
    as "BofA Finance LLC". That field is a payload quirk, not the registrant
    identity: ``company_tickers.json`` maps BAC to CIK 70858 titled "BANK OF
    AMERICA CORP /DE/", the submissions document for the same CIK is named
    "BANK OF AMERICA CORP /DE/" (formerNames BANKAMERICA CORP/DE/ <-
    NATIONSBANK CORP, tickers include BAC), and its companyfacts carries the
    full operating history (891 us-gaap concepts, NetIncomeLoss 238 facts
    2007-2026, Assets 192 facts 2008-2026). Fundamentals extraction never
    reads ``entityName``. These tests keep a well-meaning future "fix" from
    pinning BAC to a different CIK on the basis of that field alone.
    """

    _PAYLOAD = {
        "0": {"cik_str": 70858, "ticker": "BAC", "title": "BANK OF AMERICA CORP /DE/"},
    }

    def test_bac_resolves_from_table_with_and_without_market_suffix(self):
        with patch.object(sec, "throttled_get_json", return_value=self._PAYLOAD):
            assert sec.cik_for("BAC") == "0000070858"
            assert sec.cik_for("BAC.US") == "0000070858"

    def test_bac_is_not_pinned_in_overrides(self):
        assert "BAC" not in sec._TICKER_CIK_OVERRIDES


class TestCikPadding:
    """_pad_cik normalizes ints, padded strings, and CIK-prefixed strings."""

    def test_pads_int(self):
        assert sec._pad_cik(320193) == "0000320193"

    def test_passes_through_already_padded(self):
        assert sec._pad_cik("0000320193") == "0000320193"

    def test_strips_cik_prefix(self):
        assert sec._pad_cik("CIK0000320193") == "0000320193"

    def test_no_digits_raises(self):
        with pytest.raises(ValueError):
            sec._pad_cik("ABC")


class TestSubmissionsAndFacts:
    """Endpoint URL construction + raw payload passthrough."""

    def test_get_submissions_builds_padded_url(self):
        payload = {"cik": "320193", "name": "Apple Inc.", "filings": {}}
        with patch.object(
            sec, "throttled_get_json", return_value=payload
        ) as mock_get:
            out = sec.get_submissions(320193)
        assert out == payload
        called_url = mock_get.call_args[0][0]
        assert called_url == "https://data.sec.gov/submissions/CIK0000320193.json"
        kwargs = mock_get.call_args.kwargs
        assert kwargs["host_key"] == "sec"
        assert kwargs["min_interval"] >= 0.12

    def test_get_company_facts_builds_padded_url(self):
        payload = {"cik": 320193, "facts": {"us-gaap": {}}}
        with patch.object(
            sec, "throttled_get_json", return_value=payload
        ) as mock_get:
            out = sec.get_company_facts("CIK0000320193")
        assert out == payload
        called_url = mock_get.call_args[0][0]
        assert called_url == (
            "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
        )

    def test_compliant_user_agent_sent(self):
        with patch.object(
            sec, "throttled_get_json", return_value={}
        ) as mock_get:
            sec.get_submissions(320193)
        ua = mock_get.call_args.kwargs["headers"]["User-Agent"]
        assert "Vibe-Trading" in ua and "contact" in ua.lower()

    def test_user_agent_env_override(self, monkeypatch):
        monkeypatch.setenv("VIBE_TRADING_SEC_UA", "MyApp/2.0 (me@example.com)")
        with patch.object(
            sec, "throttled_get_json", return_value={}
        ) as mock_get:
            sec.get_company_facts(320193)
        assert mock_get.call_args.kwargs["headers"]["User-Agent"] == (
            "MyApp/2.0 (me@example.com)"
        )


class TestErrorPath:
    """A transport error propagates unchanged for the caller's retry policy."""

    def test_http_error_propagates(self):
        with patch.object(
            sec,
            "throttled_get_json",
            side_effect=requests.HTTPError("404 Not Found"),
        ):
            with pytest.raises(requests.HTTPError):
                sec.get_submissions(999999)

    def test_ticker_fetch_error_propagates(self):
        with patch.object(
            sec,
            "throttled_get_json",
            side_effect=requests.ConnectionError("boom"),
        ):
            with pytest.raises(requests.ConnectionError):
                sec.cik_for("AAPL")
