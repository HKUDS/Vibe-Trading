"""Regression test — get_market_data (MCP) must attach the _provenance
block its own docstring promises.

Pre-fix: fetch_market_data_json() was called without include_provenance=True,
so _provenance (including volume_unit) was silently omitted from every MCP
response, while the internal MarketDataTool.execute() call site (used by the
agent/swarm loop for the same request) always passed include_provenance=True
and got the block. An MCP client reading the tool's own docstring, which
tells it to check `_provenance.volume_unit` before comparing volume values,
got a response with no such field. Post-fix: the MCP path passes
include_provenance=True too, matching MarketDataTool.execute() exactly.
"""

from __future__ import annotations

import json

import pandas as pd

import mcp_server

# fastmcp wraps the tool; reach the raw callable.
_gmd = getattr(mcp_server.get_market_data, "fn", None) or getattr(
    mcp_server.get_market_data, "__wrapped__", mcp_server.get_market_data
)


def _df():
    df = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [100.0]},
        index=pd.to_datetime(["2026-05-01"]),
    )
    df.index.name = "trade_date"
    return df


class _ALotsLoader:
    """Declares its A-share volume unit, like the real tencent/eastmoney loaders."""

    volume_units = {"a_share": "lots"}

    def fetch(self, codes, start, end, interval="1D"):
        return {"600519.SH": _df()}


def _call(codes, source="tencent"):
    return json.loads(
        _gmd(codes=codes, start_date="2026-05-01", end_date="2026-05-02", source=source)
    )


def test_mcp_get_market_data_carries_provenance(monkeypatch):
    monkeypatch.setattr(mcp_server, "_get_loader", lambda src: _ALotsLoader)
    out = _call(["600519.SH"])
    assert "_provenance" in out
    assert out["_provenance"]["600519.SH"]["volume_unit"] == "lots"


def test_mcp_get_market_data_row_shape_unchanged(monkeypatch):
    """The fix must not alter the per-symbol row payload itself, only add
    the additive _provenance key alongside it."""
    monkeypatch.setattr(mcp_server, "_get_loader", lambda src: _ALotsLoader)
    out = _call(["600519.SH"])
    assert out["600519.SH"] == [
        {
            "trade_date": "2026-05-01T00:00:00",
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 100.0,
        }
    ]
