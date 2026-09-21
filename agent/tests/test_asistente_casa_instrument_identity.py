"""Regression gates for canonical instrument identity transport (ported patch 006)."""

from src.portfolio.normalization import normalize_position, value_position


def test_asistente_casa_identity_survives_normalization_and_native_valuation():
    raw = {
        "symbol": "YPFD",
        "name": "YPF SA",
        "asset_type": "stock",
        "quantity": 10,
        "market_price": 1000,
        "price_currency": "ARS",
        "market_value": 10000,
        "source": "asistente_casa",
        "source_instrument_id": "accion:YPFD",
        "source_instrument_type": "ACCIONES",
        "isin": "ARP9897X1319",
        "market": "BYMA",
        "venue": "BYMA",
        "exposure_currency": "ARS",
    }
    normalized = normalize_position("asistente-casa", raw)
    valued = value_position(normalized, native_currency="ARS")

    assert valued["source_instrument_id"] == "accion:YPFD"
    assert valued["source_instrument_type"] == "ACCIONES"
    assert valued["isin"] == "ARP9897X1319"
    assert valued["market"] == "BYMA"
    assert valued["venue"] == "BYMA"
    assert valued["market_value_native"] == 10000.0
    assert valued["market_value_usd"] is None


def test_null_isin_and_unknown_venue_are_not_invented_for_fund():
    raw = {
        "symbol": "FONDO",
        "asset_type": "fund",
        "quantity": 1,
        "market_price": 100,
        "price_currency": "ARS",
        "market_value": 100,
        "source": "asistente_casa",
        "source_instrument_id": "fci:FONDO",
        "source_instrument_type": "FCI",
        "isin": None,
        "market": None,
    }
    normalized = normalize_position("asistente-casa", raw)
    assert normalized["isin"] is None
    assert normalized["market"] == ""
    assert normalized["venue"] is None


def test_cedear_does_not_reuse_underlying_isin():
    """CEDEARs must carry their own local-market identity, never the ISIN of
    the foreign underlying share they track."""
    raw = {
        "symbol": "AAPL",
        "name": "Apple Inc. CEDEAR",
        "asset_type": "stock",
        "quantity": 5,
        "market_price": 25000,
        "price_currency": "ARS",
        "market_value": 125000,
        "source": "asistente_casa",
        "source_instrument_id": "cedear:AAPL",
        "source_instrument_type": "CEDEARS",
        "isin": "ARDEUT111702",  # the CEDEAR's own local ISIN, not Apple's US ISIN
        "market": "BYMA",
        "venue": "BYMA",
        "exposure_currency": "USD",
    }
    normalized = normalize_position("asistente-casa", raw)
    assert normalized["isin"] == "ARDEUT111702"
    assert normalized["isin"] != "US0378331005"  # Apple's underlying US ISIN
    assert normalized["market"] == "BYMA"
