"""Tests for get_institutional_holdings: 13F parsing, unit detection, envelopes.

Every SEC round trip is mocked at :func:`institutional_holdings_tool._sec_get`,
the single choke point through which the tool reaches the network, so no test
touches ``sec.gov`` or ``efts.sec.gov``. The XML fixtures are trimmed copies of
real information tables, including the duplicate-CUSIP layout a manager with
sub-advisers actually files.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date, timedelta
from typing import Any, Dict, List
from unittest.mock import patch
from xml.sax.saxutils import escape

import pytest

from src.config.limits import TOOL_RESULT_LIMIT
from src.tools import institutional_holdings_tool as iht
from src.tools.institutional_holdings_tool import InstitutionalHoldingsTool

_NS = 'xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable"'


@pytest.fixture(autouse=True)
def _no_network_through_the_submissions_fallback():
    """Fail loudly if a test reaches the live submissions endpoint.

    ``_list_13f_filings`` falls back to :func:`get_submissions` whenever
    full-text search fails, and that helper carries its own HTTP client — so
    patching ``_sec_get`` alone does not stop a test from calling sec.gov.
    Tests that exercise the fallback patch it themselves and override this.
    """
    with patch.object(iht, "get_submissions", side_effect=AssertionError("live SEC submissions call")):
        yield


def _info_table(rows: List[Dict[str, Any]], declaration: str = '<?xml version="1.0"?>') -> bytes:
    """Render an information-table XML document from row dicts.

    Issuer names are XML-escaped because real filings carry ampersands
    (``National Fire &amp; Marine Insurance Co``).
    """
    body = "".join(
        f"""<infoTable>
          <nameOfIssuer>{escape(r['issuer'])}</nameOfIssuer>
          <titleOfClass>{r.get('cls', 'COM')}</titleOfClass>
          <cusip>{r['cusip']}</cusip>
          <value>{r['value']}</value>
          <shrsOrPrnAmt>
            <sshPrnamt>{r['shares']}</sshPrnamt>
            <sshPrnamtType>{r.get('type', 'SH')}</sshPrnamtType>
          </shrsOrPrnAmt>
          {'<putCall>' + r['put_call'] + '</putCall>' if r.get('put_call') else ''}
          <investmentDiscretion>SOLE</investmentDiscretion>
          <votingAuthority><Sole>{r['shares']}</Sole><Shared>0</Shared><None>0</None></votingAuthority>
        </infoTable>"""
        for r in rows
    )
    return f"{declaration}<informationTable {_NS}>{body}</informationTable>".encode()


# Berkshire's real table repeats one CUSIP once per sub-adviser; these two AAPL
# rows must aggregate into a single 300-share position, not two.
_CURRENT_ROWS = [
    {"issuer": "APPLE INC", "cusip": "037833100", "value": 25000, "shares": 100},
    {"issuer": "APPLE INC", "cusip": "037833100", "value": 50000, "shares": 200},
    {"issuer": "COCA COLA CO", "cusip": "191216100", "value": 12000, "shares": 200},
    {"issuer": "VISA INC", "cusip": "92826C839", "value": 9000, "shares": 30},
    {"issuer": "NVIDIA CORP", "cusip": "67066G104", "value": 4000, "shares": 25},
    {"issuer": "SPDR S&P 500", "cusip": "78462F103", "value": 2000, "shares": 4},
]
_PRIOR_ROWS = [
    {"issuer": "APPLE INC", "cusip": "037833100", "value": 20000, "shares": 400},
    {"issuer": "COCA COLA CO", "cusip": "191216100", "value": 12000, "shares": 200},
    {"issuer": "TESLA INC", "cusip": "88160R101", "value": 7000, "shares": 40},
    {"issuer": "VISA INC", "cusip": "92826C839", "value": 8000, "shares": 30},
    {"issuer": "NVIDIA CORP", "cusip": "67066G104", "value": 3000, "shares": 25},
    {"issuer": "SPDR S&P 500", "cusip": "78462F103", "value": 1000, "shares": 4},
]

_INDEX_JSON = {
    "directory": {
        "item": [
            {"name": "0001193125-26-226661-index.html", "size": ""},
            {"name": "primary_doc.xml", "size": "5555"},
            {"name": "53405.xml", "size": "45259"},
        ]
    }
}

_PRIMARY_DOC = b"""<?xml version="1.0"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">
  <formData><coverPage>
      <reportCalendarOrQuarter>03-31-2026</reportCalendarOrQuarter>
      <filingManager><name>Test Capital LLC</name></filingManager>
      <reportType>13F HOLDINGS REPORT</reportType>
  </coverPage>
  <summaryPage><tableEntryTotal>6</tableEntryTotal><tableValueTotal>102000</tableValueTotal></summaryPage>
  </formData>
</edgarSubmission>"""


def _amended_cover(amendment_type: str | None, number: int = 1, total: int = 102000) -> bytes:
    """Render a cover page that declares an amendment, exactly as EDGAR nests it.

    Copied from DZ BANK's live 2020-09-30 amendments: ``isAmendment`` and
    ``amendmentNo`` sit directly under ``coverPage`` while ``amendmentType`` is
    wrapped in ``amendmentInfo``. Passing ``None`` reproduces the AEGON ASSET
    MANAGEMENT UK filings, which are submitted as 13F-HR/A yet declare no
    amendment fields at all.
    """
    block = f"<isAmendment>true</isAmendment><amendmentNo>{number}</amendmentNo>"
    if amendment_type is not None:
        block += f"<amendmentInfo><amendmentType>{amendment_type}</amendmentType></amendmentInfo>"
    doc = _PRIMARY_DOC.replace(b"<reportType>", block.encode() + b"<reportType>")
    return doc.replace(b"<tableValueTotal>102000<", f"<tableValueTotal>{total}<".encode())


def _untyped_amendment_cover(total: int = 102000) -> bytes:
    """A cover page with no amendment markers at all (the AEGON shape)."""
    return _PRIMARY_DOC.replace(b"<tableValueTotal>102000<", f"<tableValueTotal>{total}<".encode())


class _Response:
    """Minimal stand-in for the ``requests.Response`` fields the tool reads."""

    def __init__(self, *, content: bytes = b"", payload: Any = None, text: str = "") -> None:
        self.content = content
        self.text = text
        self._payload = payload

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no JSON payload configured")
        return self._payload


def _fts_hit(**overrides: Any) -> Dict[str, Any]:
    """Build one EDGAR full-text search hit in the live ``_source`` shape."""
    source = {
        "ciks": ["0001067983"],
        "display_names": ["TEST CAPITAL LLC  (CIK 0001067983)"],
        "form": "13F-HR",
        "file_date": "2026-05-15",
        "period_ending": "2026-03-31",
        "adsh": "0001193125-26-226661",
        "file_type": "13F-HR",
    }
    source.update(overrides)
    return {"_id": f"{source['adsh']}:primary_doc.xml", "_source": source}


def _fts_payload(hits: List[Dict[str, Any]], total: int | None = None, relation: str = "eq") -> Dict[str, Any]:
    """Wrap hits in the full-text-search envelope shape."""
    return {"hits": {"total": {"value": total if total is not None else len(hits), "relation": relation}, "hits": hits}}


# A real 13F filer is above the $100M threshold that compels filing, so a
# cover page used for ranking has to sit above it too — below that the tool
# stops trusting the filing-date unit prior and goes and reads the information
# table, which is a different code path from the one these tests pin down.
_BIG_PRIMARY_DOC = _PRIMARY_DOC.replace(
    b"<tableValueTotal>102000<", b"<tableValueTotal>102000000000<"
)


def _cover_page(total: int) -> bytes:
    """Render a cover page reporting ``total`` as its ``tableValueTotal``."""
    return _PRIMARY_DOC.replace(b"<tableValueTotal>102000<", f"<tableValueTotal>{total}<".encode())


def _router(*, current: bytes | None = None, prior: bytes | None = None, filings: List[Dict[str, Any]] | None = None):
    """Return a ``_sec_get`` stub that answers by URL, as the live endpoints do.

    Full-text search is filtered by the ``ciks`` parameter the way the live
    endpoint is, so a per-filer index lookup cannot accidentally see another
    filer's accessions.
    """
    current = current if current is not None else _info_table(_CURRENT_ROWS)
    prior = prior if prior is not None else _info_table(_PRIOR_ROWS)
    hits = filings if filings is not None else [
        _fts_hit(),
        _fts_hit(adsh="0000950123-26-000001", file_date="2026-02-14", period_ending="2025-12-31"),
    ]

    def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
        if url == iht._FTS_URL:
            wanted = (params or {}).get("ciks")
            matched = [h for h in hits if not wanted or wanted in (h["_source"].get("ciks") or [])]
            return _Response(payload=_fts_payload(matched, total=len(hits)))
        if url.endswith("/index.json"):
            return _Response(payload=_INDEX_JSON)
        if url.endswith("primary_doc.xml"):
            return _Response(content=_PRIMARY_DOC)
        # Archive paths carry the accession with its dashes stripped, so the
        # dashed form never appears in a document URL.
        if "000119312526226661" in url:
            return _Response(content=current)
        return _Response(content=prior)

    return fake


def _chain_router(entries: List[Dict[str, Any]], *, cik: str = "0001067983"):
    """Return a ``_sec_get`` stub serving a whole quarter's chain of filings.

    Each entry is ``{adsh, form, file_date, cover, rows}``: ``cover`` is the
    ``primary_doc.xml`` bytes and ``rows`` the information-table rows, so a test
    can lay out an original plus any number of amendments and assert on what the
    tool makes of them.
    """
    hits = [
        _fts_hit(ciks=[cik], adsh=e["adsh"], form=e.get("form", "13F-HR"), file_date=e["file_date"])
        for e in entries
    ]
    by_accession = {e["adsh"].replace("-", ""): e for e in entries}

    def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
        if url == iht._FTS_URL:
            return _Response(payload=_fts_payload(hits))
        key = next((k for k in by_accession if k in url), None)
        if key is None:
            raise AssertionError(f"unexpected URL {url}")
        entry = by_accession[key]
        if url.endswith("/index.json"):
            return _Response(payload={"directory": {"item": [{"name": "infotable.xml", "size": "4096"}]}})
        if url.endswith("primary_doc.xml"):
            return _Response(content=entry["cover"])
        return _Response(content=_info_table(entry["rows"]))

    return fake


# DZ BANK AG's real 2020-09-30 quarter, shrunk to four securities: an original,
# a RESTATEMENT that drops one holding and re-prices the rest, and a NEW
# HOLDINGS amendment carrying the two ETF positions the original omitted.
_DZ_ORIGINAL_ROWS = [
    {"issuer": "APPLE INC", "cusip": "037833100", "value": 25000, "shares": 100},
    {"issuer": "COCA COLA CO", "cusip": "191216100", "value": 12000, "shares": 200},
    {"issuer": "TESLA INC", "cusip": "88160R101", "value": 7000, "shares": 40},
]
_DZ_RESTATED_ROWS = [
    {"issuer": "APPLE INC", "cusip": "037833100", "value": 26000, "shares": 100},
    {"issuer": "COCA COLA CO", "cusip": "191216100", "value": 12000, "shares": 200},
]
_DZ_NEW_HOLDINGS_ROWS = [
    {"issuer": "ISHARES TR", "cls": "TIPS BD ETF", "cusip": "464287176", "value": 419548, "shares": 3310},
    {"issuer": "ISHARES TR", "cls": "0-5 YR TIPS ETF", "cusip": "46429B747", "value": 746351, "shares": 7160},
]


def _dz_chain(*, include_new_holdings: bool = True) -> List[Dict[str, Any]]:
    """Build the DZ BANK original / RESTATEMENT / NEW HOLDINGS chain."""
    chain = [
        {
            "adsh": "0001567619-20-019792",
            "form": "13F-HR",
            "file_date": "2020-11-16",
            "cover": _PRIMARY_DOC,
            "rows": _DZ_ORIGINAL_ROWS,
        },
        {
            "adsh": "0000905148-26-002029",
            "form": "13F-HR/A",
            "file_date": "2026-05-04",
            "cover": _amended_cover("RESTATEMENT", number=1),
            "rows": _DZ_RESTATED_ROWS,
        },
    ]
    if include_new_holdings:
        chain.append(
            {
                "adsh": "0000905148-26-002030",
                "form": "13F-HR/A",
                "file_date": "2026-05-04",
                "cover": _amended_cover("NEW HOLDINGS", number=2),
                "rows": _DZ_NEW_HOLDINGS_ROWS,
            }
        )
    return chain


class TestQuarterParsing:
    """``quarter`` accepts the documented forms and rejects everything else."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2026Q1", "2026-03-31"),
            ("2026q4", "2026-12-31"),
            ("2026-Q2", "2026-06-30"),
            ("2026-09-30", "2026-09-30"),
            ("2025-6-30", "2025-06-30"),
        ],
    )
    def test_accepted_forms(self, raw: str, expected: str) -> None:
        assert iht._parse_quarter(raw) == expected

    @pytest.mark.parametrize("raw", ["2026Q5", "26Q1", "2026-02-28", "last quarter", "", "1980Q1"])
    def test_rejected_forms(self, raw: str) -> None:
        with pytest.raises(ValueError):
            iht._parse_quarter(raw)

    def test_bad_quarter_reaches_the_user_as_an_envelope(self) -> None:
        tool = InstitutionalHoldingsTool()
        payload = json.loads(tool.execute(mode="manager_holdings", manager="X", quarter="2026Q7"))
        assert payload["ok"] is False
        assert "2026Q7" in payload["error"]

    def test_latest_reportable_quarter_waits_out_the_filing_lag(self) -> None:
        from datetime import date

        # 2026-08-04 is only 35 days past 2026-06-30, inside the 45-day window,
        # so the newest fully-filed quarter is still Q1.
        assert iht._latest_reportable_quarter(date(2026, 8, 4)) == "2026-03-31"
        assert iht._latest_reportable_quarter(date(2026, 8, 20)) == "2026-06-30"


