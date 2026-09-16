"""Regression gates for canonical Asistente Casa risk routing (ported patches 007+008)."""

import json

import pytest

from src.portfolio.service import PortfolioService
from src.tools import portfolio_risk_tool as risk_module
from src.tools.portfolio_risk_tool import PortfolioRiskXrayTool


def _ac_position(symbol, value, *, instrument_type="ACCIONES", market="BYMA", isin="ARP9897X1319"):
    return {
        "broker": "asistente-casa",
        "symbol": symbol,
        "asset_type": "stock" if instrument_type != "FCI" else "fund",
        "priced": True,
        "native_currency": "ARS",
        "market_value_native": value,
        "market_value_usd": None,
        "source_instrument_id": f"{instrument_type.lower()}:{symbol}",
        "source_instrument_type": instrument_type,
        "market": market,
        "isin": isin,
    }


def test_ac_risk_args_keep_bare_symbols_and_select_canonical_history_source():
    args = PortfolioService._risk_xray_args([_ac_position("YPFD", 60), _ac_position("VIST", 40, isin="ARBCOM4602V2")])
    assert args["symbols"] == ["YPFD", "VIST"]
    assert args["weights"]["YPFD"] == pytest.approx(0.6)
    assert args["weights"]["VIST"] == pytest.approx(0.4)
    assert args["source"] == "asistente-casa"


def test_ac_fci_requires_canonical_fci_identity_but_no_invented_isin_or_market():
    args = PortfolioService._risk_xray_args([
        _ac_position("SBS.FIXUSD.FPN", 100, instrument_type="FCI", market="", isin="")
    ])
    assert args["symbols"] == ["SBS.FIXUSD.FPN"]
    assert args["source"] == "asistente-casa"


def test_ac_security_without_identity_evidence_is_not_routed():
    row = _ac_position("YPFD", 100)
    row["isin"] = None
    assert PortfolioService._risk_xray_args([row]) == {"symbols": [], "weights": {}}


def test_mixed_ac_and_generic_market_sources_fail_closed():
    legacy = {
        "broker": "ibkr",
        "symbol": "AAPL.US",
        "market": "US",
        "asset_type": "stock",
        "priced": True,
        "native_currency": "ARS",
        "market_value_native": 50,
        "market_value_usd": None,
    }
    assert PortfolioService._risk_xray_args([_ac_position("YPFD", 50), legacy]) == {"symbols": [], "weights": {}}


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_ac_history_reader_uses_persisted_endpoint_and_json_numbers(monkeypatch):
    monkeypatch.setenv("ASISTENTE_CASA_BASE_URL", "http://ac.local")
    monkeypatch.setenv("ASISTENTE_CASA_API_KEY", "secret")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["key"] = request.headers.get("X-vibe-api-key")
        return _Response({
            "ok": True,
            "numeric_format": "json_number",
            "policy": "persisted_only",
            "interval": "1D",
            "complete": True,
            "unresolved_symbols": [],
            "unsafe_symbols": [],
            "symbols_without_history": [],
            "series": {
                "YPFD": {
                    "observations": [
                        {"date": "2026-09-10", "close": 8800.0},
                        {"date": "2026-09-11", "close": 8835.0},
                    ]
                }
            },
        })

    monkeypatch.setattr(risk_module, "urlopen", fake_urlopen)
    raw = risk_module._fetch_asistente_casa_history(
        codes=["YPFD"], start_date="2026-09-10", end_date="2026-09-11", interval="1D"
    )
    assert raw["YPFD"][1]["close"] == 8835.0
    assert raw["_unresolved"] == []
    assert "/inversiones/vibe/market-history?" in captured["url"]
    assert "symbols=YPFD" in captured["url"]
    assert captured["key"] == "secret"


def test_ac_history_reader_fails_closed_on_incomplete_basket(monkeypatch):
    monkeypatch.setenv("ASISTENTE_CASA_BASE_URL", "http://ac.local")
    monkeypatch.setenv("ASISTENTE_CASA_API_KEY", "secret")

    def fake_urlopen(request, timeout):
        return _Response({
            "ok": True,
            "numeric_format": "json_number",
            "policy": "persisted_only",
            "interval": "1D",
            "complete": False,
            "unresolved_symbols": ["VIST"],
            "series": {"YPFD": {"observations": [{"date": "2026-09-11", "close": 8835.0}]}},
        })

    monkeypatch.setattr(risk_module, "urlopen", fake_urlopen)
    with pytest.raises(ValueError):
        risk_module._fetch_asistente_casa_history(
            codes=["YPFD", "VIST"], start_date="2026-09-10", end_date="2026-09-11", interval="1D"
        )


def test_ac_history_reader_rejects_missing_environment(monkeypatch):
    monkeypatch.delenv("ASISTENTE_CASA_BASE_URL", raising=False)
    monkeypatch.delenv("ASISTENTE_CASA_API_KEY", raising=False)
    with pytest.raises(ValueError):
        risk_module._fetch_asistente_casa_history(
            codes=["YPFD"], start_date="2026-09-10", end_date="2026-09-11", interval="1D"
        )


def test_tool_source_asistente_casa_never_calls_generic_market_fetcher(monkeypatch):
    def forbidden_fetch(**kwargs):
        raise AssertionError("generic fetch_market_data must not be called")

    monkeypatch.setattr(
        risk_module,
        "_fetch_asistente_casa_history",
        lambda **kwargs: {
            "YPFD": [{"close": 8700.0 + i} for i in range(35)],
            "_unresolved": [],
        },
    )
    tool = PortfolioRiskXrayTool(data_fetcher=forbidden_fetch)
    out = json.loads(tool.execute(
        symbols=["YPFD"],
        weights={"YPFD": 1.0},
        start_date="2026-09-09",
        end_date="2026-09-12",
        source="asistente-casa",
    ))
    assert out["status"] == "ok"
    assert out["meta"]["source"] == "asistente-casa"
