"""Strict benchmark roster contracts; every HTTP call is mocked offline."""

from types import SimpleNamespace

import pandas as pd
import pytest
import requests

from src.tools import hsi_universe as hsi


def html_fixture(codes=None, *, revision=True):
    """Return a dated roster fixture without contacting Wikipedia."""
    codes = hsi.REFERENCE_CODES if codes is None else codes
    header = '<script>{"dateModified":"2026-10-01T18:43:56Z","wgRevisionId":123}</script>' if revision else ""
    return header + pd.DataFrame({"Ticker": codes, "Sector": ["Finance"] * len(codes)}).to_html(index=False)


def response_fixture(monkeypatch, html):
    monkeypatch.setattr(
        hsi.requests,
        "get",
        lambda *args, **kwargs: SimpleNamespace(text=html, raise_for_status=lambda: None),
    )


def test_published_count_and_provenance_pass(monkeypatch):
    response_fixture(monkeypatch, html_fixture())
    codes, sectors, meta = hsi.fetch_benchmark_constituents()
    assert len(codes) == len(set(codes)) == len(sectors) == 95
    assert meta["constituent_source_timestamp"] == "2026-10-01T18:43:56+00:00"
    assert meta["constituent_revision_id"] == "123"
    assert len(meta["constituent_sha256"]) == 64
    assert meta["degraded"] is False


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("short", "count_mismatch"),
        ("duplicate", "duplicate_symbols"),
        ("invalid", "invalid_symbols"),
        ("five_digits", "invalid_symbols"),
        ("undated", "missing_provenance"),
        ("broken", "invalid constituent data"),
    ],
)
def test_invalid_rosters_fail_without_substitution(monkeypatch, mutation, reason):
    codes = list(hsi.REFERENCE_CODES)
    if mutation == "short":
        codes = codes[:85]
    elif mutation == "duplicate":
        codes[-1] = codes[0]
    elif mutation == "invalid":
        codes[-1] = "<private source body>"
    elif mutation == "five_digits":
        codes[-1] = "10000.HK"
    html = html_fixture(codes, revision=mutation != "undated")
    if mutation == "broken":
        html = "<h1>private page</h1>"
    response_fixture(monkeypatch, html)
    with pytest.raises(hsi.HSIConstituentError, match=reason) as failure:
        hsi.fetch_benchmark_constituents()
    assert "<private" not in str(failure.value)


@pytest.mark.parametrize(
    "exc,reason",
    [
        (requests.Timeout, "request timed out"),
        (requests.HTTPError, "HTTP request failed"),
        (requests.ConnectionError, "connection failed"),
        (requests.RequestException, "request failed"),
        (ValueError, "invalid constituent data"),
        (RuntimeError, "constituent source failed"),
    ],
)
def test_transport_failures_share_nifty_sanitized_reasons(monkeypatch, exc, reason):
    def fail(*args, **kwargs):
        raise exc("secret http://private.invalid?token=private responsebody")

    monkeypatch.setattr(hsi.requests, "get", fail)
    with pytest.raises(hsi.HSIConstituentError) as failure:
        hsi.fetch_benchmark_constituents()
    assert str(failure.value) == f"HSI constituent load failed: {reason}"


def test_benchmark_does_not_use_quote_fallback(monkeypatch):
    response_fixture(monkeypatch, html_fixture(hsi.REFERENCE_CODES[:85]))
    from src.tools import alpha_bench_tool

    with pytest.raises(hsi.HSIConstituentError, match="count_mismatch"):
        alpha_bench_tool._load_hsi_panel("2016-01-01", "2026-10-31")


def test_same_count_different_members_is_blocked_before_price_fetch(monkeypatch):
    from src import market_data
    from src.tools import alpha_bench_tool

    changed = list(hsi.REFERENCE_CODES)
    changed[-1] = "0881.HK"
    response_fixture(monkeypatch, html_fixture(changed))
    monkeypatch.setattr(
        market_data, "fetch_market_data", lambda **kw: pytest.fail("Rejected roster must not fetch prices")
    )
    with pytest.raises(hsi.HSIConstituentError, match="membership_mismatch") as failure:
        alpha_bench_tool._load_hsi_panel("2026-11-02", "2026-11-24")
    meta = failure.value.metadata
    assert meta["constituent_observed_count"] == meta["constituent_reference_count"] == 95
    assert meta["constituent_reference_matches"] is False and meta["degraded"] is True
    assert meta["benchmark_eligible"] is False
    assert meta["constituent_reference_missing_symbols"] == ["9999.HK"]
    assert meta["constituent_reference_unexpected_symbols"] == ["0881.HK"]


def test_invalid_roster_cannot_reuse_previously_valid_hsi_cache(monkeypatch, tmp_path):
    from src.tools import alpha_bench_tool as bench

    response_fixture(monkeypatch, html_fixture(hsi.REFERENCE_CODES[:-1] + ["0881.HK"]))
    monkeypatch.setattr(bench, "get_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(
        bench, "_read_pickle_cache", lambda *a: pytest.fail("Must reject before reading any price cache")
    )
    with pytest.raises(hsi.HSIConstituentError, match="membership_mismatch"):
        bench._load_universe_panel("hsi", "2026-11-02/2026-11-24")


def test_cache_identity_changes_with_revision_members_or_reference(monkeypatch):
    roster = (list(hsi.REFERENCE_CODES), {}, {"constituent_revision_id": "1"})
    first = hsi.cache_identity(roster)
    assert first != hsi.cache_identity((roster[0], {}, {"constituent_revision_id": "2"}))
    assert first != hsi.cache_identity((roster[0][:-1] + ["0881.HK"], {}, roster[2]))
    monkeypatch.setattr(hsi, "REFERENCE_EFFECTIVE_DATE", "2026-12-07")
    assert first != hsi.cache_identity(roster)


def test_smoke_does_not_turn_reference_prices_into_benchmark_success(monkeypatch):
    from src.tools import hsi_smoke

    def blocked(*a, **kw):
        raise hsi.HSIConstituentError(
            "invalid constituent data", "count_mismatch", metadata={"constituent_observed_count": 85}
        )

    monkeypatch.setattr(hsi_smoke.bench, "_load_universe_panel", blocked)
    monkeypatch.setattr(hsi_smoke.bench, "_load_hsi_panel", lambda *a, **kw: {"synthetic_price_fixture": True})
    monkeypatch.setattr(hsi_smoke, "coverage", lambda panel: {"requested": 95, "fetched": 95})
    report = hsi_smoke.run("2026-11-02", "2026-11-24", reference_diagnostic=True)
    assert report["benchmark_usable"] is False
    assert report["primary"]["prices"]["status"] == "not_attempted"
    assert report["reference_price_diagnostic"]["status"] == "loaded"
    assert report["reference_price_diagnostic"]["benchmark_eligible"] is False