class TestValueUnits:
    """``value`` is thousands on old filings and dollars on new ones — usually."""

    def test_modern_filing_is_dollars(self) -> None:
        multiplier, units, basis = iht._detect_value_units(
            iht._parse_information_table(_info_table(_CURRENT_ROWS)), "2026-05-15"
        )
        assert (multiplier, units) == (1, "usd")
        assert "filing_date" in basis

    def test_pre_2023_filing_is_thousands(self) -> None:
        rows = [{"issuer": "APPLE INC", "cusip": "037833100", "value": 138, "shares": 1000}] * 6
        multiplier, units, _ = iht._detect_value_units(iht._parse_information_table(_info_table(rows)), "2022-11-14")
        assert (multiplier, units) == (1000, "usd_thousands")

    def test_implied_price_overrides_a_modern_filing_still_using_thousands(self) -> None:
        """BancFirst filed on 2023-01-03 in thousands; the date prior alone is wrong by 1000x."""
        rows = [{"issuer": "EXXON MOBIL CORP", "cusip": "30231G102", "value": 34646, "shares": 317269}] * 6
        parsed = iht._parse_information_table(_info_table(rows))
        multiplier, units, basis = iht._detect_value_units(parsed, "2023-01-03")
        assert (multiplier, units) == (1000, "usd_thousands")
        assert basis.startswith("implied_price_override")

    def test_implied_price_overrides_an_old_filing_already_using_dollars(self) -> None:
        rows = [{"issuer": "APPLE INC", "cusip": "037833100", "value": 138200, "shares": 1000}] * 6
        parsed = iht._parse_information_table(_info_table(rows))
        multiplier, units, basis = iht._detect_value_units(parsed, "2022-11-14")
        assert (multiplier, units) == (1, "usd")
        assert basis.startswith("implied_price_override")

    def test_too_few_rows_falls_back_to_the_date_alone(self) -> None:
        rows = [{"issuer": "APPLE INC", "cusip": "037833100", "value": 1, "shares": 100}]
        _, _, basis = iht._detect_value_units(iht._parse_information_table(_info_table(rows)), "2026-05-15")
        assert basis == "filing_date"

    def test_principal_rows_are_excluded_from_the_price_check(self) -> None:
        """A bond row's value/principal ratio is not a share price and must not vote."""
        rows = [{"issuer": "SOME BOND", "cusip": "111111111", "value": 1, "shares": 1000, "type": "PRN"}] * 8
        _, _, basis = iht._detect_value_units(iht._parse_information_table(_info_table(rows)), "2026-05-15")
        assert basis == "filing_date"


class TestInformationTableParsing:
    """The XML reader handles real-world encodings and refuses the wrong document."""

    def test_rows_carry_every_reported_field(self) -> None:
        rows = iht._parse_information_table(
            _info_table(
                [{"issuer": "APPLE INC", "cusip": "037833100", "value": 25000, "shares": 100, "put_call": "Put"}]
            )
        )
        assert rows == [
            {
                "issuer": "APPLE INC",
                "title_of_class": "COM",
                "cusip": "037833100",
                "value_raw": 25000.0,
                "shares": 100.0,
                "share_type": "SH",
                "put_call": "Put",
                "discretion": "SOLE",
                "other_manager": None,
                "voting_sole": 100.0,
                "voting_shared": 0.0,
                "voting_none": 0.0,
            }
        ]

    def test_non_utf8_declaration_is_honoured(self) -> None:
        """Filers do emit windows-1252 declarations; parsing bytes is what makes that work."""
        raw = _info_table(_CURRENT_ROWS, declaration='<?xml version="1.0" encoding="windows-1252"?>')
        assert len(iht._parse_information_table(raw)) == len(_CURRENT_ROWS)

    def test_cusip_filter_keeps_only_the_requested_security(self) -> None:
        rows = iht._parse_information_table(_info_table(_CURRENT_ROWS), cusip_filter="037833100")
        assert len(rows) == 2
        assert {r["cusip"] for r in rows} == {"037833100"}

    def test_primary_doc_is_rejected_by_its_root_tag(self) -> None:
        with pytest.raises(ValueError, match="informationTable"):
            iht._parse_information_table(_PRIMARY_DOC)

    def test_row_cap_bounds_a_huge_table(self) -> None:
        rows = [{"issuer": "X", "cusip": "037833100", "value": 1, "shares": 1}] * 5
        with patch.object(iht, "_MAX_INFOTABLE_ROWS", 3):
            assert len(iht._parse_information_table(_info_table(rows))) == 3


