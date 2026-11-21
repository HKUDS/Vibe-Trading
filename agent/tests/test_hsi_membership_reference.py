"""Dated roster reconciliation stays separate from source selection and price gaps."""

from types import SimpleNamespace

import pytest
import requests

from src.tools import hsi_universe as hsi


def wikipedia_response(monkeypatch, codes, *, header=None):
    """Supply a dated page and parsed roster without any network request."""
    if header is None:
        header = '{"dateModified":"2026-10-01T18:43:56Z","wgRevisionId":1377881667}'
    monkeypatch.setattr(
        hsi.requests,
        "get",
        lambda *args, **kwargs: SimpleNamespace(
            text=header, raise_for_status=lambda: None
        ),
    )
    monkeypatch.setattr(hsi, "parse_constituents", lambda _: (list(codes), {}))


def test_matching_roster_keeps_wikipedia_order_and_records_separate_dates(monkeypatch):
    expected = list(reversed(hsi.FALLBACK_CODES))
    wikipedia_response(monkeypatch, expected)
    codes, sectors, meta = hsi.fetch_constituents()
    assert codes == expected and sectors == {}
    assert meta["constituent_source"] == hsi.WIKIPEDIA_URL
    assert meta["constituent_source_date"] == "2026-10-01"
    assert meta["constituent_source_date_kind"] == "wikipedia_revision_date"
    assert meta["constituent_reference_source"] == hsi.REFERENCE_SOURCE_URL
    assert meta["constituent_reference_effective_date"] == "2026-09-07"
    assert meta["constituent_reference_snapshot_date"] == "2026-11-04"
    assert meta["constituent_observed_count"] == 95
    assert meta["constituent_reference_count"] == 95
    assert meta["constituent_reference_overlap_count"] == 95
    assert meta["constituent_reference_matches"] is True
    assert meta["constituent_reference_missing_symbols"] == []
    assert meta["constituent_reference_unexpected_symbols"] == []
    assert meta["constituent_reference_frozen"] is True
    assert "can become stale" in meta["constituent_reference_note"]
    assert meta["degraded"] is False


def test_known_85_name_mismatch_reports_eleven_missing_and_one_extra(monkeypatch):
    missing = {
        "0728.HK",
        "1347.HK",
        "1519.HK",
        "1801.HK",
        "2338.HK",
        "2600.HK",
        "3750.HK",
        "3993.HK",
        "6160.HK",
        "6181.HK",
        "9901.HK",
    }
    expected = [code for code in hsi.FALLBACK_CODES if code not in missing] + [
        "0881.HK"
    ]
    wikipedia_response(monkeypatch, expected)
    codes, _sectors, meta = hsi.fetch_constituents()
    assert codes == expected and len(codes) == 85
    assert meta["constituent_reference_missing_symbols"] == sorted(missing)
    assert meta["constituent_reference_unexpected_symbols"] == ["0881.HK"]
    assert meta["constituent_reference_overlap_count"] == 84
    assert meta["constituent_reference_matches"] is False
    assert meta["degraded"] is True
    assert "missing_instruments" not in meta  # These are not provider price failures.


def test_equal_counts_do_not_hide_different_members(monkeypatch):
    expected = hsi.FALLBACK_CODES[:-1] + ["0881.HK"]
    wikipedia_response(monkeypatch, expected)
    codes, _sectors, meta = hsi.fetch_constituents()
    assert codes == expected
    assert meta["constituent_observed_count"] == meta["constituent_reference_count"]
    assert meta["constituent_reference_missing_symbols"] == [hsi.FALLBACK_CODES[-1]]
    assert meta["constituent_reference_unexpected_symbols"] == ["0881.HK"]
    assert meta["constituent_reference_matches"] is False
    assert meta["degraded"] is True


@pytest.mark.parametrize(
    "header",
    [
        "{}",
        '{"dateModified":"2026-10-01T18:43:56Z"}',
        '{"wgRevisionId":1377881667}',
    ],
)
def test_reference_match_does_not_clear_missing_revision_degradation(
    monkeypatch, header
):
    wikipedia_response(monkeypatch, hsi.FALLBACK_CODES, header=header)
    codes, _sectors, meta = hsi.fetch_constituents()
    assert codes == hsi.FALLBACK_CODES
    assert meta["constituent_reference_matches"] is True
    assert meta["degraded"] is True


def test_source_after_reference_is_returned_without_enforcing_a_95_name_limit(
    monkeypatch,
):
    expected = hsi.FALLBACK_CODES + ["9998.HK"]
    wikipedia_response(
        monkeypatch,
        expected,
        header='{"dateModified":"2027-01-01T00:00:00Z","wgRevisionId":999}',
    )
    codes, _sectors, meta = hsi.fetch_constituents()
    assert codes == expected and len(codes) == 96
    assert meta["constituent_source_date"] == "2027-01-01"
    assert meta["constituent_reference_snapshot_date"] == hsi.FALLBACK_DATE
    assert meta["constituent_reference_unexpected_symbols"] == ["9998.HK"]
    assert (
        "does not establish which source is current"
        in meta["constituent_reference_note"]
    )


def test_fallback_stays_degraded_despite_matching_the_same_frozen_reference(
    monkeypatch,
):
    def fail(*_args, **_kwargs):
        raise requests.Timeout()

    monkeypatch.setattr(hsi.requests, "get", fail)
    codes, sectors, meta = hsi.fetch_constituents()
    assert codes == hsi.FALLBACK_CODES and sectors == {}
    assert codes is not hsi.FALLBACK_CODES
    assert meta["constituent_reference_matches"] is True
    assert meta["constituent_reference_overlap_count"] == 95
    assert meta["constituent_source_date_kind"] == "frozen_snapshot_as_of"
    assert meta["constituent_source_date"] == hsi.FALLBACK_DATE
    assert meta["degraded"] is True
