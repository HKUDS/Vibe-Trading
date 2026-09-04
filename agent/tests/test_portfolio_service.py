from __future__ import annotations

import socket
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.portfolio import service as portfolio_service
from src.portfolio.config import PortfolioSettingsStore
from src.portfolio.normalization import auth_metadata
from src.portfolio.service import PortfolioService
from src.portfolio.store import PortfolioStore
from src.trading.types import TradingProfile


def _settings_store(tmp_path):
    store = PortfolioSettingsStore(tmp_path / "portfolio.json")
    store.connection_store.ensure("ibkr", "ibkr-live-local-readonly", "IBKR")
    store.connection_store.ensure("longbridge", "longbridge-live-sdk-readonly", "Longbridge")
    store.connection_store.ensure("binance", "binance-live-sdk-readonly", "Binance")
    store.save(
        {
            "display_currency": "USD",
            "sources": [
                {"connection_id": "ibkr", "label": "IBKR", "order": 0},
                {"connection_id": "longbridge", "label": "Longbridge", "order": 1},
                {"connection_id": "binance", "label": "Binance", "order": 2},
            ],
        }
    )
    return store


def test_refresh_aggregates_three_readonly_connectors(tmp_path):
    accounts = {
        "ibkr-live-local-readonly": {"summary": [{"tag": "NetLiquidation", "value": "1000", "currency": "USD"}]},
        "longbridge-live-sdk-readonly": {"balances": [{"net_assets": "7800", "currency": "HKD"}]},
        "binance-live-sdk-readonly": {"balances": []},
    }
    positions = {
        "ibkr-live-local-readonly": {
            "positions": [
                {
                    "symbol": "AAPL",
                    "sec_type": "STK",
                    "exchange": "SMART",
                    "currency": "USD",
                    "position": 2,
                    "avg_cost": 100,
                }
            ]
        },
        "longbridge-live-sdk-readonly": {
            "positions": [
                {
                    "symbol": "700.HK",
                    "symbol_name": "Tencent",
                    "quantity": 10,
                    "cost_price": 300,
                    "currency": "HKD",
                    "market": "HK",
                }
            ]
        },
        "binance-live-sdk-readonly": {
            "positions": [
                {"symbol": "BTC", "quantity": 0.1, "free": 0.1, "used": 0},
                {"symbol": "USDT", "quantity": 50, "free": 50, "used": 0},
            ]
        },
    }

    def get_account(profile_id):
        return accounts[profile_id]

    def get_positions(profile_id):
        return positions[profile_id]

    def get_quote(symbol, profile_id, **kwargs):
        prices = {"AAPL": 150, "700.HK": 390, "BTC/USDT": 60000}
        return {"quote": {"last": prices[symbol]}}

    service = PortfolioService(
        PortfolioStore(tmp_path / "portfolio.sqlite3"),
        settings_store=_settings_store(tmp_path),
        get_account=get_account,
        get_positions=get_positions,
        get_quote=get_quote,
        fx_fetcher=lambda: (
            Decimal("7.2"),
            Decimal("7.8"),
            "2026-08-09T00:00:00+00:00",
        ),
    )
    snapshot = service.refresh()

    assert snapshot["complete"] is True
    assert snapshot["totals"]["usd"] == 8050.0
    assert len(snapshot["positions"]) == 4
    assert snapshot["positions"][0]["symbol"] == "BTC"
    assert len(snapshot["combined_holdings"]) == 4
    assert service.latest()["snapshot_id"] == snapshot["snapshot_id"]
    assert len(service.history()) == 1
    assert "broker,symbol" in service.export_csv()
    context = service.analysis_context()
    assert context["privacy"].startswith("No account numbers")
    assert "quantity" not in context["holdings"][0]


def test_latest_enriches_legacy_snapshot_with_current_compatibility(tmp_path):
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")
    settings = _settings_store(tmp_path)
    store.save_snapshot(
        {
            "snapshot_id": "legacy-snapshot",
            "valuation_version": portfolio_service.PORTFOLIO_VALUATION_VERSION,
            "created_at": "2026-08-09T00:00:00+00:00",
            "complete": True,
            "totals": {"usd": 0, "cny": 0},
            "accounts": [
                {"source_id": source, "broker": source, "status": "ok"} for source in ("ibkr", "longbridge", "binance")
            ],
            "positions": [],
            "warnings": [],
        }
    )

    latest = PortfolioService(store, settings_store=settings).latest()

    assert latest is not None
    assert {row["portfolio_compatibility"]["level"] for row in latest["accounts"]} == {"native"}