class TestAggregation:
    """Duplicate rows for one CUSIP collapse into a single position."""

    def test_subadviser_rows_merge_into_one_position(self) -> None:
        positions = iht._aggregate(iht._parse_information_table(_info_table(_CURRENT_ROWS)), 1)
        apple = next(p for p in positions if p["cusip"] == "037833100")
        assert apple["shares"] == 300.0
        assert apple["value_usd"] == 75000.0
        assert apple["rows"] == 2
        assert [p["cusip"] for p in positions] == sorted(
            (p["cusip"] for p in positions), key=lambda c: -next(x["value_usd"] for x in positions if x["cusip"] == c)
        )

    def test_multiplier_and_weights_are_applied(self) -> None:
        positions = iht._aggregate(iht._parse_information_table(_info_table(_CURRENT_ROWS)), 1000)
        assert positions[0]["value_usd"] == 75_000_000.0
        assert round(sum(p["weight_pct"] for p in positions), 4) == 100.0

    def test_puts_and_calls_stay_separate_from_the_common_stock(self) -> None:
        rows = [
            {"issuer": "APPLE INC", "cusip": "037833100", "value": 100, "shares": 10},
            {"issuer": "APPLE INC", "cusip": "037833100", "value": 50, "shares": 5, "put_call": "Put"},
        ]
        positions = iht._aggregate(iht._parse_information_table(_info_table(rows)), 1)
        assert len(positions) == 2
        assert {p["put_call"] for p in positions} == {None, "Put"}


class TestChanges:
    """Quarter-over-quarter diffs classify every move and drop the unchanged."""

    def test_all_four_actions_are_detected(self) -> None:
        current = iht._aggregate(iht._parse_information_table(_info_table(_CURRENT_ROWS)), 1)
        prior = iht._aggregate(iht._parse_information_table(_info_table(_PRIOR_ROWS)), 1)
        by_cusip = {c["cusip"]: c for c in iht._diff_positions(current, prior)}

        assert by_cusip["037833100"]["action"] == "reduced"
        assert by_cusip["037833100"]["shares_change"] == -100.0
        assert by_cusip["037833100"]["shares_change_pct"] == -25.0
        assert by_cusip["88160R101"]["action"] == "closed"
        assert by_cusip["88160R101"]["shares_after"] == 0.0
        # NVIDIA's value moved but its share count did not: a mark-to-market
        # move is not a trade, so it must not be reported as one.
        assert "67066G104" not in by_cusip
        assert "191216100" not in by_cusip

    def test_a_brand_new_position_is_flagged_new(self) -> None:
        current = iht._aggregate(iht._parse_information_table(_info_table(_CURRENT_ROWS)), 1)
        changes = iht._diff_positions(current, [])
        assert {c["action"] for c in changes} == {"new"}
        assert all(c["shares_before"] == 0.0 for c in changes)
        assert all(c["shares_change_pct"] is None for c in changes)

    def test_changes_are_ordered_by_dollar_impact(self) -> None:
        current = iht._aggregate(iht._parse_information_table(_info_table(_CURRENT_ROWS)), 1)
        changes = iht._diff_positions(current, [])
        impacts = [abs(c["value_usd_change"]) for c in changes]
        assert impacts == sorted(impacts, reverse=True)

    def test_the_diff_itself_is_uncapped_so_counts_stay_truthful(self) -> None:
        """Trimming belongs to the budget step; capping here would corrupt the totals."""
        current = iht._aggregate(
            iht._parse_information_table(
                _info_table([{"issuer": "X", "cusip": f"{i:09d}", "value": 100 + i, "shares": 5} for i in range(300)])
            ),
            1,
        )
        assert len(iht._diff_positions(current, [])) == 300

    def test_fit_changes_trims_to_the_reserved_share(self) -> None:
        current = iht._aggregate(
            iht._parse_information_table(
                _info_table([{"issuer": "X", "cusip": f"{i:09d}", "value": 100 + i, "shares": 5} for i in range(300)])
            ),
            1,
        )
        kept = iht._fit_changes(iht._diff_positions(current, []))
        assert 0 < len(kept) < 300
        assert len(json.dumps(kept)) <= TOOL_RESULT_LIMIT * iht._CHANGES_BUDGET_SHARE


