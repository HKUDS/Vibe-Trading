from __future__ import annotations

from decimal import Decimal

import pytest

from src.portfolio.config import PortfolioSettingsStore
from src.portfolio.normalization import normalize_position
from src.portfolio.service import PORTFOLIO_VALUATION_VERSION, PortfolioService
from src.portfolio.store import PortfolioStore
from src.trading.connectors.futu import sdk as futu_sdk

USD_CNY = Decimal("7")
USD_HKD = Decimal("8")
SNAPSHOT_AT = "2000-01-01T00:00:00+00:00"


def _settings_store(tmp_path) -> PortfolioSettingsStore:
    settings = PortfolioSettingsStore(tmp_path / "portfolio.json")
    settings.connection_store.ensure(
        "futu-test",
        "futu-live-sdk-readonly",
        "Synthetic Futu",
    )
    settings.save(
        {
            "display_currency": "USD",
            "sources": [
                {
                    "connection_id": "futu-test",
                    "label": "Synthetic Futu",
                    "order": 0,
                }
            ],
        }
    )
    return settings


def _service(tmp_path, account: dict, position: dict) -> PortfolioService:
    return PortfolioService(
        PortfolioStore(tmp_path / "portfolio.sqlite3"),
        settings_store=_settings_store(tmp_path),
        get_account=lambda profile_id: {"assets": [account]},
        get_positions=lambda profile_id: {"positions": [position]},
        get_quote=lambda *args, **kwargs: {},
        fx_fetcher=lambda: (USD_CNY, USD_HKD, SNAPSHOT_AT),
    )


def test_futu_hkd_position_and_account_total_are_converted_to_usd(tmp_path) -> None:
    account = futu_sdk._account_to_dict(
        {
            "total_assets": "1600",
            "cash": "800",
            "market_val": "800",
            "currency": "HKD",
        }
    )
    position = futu_sdk._position_to_dict(
        {
            "code": "HK.SYNTH",
            "qty": "100",
            "cost_price": "10",
            "market_val": "800",
            "pl_val": "-200",
            "position_market": "HK",
            "currency": "HKD",
        }
    )

    snapshot = _service(tmp_path, account, position).refresh()
    holding = snapshot["positions"][0]

    assert holding["symbol"] == "HK.SYNTH"
    assert holding["market"] == "HK"
    assert holding["currency"] == "HKD"
    assert holding["price_currency"] == "HKD"
    assert holding["market_value_usd"] == pytest.approx(100.0)
    assert holding["market_value_cny"] == pytest.approx(700.0)
    assert holding["unrealized_pnl_usd"] == pytest.approx(-25.0)
    assert snapshot["totals"]["usd"] == pytest.approx(200.0)
    assert snapshot["totals"]["cny"] == pytest.approx(1400.0)


def test_futu_hk_prefix_infers_hkd_when_currency_is_missing() -> None:
    row = normalize_position(
        "futu",
        {
            "code": "HK.SYNTH",
            "qty": 100,
            "cost_price": 10,
            "market_val": 800,
        },
    )

    assert row["currency"] == "HKD"
    assert row["price_currency"] == "HKD"


def test_non_futu_hk_market_without_currency_keeps_usd_fallback() -> None:
    row = normalize_position(
        "examplebroker",
        {
            "symbol": "SYNTHETIC",
            "market": "HK",
            "quantity": 2,
            "market_price": 10,
        },
    )

    assert row["currency"] == "USD"
    assert row["price_currency"] == "USD"


def test_legacy_valuation_snapshots_do_not_mix_with_current_history(tmp_path) -> None:
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")
    store.save_snapshot(
        {
            "snapshot_id": "legacy-v1",
            "created_at": "1999-12-31T23:00:00+00:00",
            "complete": True,
            "totals": {"usd": 1600.0, "cny": 11200.0},
            "accounts": [
                {
                    "source_id": "futu-test",
                    "broker": "futu",
                    "status": "ok",
                }
            ],
            "positions": [],
        }
    )
    account = futu_sdk._account_to_dict(
        {"total_assets": "1600", "cash": "800", "currency": "HKD"}
    )
    position = futu_sdk._position_to_dict(
        {
            "code": "HK.SYNTH",
            "qty": "100",
            "cost_price": "10",
            "market_val": "800",
            "position_market": "HK",
            "currency": "HKD",
        }
    )
    service = _service(tmp_path, account, position)

    assert service.latest() is None

    current = service.refresh()

    assert current["valuation_version"] == PORTFOLIO_VALUATION_VERSION
    assert [row["id"] for row in service.history()] == [current["snapshot_id"]]
    assert [row["id"] for row in store.history()] == [
        "legacy-v1",
        current["snapshot_id"],
    ]
