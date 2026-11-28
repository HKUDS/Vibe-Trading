"""Documented Type B transport replay, without assuming cash or ticker semantics."""

from __future__ import annotations

import cli.commands.connectors as _cmd_connectors

import httpx
import pytest

from src.live.classification import ToolClass
from src.trading.connectors.mstock.classification import MSTOCK_TOOL_CLASS
from src.trading import profiles, service
from src.trading.connections import is_portfolio_connection_profile
from src.trading.connectors.mstock import sdk
from src.trading.onboarding import onboarding_for_profile

pytestmark = pytest.mark.unit
PROFILE = "mstock-live-rest-readonly"


def test_readonly_profile_withholds_unmapped_portfolio_valuation():
    profile = profiles.profile_by_id(PROFILE)
    assert profile.readonly and profile.environment == "live"
    assert profile.capabilities == ("positions.read",)
    assert not is_portfolio_connection_profile(profile)
    onboarding = onboarding_for_profile(profile)
    assert [field.name for field in onboarding.credential_fields] == ["api_key", "access_token"]
    assert onboarding.test_operation == "positions.read"
    assert MSTOCK_TOOL_CLASS["get_positions"] is ToolClass.READ
    assert MSTOCK_TOOL_CLASS["place_order"] is ToolClass.WRITE


@pytest.mark.parametrize("operation", ["place_order", "cancel_order"])
def test_orders_refused_before_network(monkeypatch, operation):
    monkeypatch.setattr(sdk.httpx, "Client", lambda **kwargs: pytest.fail("order made a network call"))
    result = getattr(service, operation)("RELIANCE", PROFILE, side="buy", quantity=1)
    assert result["status"] == "error"
    for config in (None, sdk.MStockConfig("key", "token"), sdk.MStockConfig("key", "token", environment="paper")):
        with pytest.raises(sdk.MStockAPIError):
            getattr(sdk, operation)(config=config)


def _transport(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(
        sdk.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )


def test_actual_requests_keep_broker_books_and_fund_limits_separate(monkeypatch):
    requests = []
    holdings = [
        {
            "tradingsymbol": "BANK OF MAHARASHTRA",
            "exchange": None,
            "isin": "INE457A01014",
            "quantity": 10,
            "averageprice": 30,
            "ltp": 84.7,
        }
    ]
    net = [
        {
            "symboltoken": "50374",
            "exchange": "NSE",
            "tradingsymbol": "",
            "symbolname": "NIFTY-07Nov2024-24000-CE",
            "instrumenttype": "OPTIDX",
            "netqty": "-500",
        }
    ]
    funds = [{"AVAILABLE_BALANCE": "1234.56", "COLLATERALS": "500", "SEG": "A"}]

    def handle(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.host == "api.mstock.trade"
        assert request.headers["X-Mirae-Version"] == "1"
        assert request.headers["X-PrivateKey"] == "key"
        assert request.headers["Authorization"] == "Bearer token"
        data = {"holdings": holdings, "positions": net, "fundsummary": funds}[request.url.path.rsplit("/", 1)[1]]
        return httpx.Response(200, json={"status": "true", "errorcode": None, "data": data})

    _transport(monkeypatch, handle)
    result = service.get_positions(PROFILE, api_key="key", access_token="token")
    assert result["holdings"] == holdings and result["net_positions"] == net
    assert "positions" not in result
    account = service.get_account(PROFILE, api_key="key", access_token="token")
    assert account["fund_limits"] == funds
    assert "account_summary" not in account and "cash" not in account
    assert not account["portfolio_eligible"]
    assert len(requests) == 3


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"status": "false", "data": []},
        {"status": "true", "data": None},
        {"status": "true", "data": "None"},
        {"status": "true", "data": [None]},
        {"status": "true", "errorcode": "MA500", "data": []},
    ],
)
def test_bad_replies_are_not_empty_accounts(monkeypatch, body):
    _transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(sdk.MStockAPIError):
        sdk.get_positions(sdk.MStockConfig("key", "token"))


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
def test_transport_errors_never_echo_secret_response(monkeypatch, status):
    _transport(
        monkeypatch,
        lambda request: httpx.Response(status, headers={"Location": "https://unexpected.test"}, text="key token"),
    )
    result = sdk.check_status(sdk.MStockConfig("key", "token"))
    assert result["status"] == "error"
    assert "key token" not in result["error"]


def test_missing_credentials_make_no_network_call(monkeypatch):
    monkeypatch.setattr(sdk.httpx, "Client", lambda **kwargs: pytest.fail("missing credentials reached network"))
    assert sdk.check_status()["status"] == "error"
    assert "key" not in repr(sdk.MStockConfig("key", "token"))
    with pytest.raises(ValueError, match="only live"):
        sdk.MStockConfig.from_mapping({"environment": "paper"})


def test_cli_reads_use_named_vault_connection_and_render_raw_books(monkeypatch, capsys):
    from types import SimpleNamespace
    from src.trading import connections

    class Vault:
        def load(self, connection_id, fields):
            assert connection_id == "mstock-main"
            assert set(fields) == {"api_key", "access_token"}
            return {"api_key": "vault-key", "access_token": "vault-token"}

    monkeypatch.setattr(
        connections,
        "ConnectionStore",
        lambda: SimpleNamespace(
            get=lambda _: SimpleNamespace(profile_id=PROFILE, id="mstock-main"), credentials=Vault()
        ),
    )

    def handle(request):
        assert request.headers["Authorization"] == "Bearer vault-token"
        data = [{"AVAILABLE_BALANCE": "123.45"}] if request.url.path.endswith("fundsummary") else []
        return httpx.Response(200, json={"status": "true", "data": data})

    _transport(monkeypatch, handle)
    assert _cmd_connectors.cmd_connector_positions(PROFILE, connection_id="mstock-main") == 0
    output = capsys.readouterr().out
    assert "net_positions" in output and "broker_books_unaggregated" in output
    assert _cmd_connectors.cmd_connector_account(PROFILE, connection_id="mstock-main") == 0
    output = capsys.readouterr().out
    assert "fund_limits" in output and "123.45" in output
    assert "vault-token" not in output and "vault-key" not in output


def test_real_connection_store_accepts_reads_but_portfolio_rejects_them(tmp_path):
    from src.trading.connections import ConnectionStore, readonly_profile_catalog
    from src.portfolio.config import PortfolioSettings, parse_settings, source_catalog

    store = ConnectionStore(tmp_path / "connections.json")
    connection = store.create("mstock-main", PROFILE, "mStock account")
    assert connection.profile_id == PROFILE
    row = next(row for row in readonly_profile_catalog() if row.get("id") == PROFILE)
    assert row["portfolio_eligible"] is False
    assert source_catalog(PortfolioSettings(), connection_store=store) == []
    with pytest.raises(ValueError, match="not eligible"):
        parse_settings({"sources": [{"connection_id": "mstock-main"}]}, connection_store=store)
