"""Regression gates for canonical sector metadata transport (ported patch 014)."""

from src.portfolio.normalization import normalize_position


def test_asistente_casa_sector_metadata_survives_normalization():
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
        "sector": "Energia",
        "industry": "Petróleo y gas",
        "country": "Argentina",
        "source_asset_class": "Acciones Argentina",
        "classification_source": "override",
        "sector_constraint_eligible": True,
        "sector_metadata_policy": "ac_deterministic_v1",
    }
    normalized = normalize_position("asistente-casa", raw)
    assert normalized["sector"] == "Energia"
    assert normalized["industry"] == "Petróleo y gas"
    assert normalized["country"] == "Argentina"
    assert normalized["source_asset_class"] == "Acciones Argentina"
    assert normalized["classification_source"] == "override"
    assert normalized["sector_constraint_eligible"] is True
    assert normalized["sector_metadata_policy"] == "ac_deterministic_v1"


def test_fund_metadata_is_visible_but_not_sector_constraint_eligible():
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
        "sector": "Fondo de Inversión",
        "industry": None,
        "country": "Argentina",
        "source_asset_class": "FCI",
        "classification_source": "ppi",
        "sector_constraint_eligible": False,
        "sector_metadata_policy": "ac_deterministic_v1",
    }
    normalized = normalize_position("asistente-casa", raw)
    assert normalized["sector"] == "Fondo de Inversión"
    assert normalized["sector_constraint_eligible"] is False
    assert normalized["classification_source"] == "ppi"
