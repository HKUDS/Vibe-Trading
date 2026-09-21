"""Focused regression tests for the 2026-09-15 history-coverage customization.

Covers: 120-day default preserved, no hard max-lookback rejection, horizon
shorthands (1Y/YTD/since_inception), and the dedicated coverage tool used for
"since when do you have data" questions instead of a risk-xray default.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.tools import asistente_casa_portfolio_risk_tool as mod
from src.tools.asistente_casa_portfolio_risk_tool import (
    AsistenteCasaMarketHistoryCoverageTool,
    AsistenteCasaPortfolioRiskXrayTool,
)


def _portfolio_payload(symbols):
    return {
        "ok": True,
        "numeric_format": "json_number",
        "contract_version": "v1",
        "portfolio": {
            "positions": [
                {"symbol": s, "weight_scope": 1.0 / len(symbols), "name": s} for s in symbols
            ],
            "total_value_ars": 1000.0,
            "scope_value_ars": 1000.0,
        },
    }


def _history_payload(symbols, first_date, last_date):
    start = date.fromisoformat(first_date)
    end = date.fromisoformat(last_date)
    n_days = max((end - start).days, 1)
    obs = [
        {"date": (start + timedelta(days=i)).isoformat(), "close": 1.0 + 0.001 * i}
        for i in range(n_days + 1)
    ]
    return {
        "ok": True,
        "numeric_format": "json_number",
        "contract_version": "v1",
        "policy": "persisted_only",
        "interval": "1D",
        "complete": True,
        "series": {s: {"observations": obs} for s in symbols},
    }


def _coverage_payload(symbols, earliest_any, earliest_common, latest_common):
    return {
        "ok": True,
        "numeric_format": "json_number",
        "policy": "persisted_only",
        "complete": True,
        "unresolved_symbols": [],
        "symbols_without_history": [],
        "earliest_any_date": earliest_any,
        "earliest_common_date": earliest_common,
        "latest_common_date": latest_common,
        "series": {
            s: {
                "first_date": earliest_any if s == symbols[0] else earliest_common,
                "last_date": latest_common,
                "observation_count": 100,
            }
            for s in symbols
        },
    }


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ASISTENTE_CASA_BASE_URL", "http://asistente-casa.local")
    monkeypatch.setenv("ASISTENTE_CASA_API_KEY", "test-key")


def test_default_lookback_is_still_120_days(monkeypatch):
    calls = []

    def fake_get(base_url, api_key, path, params):
        calls.append((path, dict(params)))
        if path == "/inversiones/vibe/portfolio":
            return _portfolio_payload(["YPFD"])
        if path == "/inversiones/vibe/market-history":
            return _history_payload(["YPFD"], params["from"], params["to"])
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(mod, "_get", fake_get)
    tool = AsistenteCasaPortfolioRiskXrayTool()
    tool.execute(asset_type="ACCIONES")

    history_call = next(c for c in calls if c[0] == "/inversiones/vibe/market-history")
    end = date.today()
    expected_start = (end - timedelta(days=120)).isoformat()
    assert history_call[1]["from"] == expected_start
    assert history_call[1]["to"] == end.isoformat()


def test_explicit_long_range_no_longer_hard_capped(monkeypatch):
    def fake_get(base_url, api_key, path, params):
        if path == "/inversiones/vibe/portfolio":
            return _portfolio_payload(["YPFD"])
        if path == "/inversiones/vibe/market-history":
            return _history_payload(["YPFD"], params["from"], params["to"])
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(mod, "_get", fake_get)
    tool = AsistenteCasaPortfolioRiskXrayTool()
    result = tool.execute(asset_type="ACCIONES", start_date="2021-08-24", end_date="2026-09-15")

    import json
    payload = json.loads(result)
    assert payload["status"] == "ok"
    assert payload["meta"]["start_date"] == "2021-08-24"


def test_horizon_1y_and_ytd(monkeypatch):
    seen_ranges = []

    def fake_get(base_url, api_key, path, params):
        if path == "/inversiones/vibe/portfolio":
            return _portfolio_payload(["YPFD"])
        if path == "/inversiones/vibe/market-history":
            seen_ranges.append((params["from"], params["to"]))
            return _history_payload(["YPFD"], params["from"], params["to"])
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(mod, "_get", fake_get)
    tool = AsistenteCasaPortfolioRiskXrayTool()

    tool.execute(asset_type="ACCIONES", horizon="1Y", end_date="2026-09-15")
    tool.execute(asset_type="ACCIONES", horizon="YTD", end_date="2026-09-15")

    assert seen_ranges[0] == ("2025-09-15", "2026-09-15")
    assert seen_ranges[1] == ("2026-01-01", "2026-09-15")


def test_horizon_since_inception_uses_basket_common_coverage(monkeypatch):
    seen_ranges = []

    def fake_get(base_url, api_key, path, params):
        if path == "/inversiones/vibe/portfolio":
            return _portfolio_payload(["YPFD", "PAMP"])
        if path == "/inversiones/vibe/market-history/coverage":
            return _coverage_payload(["YPFD", "PAMP"], "2021-03-08", "2025-08-27", "2026-09-14")
        if path == "/inversiones/vibe/market-history":
            seen_ranges.append((params["from"], params["to"]))
            return _history_payload(["YPFD", "PAMP"], params["from"], params["to"])
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(mod, "_get", fake_get)
    tool = AsistenteCasaPortfolioRiskXrayTool()
    tool.execute(asset_type="ACCIONES", horizon="since_inception", end_date="2026-09-15")

    assert seen_ranges[0][0] == "2025-08-27"  # basket earliest_common_date, not any single ticker's first_date


def test_start_date_and_horizon_are_mutually_exclusive(monkeypatch):
    monkeypatch.setattr(mod, "_get", lambda *a, **k: pytest.fail("should not call Asistente Casa"))
    tool = AsistenteCasaPortfolioRiskXrayTool()
    result = tool.execute(asset_type="ACCIONES", start_date="2026-01-01", horizon="YTD")
    import json
    payload = json.loads(result)
    assert payload["status"] == "error"
    assert "mutually exclusive" in payload["error"]


def test_coverage_tool_reports_individual_and_common_dates_without_downloading_prices(monkeypatch):
    calls = []

    def fake_get(base_url, api_key, path, params):
        calls.append(path)
        if path == "/inversiones/vibe/portfolio":
            return _portfolio_payload(["YPFD", "PAMP"])
        if path == "/inversiones/vibe/market-history/coverage":
            return _coverage_payload(["YPFD", "PAMP"], "2021-08-24", "2021-08-24", "2026-09-14")
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(mod, "_get", fake_get)
    tool = AsistenteCasaMarketHistoryCoverageTool()
    result = tool.execute(asset_type="ACCIONES")

    import json
    payload = json.loads(result)
    assert payload["status"] == "ok"
    assert "/inversiones/vibe/market-history" not in calls  # never downloads OHLC rows
    assert payload["scopes"]["ACCIONES"]["earliest_any_date"] == "2021-08-24"
    assert payload["scopes"]["ACCIONES"]["earliest_common_date"] == "2021-08-24"
    assert payload["scopes"]["ACCIONES"]["series"]["YPFD"]["first_date"] == "2021-08-24"


def test_coverage_tool_distinguishes_individual_vs_common_for_cedears(monkeypatch):
    def fake_get(base_url, api_key, path, params):
        if path == "/inversiones/vibe/portfolio":
            return _portfolio_payload(["GPRK", "MU"])
        if path == "/inversiones/vibe/market-history/coverage":
            return _coverage_payload(["GPRK", "MU"], "2021-03-08", "2025-08-27", "2026-09-14")
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(mod, "_get", fake_get)
    tool = AsistenteCasaMarketHistoryCoverageTool()
    import json
    payload = json.loads(tool.execute(asset_type="CEDEARS"))

    scope = payload["scopes"]["CEDEARS"]
    assert scope["earliest_any_date"] == "2021-03-08"   # oldest individual (GPRK)
    assert scope["earliest_common_date"] == "2025-08-27"  # common to the whole basket
    assert scope["earliest_any_date"] != scope["earliest_common_date"]


def test_coverage_tool_without_asset_type_covers_both_scopes(monkeypatch):
    def fake_get(base_url, api_key, path, params):
        if path == "/inversiones/vibe/portfolio":
            symbols = ["YPFD"] if params["asset_type"] == "ACCIONES" else ["GPRK"]
            return _portfolio_payload(symbols)
        if path == "/inversiones/vibe/market-history/coverage":
            symbols = params["symbols"].split(",")
            first = "2021-08-24" if params["asset_type"] == "ACCIONES" else "2021-03-08"
            return _coverage_payload(symbols, first, first, "2026-09-14")
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(mod, "_get", fake_get)
    tool = AsistenteCasaMarketHistoryCoverageTool()
    import json
    payload = json.loads(tool.execute())

    assert set(payload["scopes"].keys()) == {"ACCIONES", "CEDEARS"}
    assert payload["overall"]["earliest_any_date"] == "2021-03-08"
    assert payload["overall"]["latest_any_date"] == "2026-09-14"


def test_no_padding_when_since_inception_coverage_missing(monkeypatch):
    def fake_get(base_url, api_key, path, params):
        if path == "/inversiones/vibe/portfolio":
            return _portfolio_payload(["YPFD"])
        if path == "/inversiones/vibe/market-history/coverage":
            return _coverage_payload(["YPFD"], None, None, None)
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(mod, "_get", fake_get)
    tool = AsistenteCasaPortfolioRiskXrayTool()
    import json
    payload = json.loads(tool.execute(asset_type="ACCIONES", horizon="since_inception"))
    assert payload["status"] == "error"
    assert "earliest_common_date" in payload["error"]
