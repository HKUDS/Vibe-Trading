"""Tests for the NSE Kenya daily-price-list loader.

The row fixtures reproduce the layout of the exchange's Daily Equity Price List
(52-week high/low, security name, ISIN, day high/low, VWAP, previous, volume);
the first three rows are taken from the 27 February 2026 list. No test touches
the network: HTTP goes through a patched ``throttled_get``.
"""

from __future__ import annotations

import io
from datetime import date

import pandas as pd
import pytest

from backtest.loaders import nse_ke_loader
from backtest.loaders.nse_ke_loader import (
    DataLoader,
    fetch_price_list,
    latest_price_list,
    parse_price_list_text,
    price_list_url,
)
from backtest.loaders.nse_ke_symbols import code_for_name, is_isin, strip_suffix

PRICE_LIST_TEXT = """\
NAIROBI SECURITIES EXCHANGE
February 27, 2026
DAILY PRICE LIST
52WK HIGH 52WK LOW SECURITY ISIN TRADING HIGH LOW VWAP PREVIOUS VOLUME
AGRICULTURAL
35.25 10.00 Eaagads Ltd Ord 1.25 SME KE0000000208 32.00 30.00 30.10 31.05 3,052
440.00 240.00 Kakuzi Plc Ord.5.00 KE0000000281 436.00 405.00 433.00 436.50 443
33.90 13.60 Sasini Plc Ord 1.00 KE0000000430 29.50 28.00 28.15 28.40 32,885
TELECOMMUNICATION
39.50 25.80 Safaricom Plc Ord 0.05 KE1000001402 36.80 36.35 36.60 36.30 7,340,000
ENERGY & PETROLEUM
25.00 11.20 Kenya Power & Lighting Co Ltd Ord 2.50 KE0000000349 24.40 23.20 23.35 24.35 1,070,000
5.50 4.10 Kenya Power & Lighting Ltd 4% Pref 20.00 KE0000000356 - - - 5.26 -
BANKING
109.00 54.00 Equity Group Holdings Plc Ord 0.50 KE0000000554 103.00 98.75 102.75 98.50 472,506
"""


class _FakeResponse:
    def __init__(self, status_code: int = 200, content: bytes = b"", text: str = "") -> None:
        self.status_code = status_code
        self.content = content
        self.text = text


@pytest.fixture(autouse=True)
def _fresh_memo():
    nse_ke_loader.clear_memo()
    yield
    nse_ke_loader.clear_memo()


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


class TestParsePriceListText:
    def test_every_security_row_is_parsed(self) -> None:
        frame = parse_price_list_text(PRICE_LIST_TEXT)
        assert len(frame) == 7
        assert list(frame.columns) == nse_ke_loader.PRICE_LIST_COLUMNS

    def test_headers_titles_and_sectors_are_ignored(self) -> None:
        frame = parse_price_list_text(PRICE_LIST_TEXT)
        assert not frame["name"].str.contains("DAILY PRICE LIST|BANKING").any()

    def test_row_values(self) -> None:
        frame = parse_price_list_text(PRICE_LIST_TEXT).set_index("isin")
        kakuzi = frame.loc["KE0000000281"]
        assert kakuzi["code"] == "KUKZ"
        assert kakuzi["hi52"] == 440.0 and kakuzi["lo52"] == 240.0
        assert kakuzi["high"] == 436.0 and kakuzi["low"] == 405.0
        assert kakuzi["vwap"] == 433.0 and kakuzi["prev"] == 436.5
        assert kakuzi["volume"] == 443.0

    def test_thousands_separators(self) -> None:
        frame = parse_price_list_text(PRICE_LIST_TEXT).set_index("code")
        assert frame.loc["SCOM", "volume"] == 7_340_000.0
        assert frame.loc["SASN", "volume"] == 32_885.0

    def test_digits_in_the_name_do_not_shift_columns(self) -> None:
        # "Ord 1.25 SME" sits between the 52-week columns and the ISIN.
        frame = parse_price_list_text(PRICE_LIST_TEXT).set_index("code")
        assert frame.loc["EGAD", "name"] == "Eaagads Ltd Ord 1.25 SME"
        assert frame.loc["EGAD", "vwap"] == 30.10

    def test_untraded_row_keeps_dashes_as_missing(self) -> None:
        frame = parse_price_list_text(PRICE_LIST_TEXT).set_index("code")
        pref = frame.loc["KPLC-P4"]
        assert pd.isna(pref["vwap"]) and pd.isna(pref["volume"])
        assert pref["prev"] == 5.26

    def test_row_without_52_week_columns(self) -> None:
        text = "Family Bank Ltd Ord 5.00 KE0000000547 30.10 27.95 29.90 27.95 183,197"
        frame = parse_price_list_text(text)
        assert len(frame) == 1
        assert frame.iloc[0]["code"] == "FMLY"
        assert pd.isna(frame.iloc[0]["hi52"])

    def test_repeated_isin_on_a_page_break_is_kept_once(self) -> None:
        line = "39.50 25.80 Safaricom Plc Ord 0.05 KE1000001402 36.80 36.35 36.60 36.30 7,340,000"
        assert len(parse_price_list_text(line + "\n" + line)) == 1

    def test_empty_text(self) -> None:
        assert parse_price_list_text("").empty


