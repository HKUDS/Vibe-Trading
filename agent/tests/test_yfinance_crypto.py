"""Tests for yfinance loader crypto support: symbol conversion and market registration."""

from __future__ import annotations

import pytest

from backtest.loaders.yfinance_loader import DataLoader, _to_yfinance_symbol


# ---------------------------------------------------------------------------
# _to_yfinance_symbol — crypto conversions
# ---------------------------------------------------------------------------


class TestToYfinanceSymbolCrypto:
    def test_usdt_suffix_converted_to_usd(self) -> None:
        assert _to_yfinance_symbol("BTC-USDT") == "BTC-USD"

    def test_usdc_suffix_converted_to_usd(self) -> None:
        assert _to_yfinance_symbol("ETH-USDC") == "ETH-USD"

    def test_lowercase_normalized(self) -> None:
        assert _to_yfinance_symbol("sol-usdt") == "SOL-USD"

    def test_existing_usd_pair_unchanged(self) -> None:
        assert _to_yfinance_symbol("BTC-USD") == "BTC-USD"

    def test_non_crypto_symbol_unchanged(self) -> None:
        assert _to_yfinance_symbol("AAPL") == "AAPL"

    def test_hk_symbol_converted(self) -> None:
        assert _to_yfinance_symbol("0700.HK") == "0700.HK"

    def test_us_suffix_stripped(self) -> None:
        assert _to_yfinance_symbol("AAPL.US") == "AAPL"

    def test_whitespace_stripped(self) -> None:
        assert _to_yfinance_symbol("  BTC-USDT  ") == "BTC-USD"


# ---------------------------------------------------------------------------
# DataLoader — crypto market registration
# ---------------------------------------------------------------------------


class TestDataLoaderCryptoMarket:
    def test_crypto_in_markets(self) -> None:
        assert "crypto" in DataLoader.markets

    def test_us_equity_still_supported(self) -> None:
        assert "us_equity" in DataLoader.markets

    def test_hk_equity_still_supported(self) -> None:
        assert "hk_equity" in DataLoader.markets

    def test_does_not_require_auth(self) -> None:
        assert DataLoader.requires_auth is False

    def test_is_available(self) -> None:
        """yfinance should be available if the package is installed."""
        loader = DataLoader()
        assert loader.is_available() is True
