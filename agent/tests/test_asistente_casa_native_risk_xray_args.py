"""Regression gates for native-currency risk_xray_args (ported patch 005)."""

import pytest

from src.portfolio.service import PortfolioService


def _position(
    symbol: str,
    *,
    native_currency: str | None = None,
    market_value_native: float | None = None,
    market_value_usd: float | None = None,
):
    return {
        "symbol": symbol,
        "market": "US",
        "asset_type": "stock",
        "priced": True,
        "native_currency": native_currency,
        "market_value_native": market_value_native,
        "market_value_usd": market_value_usd,
    }


def test_risk_xray_args_use_single_native_currency_values():
    args = PortfolioService._risk_xray_args(
        [
            _position("AAPL.US", native_currency="ARS", market_value_native=60),
            _position("MSFT.US", native_currency="ARS", market_value_native=40),
        ]
    )

    assert args["symbols"] == ["AAPL.US", "MSFT.US"]
    assert args["weights"]["AAPL.US"] == pytest.approx(0.6)
    assert args["weights"]["MSFT.US"] == pytest.approx(0.4)


def test_risk_xray_args_preserve_legacy_usd_behavior():
    args = PortfolioService._risk_xray_args(
        [
            _position("AAPL.US", market_value_usd=75),
            _position("MSFT.US", market_value_usd=25),
        ]
    )

    assert args["symbols"] == ["AAPL.US", "MSFT.US"]
    assert args["weights"]["AAPL.US"] == pytest.approx(0.75)
    assert args["weights"]["MSFT.US"] == pytest.approx(0.25)


def test_risk_xray_args_fail_closed_for_mixed_valuation_bases():
    args = PortfolioService._risk_xray_args(
        [
            _position("AAPL.US", native_currency="ARS", market_value_native=60),
            _position("MSFT.US", market_value_usd=40),
        ]
    )

    assert args == {"symbols": [], "weights": {}}


def test_risk_xray_args_fail_closed_for_multiple_native_currencies():
    args = PortfolioService._risk_xray_args(
        [
            _position("AAPL.US", native_currency="ARS", market_value_native=60),
            _position("MSFT.US", native_currency="EUR", market_value_native=40),
        ]
    )

    assert args == {"symbols": [], "weights": {}}
