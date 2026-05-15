"""Unit tests for MarketDataTool — the first-class entrypoint for price/OHLCV.

Risk level 3: this tool is the deterministic dispatch path that prevents the
agent from hallucinating a skill or falling back to web_search for market data.

All tests are offline. The ccxt/yfinance/akshare providers are monkeypatched.
"""

from __future__ import annotations

import json
from typing import Any

import pytest


@pytest.mark.unit
def test_tool_is_registered() -> None:
    from src.tools import build_registry

    registry = build_registry()
    assert registry.get("get_market_data") is not None, (
        "MarketDataTool must be discovered by the auto-registry."
    )


@pytest.mark.unit
def test_normalize_btc_usdt_variants(monkeypatch) -> None:
    from src.tools.market_data_tool import MarketDataTool

    tool = MarketDataTool()
    captured: dict[str, str] = {}

    def fake_fetch_ccxt(symbol: str, timeframe: str, limit: int) -> dict[str, Any]:
        captured["symbol"] = symbol
        return {"current_price": 1.0, "candles": []}

    monkeypatch.setattr(tool, "_fetch_ccxt", fake_fetch_ccxt)

    for variant in ("BTC-USDT", "BTC/USDT", "BTCUSDT"):
        captured.clear()
        result = json.loads(tool.execute(symbol=variant))
        assert result.get("status") == "ok", f"{variant} -> {result}"
        assert captured["symbol"] == "BTC/USDT", (
            f"{variant} normalized to {captured['symbol']!r}, expected 'BTC/USDT'"
        )


@pytest.mark.unit
def test_normalize_invalid_symbol_returns_sanitized_error() -> None:
    from src.tools.market_data_tool import MarketDataTool

    tool = MarketDataTool()
    result = json.loads(tool.execute(symbol="!!!garbage!!!"))

    assert result["status"] == "error"
    assert "symbol" in result["error"].lower()
    assert "exception" not in result["error"].lower()
    assert "traceback" not in result["error"].lower()


@pytest.mark.unit
def test_provider_routing_crypto_uses_ccxt(monkeypatch) -> None:
    from src.tools.market_data_tool import MarketDataTool

    tool = MarketDataTool()
    called: list[str] = []

    monkeypatch.setattr(tool, "_fetch_ccxt", lambda *a, **k: (called.append("ccxt"), {"current_price": 1.0, "candles": []})[1])
    monkeypatch.setattr(tool, "_fetch_yfinance", lambda *a, **k: (called.append("yfinance"), {"current_price": 1.0, "candles": []})[1])
    monkeypatch.setattr(tool, "_fetch_akshare", lambda *a, **k: (called.append("akshare"), {"current_price": 1.0, "candles": []})[1])

    json.loads(tool.execute(symbol="ETH-USDT"))
    assert called == ["ccxt"], f"crypto routing expected ccxt, got {called}"


@pytest.mark.unit
def test_provider_routing_hk_stock_uses_akshare(monkeypatch) -> None:
    from src.tools.market_data_tool import MarketDataTool

    tool = MarketDataTool()
    called: list[str] = []

    monkeypatch.setattr(tool, "_fetch_ccxt", lambda *a, **k: (called.append("ccxt"), {"current_price": 1.0, "candles": []})[1])
    monkeypatch.setattr(tool, "_fetch_yfinance", lambda *a, **k: (called.append("yfinance"), {"current_price": 1.0, "candles": []})[1])
    monkeypatch.setattr(tool, "_fetch_akshare", lambda *a, **k: (called.append("akshare"), {"current_price": 1.0, "candles": []})[1])

    json.loads(tool.execute(symbol="0700.HK"))
    assert called == ["akshare"], f"HK stock routing expected akshare, got {called}"


@pytest.mark.unit
def test_provider_routing_us_stock_uses_yfinance(monkeypatch) -> None:
    from src.tools.market_data_tool import MarketDataTool

    tool = MarketDataTool()
    called: list[str] = []

    monkeypatch.setattr(tool, "_fetch_ccxt", lambda *a, **k: (called.append("ccxt"), {"current_price": 1.0, "candles": []})[1])
    monkeypatch.setattr(tool, "_fetch_yfinance", lambda *a, **k: (called.append("yfinance"), {"current_price": 1.0, "candles": []})[1])
    monkeypatch.setattr(tool, "_fetch_akshare", lambda *a, **k: (called.append("akshare"), {"current_price": 1.0, "candles": []})[1])

    json.loads(tool.execute(symbol="AAPL"))
    assert called == ["yfinance"], f"US stock routing expected yfinance, got {called}"


@pytest.mark.unit
def test_provider_failure_returns_sanitized_error_no_web_fallback(monkeypatch) -> None:
    from src.tools.market_data_tool import MarketDataTool

    tool = MarketDataTool()

    def explode(*_a, **_k):
        raise RuntimeError("internal://proxy.local:8080/secret-path failed with token=ABC")

    monkeypatch.setattr(tool, "_fetch_ccxt", explode)

    result = json.loads(tool.execute(symbol="BTC-USDT"))

    assert result["status"] == "error"
    assert "secret-path" not in result["error"]
    assert "token=ABC" not in result["error"]
    assert "proxy.local" not in result["error"]
    assert "Traceback" not in result["error"]
    assert "web_search" not in result.get("error", "")
    assert "read_url" not in result.get("error", "")


@pytest.mark.unit
def test_explicit_provider_override(monkeypatch) -> None:
    from src.tools.market_data_tool import MarketDataTool

    tool = MarketDataTool()
    called: list[str] = []

    monkeypatch.setattr(tool, "_fetch_ccxt", lambda *a, **k: (called.append("ccxt"), {"current_price": 1.0, "candles": []})[1])
    monkeypatch.setattr(tool, "_fetch_yfinance", lambda *a, **k: (called.append("yfinance"), {"current_price": 1.0, "candles": []})[1])

    json.loads(tool.execute(symbol="BTC-USDT", provider="yfinance"))
    assert called == ["yfinance"], f"explicit provider override failed: {called}"


@pytest.mark.unit
def test_output_shape_includes_current_price_and_candles(monkeypatch) -> None:
    from src.tools.market_data_tool import MarketDataTool

    tool = MarketDataTool()
    monkeypatch.setattr(
        tool,
        "_fetch_ccxt",
        lambda *a, **k: {
            "current_price": 79216.58,
            "candles": [
                {"date": "2026-05-09", "open": 80193.18, "high": 81080.0, "low": 80129.85, "close": 80678.4, "volume": 7548.42},
            ],
        },
    )

    result = json.loads(tool.execute(symbol="BTC-USDT", limit=1))
    assert result["status"] == "ok"
    assert result["symbol"] == "BTC/USDT"
    assert result["provider"] == "ccxt"
    assert result["timeframe"] == "1d"
    assert result["current_price"] == 79216.58
    assert len(result["candles"]) == 1
    assert result["candles"][0]["close"] == 80678.4