class TestNameMatching:
    @pytest.mark.parametrize(
        "name,code",
        [
            ("Safaricom Plc Ord 0.05", "SCOM"),
            ("Kakuzi Plc Ord.5.00", "KUKZ"),
            ("E.A.Portland Cement Co. Ltd Ord 5.00", "PORT"),
            ("East African Breweries Plc Ord 2.00", "EABL"),
            ("Co-operative Bank of Kenya Ltd Ord 1.00", "COOP"),
            ("I&M Group Plc Ord 1.00", "IMH"),
            ("Kenya Re Insurance Corporation Ltd Ord 2.50", "KNRE"),
            ("Kenya Power & Lighting Co Ltd Ord 2.50", "KPLC"),
            ("Kenya Power & Lighting Ltd 4% Pref 20.00", "KPLC-P4"),
            ("Kenya Power & Lighting Ltd 7% Pref 20.00", "KPLC-P7"),
            ("Absa Bank Kenya Plc Ord 0.50", "ABSA"),
            ("Absa NewGold ETF", "GLD"),
        ],
    )
    def test_names_resolve_to_codes(self, name: str, code: str) -> None:
        assert code_for_name(name) == code

    def test_unknown_name_resolves_to_none(self) -> None:
        assert code_for_name("Some New Listing Plc Ord 1.00") is None

    def test_isin_and_suffix_helpers(self) -> None:
        assert is_isin("KE0000000281") and not is_isin("SCOM")
        assert strip_suffix("scom.nr") == "SCOM"
        assert strip_suffix("KPLC-P4.NR") == "KPLC-P4"


# --------------------------------------------------------------------------
# Network paths (patched)
# --------------------------------------------------------------------------


def test_price_list_url_pattern() -> None:
    assert price_list_url(date(2026, 2, 27)) == (
        "https://www.nse.co.ke/wp-content/uploads/27-FEB-26.pdf"
    )
    assert price_list_url(date(2026, 9, 1)).endswith("/01-SEP-26.pdf")


def _serve(monkeypatch, pages: dict[date, str | None], calls: list | None = None) -> None:
    """Serve *pages* (text per session, ``None`` for a scanned PDF); 404 otherwise."""

    by_url = {price_list_url(d): d for d in pages}

    def fake_get(url, **kwargs):
        if calls is not None:
            calls.append(url)
        day = by_url.get(url)
        if day is None:
            return _FakeResponse(404)
        return _FakeResponse(200, content=b"%PDF-1.4 " + str(day).encode())

    def fake_text(content: bytes):
        day = date.fromisoformat(content.split(b" ", 1)[1].decode())
        return pages[day]

    monkeypatch.setattr(nse_ke_loader, "throttled_get", fake_get)
    monkeypatch.setattr(nse_ke_loader, "_pdf_text", fake_text)


