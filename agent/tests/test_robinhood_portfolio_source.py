"""Read-only Robinhood portfolio source (#1428), end to end through the real read path.

``PortfolioService`` uses its default readers here, so a refresh goes through
``trading.service`` → the Robinhood mapping → the portfolio contract. Only the
MCP adapter is stubbed, and it answers with the shapes posted on #1428.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import connection_routes
from src.portfolio.config import PortfolioSettingsStore
from src.portfolio.service import PortfolioService
from src.portfolio.store import PortfolioStore
from src.trading.connections import ConnectionStore, is_portfolio_connection_profile
from src.trading.profiles import profile_by_id
from tests import robinhood_mcp_helpers as rh

pytestmark = pytest.mark.unit

ACCOUNT = "5QR12345"


class _Broker:
    """Records every MCP call and answers with the configured replies."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.replies: dict[str, dict] = {
            "get_accounts": rh.accounts([rh.account(ACCOUNT, nickname="Main"), rh.account("5QR00009")]),
            "get_portfolio": rh.portfolio(total_value="1500.00", cash="500.00"),
            "get_equity_positions": rh.positions([]),
        }

    def adapter_class(self):
        broker = self

        class _Adapter:
            def __init__(self, server_name, server_config, **kwargs):  # noqa: ANN001
                assert server_name == "robinhood"
                assert kwargs.get("interactive_oauth") is False

            def call_tool(self, remote_name, arguments):  # noqa: ANN001
                broker.calls.append((remote_name, dict(arguments)))
                return broker.replies[remote_name]

        return _Adapter


@pytest.fixture
def broker(monkeypatch: pytest.MonkeyPatch) -> _Broker:
    fake = _Broker()
    server = SimpleNamespace(
        url="https://agent.robinhood.com/mcp/trading",
        enabled_tools=["get_accounts", "get_portfolio", "get_equity_positions", "get_equity_quotes"],
        auth=SimpleNamespace(cache_dir="/tmp/vibe-token"),
    )
    monkeypatch.setattr(
        "src.config.loader.load_agent_config", lambda: SimpleNamespace(mcp_servers={"robinhood": server})
    )
    monkeypatch.setattr("src.live.registry.has_cached_oauth_token", lambda *_: True)
    monkeypatch.setattr("src.tools.mcp.MCPServerAdapter", fake.adapter_class())
    return fake


def _service(tmp_path, *, account_ref: str = ACCOUNT) -> PortfolioService:
    settings = PortfolioSettingsStore(tmp_path / "portfolio.json")
    settings.connection_store.ensure("robinhood-live", "robinhood-live-mcp-readonly", "Robinhood")
    if account_ref:
        settings.connection_store.select_account("robinhood-live", account_ref)
    settings.save({"display_currency": "USD", "sources": [{"connection_id": "robinhood-live", "label": "Robinhood"}]})
    return PortfolioService(
        PortfolioStore(tmp_path / "portfolio.sqlite3"),
        settings_store=settings,
        fx_fetcher=lambda: (Decimal("7.2"), Decimal("7.8"), "2026-09-17T00:00:00+00:00"),
    )


def test_only_the_readonly_profile_can_back_a_portfolio_connection() -> None:
    assert is_portfolio_connection_profile(profile_by_id("robinhood-live-mcp-readonly")) is True
    assert is_portfolio_connection_profile(profile_by_id("robinhood-live-mcp")) is False


def test_a_source_without_a_selected_account_errors_before_any_call(tmp_path, broker: _Broker) -> None:
    snapshot = _service(tmp_path, account_ref="").refresh()

    account = snapshot["accounts"][0]
    assert account["status"] == "error"
    assert "Select a robinhood account" in account["error"]
    assert snapshot["complete"] is False
    assert broker.calls == []


def test_an_empty_account_is_a_complete_snapshot_read_for_the_selected_account(tmp_path, broker: _Broker) -> None:
    snapshot = _service(tmp_path).refresh()

    account = snapshot["accounts"][0]
    assert snapshot["complete"] is True
    assert account["status"] == "ok"
    assert account["total_usd"] == 1500.0
    assert account["cash_usd"] == 500.0
    assert broker.calls == [
        ("get_portfolio", {"account_number": ACCOUNT}),
        ("get_equity_positions", {"account_number": ACCOUNT}),
    ]


def test_positions_are_listed_unpriced_and_quotes_are_never_called(tmp_path, broker: _Broker) -> None:
    broker.replies["get_portfolio"] = rh.portfolio(total_value="2500.00", cash="500.00")
    broker.replies["get_equity_positions"] = rh.positions(
        [
            rh.position("AAPL", "4", average_buy_price="150.00"),
            rh.position("MSFT", "2", average_buy_price=None),
        ]
    )

    snapshot = _service(tmp_path).refresh()

    rows = {row["symbol"]: row for row in snapshot["positions"]}
    assert rows["AAPL"]["quantity"] == 4.0
    assert rows["AAPL"]["cost_price"] == 150.0
    assert rows["MSFT"]["cost_price"] is None  # omitted while reconciling, never zero
    assert all(row["market_price"] is None for row in rows.values())
    assert all("quotes are not mapped" in row["price_error"] for row in rows.values())
    assert snapshot["accounts"][0]["total_usd"] == 2500.0
    assert snapshot["accounts"][0]["unpriced_or_other_usd"] == 2000.0
    assert any("No price available" in warning for warning in snapshot["warnings"])
    assert "get_equity_quotes" not in [name for name, _ in broker.calls]