class TestManagerHoldingsMode:
    """The default mode returns a ranked portfolio and an honest envelope."""

    def test_success_envelope(self) -> None:
        with patch.object(iht, "_sec_get", side_effect=_router()):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1", top_n=3)
            )

        assert payload["ok"] is True
        assert payload["market"] == "US"
        assert payload["source"] == "sec_edgar_13f"
        assert payload["mode"] == "manager_holdings"
        data = payload["data"]
        assert data["cik"] == "0001067983"
        assert data["position_count"] == 5
        assert data["portfolio_value_usd"] == 102000.0
        assert data["filing"]["quarter"] == "2026Q1"
        assert data["filing"]["value_units"] == "usd"
        assert len(data["positions"]) == 3
        assert data["positions"][0]["issuer"] == "APPLE INC"

    def test_a_top_n_capped_list_does_not_pass_itself_off_as_complete(self) -> None:
        """``paging.complete`` covers the ranked slice, not the whole portfolio."""
        with patch.object(iht, "_sec_get", side_effect=_router()):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1", top_n=2)
            )

        data = payload["data"]
        assert payload["paging"]["complete"] is True, "the 2-record slice is fully delivered"
        assert data["position_count"] == 5, "but the filer really reported 5 positions"
        assert data["positions_truncated"] is True
        assert data["positions_ranked_limit"] == 2

    def test_an_uncapped_list_is_not_flagged_as_truncated(self) -> None:
        with patch.object(iht, "_sec_get", side_effect=_router()):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1", top_n=50)
            )
        assert payload["data"]["positions_truncated"] is False

    def test_portfolio_total_matches_the_cover_page(self) -> None:
        """Aggregated positions must reconcile to the filer's own reported total."""
        with patch.object(iht, "_sec_get", side_effect=_router()):
            payload = json.loads(InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1"))
            summary = iht._fetch_summary("0001067983", "0001193125-26-226661")
        assert payload["data"]["portfolio_value_usd"] == summary["total_value_raw"]

    def test_include_changes_diffs_against_the_previous_quarter(self) -> None:
        with patch.object(iht, "_sec_get", side_effect=_router()):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1", include_changes=True)
            )
        changes = payload["data"]["changes"]
        assert changes["prior_quarter"] == "2025Q4"
        assert changes["counts"] == {"reduced": 1, "closed": 1}

    def test_a_busy_diff_stays_inside_the_result_budget(self) -> None:
        """The change list rides outside the paged position list, so it needs its own cap.

        Measured live before this was bounded: Bridgewater's 2026Q1 diff
        serialized to 60,419 characters against a 10,000-character budget, which
        the agent loop would have cut mid-structure.
        """
        current = [
            {"issuer": f"ISSUER {i:04d} INC OF DELAWARE", "cusip": f"{i:09d}", "value": 9_000 - i, "shares": 70}
            for i in range(300)
        ]
        prior = [{**row, "shares": 40, "value": row["value"] // 2} for row in current[:250]]

        with patch.object(iht, "_sec_get", side_effect=_router(current=_info_table(current), prior=_info_table(prior))):
            out = InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1", include_changes=True)

        payload = json.loads(out)
        changes = payload["data"]["changes"]
        assert len(out) <= TOOL_RESULT_LIMIT
        assert changes["truncated"] is True
        assert changes["returned"] < changes["total"]
        # Per-action totals are computed before trimming, so they must still
        # describe the whole quarter rather than only the surviving rows.
        assert sum(changes["counts"].values()) == changes["total"] == 300
        assert changes["counts"]["new"] == 50
        assert changes["counts"]["increased"] == 250

    def test_changes_report_their_own_absence(self) -> None:
        with patch.object(iht, "_sec_get", side_effect=_router(filings=[_fts_hit()])):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1", include_changes=True)
            )
        assert "no earlier 13F-HR filing" in payload["data"]["changes"]["error"]


    def test_manager_name_resolves_through_full_text_search(self) -> None:
        captured: List[Dict[str, Any]] = []
        router = _router()

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL:
                captured.append(params or {})
            return router(url, params)

        with patch.object(iht, "_sec_get", side_effect=fake):
            payload = json.loads(InstitutionalHoldingsTool().execute(manager="Test Capital"))

        assert captured[0]["entityName"] == "Test Capital"
        assert captured[0]["forms"] == "13F-HR"
        assert payload["data"]["cik"] == "0001067983"

    def test_ambiguous_manager_names_are_surfaced_not_hidden(self) -> None:
        hits = [
            _fts_hit(ciks=["0001350694"], display_names=["Bridgewater Associates, LP  (CIK 0001350694)"]),
            _fts_hit(ciks=["0001600319"], display_names=["Bridgewater Advisors Inc.  (CIK 0001600319)"]),
        ]

        resolved = _router(filings=[_fts_hit(ciks=["0001350694"])])

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL and (params or {}).get("entityName"):
                return _Response(payload=_fts_payload(hits))
            return resolved(url, params)

        with patch.object(iht, "_sec_get", side_effect=fake):
            payload = json.loads(InstitutionalHoldingsTool().execute(manager="Bridgewater"))

        assert payload["data"]["cik"] == "0001350694"
        assert payload["data"]["other_name_matches"] == [
            {"cik": "0001600319", "name": "Bridgewater Advisors Inc.  (CIK 0001600319)"}
        ]

    def test_pre_xml_filing_reports_why_it_cannot_be_read(self) -> None:
        """Berkshire's 2011 filing holds one .txt document and no XML at all."""
        text_only = {"directory": {"item": [{"name": "d254132d13fhr.txt", "size": "20492"}]}}

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL:
                return _Response(payload=_fts_payload([_fts_hit()]))
            if url.endswith("/index.json"):
                return _Response(payload=text_only)
            raise AssertionError(f"no document should be fetched, got {url}")

        with patch.object(iht, "_sec_get", side_effect=fake):
            payload = json.loads(InstitutionalHoldingsTool().execute(manager="0001067983"))

        assert payload["ok"] is False
        assert "pre-2013" in payload["error"]

    def test_oversized_information_table_is_skipped_with_a_reason(self) -> None:
        huge = {"directory": {"item": [{"name": "big.xml", "size": str(999 * 1024 * 1024)}]}}

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL:
                return _Response(payload=_fts_payload([_fts_hit()]))
            return _Response(payload=huge)

        with patch.object(iht, "_sec_get", side_effect=fake):
            payload = json.loads(InstitutionalHoldingsTool().execute(manager="0001067983"))

        assert payload["ok"] is False
        assert "ceiling" in payload["error"]

    def test_an_unrelated_xml_candidate_does_not_abort_the_filing(self) -> None:
        """Only the root tag identifies the table, so a decoy XML must be skipped."""
        index = {"directory": {"item": [{"name": "decoy.xml", "size": "10"}, {"name": "53405.xml", "size": "45259"}]}}

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL:
                return _Response(payload=_fts_payload([_fts_hit()]))
            if url.endswith("/index.json"):
                return _Response(payload=index)
            if url.endswith("decoy.xml"):
                return _Response(content=b"<somethingElse/>")
            return _Response(content=_info_table(_CURRENT_ROWS))

        with patch.object(iht, "_sec_get", side_effect=fake):
            payload = json.loads(InstitutionalHoldingsTool().execute(manager="0001067983"))

        assert payload["ok"] is True
        assert payload["data"]["filing"]["document_url"].endswith("53405.xml")

    def test_submissions_fallback_when_full_text_search_is_down(self) -> None:
        submissions = {
            "filings": {
                "recent": {
                    "form": ["10-K", "13F-HR"],
                    "accessionNumber": ["x", "0001193125-26-226661"],
                    "filingDate": ["2026-01-01", "2026-05-15"],
                    "reportDate": ["2025-12-31", "2026-03-31"],
                }
            }
        }

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL and (params or {}).get("ciks"):
                raise RuntimeError("full-text search unavailable")
            return _router()(url, params)

        with patch.object(iht, "_sec_get", side_effect=fake), patch.object(
            iht, "get_submissions", return_value=submissions
        ):
            payload = json.loads(InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1"))

        assert payload["ok"] is True
        assert payload["data"]["filing"]["accession"] == "0001193125-26-226661"

    def test_missing_quarter_says_how_far_back_it_looked(self) -> None:
        with patch.object(iht, "_sec_get", side_effect=_router()):
            payload = json.loads(InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2011Q3"))
        assert payload["ok"] is False
        assert "most recent" in payload["error"]
        assert payload["available_quarters"] == ["2026-03-31", "2025-12-31"]


class TestAmendmentClassification:
    """``amendmentType`` decides everything, and neither signal alone is trusted."""

    @pytest.mark.parametrize(
        ("form", "cover", "expected"),
        [
            ("13F-HR", _PRIMARY_DOC, iht._ROLE_ORIGINAL),
            ("13F-HR/A", _amended_cover("RESTATEMENT"), iht._ROLE_RESTATEMENT),
            ("13F-HR/A", _amended_cover("NEW HOLDINGS"), iht._ROLE_NEW_HOLDINGS),
            # AEGON ASSET MANAGEMENT UK Plc: submitted as /A, cover page silent.
            ("13F-HR/A", _untyped_amendment_cover(), iht._ROLE_UNSPECIFIED),
            # Nova Wealth Management: submitted as plain 13F-HR, cover page says
            # NEW HOLDINGS. The cover page wins over the missing suffix.
            ("13F-HR", _amended_cover("NEW HOLDINGS"), iht._ROLE_NEW_HOLDINGS),
            # A value outside the two SEC filers actually use must not be mapped
            # onto either behaviour.
            ("13F-HR/A", _amended_cover("PARTIAL WITHDRAWAL"), iht._ROLE_UNSPECIFIED),
        ],
    )
    def test_role_comes_from_both_signals(self, form: str, cover: bytes, expected: str) -> None:
        with patch.object(iht, "_sec_get", return_value=_Response(content=cover)):
            summary = iht._fetch_summary("0001067983", "0001193125-26-226661")
        verdict = iht._classify_filing({"form": form}, summary)

        assert verdict["role"] == expected
        assert verdict["is_amendment"] is (expected != iht._ROLE_ORIGINAL)
        # Whatever the verdict, the evidence behind it has to be legible.
        assert "submissionType" in verdict["role_basis"]
        assert "coverPage.amendmentType" in verdict["role_basis"]

    def test_an_unreadable_cover_page_falls_back_to_the_form_and_says_so(self) -> None:
        verdict = iht._classify_filing({"form": "13F-HR/A"}, {"error": "connection reset"})
        assert verdict["role"] == iht._ROLE_UNSPECIFIED
        assert verdict["amendment_type_known"] is False
        assert "coverPage=unreadable" in verdict["role_basis"]

    def test_amendment_number_orders_two_same_day_amendments(self) -> None:
        """DZ BANK filed both of its 2020Q3 amendments on 2026-05-04."""
        with patch.object(iht, "_sec_get", side_effect=_chain_router(_dz_chain())):
            filings = iht._filings_for_period(iht._list_13f_filings("0001067983"), "2026-03-31")
            chain, truncated = iht._quarter_chain("0001067983", filings)

        assert truncated is False
        assert [f["role"] for f in chain] == [
            iht._ROLE_ORIGINAL,
            iht._ROLE_RESTATEMENT,
            iht._ROLE_NEW_HOLDINGS,
        ]
        assert [f["amendment_no"] for f in chain] == [None, 1.0, 2.0]

    def test_true_and_false_flags_are_read_but_a_missing_one_stays_unknown(self) -> None:
        assert iht._to_bool("true") is True
        assert iht._to_bool("Y") is True
        assert iht._to_bool("false") is False
        assert iht._to_bool("N") is False
        assert iht._to_bool(None) is None, "absent is a third state, never a silent False"
        assert iht._to_bool("maybe") is None


class TestAmendmentChainResolution:
    """A quarter is the whole chain of filings, not whichever one arrived first."""

    def test_restatement_replaces_and_new_holdings_merges(self) -> None:
        with patch.object(iht, "_sec_get", side_effect=_chain_router(_dz_chain())):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1", top_n=50)
            )

        data = payload["data"]
        held = {p["cusip"]: p for p in data["positions"]}
        # The restatement dropped Tesla, so it must be gone despite the original.
        assert "88160R101" not in held
        # ... and re-priced Apple, so the restated number must win.
        assert held["037833100"]["value_usd"] == 26000.0
        # The NEW HOLDINGS rows are additions, not a replacement portfolio.
        assert held["464287176"]["value_usd"] == 419548.0
        assert held["46429B747"]["value_usd"] == 746351.0
        assert data["position_count"] == 4
        assert data["portfolio_value_usd"] == 26000.0 + 12000.0 + 419548.0 + 746351.0

        resolution = data["amendment_resolution"]
        assert resolution["resolution"] == "restated_then_extended"
        assert resolution["unresolved_amendments"] == 0
        assert [(f["role"], f["applied"], f.get("effect")) for f in resolution["filings"]] == [
            (iht._ROLE_ORIGINAL, False, None),
            (iht._ROLE_RESTATEMENT, True, "replace"),
            (iht._ROLE_NEW_HOLDINGS, True, "merge"),
        ]
        assert resolution["filings"][0]["not_applied_reason"] == (
            "superseded by a later RESTATEMENT for the same quarter"
        )

    def test_a_superseded_table_is_never_downloaded(self) -> None:
        """Reading a table only to throw it away costs a full document fetch."""
        fetched: List[str] = []
        router = _chain_router(_dz_chain())

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url != iht._FTS_URL:
                fetched.append(url)
            return router(url, params)

        with patch.object(iht, "_sec_get", side_effect=fake):
            InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1")

        superseded = "0001567619-20-019792".replace("-", "")
        assert not any(u.endswith("infotable.xml") and superseded in u for u in fetched)
        assert any(u.endswith("primary_doc.xml") and superseded in u for u in fetched), (
            "its cover page is still read — that is what proves it was superseded"
        )

    def test_an_unreadable_restatement_falls_back_to_what_it_superseded(self) -> None:
        """Skipping superseded tables must never turn one bad fetch into no answer."""
        router = _chain_router(_dz_chain(include_new_holdings=False))
        restatement = "0000905148-26-002029".replace("-", "")

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if restatement in url and url.endswith("infotable.xml"):
                raise OSError("connection reset")
            return router(url, params)

        with patch.object(iht, "_sec_get", side_effect=fake):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1", top_n=50)
            )

        data = payload["data"]
        assert data["position_count"] == 3, "the original's three rows, not an error"
        assert data["filing"]["accession"] == "0001567619-20-019792"
        failed = [f for f in data["amendment_resolution"]["filings"] if f.get("error")]
        assert "connection reset" in failed[0]["error"]

    def test_an_unreadable_restatement_falls_back_even_when_new_holdings_stands_in(self) -> None:
        """The fallback must key on 'no restatement applied', not on 'no answer at all'.

        DZ BANK's real chain is original + RESTATEMENT + NEW HOLDINGS. With the
        NEW HOLDINGS leg present a failed restatement fetch still leaves *an*
        answer standing, so an error-only retry guard never fires and the 2-row
        fragment is returned while the original is skipped undownloaded.
        """
        router = _chain_router(_dz_chain(include_new_holdings=True))
        restatement = "0000905148-26-002029".replace("-", "")

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if restatement in url and url.endswith("infotable.xml"):
                raise OSError("connection reset")
            return router(url, params)

        with patch.object(iht, "_sec_get", side_effect=fake):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1", top_n=50)
            )

        data = payload["data"]
        resolution = data["amendment_resolution"]
        assert resolution["resolution"] == "original_plus_new_holdings"
        assert data["position_count"] == 5, "the original's three rows plus the two merged in"
        assert data["filing"]["accession"] == "0001567619-20-019792"
        assert [f["applied"] for f in resolution["filings"]] == [True, False, True]

    def test_a_fragment_never_claims_the_base_filing_was_absent(self) -> None:
        """'No base filing was found' is a different fact from 'none could be read'."""
        chain = _dz_chain(include_new_holdings=True)
        del chain[1]  # original + NEW HOLDINGS, no restatement to fall back through
        router = _chain_router(chain)
        original = "0001567619-20-019792".replace("-", "")

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if original in url and url.endswith("infotable.xml"):
                raise OSError("connection reset")
            return router(url, params)

        with patch.object(iht, "_sec_get", side_effect=fake):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1", top_n=50)
            )

        resolution = payload["data"]["amendment_resolution"]
        assert resolution["resolution"] == "new_holdings_without_base"
        assert any(f["role"] == "original" for f in resolution["filings"]), "the base filing IS listed"
        assert "no base filing was found" not in resolution["note"]
        assert "none could be read" in resolution["note"]
        assert "FRAGMENT" in resolution["note"]

    def test_the_standing_filing_is_the_restatement_not_the_original(self) -> None:
        """Downstream has to be able to tell which document the answer stands on."""
        with patch.object(iht, "_sec_get", side_effect=_chain_router(_dz_chain())):
            payload = json.loads(InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1"))

        filing = payload["data"]["filing"]
        assert filing["accession"] == "0000905148-26-002029"
        assert filing["form"] == "13F-HR/A"

    def test_a_restatement_alone_replaces_the_original(self) -> None:
        with patch.object(iht, "_sec_get", side_effect=_chain_router(_dz_chain(include_new_holdings=False))):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1", top_n=50)
            )

        data = payload["data"]
        assert data["amendment_resolution"]["resolution"] == "restated"
        assert data["position_count"] == 2
        assert data["portfolio_value_usd"] == 38000.0

    def test_new_holdings_on_top_of_an_untouched_original(self) -> None:
        chain = [_dz_chain()[0], _dz_chain()[2]]
        with patch.object(iht, "_sec_get", side_effect=_chain_router(chain)):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1", top_n=50)
            )

        data = payload["data"]
        assert data["amendment_resolution"]["resolution"] == "original_plus_new_holdings"
        assert data["position_count"] == 5, "3 original + 2 added, none replaced"
        assert data["filing"]["accession"] == "0001567619-20-019792"

    def test_filings_in_different_value_units_merge_correctly(self) -> None:
        """A 2020 original in thousands, amended in 2026 in whole dollars.

        DZ BANK's real chain is exactly this: 41,697,805 (thousands) restated as
        41,684,874,610 (dollars). Each filing is scaled to USD on its own before
        anything is merged, so the two never get added in different units.
        """
        chain = [
            {
                "adsh": "0001567619-20-019792",
                "form": "13F-HR",
                "file_date": "2020-11-16",
                "cover": _PRIMARY_DOC,
                # 6 rows priced around $250/share once the thousands multiplier
                # is applied, which is what settles the unit check.
                "rows": [
                    {"issuer": f"ISSUER {i}", "cusip": f"00000000{i}", "value": 25, "shares": 100}
                    for i in range(6)
                ],
            },
            {
                "adsh": "0000905148-26-002030",
                "form": "13F-HR/A",
                "file_date": "2026-05-04",
                "cover": _amended_cover("NEW HOLDINGS", number=1),
                "rows": [{"issuer": "ISHARES TR", "cusip": "464287176", "value": 419548, "shares": 3310}],
            },
        ]
        with patch.object(iht, "_sec_get", side_effect=_chain_router(chain)):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1", top_n=50)
            )

        data = payload["data"]
        sources = {f["accession"]: f for f in data["amendment_resolution"]["filings"]}
        assert sources["0001567619-20-019792"]["value_units"] == "usd_thousands"
        assert sources["0000905148-26-002030"]["value_units"] == "usd"
        # 6 x 25 thousand = 150,000 USD, plus the amendment's 419,548 USD.
        assert data["portfolio_value_usd"] == 150_000.0 + 419_548.0

    def test_an_untyped_amendment_is_reported_unresolved_not_guessed(self) -> None:
        """AEGON files 13F-HR/A with no amendmentType; neither behaviour is assumed."""
        chain = [
            {
                "adsh": "0001539994-25-000009",
                "form": "13F-HR",
                "file_date": "2025-07-28",
                "cover": _PRIMARY_DOC,
                "rows": _DZ_ORIGINAL_ROWS,
            },
            {
                "adsh": "0001539994-26-000022",
                "form": "13F-HR/A",
                "file_date": "2026-04-10",
                "cover": _untyped_amendment_cover(),
                "rows": _DZ_NEW_HOLDINGS_ROWS,
            },
        ]
        with patch.object(iht, "_sec_get", side_effect=_chain_router(chain)):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1", top_n=50)
            )

        data = payload["data"]
        resolution = data["amendment_resolution"]
        assert resolution["resolution"] == "incomplete_unspecified_amendment"
        assert resolution["unresolved_amendments"] == 1
        assert "UNKNOWN" in resolution["note"]
        # Neither merged nor substituted: the base stands and the amendment is
        # described well enough for the caller to go and read it.
        assert data["position_count"] == 3
        unresolved = [f for f in resolution["filings"] if not f["applied"]]
        assert unresolved[0]["row_count"] == 2
        assert unresolved[0]["document_url"].endswith("infotable.xml")
        assert unresolved[0]["amendment_type_known"] is False

    def test_a_new_holdings_amendment_with_no_base_is_called_a_fragment(self) -> None:
        """Nova Wealth Management's only 2026Q1 filing declares NEW HOLDINGS."""
        chain = [
            {
                "adsh": "0001376474-26-000287",
                "form": "13F-HR",
                "file_date": "2026-05-12",
                "cover": _amended_cover("NEW HOLDINGS", number=1),
                "rows": _DZ_NEW_HOLDINGS_ROWS,
            }
        ]
        with patch.object(iht, "_sec_get", side_effect=_chain_router(chain)):
            payload = json.loads(InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1"))

        resolution = payload["data"]["amendment_resolution"]
        assert resolution["resolution"] == "new_holdings_without_base"
        assert "FRAGMENT" in resolution["note"]

    def test_an_untyped_amendment_alone_is_reported_but_labelled_unverified(self) -> None:
        chain = [
            {
                "adsh": "0001539994-26-000022",
                "form": "13F-HR/A",
                "file_date": "2026-04-10",
                "cover": _untyped_amendment_cover(),
                "rows": _DZ_ORIGINAL_ROWS,
            }
        ]
        with patch.object(iht, "_sec_get", side_effect=_chain_router(chain)):
            payload = json.loads(InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1"))

        data = payload["data"]
        assert data["position_count"] == 3
        assert data["amendment_resolution"]["resolution"] == "unverified_amendment_only"
        assert "NOT confirmed" in data["amendment_resolution"]["note"]

    def test_a_repeated_security_in_a_new_holdings_amendment_is_counted(self) -> None:
        """Overlap should be empty by definition, so it is surfaced when it is not."""
        chain = [
            _dz_chain()[0],
            {
                "adsh": "0000905148-26-002030",
                "form": "13F-HR/A",
                "file_date": "2026-05-04",
                "cover": _amended_cover("NEW HOLDINGS", number=1),
                "rows": [{"issuer": "APPLE INC", "cusip": "037833100", "value": 5000, "shares": 20}],
            },
        ]
        with patch.object(iht, "_sec_get", side_effect=_chain_router(chain)):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1", top_n=50)
            )

        data = payload["data"]
        assert data["amendment_resolution"]["overlapping_positions"] == 1
        assert data["position_count"] == 3
        apple = next(p for p in data["positions"] if p["cusip"] == "037833100")
        assert apple["shares"] == 120.0

    def test_the_prior_quarter_of_a_diff_is_resolved_the_same_way(self) -> None:
        """Diffing against a superseded original would invent changes."""
        chain = [
            {
                "adsh": "0001193125-26-226661",
                "form": "13F-HR",
                "file_date": "2026-05-15",
                "cover": _PRIMARY_DOC,
                "rows": _DZ_RESTATED_ROWS,
            },
            {
                "adsh": "0000950123-26-000001",
                "form": "13F-HR",
                "file_date": "2026-02-14",
                "cover": _PRIMARY_DOC,
                "rows": _DZ_ORIGINAL_ROWS,
            },
            {
                "adsh": "0000950123-26-000077",
                "form": "13F-HR/A",
                "file_date": "2026-03-01",
                "cover": _amended_cover("RESTATEMENT", number=1),
                "rows": _DZ_RESTATED_ROWS,
            },
        ]
        hits = [
            _fts_hit(adsh=chain[0]["adsh"], file_date=chain[0]["file_date"]),
            _fts_hit(adsh=chain[1]["adsh"], file_date=chain[1]["file_date"], period_ending="2025-12-31"),
            _fts_hit(
                adsh=chain[2]["adsh"],
                form="13F-HR/A",
                file_date=chain[2]["file_date"],
                period_ending="2025-12-31",
            ),
        ]
        by_accession = {e["adsh"].replace("-", ""): e for e in chain}

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL:
                return _Response(payload=_fts_payload(hits))
            entry = by_accession[next(k for k in by_accession if k in url)]
            if url.endswith("/index.json"):
                return _Response(payload={"directory": {"item": [{"name": "infotable.xml", "size": "4096"}]}})
            if url.endswith("primary_doc.xml"):
                return _Response(content=entry["cover"])
            return _Response(content=_info_table(entry["rows"]))

        with patch.object(iht, "_sec_get", side_effect=fake):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(
                    manager="0001067983", quarter="2026Q1", include_changes=True
                )
            )

        changes = payload["data"]["changes"]
        # 2025Q4 was restated to the same two rows the current quarter reports,
        # so a chain-aware diff sees no change at all. Reading 2025Q4's original
        # instead would have reported a phantom "closed TESLA".
        assert changes["prior_quarter"] == "2025Q4"
        assert changes["prior_accession"] == "0000950123-26-000077"
        assert changes["prior_amendment_resolution"]["resolution"] == "restated"
        assert changes["counts"] == {}


