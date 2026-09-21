from decimal import Decimal

import pytest

from src.portfolio.compatibility import PortfolioContractError, ensure_supported_currencies
from src.portfolio.fx import build_rates
from src.portfolio.normalization import account_cash_native, account_total_native, value_position


def _rates():
    return build_rates(Decimal("7.2"), Decimal("7.8"))


def test_iso_currency_identity_accepts_ars_without_fx_and_rejects_invalid_code():
    account = {"account": {"currency": "ARS", "portfolio_value": 1000.0, "cash": 100.0}}
    rows = [{"currency": "ARS", "price_currency": "ARS"}]

    # #1510 separates currency identity from FX availability: ARS is valid
    # metadata even though the production rates map has no ARS conversion.
    ensure_supported_currencies(rows, account)

    with pytest.raises(PortfolioContractError, match="valid ISO-4217"):
        ensure_supported_currencies(
            [{"currency": "ZZZ", "price_currency": "ZZZ"}],
            {"account": {"currency": "ZZZ"}},
        )


def test_native_ars_position_uses_canonical_source_market_value():
    row = {
        "currency": "ARS",
        "price_currency": "ARS",
        "quantity": 5410.0,
        "market_price": 8835.0,
        "source_market_value": 47797350.0,
    }
    valued = value_position(row, native_currency="ARS")
    assert valued["native_currency"] == "ARS"
    assert valued["market_value_native"] == 47797350.0
    assert valued["market_value_usd"] is None
    assert valued["market_value_cny"] is None


def test_unrated_iso_currency_fails_inside_converted_valuation():
    row = {"currency": "BRL", "price_currency": "BRL", "quantity": 1, "market_price": 10}
    with pytest.raises(PortfolioContractError, match="BRL"):
        value_position(row, rates=_rates())


def test_native_account_total_and_cash_do_not_use_fx():
    account = {"account": {"currency": "ARS", "portfolio_value": 228064538.23, "cash": 1436455.455}}
    assert account_total_native("asistente-casa", account, currency="ARS") == Decimal("228064538.23")
    assert account_cash_native("asistente-casa", account, currency="ARS") == Decimal("1436455.455")


def test_legacy_usd_position_unaffected_by_native_path():
    row = {
        "currency": "USD",
        "price_currency": "USD",
        "quantity": 10,
        "market_price": 100,
        "cost_price": 90,
    }
    valued = value_position(row, rates=_rates())
    assert valued["market_value_usd"] == 1000.0
    assert "native_currency" not in valued


def test_legacy_hkd_position_still_converts_via_fx():
    row = {
        "currency": "HKD",
        "price_currency": "HKD",
        "quantity": 100,
        "market_price": 78,
    }
    valued = value_position(row, rates=_rates())
    assert valued["market_value_usd"] == 1000.0