def test_partial_refresh_is_saved_and_marked_incomplete(tmp_path):
    def get_account(profile_id):
        if profile_id.startswith("longbridge"):
            raise ConnectionError("offline")
        return {"summary": []}

    service = PortfolioService(
        PortfolioStore(tmp_path / "portfolio.sqlite3"),
        settings_store=_settings_store(tmp_path),
        get_account=get_account,
        get_positions=lambda profile_id: {"positions": []},
        get_quote=lambda *args, **kwargs: {},
        fx_fetcher=lambda: (
            Decimal("7.2"),
            Decimal("7.8"),
            "2026-08-09T00:00:00+00:00",
        ),
    )

    snapshot = service.refresh()
    assert snapshot["complete"] is False
    assert any("longbridge" in warning.lower() for warning in snapshot["warnings"])


def test_failed_source_is_excluded_from_totals_and_reports_its_last_success(tmp_path):
    """A source that fails contributes nothing; only its last-healthy time survives."""
    offline = False

    def get_account(profile_id):
        if offline and profile_id.startswith("ibkr"):
            raise ConnectionError("offline")
        if profile_id.startswith("ibkr"):
            return {"summary": [{"tag": "NetLiquidation", "value": "1000", "currency": "USD"}]}
        return {"summary": []}

    service = PortfolioService(
        PortfolioStore(tmp_path / "portfolio.sqlite3"),
        settings_store=_settings_store(tmp_path),
        get_account=get_account,
        get_positions=lambda profile_id: {
            "positions": (
                [
                    {
                        "symbol": "AAPL",
                        "sec_type": "STK",
                        "exchange": "SMART",
                        "currency": "USD",
                        "position": 2,
                        "avg_cost": 100,
                    }
                ]
                if profile_id.startswith("ibkr")
                else []
            ),
        },
        get_quote=lambda *args, **kwargs: {"quote": {"last": 150}},
        fx_fetcher=lambda: (
            Decimal("7.2"),
            Decimal("7.8"),
            "2026-08-09T00:00:00+00:00",
        ),
    )
    complete = service.refresh()
    offline = True
    partial = service.refresh()

    ibkr = next(item for item in partial["accounts"] if item["broker"] == "ibkr")
    assert complete["complete"] is True
    assert complete["totals"]["usd"] == 1000.0

    # The failed source is an error, not a quietly shorter portfolio: its cached
    # value is never added back into any aggregate.
    assert partial["complete"] is False
    assert partial["totals"]["usd"] == 0.0
    assert partial["totals"]["cny"] == 0.0
    assert ibkr["status"] == "error"
    assert ibkr["error_code"] == "ConnectionError"
    assert ibkr["failure_kind"] == "transient"
    assert ibkr["reconnect_required"] is False
    assert ibkr["total_usd"] is None
    assert ibkr["total_cny"] is None
    assert ibkr["position_count"] == 0
    assert [item["broker"] for item in partial["positions"] if item["broker"] == "ibkr"] == []
    assert [item for item in partial["combined_holdings"] if "ibkr" in item["brokers"]] == []
    assert partial["valuation"]["priced_usd"] == 0.0

    # ...but the dashboard can still say when that source was last healthy.
    assert ibkr["last_success_at"] == complete["created_at"]

    # No account carries the removed cached/stale state.
    assert {item["status"] for item in partial["accounts"]} == {"ok", "error"}
    assert all("data_state" not in item for item in partial["accounts"])
    assert all("stale" not in item for item in partial["positions"])

    excluded = [warning for warning in partial["warnings"] if "excluded" in warning.lower()]
    assert len(excluded) == 1
    assert "IBKR" in excluded[0]

    assert [item["id"] for item in service.history()] == [complete["snapshot_id"]]
    assert len(service.store.history(complete_only=False)) == 2


def test_a_source_that_never_succeeded_reports_no_last_success_time(tmp_path):
    """last_success_at is None rather than invented when no healthy snapshot exists."""

    def get_account(profile_id):
        if profile_id.startswith("ibkr"):
            raise ConnectionError("offline")
        return {"summary": []}

    service = PortfolioService(
        PortfolioStore(tmp_path / "portfolio.sqlite3"),
        settings_store=_settings_store(tmp_path),
        get_account=get_account,
        get_positions=lambda profile_id: {"positions": []},
        get_quote=lambda *args, **kwargs: {},
        fx_fetcher=lambda: (
            Decimal("7.2"),
            Decimal("7.8"),
            "2026-08-09T00:00:00+00:00",
        ),
    )

    snapshot = service.refresh()
    ibkr = next(item for item in snapshot["accounts"] if item["broker"] == "ibkr")
    assert ibkr["status"] == "error"
    assert ibkr["last_success_at"] is None