class TestTickerHoldersMode:
    """Holder discovery never invents a CUSIP and always states its sample."""

    def test_explicit_cusip_skips_the_mapping_entirely(self) -> None:
        hits = [_fts_hit(file_type="INFORMATION TABLE")]
        searches: List[Dict[str, Any]] = []
        # The deadline window and the late tail are separate date ranges with
        # separate totals; the reported universe is their sum, not either one.
        totals = {"2026-05-15": 9627, "2026-07-29": 240}

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL:
                searches.append(params or {})
                if (params or {}).get("q") == '"037833100"':
                    page = [] if (params or {}).get("from") else hits
                    return _Response(payload=_fts_payload(page, total=totals[params["enddt"]]))
            return _router()(url, params)

        with patch.object(iht, "_sec_get", side_effect=fake), patch.object(
            iht, "_cusip_map", side_effect=AssertionError("must not build the CUSIP map")
        ):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(mode="ticker_holders", cusip="037833100", quarter="2026Q1")
            )

        data = payload["data"]
        assert data["cusip_source"] == "caller"
        assert data["holders"][0]["value_usd"] == 75000.0
        assert data["holders"][0]["shares"] == 300.0
        assert data["holders"][0]["held"] is True
        # Discovery is CUSIP-scoped; the per-filer chain lookup that follows is
        # CIK-scoped and must not carry the CUSIP query over.
        cusip_queries = [s for s in searches if s.get("q") == '"037833100"']
        assert cusip_queries and all(s.get("ciks") is None for s in cusip_queries)
        assert any(s.get("ciks") == "0001067983" for s in searches)
        assert data["matching_documents_total"] == 9627 + 240

    def test_unmapped_ticker_refuses_rather_than_guessing(self) -> None:
        with patch.object(iht, "_cusip_map", return_value=({}, ["https://example.invalid/f.zip"])):
            payload = json.loads(InstitutionalHoldingsTool().execute(mode="ticker_holders", ticker="ZZZZ"))

        assert payload["ok"] is False
        assert "No CUSIP was guessed" in payload["error"]
        assert payload["ticker"] == "ZZZZ"

    def test_ticker_resolves_through_fails_to_deliver_data(self) -> None:
        mapping = {"AAPL": ("037833100", "APPLE INC;COM NPV")}

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL:
                return _Response(payload=_fts_payload([_fts_hit(file_type="INFORMATION TABLE")]))
            return _router()(url, params)

        with patch.object(iht, "_sec_get", side_effect=fake), patch.object(
            iht, "_cusip_map", return_value=(mapping, ["u"])
        ):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(mode="ticker_holders", ticker="aapl", quarter="2026Q1")
            )

        assert payload["data"]["cusip"] == "037833100"
        assert payload["data"]["cusip_source"] == "sec_fails_to_deliver"

    def test_share_class_separators_are_normalized(self) -> None:
        """The fails-to-deliver feed writes Berkshire class B as BRKB, not BRK.B."""
        with patch.object(iht, "_cusip_map", return_value=({"BRKB": ("084670702", "BERKSHIRE B")}, ["u"])):
            assert iht._cusip_for_ticker("BRK.B")[0] == "084670702"
            assert iht._cusip_for_ticker("BRK-B")[0] == "084670702"
            assert iht._cusip_for_ticker("BRKB")[0] == "084670702"

    def test_cover_pages_and_other_quarters_are_filtered_out(self) -> None:
        hits = [
            _fts_hit(file_type="13F-HR"),
            _fts_hit(file_type="INFORMATION TABLE", period_ending="2025-12-31", ciks=["0000000002"]),
            _fts_hit(file_type="INFORMATION TABLE", ciks=["0000000003"]),
        ]

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL:
                return _Response(payload=_fts_payload(hits))
            return _router()(url, params)

        with patch.object(iht, "_sec_get", side_effect=fake):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(mode="ticker_holders", cusip="037833100", quarter="2026Q1")
            )

        assert payload["data"]["filers_seen"] == 1
        assert [h["cik"] for h in payload["data"]["holders"]] == ["0000000003"]

    def test_one_unreadable_filer_does_not_abort_the_batch(self) -> None:
        hits = [
            _fts_hit(file_type="INFORMATION TABLE", ciks=["0000000001"], adsh="0000000001-26-000001"),
            _fts_hit(file_type="INFORMATION TABLE", ciks=["0000000002"], adsh="0001193125-26-226661"),
        ]

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL:
                wanted = (params or {}).get("ciks")
                page = [h for h in hits if not wanted or wanted in h["_source"]["ciks"]]
                return _Response(payload=_fts_payload(page if not (params or {}).get("from") else []))
            if "000000000126000001" in url:
                raise OSError("connection reset")
            return _router()(url, params)

        with patch.object(iht, "_sec_get", side_effect=fake):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(mode="ticker_holders", cusip="037833100", quarter="2026Q1")
            )

        holders = {h["cik"]: h for h in payload["data"]["holders"]}
        assert payload["ok"] is True
        assert holders["0000000002"]["value_usd"] == 75000.0
        assert "connection reset" in holders["0000000001"]["error"]
        # The broken filer must sort last, never above a real position.
        assert payload["data"]["holders"][0]["cik"] == "0000000002"

    def test_a_restatement_that_dropped_the_security_reports_held_false(self) -> None:
        """The filer surfaced because its original named the CUSIP; the restatement did not."""
        chain = [
            {
                "adsh": "0001193125-26-226661",
                "form": "13F-HR",
                "file_date": "2026-05-15",
                "cover": _PRIMARY_DOC,
                "rows": _DZ_ORIGINAL_ROWS,
            },
            {
                "adsh": "0000905148-26-002029",
                "form": "13F-HR/A",
                "file_date": "2026-06-04",
                "cover": _amended_cover("RESTATEMENT", number=1),
                "rows": _DZ_RESTATED_ROWS,
            },
        ]
        router = _chain_router(chain)

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL and (params or {}).get("q"):
                hit = _fts_hit(file_type="INFORMATION TABLE", adsh=chain[0]["adsh"])
                return _Response(payload=_fts_payload([] if (params or {}).get("from") else [hit]))
            return router(url, params)

        with patch.object(iht, "_sec_get", side_effect=fake):
            payload = json.loads(
                # TESLA is in the original table and gone from the restatement.
                InstitutionalHoldingsTool().execute(
                    mode="ticker_holders", cusip="88160R101", quarter="2026Q1"
                )
            )

        holder = payload["data"]["holders"][0]
        assert holder["held"] is False
        assert holder["value_usd"] is None
        assert holder["error"] is None, "no longer holding it is not a failure to read it"
        assert holder["standing_accession"] == "0000905148-26-002029"
        assert holder["amendment_resolution"]["resolution"] == "restated"
        assert holder["amendment_scope"] == "filer_index"

    def test_a_capped_total_is_labelled_as_a_lower_bound(self) -> None:
        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL:
                hits = [_fts_hit(file_type="INFORMATION TABLE")]
                return _Response(payload=_fts_payload(hits, total=10000, relation="gte"))
            return _router()(url, params)

        with patch.object(iht, "_sec_get", side_effect=fake):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(mode="ticker_holders", cusip="037833100", quarter="2026Q1")
            )

        assert payload["data"]["matching_documents_total_is_lower_bound"] is True

    def test_ticker_and_cusip_both_missing_is_an_error(self) -> None:
        payload = json.loads(InstitutionalHoldingsTool().execute(mode="ticker_holders"))
        assert payload["ok"] is False
        assert "'ticker' or 'cusip'" in payload["error"]


