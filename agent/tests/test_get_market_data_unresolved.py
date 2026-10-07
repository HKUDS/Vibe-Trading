"""Regression test for P05 — get_market_data must not silently drop a
requested symbol that returned no data.

Pre-fix: the result dict only held winners, so a typo / wrong-suffix /
delisted / no-data code just vanished — indistinguishable from "no data",
and a loader exception lost every already-resolved symbol. Post-fix: any
unresolved requested code is surfaced under the reserved ``_unresolved``
key (additive: omitted entirely when all codes resolve, so the happy-path
payload is byte-identical to before), and a loader blow-up is contained.
"""

from __future__ import annotations

import json
import logging

import pandas as pd
import pytest

import mcp_server

# fastmcp wraps the tool; reach the raw callable.
_gmd = getattr(mcp_server.get_market_data, "fn", None) or getattr(
    mcp_server.get_market_data, "__wrapped__", mcp_server.get_market_data
)


def _df():
    df = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
        index=pd.to_datetime(["2026-05-01"]),
    )
    df.index.name = "trade_date"
    return df


class _GoodOnlyLoader:
    def fetch(self, codes, start, end, interval="1D"):
        return {"GOOD.US": _df()} if "GOOD.US" in codes else {}


class _PartialLoader:
    """Returns only a subset of the requested codes."""

    def fetch(self, codes, start, end, interval="1D"):
        return {c: _df() for c in codes if c.startswith("OK")}


class _BoomLoader:
    def fetch(self, codes, start, end, interval="1D"):
        raise RuntimeError("simulated loader blow-up")


@pytest.fixture
def good_only(monkeypatch):
    monkeypatch.setattr(mcp_server, "_get_loader", lambda src: _GoodOnlyLoader)


def _call(codes):
    return json.loads(_gmd(codes=codes, start_date="2026-05-01", end_date="2026-05-02", source="yfinance"))


def test_unresolved_symbol_is_surfaced(good_only):
    out = _call(["GOOD.US", "BOGUS.US"])
    assert "GOOD.US" in out
    assert out.get("_unresolved") == ["BOGUS.US"]


def test_all_resolved_has_no_unresolved_key(good_only):
    """Happy path must stay byte-identical (additive only)."""
    out = _call(["GOOD.US"])
    assert "GOOD.US" in out
    assert "_unresolved" not in out


def test_loader_exception_is_contained_not_lost(monkeypatch):
    monkeypatch.setattr(mcp_server, "_get_loader", lambda src: _BoomLoader)
    out = _call(["AAA.US", "BBB.US"])  # must not raise an opaque MCP error
    assert sorted(out.get("_unresolved", [])) == ["AAA.US", "BBB.US"]


def test_partial_loader_only_missing_codes_unresolved(monkeypatch):
    """G2: a loader returning only SOME requested codes -> the rest land
    under _unresolved (not silently dropped)."""
    monkeypatch.setattr(mcp_server, "_get_loader", lambda src: _PartialLoader)
    out = _call(["OK1.US", "OK2.US", "MISS1.US", "MISS2.US"])
    assert "OK1.US" in out and "OK2.US" in out
    assert sorted(out.get("_unresolved", [])) == ["MISS1.US", "MISS2.US"]


def test_swallowed_loader_exception_is_logged(monkeypatch, caplog):
    """G2: the contained loader blow-up must still be logged (was silent)."""
    monkeypatch.setattr(mcp_server, "_get_loader", lambda src: _BoomLoader)
    with caplog.at_level(logging.ERROR, logger=mcp_server.logger.name):
        _call(["AAA.US", "BBB.US"])
    assert any("market-data loader" in r.message for r in caplog.records)


def test_nothing_resolved_is_an_error_envelope(monkeypatch):
    """A fetch where no symbol returned data must not read as success.

    ``{"_unresolved": [...]}`` alone classified as a successful call, so the
    loop neither refused the identical retry nor told the model to change the
    request; repeats only counted as "no new information".
    """
    from src.agent.loop import _is_tool_success

    monkeypatch.setattr(mcp_server, "_get_loader", lambda src: _BoomLoader)
    raw = _gmd(codes=["AAA.US", "BBB.US"], start_date="2026-05-01", end_date="2026-05-02", source="yfinance")
    out = json.loads(raw)

    assert out["status"] == "error"
    assert out["error_code"] == "no_market_data"
    assert "AAA.US" in out["error"] and "BBB.US" in out["error"]
    assert sorted(out["_unresolved"]) == ["AAA.US", "BBB.US"]
    assert _is_tool_success(raw) is False


def test_partial_and_full_results_stay_successful(monkeypatch, good_only):
    from src.agent.loop import _is_tool_success

    partial = _gmd(codes=["GOOD.US", "BOGUS.US"], start_date="2026-05-01", end_date="2026-05-02", source="yfinance")
    full = _gmd(codes=["GOOD.US"], start_date="2026-05-01", end_date="2026-05-02", source="yfinance")

    assert "status" not in json.loads(partial) and _is_tool_success(partial)
    assert "status" not in json.loads(full) and _is_tool_success(full)


def test_grounding_still_records_each_unavailable_symbol(tmp_path):
    """The failed envelope keeps per-symbol unavailable evidence."""
    from src.agent.grounding.ledger import GroundingLedger

    ledger = GroundingLedger(run_dir=tmp_path, user_message="price of AAA.US")
    raw = json.dumps({"status": "error", "error_code": "no_market_data", "error": "x",
                      "_unresolved": ["AAA.US"]})
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["AAA.US"], "start_date": "2026-05-01", "end_date": "2026-05-02"},
        result=raw,
        call_id="call-1",
        success=False,
    )
    unavailable = [r for r in ledger._evidence if r.field == "availability"]
    assert [(r.symbol, r.status) for r in unavailable] == [("AAA.US", "unavailable")]
    assert ledger._tool_failures[-1]["error_code"] == "no_market_data"