def test_remote_mcp_sources_are_read_without_an_interactive_oauth_prompt(tmp_path, monkeypatch):
    """A dashboard refresh must never be able to pop a browser, for any connector."""
    settings = PortfolioSettingsStore(tmp_path / "portfolio.json")
    settings.connection_store.ensure("remote", "alpaca-live-sdk-readonly", "Remote")
    settings.save(
        {
            "display_currency": "USD",
            "sources": [{"connection_id": "remote", "label": "Remote", "order": 0}],
        }
    )
    # A read-only remote_mcp profile whose connector is deliberately not IBKR:
    # the non-interactive read is a property of the transport, not of a broker.
    remote = TradingProfile(
        id="alpaca-live-sdk-readonly",
        connector="examplebroker",
        label="Example remote MCP",
        environment="live",
        transport="remote_mcp",
        capabilities=("account.read", "positions.read"),
        readonly=True,
    )
    monkeypatch.setattr(portfolio_service, "profile_by_id", lambda _: remote)

    seen: list[tuple[str, dict]] = []

    def get_account(profile_id, **options):
        seen.append(("account", options))
        return {"account": {"portfolio_value": "500", "currency": "USD"}}

    def get_positions(profile_id, **options):
        seen.append(("positions", options))
        return {"positions": [{"symbol": "AAPL", "quantity": "2", "market_price": "250"}]}

    service = PortfolioService(
        PortfolioStore(tmp_path / "portfolio.sqlite3"),
        settings_store=settings,
        get_account=get_account,
        get_positions=get_positions,
        get_quote=lambda *args, **kwargs: {},
        fx_fetcher=lambda: (
            Decimal("7.2"),
            Decimal("7.8"),
            "2026-08-09T00:00:00+00:00",
        ),
    )
    snapshot = service.refresh()

    assert snapshot["complete"] is True
    assert [call for call, _ in seen] == ["account", "positions"]
    assert [options for _, options in seen] == [
        {"interactive_oauth": False},
        {"interactive_oauth": False},
    ]


def test_remote_mcp_authorization_failure_is_the_only_reconnectable_failure(
    tmp_path, monkeypatch
):
    settings = PortfolioSettingsStore(tmp_path / "portfolio.json")
    settings.connection_store.ensure("remote", "alpaca-live-sdk-readonly", "Remote")
    settings.save(
        {
            "display_currency": "USD",
            "sources": [
                {"connection_id": "remote", "label": "Remote", "order": 0}
            ],
        }
    )
    remote = TradingProfile(
        id="alpaca-live-sdk-readonly",
        connector="examplebroker",
        label="Example remote MCP",
        environment="live",
        transport="remote_mcp",
        capabilities=("account.read", "positions.read"),
        readonly=True,
    )
    monkeypatch.setattr(portfolio_service, "profile_by_id", lambda _: remote)

    service = PortfolioService(
        PortfolioStore(tmp_path / "portfolio.sqlite3"),
        settings_store=settings,
        get_account=lambda *args, **kwargs: {
            "status": "not_authorized",
            "error": "OAuth authorization required",
        },
        get_positions=lambda *args, **kwargs: {"positions": []},
        get_quote=lambda *args, **kwargs: {},
        fx_fetcher=lambda: (
            Decimal("7.2"),
            Decimal("7.8"),
            "2026-08-09T00:00:00+00:00",
        ),
    )

    snapshot = service.refresh()
    account = snapshot["accounts"][0]

    assert account["status"] == "error"
    assert account["failure_kind"] == "authorization"
    assert account["reconnect_required"] is True