class TestTopManagersMode:
    """Ranking is bounded, deduplicated and explicitly scoped to its sample."""

    def test_managers_are_ranked_by_reported_portfolio_value(self) -> None:
        hits = [
            _fts_hit(ciks=["0000000001"], adsh="0000000001-26-000001"),
            _fts_hit(ciks=["0000000002"], adsh="0000000002-26-000001"),
            _fts_hit(ciks=["0000000001"], adsh="0000000001-26-000002"),
        ]
        totals = {
            "0000000001-26-000001": 5_000_000_000,
            "0000000001-26-000002": 6_000_000_000,
            "0000000002-26-000001": 900_000_000_000,
        }

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL:
                wanted = (params or {}).get("ciks")
                page = [h for h in hits if not wanted or wanted in h["_source"]["ciks"]]
                if (params or {}).get("from"):
                    page = []
                return _Response(payload=_fts_payload(page, total=12000, relation="gte"))
            accession = url.split("/")[-2]
            for raw, value in totals.items():
                if raw.replace("-", "") == accession:
                    return _Response(content=_cover_page(value))
            raise AssertionError(url)

        with patch.object(iht, "_sec_get", side_effect=fake):
            payload = json.loads(InstitutionalHoldingsTool().execute(mode="top_managers", quarter="2026Q1"))

        data = payload["data"]
        assert data["scanned"] == 2, "the same CIK filing twice must be scanned once"
        assert [m["cik"] for m in data["managers"]] == ["0000000002", "0000000001"]
        assert data["managers"][0]["portfolio_value_usd"] == 900_000_000_000.0
        assert data["managers"][0]["value_units_basis"] == "filing_date"
        assert data["universe_documents_is_lower_bound"] is True
        assert "NOT a league table" in data["ranking_note"]
        # Two filings for CIK 1, neither marked as an amendment: the second has
        # no stated relationship to the first, so it is not silently summed in.
        ranked = {m["cik"]: m for m in data["managers"]}
        assert ranked["0000000001"]["portfolio_value_usd"] == 5_000_000_000.0
        assert ranked["0000000001"]["amendment_resolution"]["unresolved_duplicate_originals"] == 1
        assert ranked["0000000001"]["amendment_scope"] == "filer_index"
        assert ranked["0000000002"]["amendment_scope"] == "discovery_window"

    def test_scan_limit_bounds_the_number_of_filings_read(self) -> None:
        hits = [_fts_hit(ciks=[f"000000000{i}"], adsh=f"000000000{i}-26-000001") for i in range(1, 6)]
        fetched: List[str] = []

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL:
                return _Response(payload=_fts_payload(hits))
            fetched.append(url)
            return _Response(content=_BIG_PRIMARY_DOC)

        with patch.object(iht, "_sec_get", side_effect=fake):
            payload = json.loads(
                InstitutionalHoldingsTool().execute(mode="top_managers", quarter="2026Q1", scan_limit=2)
            )

        assert len(fetched) == 2
        assert payload["data"]["scanned"] == 2

    def test_a_broken_cover_page_is_reported_not_ranked_first(self) -> None:
        hits = [
            _fts_hit(ciks=["0000000001"], adsh="0000000001-26-000001"),
            _fts_hit(ciks=["0000000002"], adsh="0000000002-26-000001"),
        ]

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL:
                return _Response(payload=_fts_payload(hits))
            if "000000000126000001" in url:
                return _Response(content=b"not xml at all")
            return _Response(content=_BIG_PRIMARY_DOC)

        with patch.object(iht, "_sec_get", side_effect=fake):
            payload = json.loads(InstitutionalHoldingsTool().execute(mode="top_managers", quarter="2026Q1"))

        managers = payload["data"]["managers"]
        assert managers[0]["cik"] == "0000000002"
        assert managers[-1]["error"]
        assert managers[-1]["portfolio_value_usd"] is None

    def test_a_sub_threshold_cover_page_is_rescaled_from_the_information_table(self) -> None:
        """A filer still reporting thousands must not be shrunk 1000x and mis-ranked.

        Modelled on CapitalatWork S.A. (CIK 0002135126), whose 2026-03-31 cover
        page reports 3,361,057. Read as whole dollars that is $3.4M — below the
        $100M that compels filing at all — while its information table prices
        Apple at a believable per-share figure and settles the unit at
        thousands, i.e. a $3.4B portfolio.
        """
        thousands_rows = [
            {"issuer": "APPLE INC", "cusip": "037833100", "value": 16323, "shares": 64258},
            {"issuer": "COCA COLA CO", "cusip": "191216100", "value": 12000, "shares": 157790},
            {"issuer": "VISA INC", "cusip": "92826C839", "value": 9000, "shares": 25641},
            {"issuer": "NVIDIA CORP", "cusip": "67066G104", "value": 4000, "shares": 22936},
            {"issuer": "SPDR S&P 500", "cusip": "78462F103", "value": 2000, "shares": 3610},
            {"issuer": "TESLA INC", "cusip": "88160R101", "value": 1000, "shares": 2500},
        ]

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL:
                return _Response(payload=_fts_payload([_fts_hit(ciks=["0002135126"])]))
            if url.endswith("primary_doc.xml"):
                return _Response(content=_cover_page(3_361_057))
            if url.endswith("/index.json"):
                return _Response(payload=_INDEX_JSON)
            return _Response(content=_info_table(thousands_rows))

        with patch.object(iht, "_sec_get", side_effect=fake):
            payload = json.loads(InstitutionalHoldingsTool().execute(mode="top_managers", quarter="2026Q1"))

        manager = payload["data"]["managers"][0]
        assert manager["value_units"] == "usd_thousands"
        assert manager["value_units_basis"] == "information_table_implied_price"
        assert manager["portfolio_value_usd"] == 3_361_057_000.0

    def test_an_unreadable_table_leaves_the_prior_intact_and_says_so(self) -> None:
        """When the check cannot run, the number must not silently change."""

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL:
                return _Response(payload=_fts_payload([_fts_hit()]))
            if url.endswith("primary_doc.xml"):
                return _Response(content=_cover_page(3_361_057))
            raise OSError("index unavailable")

        with patch.object(iht, "_sec_get", side_effect=fake):
            payload = json.loads(InstitutionalHoldingsTool().execute(mode="top_managers", quarter="2026Q1"))

        manager = payload["data"]["managers"][0]
        assert manager["portfolio_value_usd"] == 3_361_057.0
        assert manager["value_units_basis"].startswith("filing_date (unverified:")

    def test_a_new_holdings_fragment_is_not_ranked_as_the_whole_portfolio(self) -> None:
        """DZ BANK's NEW HOLDINGS amendment reports $1.17M against a $41.68B quarter."""
        chain = [
            {
                "adsh": "0001567619-20-019792",
                "form": "13F-HR",
                "file_date": "2026-05-15",
                "cover": _cover_page(41_697_805_000),
                "rows": _DZ_ORIGINAL_ROWS,
            },
            {
                "adsh": "0000905148-26-002030",
                "form": "13F-HR/A",
                "file_date": "2026-05-20",
                "cover": _amended_cover("NEW HOLDINGS", number=1, total=1_165_899_000),
                "rows": _DZ_NEW_HOLDINGS_ROWS,
            },
        ]
        router = _chain_router(chain)
        # Discovery lands on the amendment, which is the trap: read alone it
        # ranks a $41.7B manager as a $1.2M one.
        discovered = _fts_hit(adsh=chain[1]["adsh"], form="13F-HR/A", file_date=chain[1]["file_date"])

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL and not (params or {}).get("ciks"):
                return _Response(payload=_fts_payload([] if (params or {}).get("from") else [discovered]))
            return router(url, params)

        with patch.object(iht, "_sec_get", side_effect=fake):
            payload = json.loads(InstitutionalHoldingsTool().execute(mode="top_managers", quarter="2026Q1"))

        manager = payload["data"]["managers"][0]
        assert manager["portfolio_value_usd"] == 41_697_805_000.0 + 1_165_899_000.0
        assert manager["amendment_resolution"]["resolution"] == "original_plus_new_holdings"
        assert manager["amendment_resolution"]["standing_accession"] == "0001567619-20-019792"
        assert manager["amendment_scope"] == "filer_index"
        assert "merged_1_new_holdings_amendment" in manager["value_units_basis"]

    def test_a_plain_filing_costs_exactly_one_cover_page_request(self) -> None:
        """The filer index is only pulled when this quarter is actually amended."""
        fetched: List[str] = []

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL:
                if (params or {}).get("ciks"):
                    raise AssertionError("must not pull the filer index for an unamended quarter")
                page = [] if (params or {}).get("from") else [_fts_hit()]
                return _Response(payload=_fts_payload(page))
            fetched.append(url)
            return _Response(content=_BIG_PRIMARY_DOC)

        with patch.object(iht, "_sec_get", side_effect=fake):
            payload = json.loads(InstitutionalHoldingsTool().execute(mode="top_managers", quarter="2026Q1"))

        assert len(fetched) == 1
        assert payload["data"]["managers"][0]["amendment_scope"] == "discovery_window"

    def test_cover_page_units_follow_the_filing_date(self) -> None:
        assert iht._summary_value_usd({"total_value_raw": 296_096_640.0}, "2022-11-14") == 296_096_640_000.0
        assert iht._summary_value_usd({"total_value_raw": 299_007_622_119.0}, "2023-02-14") == 299_007_622_119.0
        assert iht._summary_value_usd({}, "2026-05-15") is None


