"""Tests for FXMacroData agent tools and MCP wrappers."""

from __future__ import annotations

import json
from typing import Any

from src.tools import build_registry
from src.tools import fxmacrodata_tools as tools_mod
from src.tools.fxmacrodata_tools import (
    FXMacroDataCatalogueTool,
    FXMacroDataIndicatorTool,
    FXMacroDataRatesTool,
)


FXMACRODATA_TOOL_NAMES = {
    "get_fxmacrodata_catalogue",
    "get_fxmacrodata_indicator",
    "get_fxmacrodata_release_calendar",
    "get_fxmacrodata_predictions",
    "get_fxmacrodata_cot",
    "get_fxmacrodata_commodities",
    "get_fxmacrodata_rate_differentials",
    "get_fxmacrodata_curves",
    "get_fxmacrodata_news",
    "get_fxmacrodata_market_sessions",
    "get_fxmacrodata_risk_sentiment",
}


def test_registry_exposes_fxmacrodata_tools() -> None:
    registry = build_registry()

    assert FXMACRODATA_TOOL_NAMES <= set(registry.tool_names)


def test_catalogue_tool_normalizes_currency_and_returns_envelope(monkeypatch) -> None:
    captured = {}

    def fake_catalogue(currency: str, *, include_coverage: bool):
        captured["currency"] = currency
        captured["include_coverage"] = include_coverage
        return {"catalogue": {"inflation": {"name": "Inflation"}}}

    monkeypatch.setattr(tools_mod.fxmd, "data_catalogue", fake_catalogue)

    out = json.loads(FXMacroDataCatalogueTool().execute(currency="usd", include_coverage=False))

    assert out["ok"] is True
    assert out["source"] == "fxmacrodata"
    assert out["endpoint"] == "/data_catalogue/usd"
    assert out["data"]["catalogue"]["inflation"]["name"] == "Inflation"
    assert captured == {"currency": "USD", "include_coverage": False}


def test_indicator_tool_does_not_echo_secrets(monkeypatch) -> None:
    def fake_indicator(currency: str, indicator: str, **kwargs):
        assert currency == "USD"
        assert indicator == "inflation"
        return {"data": [{"date": "2024-01-01", "value": 3.2}]}

    monkeypatch.setenv("FXMD_API_KEY", "fxmd-secret-value")
    monkeypatch.setattr(tools_mod.fxmd, "indicator", fake_indicator)

    raw = FXMacroDataIndicatorTool().execute(
        currency="usd",
        indicator="Inflation",
        limit=5,
    )
    out = json.loads(raw)

    assert out["ok"] is True
    assert out["endpoint"] == "/announcements/usd/inflation"
    assert "fxmd-secret-value" not in raw


def test_tool_errors_are_json_envelopes(monkeypatch) -> None:
    monkeypatch.setattr(
        tools_mod.fxmd,
        "data_catalogue",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("upstream 500")),
    )

    out = json.loads(FXMacroDataCatalogueTool().execute(currency="usd"))

    assert out["ok"] is False
    assert out["source"] == "fxmacrodata"
    assert out["endpoint"] == "/data_catalogue/usd"
    assert "upstream 500" in out["error"]


def test_rates_tool_switches_forward_endpoint(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_forward(base: str, quote: str, **kwargs):
        captured["base"] = base
        captured["quote"] = quote
        captured["kwargs"] = kwargs
        return {"data": [{"date": "2024-01-01", "value": 0.25}]}

    monkeypatch.setattr(tools_mod.fxmd, "forward_differentials", fake_forward)

    out = json.loads(
        FXMacroDataRatesTool().execute(base="eur", quote="usd", forward=True, limit=3)
    )

    assert out["ok"] is True
    assert out["endpoint"] == "/forward_differentials/eur/usd"
    assert captured["base"] == "EUR"
    assert captured["quote"] == "USD"
    assert captured["kwargs"]["limit"] == 3


def test_mcp_wrappers_delegate_to_registry(monkeypatch) -> None:
    import mcp_server

    calls = []

    class _Registry:
        def execute(self, name: str, params: dict[str, Any]) -> str:
            calls.append((name, params))
            return json.dumps({"ok": True, "tool": name, "params": params})

    monkeypatch.setattr(mcp_server, "_get_registry", lambda: _Registry())

    fn = getattr(
        mcp_server.get_fxmacrodata_indicator,
        "fn",
        getattr(mcp_server.get_fxmacrodata_indicator, "__wrapped__", mcp_server.get_fxmacrodata_indicator),
    )
    raw = fn(currency="usd", indicator="inflation", limit=7)
    out = json.loads(raw)

    assert out["tool"] == "get_fxmacrodata_indicator"
    assert calls == [
        (
            "get_fxmacrodata_indicator",
            {
                "currency": "usd",
                "indicator": "inflation",
                "start_date": None,
                "end_date": None,
                "limit": 7,
                "seasonality": None,
                "frequency": None,
                "revisions": None,
                "basis": None,
            },
        )
    ]