class TestFetchPriceList:
    def test_parses_a_published_session(self, monkeypatch) -> None:
        _serve(monkeypatch, {date(2026, 2, 27): PRICE_LIST_TEXT})
        frame = fetch_price_list(date(2026, 2, 27))
        assert frame is not None and len(frame) == 7

    def test_missing_session_is_none_and_memoised(self, monkeypatch) -> None:
        calls: list = []
        _serve(monkeypatch, {}, calls)
        assert fetch_price_list(date(2026, 2, 28)) is None
        assert fetch_price_list(date(2026, 2, 28)) is None
        assert len(calls) == 1

    def test_scanned_list_is_skipped(self, monkeypatch) -> None:
        _serve(monkeypatch, {date(2026, 9, 22): None})
        assert fetch_price_list(date(2026, 9, 22)) is None

    def test_non_pdf_body_is_rejected(self, monkeypatch) -> None:
        monkeypatch.setattr(
            nse_ke_loader, "throttled_get",
            lambda url, **kw: _FakeResponse(200, content=b"<html>maintenance</html>"),
        )
        assert fetch_price_list(date(2026, 2, 27)) is None

    def test_latest_follows_the_market_statistics_link(self, monkeypatch) -> None:
        stats = (
            '<a href="https://www.nse.co.ke/wp-content/uploads/27-FEB-26.pdf">'
            "Download Daily Equity Price List</a>"
        )
        text_pages = {date(2026, 2, 27): PRICE_LIST_TEXT}
        _serve(monkeypatch, text_pages)
        inner = nse_ke_loader.throttled_get

        def fake_get(url, **kwargs):
            if url == nse_ke_loader.MARKET_STATS_URL:
                return _FakeResponse(200, text=stats)
            return inner(url, **kwargs)

        monkeypatch.setattr(nse_ke_loader, "throttled_get", fake_get)
        day, frame = latest_price_list(today=date(2026, 3, 1))
        assert day == date(2026, 2, 27)
        assert frame is not None and "SCOM" in set(frame["code"])


class TestDataLoader:
    def test_contract(self) -> None:
        loader = DataLoader()
        assert loader.name == "nse_ke"
        assert loader.markets == {"kenya_equity"}
        assert loader.requires_auth is False
        assert loader.volume_units == {"kenya_equity": "shares"}

    def test_availability_tracks_pdfplumber(self, monkeypatch) -> None:
        import builtins

        real_import = builtins.__import__

        def no_pdfplumber(name, *args, **kwargs):
            if name == "pdfplumber":
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_pdfplumber)
        assert DataLoader().is_available() is False

    def test_builds_daily_bars_across_sessions(self, monkeypatch) -> None:
        second = PRICE_LIST_TEXT.replace(
            "KE1000001402 36.80 36.35 36.60 36.30 7,340,000",
            "KE1000001402 37.10 36.55 36.90 36.60 5,100,000",
        )
        _serve(monkeypatch, {date(2026, 2, 26): PRICE_LIST_TEXT, date(2026, 2, 27): second})
        out = DataLoader().fetch(["SCOM.NR"], "2026-02-26", "2026-02-27")
        frame = out["SCOM.NR"]
        assert frame.index.name == "trade_date"
        assert list(frame.columns) == ["open", "high", "low", "close", "volume", "pre_close"]
        assert frame.index.is_monotonic_increasing
        assert (frame.dtypes == float).all()
        assert list(frame["close"]) == [36.60, 36.90]
        # The list prints no open: open is the session VWAP, pre_close the PREVIOUS column.
        assert list(frame["open"]) == [36.60, 36.90]
        assert list(frame["pre_close"]) == [36.30, 36.60]

    def test_isin_symbol_is_matched_exactly(self, monkeypatch) -> None:
        _serve(monkeypatch, {date(2026, 2, 27): PRICE_LIST_TEXT})
        out = DataLoader().fetch(["KE0000000281.NR"], "2026-02-27", "2026-02-27")
        assert out["KE0000000281.NR"]["close"].iloc[0] == 433.0

    def test_untraded_session_yields_no_bar(self, monkeypatch) -> None:
        _serve(monkeypatch, {date(2026, 2, 27): PRICE_LIST_TEXT})
        assert DataLoader().fetch(["KPLC-P4.NR"], "2026-02-27", "2026-02-27") == {}

    def test_bars_bracket_the_vwap(self, monkeypatch) -> None:
        odd = "39.50 25.80 Safaricom Plc Ord 0.05 KE1000001402 36.50 36.35 36.60 36.30 1,000"
        _serve(monkeypatch, {date(2026, 2, 27): odd})
        bar = DataLoader().fetch(["SCOM.NR"], "2026-02-27", "2026-02-27")["SCOM.NR"].iloc[0]
        assert bar["low"] <= bar["close"] <= bar["high"]

    def test_unknown_code_is_skipped_not_fatal(self, monkeypatch) -> None:
        _serve(monkeypatch, {date(2026, 2, 27): PRICE_LIST_TEXT})
        out = DataLoader().fetch(["NOPE.NR", "SCOM.NR"], "2026-02-27", "2026-02-27")
        assert set(out) == {"SCOM.NR"}

    def test_intraday_interval_is_declined(self) -> None:
        assert DataLoader().fetch(["SCOM.NR"], "2026-02-27", "2026-02-27", interval="1H") == {}

    def test_session_cap(self, monkeypatch) -> None:
        calls: list = []
        _serve(monkeypatch, {}, calls)
        monkeypatch.setenv("VIBE_TRADING_NSE_KE_MAX_SESSIONS", "5")
        DataLoader().fetch(["SCOM.NR"], "2026-01-01", "2026-03-31")
        assert len(calls) == 5
        # The newest sessions are the ones read.
        assert calls[-1] == price_list_url(date(2026, 3, 31))

    def test_one_pdf_serves_every_symbol(self, monkeypatch) -> None:
        calls: list = []
        _serve(monkeypatch, {date(2026, 2, 27): PRICE_LIST_TEXT}, calls)
        out = DataLoader().fetch(["SCOM.NR", "KUKZ.NR", "EQTY.NR"], "2026-02-27", "2026-02-27")
        assert set(out) == {"SCOM.NR", "KUKZ.NR", "EQTY.NR"}
        assert len(calls) == 1