class TestDiscoveryWindows:
    """Filer discovery is windowed on the statutory deadline, not a flat lag."""

    def test_the_first_window_is_the_filing_season_itself(self) -> None:
        windows = iht._discovery_windows("2026-03-31")
        assert windows[0] == ("2026-04-01", "2026-05-15"), "quarter end through the 45-day deadline"

    def test_the_windows_tile_the_old_flat_lag_exactly(self) -> None:
        """Splitting the span must not make any filing unreachable."""
        windows = iht._discovery_windows("2026-03-31")
        assert windows[0][0] == "2026-04-01"
        assert windows[-1][1] == "2026-07-29", "still 120 days out, as before the split"
        for earlier, later in zip(windows, windows[1:]):
            assert date.fromisoformat(later[0]) - date.fromisoformat(earlier[1]) == timedelta(days=1)

    def test_the_late_tail_is_only_paged_when_the_sample_is_short(self) -> None:
        queried: List[str] = []

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL:
                if (params or {}).get("ciks"):
                    return _Response(payload=_fts_payload([]))
                queried.append(params["enddt"])
                page = [] if (params or {}).get("from") else [
                    _fts_hit(ciks=[f"000000{i:04d}"], adsh=f"000000{i:04d}-26-000001") for i in range(3)
                ]
                return _Response(payload=_fts_payload(page))
            return _Response(content=_BIG_PRIMARY_DOC)

        with patch.object(iht, "_sec_get", side_effect=fake):
            json.loads(
                InstitutionalHoldingsTool().execute(mode="top_managers", quarter="2026Q1", scan_limit=3)
            )
        assert queried == ["2026-05-15"], "the deadline window filled the sample on its own"

        queried.clear()
        with patch.object(iht, "_sec_get", side_effect=fake):
            json.loads(
                InstitutionalHoldingsTool().execute(mode="top_managers", quarter="2026Q1", scan_limit=25)
            )
        assert list(dict.fromkeys(queried)) == [
            "2026-05-15",
            "2026-07-29",
        ], "a short sample reaches into the late tail, and only after exhausting the deadline window"


