"""Tests for the FXMacroData REST client and backtest loader.

All HTTP and FXMacroData API calls are mocked at the module boundary. These
tests verify symbol routing, OHLCV normalization, auth header handling, and
batch resilience without touching the live service.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.loaders import fxmacrodata_client as client
from backtest.loaders import fxmacrodata_loader as loader_mod
from backtest.loaders.fxmacrodata_loader import DataLoader, parse_symbol
from src.config.accessor import reset_env_config


def _series_payload() -> dict:
    return {
        "data": [
            {"date": "2024-01-03", "value": "1.12"},
            {"date": "2024-01-02", "value": 1.11},
            {"date": "bad", "value": 99},
            {"date": "2024-01-04", "value": None},
        ]
    }


class TestClient:
    def test_headers_use_x_api_key_without_query_secret(self, monkeypatch):
        monkeypatch.setenv("FXMD_API_KEY", "fxmd-secret-value")
        monkeypatch.setenv("FXMACRODATA_API_BASE_URL", "https://example.test/api/v1/")
        captured = {}

        def fake_get_json(url, **kwargs):
            captured["url"] = url
            captured["params"] = kwargs.get("params")
            captured["headers"] = kwargs.get("headers")
            return {"ok": True}

        monkeypatch.setattr(client, "throttled_get_json", fake_get_json)

        assert client.forex("EUR", "USD", start_date="2024-01-01", end_date="") == {"ok": True}

        assert captured["url"] == "https://example.test/api/v1/forex/eur/usd"
        assert captured["headers"] == {"X-API-Key": "fxmd-secret-value"}
        assert captured["params"] == {"start_date": "2024-01-01"}
        assert "api_key" not in captured["params"]
        assert "fxmd-secret-value" not in captured["url"]

    def test_missing_key_sends_no_auth_header(self, monkeypatch):
        monkeypatch.delenv("FXMD_API_KEY", raising=False)
        captured = {}

        def fake_get_json(url, **kwargs):
            captured["headers"] = kwargs.get("headers")
            return {"ok": True}

        monkeypatch.setattr(client, "throttled_get_json", fake_get_json)
        client.market_sessions()

        assert captured["headers"] is None


class TestSymbolParsing:
    @pytest.mark.parametrize(
        "code,kind,base,quote,currency,indicator",
        [
            ("EUR/USD", "forex", "EUR", "USD", None, None),
            ("EURUSD", "forex", "EUR", "USD", None, None),
            ("EURUSD.FX", "forex", "EUR", "USD", None, None),
            ("fx:EUR/USD", "forex", "EUR", "USD", None, None),
            ("fxmd:forex:EUR/USD", "forex", "EUR", "USD", None, None),
            ("fxmd:commodity:gold", "commodity", None, None, None, "gold"),
            ("fxmd:indicator:USD:inflation", "indicator", None, None, "USD", "inflation"),
            ("fxmd:cot:JPY", "cot", None, None, "JPY", None),
            ("fxmd:risk_sentiment", "risk_sentiment", None, None, None, None),
            ("fxmd:rate_diff:EUR/USD:policy_rate", "rate_diff", "EUR", "USD", None, None),
            ("fxmd:forward_diff:EUR/USD", "forward_diff", "EUR", "USD", None, None),
        ],
    )
    def test_parse_symbol_formats(self, code, kind, base, quote, currency, indicator):
        parsed = parse_symbol(code)

        assert parsed.kind == kind
        assert parsed.base == base
        assert parsed.quote == quote
        assert parsed.currency == currency
        assert parsed.indicator == indicator

    def test_parse_rejects_unknown_format(self):
        with pytest.raises(ValueError):
            parse_symbol("AAPL.US")


class TestLoader:
    def test_available_only_with_key(self, monkeypatch):
        monkeypatch.delenv("FXMD_API_KEY", raising=False)
        reset_env_config()
        assert DataLoader().is_available() is False
        monkeypatch.setenv("FXMD_API_KEY", "secret")
        reset_env_config()
        assert DataLoader().is_available() is True
        monkeypatch.setenv("FXMD_API_KEY", "   ")
        reset_env_config()
        assert DataLoader().is_available() is False

    def test_fetch_forex_normalizes_to_ohlcv(self, monkeypatch):
        monkeypatch.setenv("FXMD_API_KEY", "secret")
        monkeypatch.setattr(loader_mod.client, "forex", lambda *args, **kwargs: _series_payload())

        out = DataLoader().fetch(["EUR/USD"], "2024-01-01", "2024-01-31")

        assert set(out) == {"EUR/USD"}
        df = out["EUR/USD"]
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert list(df.index) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
        assert df.index.name == "trade_date"
        assert df["close"].tolist() == [1.11, 1.12]
        assert df["volume"].tolist() == [0.0, 0.0]
        assert all(str(df[col].dtype) == "float64" for col in df.columns)

    def test_fetch_indicator_uses_currency_and_slug(self, monkeypatch):
        monkeypatch.setenv("FXMD_API_KEY", "secret")
        captured = {}

        def fake_indicator(currency, indicator, **kwargs):
            captured["currency"] = currency
            captured["indicator"] = indicator
            captured["kwargs"] = kwargs
            return _series_payload()

        monkeypatch.setattr(loader_mod.client, "indicator", fake_indicator)

        out = DataLoader().fetch(
            ["fxmd:indicator:usd:Inflation"],
            "2024-01-01",
            "2024-01-31",
        )

        assert "fxmd:indicator:usd:Inflation" in out
        assert captured["currency"] == "USD"
        assert captured["indicator"] == "inflation"
        assert captured["kwargs"]["start_date"] == "2024-01-01"
        assert captured["kwargs"]["end_date"] == "2024-01-31"

    def test_one_bad_symbol_does_not_abort_batch(self, monkeypatch):
        monkeypatch.setenv("FXMD_API_KEY", "secret")

        def fake_forex(base, quote, **kwargs):
            if base == "BAD":
                raise RuntimeError("boom")
            return _series_payload()

        monkeypatch.setattr(loader_mod.client, "forex", fake_forex)

        out = DataLoader().fetch(["BAD/USD", "EUR/USD"], "2024-01-01", "2024-01-31")

        assert set(out) == {"EUR/USD"}

    def test_empty_payload_is_omitted(self, monkeypatch):
        monkeypatch.setenv("FXMD_API_KEY", "secret")
        monkeypatch.setattr(loader_mod.client, "risk_sentiment", lambda **kwargs: {"data": []})

        assert DataLoader().fetch(["fxmd:risk_sentiment"], "2024-01-01", "2024-01-31") == {}