def test_real_pdf_text_layer_round_trip(monkeypatch) -> None:
    """Render the fixture to a real PDF and read it back through pdfplumber."""
    pytest.importorskip("pdfplumber")
    canvas_mod = pytest.importorskip("reportlab.pdfgen.canvas")
    from reportlab.lib.pagesizes import landscape, A4

    buf = io.BytesIO()
    pdf = canvas_mod.Canvas(buf, pagesize=landscape(A4))
    y = 560
    for line in PRICE_LIST_TEXT.splitlines():
        pdf.setFont("Helvetica", 8)
        pdf.drawString(20, y, line)
        y -= 14
    pdf.showPage()
    pdf.save()

    text = nse_ke_loader._pdf_text(buf.getvalue())
    assert text is not None
    frame = parse_price_list_text(text)
    assert set(frame["code"].dropna()) >= {"SCOM", "KUKZ", "EGAD", "SASN", "EQTY", "KPLC"}


# --------------------------------------------------------------------------
# Registry / routing
# --------------------------------------------------------------------------


def test_kenya_chain_and_auto_routing() -> None:
    from backtest.loaders.registry import FALLBACK_CHAINS, PRICE_CALIBER_BY_SOURCE, VALID_SOURCES
    from src.market_data import detect_source

    assert FALLBACK_CHAINS["kenya_equity"] == ["nse_ke", "local"]
    assert "nse_ke" in VALID_SOURCES
    assert PRICE_CALIBER_BY_SOURCE["nse_ke"] == "raw"
    assert detect_source("SCOM.NR") == "nse_ke"
    assert detect_source("KPLC-P4.NR") == "nse_ke"


def test_every_table_entry_resolves_to_itself() -> None:
    """No two entries in the name table may claim the same registered name."""
    from backtest.loaders.nse_ke_symbols import SECURITIES

    for code, sec in SECURITIES.items():
        assert code_for_name(f"{sec.name} Plc Ord 1.00") == code, code