def test_analysis_context_supplies_risk_xray_arguments(tmp_path):
    """The portfolio feeds the existing risk x-ray; it does not reimplement it."""
    accounts = {
        "ibkr-live-local-readonly": {"summary": [{"tag": "NetLiquidation", "value": "300", "currency": "USD"}]},
        "longbridge-live-sdk-readonly": {"balances": [{"net_assets": "3900", "currency": "HKD"}]},
        "binance-live-sdk-readonly": {"balances": []},
    }
    positions = {
        "ibkr-live-local-readonly": {
            "positions": [
                {
                    "symbol": "AAPL",
                    "sec_type": "STK",
                    "exchange": "SMART",
                    "currency": "USD",
                    "position": 2,
                    "avg_cost": 100,
                }
            ]
        },
        "longbridge-live-sdk-readonly": {
            "positions": [
                {
                    "symbol": "700.HK",
                    "symbol_name": "Tencent",
                    "quantity": 10,
                    "cost_price": 300,
                    "currency": "HKD",
                    "market": "HK",
                }
            ]
        },
        "binance-live-sdk-readonly": {
            "positions": [
                {"symbol": "BTC", "quantity": 0.1, "free": 0.1, "used": 0},
                {"symbol": "USDT", "quantity": 50, "free": 50, "used": 0},
            ]
        },
    }

    service = PortfolioService(
        PortfolioStore(tmp_path / "portfolio.sqlite3"),
        settings_store=_settings_store(tmp_path),
        get_account=lambda profile_id: accounts[profile_id],
        get_positions=lambda profile_id: positions[profile_id],
        get_quote=lambda symbol, profile_id, **kwargs: {
            "quote": {"last": {"AAPL": 150, "700.HK": 390, "BTC/USDT": 60000}[symbol]}
        },
        fx_fetcher=lambda: (
            Decimal("7.2"),
            Decimal("7.8"),
            "2026-08-09T00:00:00+00:00",
        ),
    )
    service.refresh()
    args = service.analysis_context()["risk_xray_args"]

    # Symbols carry the market suffix the risk x-ray's loaders route on: a bare
    # "AAPL" is read as an A-share code by src.market_data.detect_source.
    assert args["symbols"] == ["700.HK", "AAPL.US"]
    assert set(args["weights"]) == set(args["symbols"])
    assert args["weights"]["700.HK"] == pytest.approx(0.625)
    assert args["weights"]["AAPL.US"] == pytest.approx(0.375)
    assert sum(args["weights"].values()) == pytest.approx(1.0)
    # Crypto and stablecoins are not priced by the daily-bar loaders.
    assert not any("BTC" in symbol for symbol in args["symbols"])
    assert not any("USDT" in symbol for symbol in args["symbols"])


def test_risk_xray_arguments_are_empty_when_nothing_priced_can_be_routed(tmp_path):
    """An unroutable or unpriced book yields no arguments instead of a guess."""
    assert PortfolioService._risk_xray_args(
        [
            {"symbol": "AAPL", "asset_type": "stock", "priced": False, "market_value_usd": 0},
            {
                "symbol": "BTC",
                "asset_type": "crypto",
                "priced": True,
                "market_value_usd": 6000,
                "currency": "USD",
            },
            {
                "symbol": "0700",
                "asset_type": "stock",
                "priced": True,
                "market_value_usd": 500,
                "currency": "JPY",
                "market": "TSE",
            },
        ]
    ) == {"symbols": [], "weights": {}}


def test_generic_readonly_profile_uses_common_account_and_position_fields(tmp_path):
    settings = PortfolioSettingsStore(tmp_path / "portfolio.json")
    settings.connection_store.ensure(
        "main-stocks",
        "alpaca-live-sdk-readonly",
        "Main stocks",
    )
    settings.save(
        {
            "display_currency": "CNY",
            "sources": [
                {
                    "connection_id": "main-stocks",
                    "label": "Main stocks",
                    "enabled": True,
                    "order": 0,
                    "include_cash": False,
                }
            ],
        }
    )
    service = PortfolioService(
        PortfolioStore(tmp_path / "portfolio.sqlite3"),
        settings_store=settings,
        get_account=lambda profile_id: {"account": {"portfolio_value": "1000", "cash": "200", "currency": "USD"}},
        get_positions=lambda profile_id: {
            "positions": [
                {
                    "symbol": "AAPL",
                    "quantity": "4",
                    "average_cost": "150",
                    "current_price": "200",
                    "market_value": "800",
                }
            ]
        },
        get_quote=lambda *args, **kwargs: {},
        fx_fetcher=lambda: (
            Decimal("7.2"),
            Decimal("7.8"),
            "2026-08-09T00:00:00+00:00",
        ),
    )

    snapshot = service.refresh()
    account = snapshot["accounts"][0]
    position = snapshot["positions"][0]
    assert snapshot["display_currency"] == "CNY"
    assert snapshot["totals"]["usd"] == 800.0
    assert account["source_id"] == "main-stocks"
    assert account["cash_usd"] == 0.0
    assert position["source_label"] == "Main stocks"
    assert position["market_value_usd"] == 800.0