@pytest.mark.parametrize("field", ["options_value", "crypto_value", "futures_value", "fixed_income_value"])
def test_holdings_outside_equities_fail_the_source_instead_of_shortening_it(
    tmp_path, broker: _Broker, field: str
) -> None:
    broker.replies["get_portfolio"] = rh.portfolio(total_value="3000.00", **{field: "125.00"})
    broker.replies["get_equity_positions"] = rh.positions([rh.position("AAPL", "1")])

    snapshot = _service(tmp_path).refresh()

    account = snapshot["accounts"][0]
    assert account["status"] == "error"
    assert field in account["error"]
    assert account["total_usd"] is None
    assert snapshot["positions"] == []
    assert snapshot["complete"] is False


def test_an_unreported_non_equity_value_is_not_read_as_zero(tmp_path, broker: _Broker) -> None:
    envelope = rh.portfolio()
    del envelope["structured_content"]["data"]["event_contracts_value"]
    broker.replies["get_portfolio"] = envelope

    account = _service(tmp_path).refresh()["accounts"][0]

    assert account["status"] == "error"
    assert "did not report event_contracts_value" in account["error"]


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (rh.positions([rh.position("AAPL", "1")], next_page="cursor-2"), "more than one page"),
        (rh.positions(None), "no positions list"),
        (rh.positions([None]), "is not an object"),
    ],
)
def test_a_partial_or_null_position_read_is_an_error_not_an_empty_account(
    tmp_path, broker: _Broker, reply: dict, message: str
) -> None:
    broker.replies["get_equity_positions"] = reply

    account = _service(tmp_path).refresh()["accounts"][0]

    assert account["status"] == "error"
    assert message in account["error"]


def test_a_missing_total_value_is_an_error_not_a_zero_account(tmp_path, broker: _Broker) -> None:
    envelope = rh.portfolio()
    del envelope["structured_content"]["data"]["total_value"]
    broker.replies["get_portfolio"] = envelope

    account = _service(tmp_path).refresh()["accounts"][0]

    assert account["status"] == "error"
    assert "total_value is missing" in account["error"]


def test_the_connection_store_refuses_an_account_on_a_profile_that_takes_none(tmp_path) -> None:
    store = ConnectionStore(tmp_path / "connections.json")
    store.ensure("ibkr", "ibkr-live-local-readonly", "IBKR")

    with pytest.raises(ValueError, match="does not take an account"):
        store.select_account("ibkr", "U1234")


def test_the_connection_store_refuses_a_control_character_in_an_account(tmp_path) -> None:
    store = ConnectionStore(tmp_path / "connections.json")
    store.ensure("robinhood-live", "robinhood-live-mcp-readonly", "Robinhood")

    with pytest.raises(ValueError, match="printable"):
        store.select_account("robinhood-live", "5QR\n1")


def _client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, ConnectionStore]:
    store = ConnectionStore(tmp_path / "connections.json")
    store.ensure("robinhood-live", "robinhood-live-mcp-readonly", "Robinhood")
    monkeypatch.setattr(connection_routes, "ConnectionStore", lambda: store)
    monkeypatch.setattr(connection_routes, "require_auth", lambda: None)
    monkeypatch.setattr(connection_routes, "require_settings_write_auth", lambda: None)
    app = FastAPI()
    connection_routes.register_connection_routes(app)
    return TestClient(app), store


def test_accounts_route_lists_the_login_accounts(tmp_path, monkeypatch, broker: _Broker) -> None:
    client, _ = _client(tmp_path, monkeypatch)

    response = client.get("/api/connections/robinhood-live/accounts")

    assert response.status_code == 200
    body = response.json()
    assert [row["account_ref"] for row in body["accounts"]] == [ACCOUNT, "5QR00009"]
    assert body["account_ref"] == ""
    assert broker.calls == [("get_accounts", {})]


@pytest.mark.parametrize(
    ("accounts", "status", "detail"),
    [
        ([rh.account("5QR00009")], 400, "not one of the accounts"),
        ([rh.account(ACCOUNT, deactivated=True)], 400, "deactivated"),
    ],
)
def test_selecting_an_account_the_login_cannot_use_is_refused(
    tmp_path, monkeypatch, broker: _Broker, accounts: list, status: int, detail: str
) -> None:
    broker.replies["get_accounts"] = rh.accounts(accounts)
    client, store = _client(tmp_path, monkeypatch)

    response = client.put("/api/connections/robinhood-live/account", json={"account_ref": ACCOUNT})

    assert response.status_code == status
    assert detail in response.json()["detail"]
    assert store.get("robinhood-live").account_ref == ""


def test_selecting_clearing_and_renaming_keep_the_account_where_it_belongs(
    tmp_path, monkeypatch, broker: _Broker
) -> None:
    client, store = _client(tmp_path, monkeypatch)

    assert client.put("/api/connections/robinhood-live/account", json={"account_ref": ACCOUNT}).status_code == 200
    assert store.get("robinhood-live").account_ref == ACCOUNT

    renamed = client.put(
        "/api/connections/robinhood-live",
        json={"id": "robinhood-live", "profile_id": "robinhood-live-mcp-readonly", "label": "RH main"},
    )
    assert renamed.status_code == 200
    assert store.get("robinhood-live").label == "RH main"
    assert store.get("robinhood-live").account_ref == ACCOUNT

    calls_before_clear = len(broker.calls)
    assert client.put("/api/connections/robinhood-live/account", json={"account_ref": ""}).status_code == 200
    assert store.get("robinhood-live").account_ref == ""
    assert len(broker.calls) == calls_before_clear  # clearing needs no broker read


def test_accounts_route_reports_an_unavailable_broker_as_503(tmp_path, monkeypatch, broker: _Broker) -> None:
    broker.replies["get_accounts"] = {"status": "error", "error": "token expired"}
    client, _ = _client(tmp_path, monkeypatch)

    response = client.get("/api/connections/robinhood-live/accounts")

    assert response.status_code == 503
    assert "token expired" in response.json()["detail"]