class TestInformationTableDiscovery:
    """The right XML is chosen by name and size, not by where EDGAR listed it."""

    def test_a_table_listed_after_the_decoys_is_still_probed_first(self) -> None:
        index = {
            "directory": {
                "item": [
                    {"name": "0001193125-26-226661-index.html", "size": ""},
                    {"name": "primary_doc.xml", "size": "5555"},
                    {"name": "decoy_a.xml", "size": "10"},
                    {"name": "decoy_b.xml", "size": "10"},
                    {"name": "decoy_c.xml", "size": "10"},
                    {"name": "infotable.xml", "size": "45259"},
                ]
            }
        }
        with patch.object(iht, "_sec_get", return_value=_Response(payload=index)):
            urls, note = iht._information_table_urls("0001067983", "0001193125-26-226661")

        assert note is None
        assert urls[0].endswith("infotable.xml"), "fourth in the listing, first in the probe order"
        assert len(urls) == 4

    def test_unnamed_candidates_are_probed_largest_first(self) -> None:
        index = {
            "directory": {
                "item": [
                    {"name": "aaa.xml", "size": "10"},
                    {"name": "53405.xml", "size": "45259"},
                    {"name": "zzz.xml", "size": "900"},
                ]
            }
        }
        with patch.object(iht, "_sec_get", return_value=_Response(payload=index)):
            urls, _ = iht._information_table_urls("0001067983", "0001193125-26-226661")

        assert [u.rsplit("/", 1)[-1] for u in urls] == ["53405.xml", "zzz.xml", "aaa.xml"]

    def test_the_candidate_list_stays_bounded(self) -> None:
        index = {"directory": {"item": [{"name": f"x{i}.xml", "size": "10"} for i in range(40)]}}
        with patch.object(iht, "_sec_get", return_value=_Response(payload=index)):
            urls, _ = iht._information_table_urls("0001067983", "0001193125-26-226661")

        assert len(urls) == iht._MAX_TABLE_CANDIDATES


class TestCusipMapping:
    """The fails-to-deliver archive is parsed, never fabricated."""

    def test_archive_is_parsed_into_a_ticker_map(self) -> None:
        payload = (
            "SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE\n"
            "20260701|037833100|AAPL|85824|APPLE INC;COM NPV|294.38\n"
            "20260701|084670702|BRKB|11995|BERKSHIRE HATHWY INC(HLDG CO)B|500.39\n"
            "20260702|037833100|AAPL|14619|APPLE INC;COM NPV|308.63\n"
            "malformed row\n"
            "\n"
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("cnsfails202607a.txt", payload)

        mapping: Dict[str, Any] = {}
        with patch.object(iht, "_sec_get", return_value=_Response(content=buffer.getvalue())):
            iht._load_ftd_map("https://example.invalid/cnsfails202607a.zip", mapping)

        assert mapping["AAPL"] == ("037833100", "APPLE INC;COM NPV")
        assert mapping["BRKB"] == ("084670702", "BERKSHIRE HATHWY INC(HLDG CO)B")
        assert len(mapping) == 2, "a blank or malformed row must be skipped, not crash the build"

    def test_newest_archive_is_discovered_from_the_foia_index(self) -> None:
        html = (
            '<a href="/files/data/fails-deliver-data/cnsfails202605a.zip">x</a>'
            '<a href="/files/data/other/fails-deliver-data/cnsfails202607a.zip">y</a>'
            '<a href="/files/data/fails-deliver-data/cnsfails202606b.zip">z</a>'
        )
        with patch.object(iht, "_sec_get", return_value=_Response(text=html)):
            urls = iht._ftd_urls()

        assert urls == ["https://www.sec.gov/files/data/other/fails-deliver-data/cnsfails202607a.zip"]

    def test_pinned_url_wins_and_costs_no_request(self) -> None:
        with patch.dict("os.environ", {iht._ENV_FTD_URL: "https://example.invalid/pinned.zip"}), patch.object(
            iht, "_sec_get", side_effect=AssertionError("must not fetch the index")
        ):
            assert iht._ftd_urls() == ["https://example.invalid/pinned.zip"]


class TestToolContract:
    """The BaseTool contract the registry relies on."""

    def test_schema_and_flags(self) -> None:
        tool = InstitutionalHoldingsTool()
        assert tool.name == "get_institutional_holdings"
        assert tool.is_readonly is True
        assert InstitutionalHoldingsTool.check_available() is True
        schema = tool.to_openai_schema()["function"]
        assert set(schema["parameters"]["properties"]) == {
            "mode", "manager", "ticker", "cusip", "quarter", "include_changes", "top_n", "scan_limit", "offset",
        }
        assert schema["parameters"]["properties"]["mode"]["enum"] == list(iht._MODES)

    def test_the_tool_is_auto_discovered(self) -> None:
        from src.tools import build_registry

        assert "get_institutional_holdings" in build_registry()

    @pytest.mark.parametrize(
        ("kwargs", "fragment"),
        [
            ({"mode": "nope"}, "mode must be one of"),
            ({"mode": "manager_holdings"}, "requires 'manager'"),
            ({"manager": "X", "offset": "abc"}, "offset must be an integer"),
        ],
    )
    def test_bad_arguments_return_envelopes_not_exceptions(self, kwargs: Dict[str, Any], fragment: str) -> None:
        payload = json.loads(InstitutionalHoldingsTool().execute(**kwargs))
        assert payload["ok"] is False
        assert fragment in payload["error"]

    def test_full_text_search_error_document_is_not_read_as_success(self) -> None:
        """EDGAR answers HTTP 200 with an error body, so a missing hits block must raise."""
        error_doc = {"errorType": "ResponseError", "errorMessage": "boom"}
        with pytest.raises(RuntimeError, match="boom"), patch.object(
            iht, "_sec_get", return_value=_Response(payload=error_doc)
        ):
            iht._fts({"forms": "13F-HR"})

    def test_a_search_error_falls_back_instead_of_reporting_an_empty_portfolio(self) -> None:
        """Losing full-text search must degrade to the submissions index, not to zero filings."""
        submissions = {
            "filings": {
                "recent": {
                    "form": ["13F-HR"],
                    "accessionNumber": ["0001193125-26-226661"],
                    "filingDate": ["2026-05-15"],
                    "reportDate": ["2026-03-31"],
                }
            }
        }

        def fake(url: str, params: Dict[str, Any] | None = None) -> _Response:
            if url == iht._FTS_URL:
                return _Response(payload={"errorMessage": "boom"})
            return _router()(url, params)

        with patch.object(iht, "_sec_get", side_effect=fake), patch.object(
            iht, "get_submissions", return_value=submissions
        ):
            payload = json.loads(InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1"))

        assert payload["ok"] is True
        assert payload["data"]["position_count"] == 5

    def test_both_filing_indexes_failing_surfaces_the_error(self) -> None:
        with patch.object(iht, "_sec_get", side_effect=OSError("sec.gov unreachable")), patch.object(
            iht, "get_submissions", side_effect=OSError("sec.gov unreachable")
        ):
            payload = json.loads(InstitutionalHoldingsTool().execute(manager="0001067983"))
        assert payload["ok"] is False
        assert "sec.gov unreachable" in payload["error"]

    def test_result_stays_inside_the_tool_result_budget(self) -> None:
        """A 400-position portfolio must page, not overflow and lose its tail silently."""
        rows = [
            {"issuer": f"ISSUER NUMBER {i:04d} INCORPORATED", "cusip": f"{i:09d}", "value": 10_000 - i, "shares": 50}
            for i in range(400)
        ]
        with patch.object(iht, "_sec_get", side_effect=_router(current=_info_table(rows))):
            out = InstitutionalHoldingsTool().execute(manager="0001067983", quarter="2026Q1", top_n=100)

        payload = json.loads(out)
        assert len(out) <= TOOL_RESULT_LIMIT
        assert payload["data"]["position_count"] == 400
        assert payload["paging"]["returned"] < 100
        assert payload["paging"]["complete"] is False
        assert payload["paging"]["next_offset"] == payload["paging"]["returned"]

    def test_requests_share_the_sec_throttle_bucket(self) -> None:
        """Every call must be spaced under the same bucket as the other SEC callers."""
        captured: Dict[str, Any] = {}

        def fake_throttled_get(url: str, **kwargs: Any) -> Any:
            captured.update(kwargs)
            captured["url"] = url
            raise OSError("stop here")

        with patch.object(iht, "throttled_get", side_effect=fake_throttled_get):
            with pytest.raises(OSError):
                iht._sec_get("https://data.sec.gov/x")

        assert captured["host_key"] == "sec"
        assert captured["min_interval"] > 0
        assert "User-Agent" in captured["headers"]
