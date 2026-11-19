"""Strict benchmark roster contracts; every HTTP call is mocked offline."""

from types import SimpleNamespace

import pandas as pd
import pytest
import requests

from src.tools import hsi_universe as hsi


def html_fixture(codes=None, *, revision=True):
    """Return a dated roster fixture without contacting Wikipedia."""
    codes = hsi.FALLBACK_CODES if codes is None else codes
    header = (
        '<script>{"dateModified":"2026-10-01T18:43:56Z","wgRevisionId":123}</script>'
        if revision
        else ""
    )
    return header + pd.DataFrame(
        {"Ticker": codes, "Sector": ["Finance"] * len(codes)}
    ).to_html(index=False)


def response_fixture(monkeypatch, html):
    monkeypatch.setattr(
        hsi.requests,
        "get",
        lambda *args, **kwargs: SimpleNamespace(
            text=html, raise_for_status=lambda: None
        ),
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
    codes = list(hsi.FALLBACK_CODES)
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
    monkeypatch.setattr(
        hsi,
        "fetch_constituents",
        lambda: pytest.fail("operational fallback must not run"),
    )
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
    response_fixture(monkeypatch, html_fixture(hsi.FALLBACK_CODES[:85]))
    from src.tools import alpha_bench_tool

    with pytest.raises(hsi.HSIConstituentError, match="count_mismatch"):
        alpha_bench_tool._load_hsi_panel("2016-01-01", "2026-10-31")