def test_okx_spot_balances_flow_through_the_generic_portfolio_contract(tmp_path):
    settings = PortfolioSettingsStore(tmp_path / "portfolio.json")
    settings.connection_store.ensure(
        "okx-spot",
        "okx-live-sdk-readonly",
        "OKX Spot",
    )
    settings.save(
        {
            "display_currency": "USD",
            "sources": [
                {
                    "connection_id": "okx-spot",
                    "label": "OKX Spot",
                    "enabled": True,
                    "order": 0,
                    "include_cash": True,
                }
            ],
        }
    )
    quoted = []

    def get_quote(symbol, profile_id, **kwargs):
        quoted.append((symbol, profile_id))
        return {"quote": {"last": "40000"}}

    service = PortfolioService(
        PortfolioStore(tmp_path / "portfolio.sqlite3"),
        settings_store=settings,
        get_account=lambda profile_id: {
            "account": {
                "total_equity": "60250",
                "details": [
                    {"currency": "BTC", "equity": "1.5", "available": "1.5"},
                    {"currency": "USDT", "equity": "250", "available": "250"},
                ],
            }
        },
        get_positions=lambda profile_id: {"positions": []},
        get_quote=get_quote,
        fx_fetcher=lambda: (
            Decimal("7.2"),
            Decimal("7.8"),
            "2026-08-25T00:00:00+00:00",
        ),
    )

    snapshot = service.refresh()

    assert snapshot["complete"] is True
    assert snapshot["totals"]["usd"] == 60250.0
    assert [row["symbol"] for row in snapshot["positions"]] == ["BTC", "USDT"]
    assert quoted == [("BTC-USDT", "okx-live-sdk-readonly")]
    assert snapshot["accounts"][0]["portfolio_compatibility"]["level"] == ("contract_tested")
    assert any("okx" in warning.lower() for warning in snapshot["warnings"])


def test_auth_metadata_describes_the_profile_without_claiming_key_permissions():
    profile = TradingProfile(
        id="example-live-readonly",
        connector="example",
        label="Example",
        environment="live",
        transport="broker_sdk",
        capabilities=("account.read", "positions.read"),
        readonly=True,
        notes="Use credentials configured by the local operator.",
    )

    assert auth_metadata(profile) == {
        "method": "API credentials",
        "renewal": "provider_managed",
        "readonly": True,
        "detail": "Use credentials configured by the local operator.",
    }


def _reconnect_service(tmp_path):
    return PortfolioService(
        PortfolioStore(tmp_path / "portfolio.sqlite3"),
        settings_store=_settings_store(tmp_path),
        get_account=lambda *_args, **_kwargs: {},
        get_positions=lambda *_args, **_kwargs: {},
        get_quote=lambda *_args, **_kwargs: {},
    )


def _oauth_profile():
    return TradingProfile(
        id="ibkr-live-official-mcp-readonly",
        connector="ibkr",
        label="IBKR OAuth",
        environment="live",
        transport="remote_mcp",
        capabilities=("account.read", "positions.read"),
        readonly=True,
    )


def test_reconnect_rejects_an_occupied_oauth_callback_port(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio_service, "profile_by_id", lambda *_: _oauth_profile())
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        callback_port = listener.getsockname()[1]
        server = SimpleNamespace(
            auth=SimpleNamespace(callback_port=callback_port),
        )
        monkeypatch.setattr(
            "src.config.loader.load_agent_config",
            lambda: SimpleNamespace(mcp_servers={"ibkr": server}),
        )

        with pytest.raises(RuntimeError, match=str(callback_port)):
            _reconnect_service(tmp_path).reconnect_source("ibkr")


def test_reconnect_contains_callback_server_system_exit(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio_service, "profile_by_id", lambda *_: _oauth_profile())
    server = SimpleNamespace(auth=SimpleNamespace(callback_port=None))
    monkeypatch.setattr(
        "src.config.loader.load_agent_config",
        lambda: SimpleNamespace(mcp_servers={"ibkr": server}),
    )

    class FailingAdapter:
        def __init__(self, *_args, **_kwargs):
            pass

        def discover_tools(self):
            raise BaseExceptionGroup("callback startup", [SystemExit(3)])

    monkeypatch.setattr("src.tools.mcp.MCPServerAdapter", FailingAdapter)

    with pytest.raises(RuntimeError, match="stopped safely"):
        _reconnect_service(tmp_path).reconnect_source("ibkr")
