from decimal import Decimal

import pytest

from src.portfolio.compatibility import PortfolioContractError, ensure_supported_currencies
from src.portfolio.normalization import account_cash_native, account_total_native, value_position


def test_asistente_casa_allows_only_ars():
    account = {"account": {"currency": "ARS", "portfolio_value": 1000.0, "cash": 100.0}}
    rows = [{"currency": "ARS", "price_currency": "ARS"}]
    ensure_supported_currencies(rows, account, connector="asistente-casa")
    with pytest.raises(PortfolioContractError):
        ensure_supported_currencies([{"currency": "USD", "price_currency": "USD"}], account, connector="asistente-casa")


def test_native_ars_position_uses_canonical_source_market_value():
    row = {
        "currency": "ARS",
        "price_currency": "ARS",
        "quantity": 5410.0,
        "market_price": 8835.0,
        "source_market_value": 47797350.0,
    }
    valued = value_position(row, usd_hkd=Decimal("0"), usd_cny=Decimal("0"), native_currency="ARS")
    assert valued["native_currency"] == "ARS"
    assert valued["market_value_native"] == 47797350.0
    assert valued["market_value_usd"] is None
    assert valued["market_value_cny"] is None


def test_unknown_currency_fails_inside_valuation():
    row = {"currency": "BRL", "price_currency": "BRL", "quantity": 1, "market_price": 10}
    with pytest.raises(PortfolioContractError):
        value_position(row, usd_hkd=Decimal("7.8"), usd_cny=Decimal("7.2"))


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
    valued = value_position(row, usd_hkd=Decimal("7.8"), usd_cny=Decimal("7.2"))
    assert valued["market_value_usd"] == 1000.0
    assert "native_currency" not in valued


def test_legacy_hkd_position_still_converts_via_fx():
    row = {
        "currency": "HKD",
        "price_currency": "HKD",
        "quantity": 100,
        "market_price": 78,
    }
    valued = value_position(row, usd_hkd=Decimal("7.8"), usd_cny=Decimal("7.2"))
    assert valued["market_value_usd"] == 1000.0
