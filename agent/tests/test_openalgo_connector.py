"""OpenAlgo read-only transport replayed on redacted fixtures pinned to OpenAlgo 2.0.3.3.

The fixtures follow the documented samples and sandbox source at the pinned
commit; see ``fixtures/openalgo/responses_2.0.3.3.json`` for provenance. No
OpenAlgo server or broker is contacted.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from src.live.classification import ToolClass
from src.trading import profiles, service
from src.trading.connections import is_portfolio_connection_profile
from src.trading.connectors.openalgo import sdk
from src.trading.connectors.openalgo.classification import OPENALGO_TOOL_CLASS
from src.trading.onboarding import onboarding_for_profile

pytestmark = pytest.mark.unit
PROFILE = "openalgo-live-rest-readonly"
HOST = "http://127.0.0.1:5000"
KEY = "oa-test-key-0123456789"
FIXTURES = json.loads(
    (
        Path(__file__).parent / "fixtures" / "openalgo" / "responses_2.0.3.3.json"
    ).read_text(encoding="utf-8")
)
CREDS = {"host_url": HOST, "api_key": KEY}

#: Every write-capable namespace registered in OpenAlgo's restx_api/__init__.py
#: at the pinned commit, plus the analyzer mode switch.
OPENALGO_WRITE_ENDPOINTS = (
    "placeorder",
    "placesmartorder",
    "modifyorder",
    "cancelorder",
    "closeposition",
    "cancelallorder",
    "basketorder",
    "splitorder",
    "optionsorder",
    "optionsmultiorder",
    "placegttorder",
    "modifygttorder",
    "cancelgttorder",
    "analyzer/toggle",
    "telegram",
    "whatsapp",
    "chart",
    "strategy",
)


def _config(**values):
    return sdk.OpenAlgoConfig.from_mapping({**CREDS, **values})


_REAL_CLIENT = httpx.Client


def _transport(monkeypatch, handler):
    monkeypatch.setattr(
        sdk.httpx,
        "Client",
        lambda **kwargs: _REAL_CLIENT(transport=httpx.MockTransport(handler), **kwargs),
    )


def _replay(monkeypatch, bodies: dict[str, str], seen: list | None = None):
    """Serve fixture ``bodies[endpoint]`` for each POST /api/v1/<endpoint>."""

    def handle(request):
        assert request.method == "POST"
        assert request.url.host == "127.0.0.1" and request.url.port == 5000
        endpoint = request.url.path.removeprefix("/api/v1/")
        body = json.loads(request.content)
        assert body["apikey"] == KEY
        if seen is not None:
            seen.append((endpoint, body))
        return httpx.Response(200, json=FIXTURES[bodies[endpoint]])

    _transport(monkeypatch, handle)


def _no_network(monkeypatch):
    monkeypatch.setattr(
        sdk.httpx, "Client", lambda **kwargs: pytest.fail("made a network call")
    )


# --------------------------------------------------------------------------- profile


def test_readonly_profile_withholds_portfolio_valuation():
    profile = profiles.profile_by_id(PROFILE)
    assert (
        profile.readonly
        and profile.environment == "live"
        and profile.transport == "broker_sdk"
    )
    assert profile.capabilities == (
        "positions.read",
        "orders.read",
        "quotes.read",
        "history.read",
    )
    assert not any(
        ".place" in cap or "requires_mandate" in cap for cap in profile.capabilities
    )
    assert not is_portfolio_connection_profile(profile)
    assert [p.id for p in profiles.list_profiles() if p.connector == "openalgo"] == [
        PROFILE
    ]
    onboarding = onboarding_for_profile(profile)
    assert [(f.name, f.secret) for f in onboarding.credential_fields] == [
        ("host_url", False),
        ("api_key", True),
    ]
    assert onboarding.test_operation == "positions.read"
    assert OPENALGO_TOOL_CLASS["get_positions"] is ToolClass.READ
    assert OPENALGO_TOOL_CLASS["place_order"] is ToolClass.WRITE
    assert OPENALGO_TOOL_CLASS["cancel_order"] is ToolClass.WRITE


def test_registry_classifies_orders_write():
    from src.live import registry
    from src.live.classification import classify_tool

    curated = registry._BROKER_CURATED_MAPS["openalgo"]
    assert classify_tool("place_order", None, curated) is ToolClass.WRITE
    assert classify_tool("cancel_order", None, curated) is ToolClass.WRITE
    assert classify_tool("placesmartorder", None, curated) is not ToolClass.READ


# --------------------------------------------------------------------------- writes


@pytest.mark.parametrize("operation", ["place_order", "cancel_order"])
def test_orders_refused_before_any_http_request(monkeypatch, operation):
    calls = []
    _transport(
        monkeypatch,
        lambda request: calls.append(request) or httpx.Response(200, json={}),
    )
    args = ("RELIANCE",) if operation == "place_order" else ("100000000000001",)
    result = getattr(service, operation)(
        *args, PROFILE, side="buy", quantity=1, **CREDS
    )
    assert result["status"] == "error"
    for config in (None, _config(), sdk.OpenAlgoConfig(HOST, KEY, environment="paper")):
        with pytest.raises(sdk.OpenAlgoAPIError, match="disabled"):
            getattr(sdk, operation)(
                config, config=config, symbol="RELIANCE", side="buy", quantity=1
            )
    assert calls == []


def test_transport_cannot_reach_a_write_endpoint(monkeypatch):
    _no_network(monkeypatch)
    for endpoint in OPENALGO_WRITE_ENDPOINTS:
        assert endpoint not in sdk.READ_ENDPOINTS
        with pytest.raises(sdk.OpenAlgoAPIError, match="Unsupported"):
            sdk._post(_config(), endpoint)


# --------------------------------------------------------------------------- live reads


def test_live_books_are_mapped_with_units_and_live_provenance(monkeypatch):
    seen = []
    _replay(
        monkeypatch,
        {
            "funds": "funds_live",
            "positionbook": "positionbook_live",
            "holdings": "holdings_live",
        },
        seen,
    )
    account = service.get_account(PROFILE, **CREDS)
    assert account["openalgo_mode"] == "live" and account["provenance"] == "live_broker"
    assert account["funds"] == {
        "available_cash": 320.66,
        "collateral": 0.0,
        "realized_mtm": 3.27,
        "unrealized_mtm": -7.88,
        "utilised_debits": 679.34,
    }
    assert account["valuation_basis"] == "margin_limits_not_net_liquidation"
    assert account["currency"] is None and not account["portfolio_eligible"]
    assert account["openalgo_contract"] == sdk.OPENALGO_CONTRACT

    books = service.get_positions(PROFILE, **CREDS)
    assert (
        books["openalgo_mode"] == "live"
        and books["valuation_basis"] == "broker_books_unaggregated"
    )
    assert "positions" not in books and not books["portfolio_eligible"]
    nhpc, closed, carried = books["net_positions"]
    assert nhpc == {
        "symbol": "NHPC",
        "exchange": "NSE",
        "product": "MIS",
        "quantity": -1.0,
        "average_price": 83.74,
        "ltp": 83.72,
        "pnl": 0.02,
        "average_price_basis": None,
        "currency": "INR",
    }
    assert closed["quantity"] == 0.0
    assert (
        carried["average_price_basis"] == "carry_forward_valuation"
        and carried["exchange"] == "NFO"
    )
    reliance, tatasteel = books["holdings"]
    assert reliance["average_price"] == 1341.0 and reliance["pnl_percent"] == -11.1
    assert (
        tatasteel["average_price"] is None and tatasteel["ltp"] is None
    )  # absent, not zero
    assert books["holdings_statistics"] == {
        "total_holding_value": 1768.0,
        "total_investment_value": 2001.0,
        "total_pnl": -233.15,
        "total_pnl_percent": -11.65,
    }
    assert [endpoint for endpoint, _ in seen] == ["funds", "positionbook", "holdings"]
    assert all(body == {"apikey": KEY} for _, body in seen)


def test_orders_and_trades_keep_open_filter_and_full_book(monkeypatch):
    _replay(monkeypatch, {"orderbook": "orderbook_live", "tradebook": "tradebook_live"})
    result = service.get_open_orders(PROFILE, include_executions=True, **CREDS)
    assert result["openalgo_mode"] == "live"
    assert [order["order_id"] for order in result["orders"]] == [
        "100000000000001",
        "100000000000002",
        "100000000000003",
    ]
    assert [order["status"] for order in result["open_orders"]] == [
        "open",
        "trigger pending",
    ]
    stop = result["open_orders"][1]
    assert (
        stop["side"] == "sell"
        and stop["order_type"] == "SL-M"
        and stop["trigger_price"] == 790.0
    )
    (trade,) = result["executions"]
    assert (
        trade["average_price"] == 1180.1
        and trade["trade_value"] == 1180.1
        and trade["trade_id"] is None
    )
    without = service.get_open_orders(PROFILE, **CREDS)
    assert "executions" not in without


# --------------------------------------------------------------------------- analyzer provenance


def test_analyzer_books_are_labelled_sandbox(monkeypatch):
    _replay(
        monkeypatch,
        {
            "funds": "funds_analyze",
            "positionbook": "positionbook_analyze",
            "holdings": "holdings_analyze",
            "orderbook": "orderbook_analyze",
            "tradebook": "tradebook_analyze",
        },
    )
    account = sdk.get_account_snapshot(_config())
    assert (
        account["openalgo_mode"] == "analyze"
        and account["provenance"] == "analyzer_sandbox"
    )
    assert account["funds"]["available_cash"] == 9985000.0
    assert account["funds"]["extra"]["reset_count"] == 1
    books = sdk.get_positions(_config())
    assert books["openalgo_mode"] == "analyze"
    assert books["net_positions"][0]["extra"]["lot_size"] == 1.0
    orders = sdk.get_open_orders(_config(), include_executions=True)
    assert (
        orders["openalgo_mode"] == "analyze"
        and orders["executions"][0]["trade_id"] == "SBT-0000000001"
    )


@pytest.mark.parametrize(
    "first, second, read",
    [
        ("positionbook_live", "holdings_analyze", "get_positions"),
        ("positionbook_analyze", "holdings_live", "get_positions"),
    ],
)
def test_a_mode_change_between_reads_never_mixes_books(
    monkeypatch, first, second, read
):
    _replay(monkeypatch, {"positionbook": first, "holdings": second})
    with pytest.raises(sdk.OpenAlgoAPIError, match="mode changed"):
        getattr(sdk, read)(_config())


def test_orders_and_trades_from_different_modes_fail(monkeypatch):
    _replay(
        monkeypatch, {"orderbook": "orderbook_live", "tradebook": "tradebook_analyze"}
    )
    with pytest.raises(sdk.OpenAlgoAPIError, match="mode changed"):
        sdk.get_open_orders(_config(), include_executions=True)


@pytest.mark.parametrize("marker", ["live", "ANALYZE", "", None, True])
def test_unmapped_mode_marker_fails_closed(monkeypatch, marker):
    body = {**FIXTURES["funds_live"], "mode": marker}
    _transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(sdk.OpenAlgoAPIError, match="mode marker"):
        sdk.get_account_snapshot(_config())


# --------------------------------------------------------------------------- market data


def test_quote_maps_exchange_symbol_and_rejects_placeholder_price(monkeypatch):
    seen = []
    _replay(monkeypatch, {"quotes": "quotes_live"}, seen)
    quote = service.get_quote("nse:reliance", PROFILE, **CREDS)
    assert (
        quote["status"] == "ok"
        and quote["exchange"] == "NSE"
        and quote["currency"] == "INR"
    )
    assert quote["quote"]["ltp"] == 1187.75 and quote["quote"]["prev_close"] == 1165.7
    assert quote["quote"]["volume"] == 14414545 and quote["quote"]["oi"] is None
    assert seen[0][1] == {"apikey": KEY, "symbol": "RELIANCE", "exchange": "NSE"}
    sdk.get_quote("NIFTY25NOV2624000CE", config=_config(), exchange="NFO")
    assert seen[1][1]["exchange"] == "NFO"

    zero = {"status": "success", "data": {**FIXTURES["quotes_live"]["data"], "ltp": 0}}
    _transport(monkeypatch, lambda request: httpx.Response(200, json=zero))
    assert sdk.get_quote("NSE:RELIANCE", config=_config())["status"] == "error"


@pytest.mark.parametrize("symbol", ["NYSE:AAPL", "NSE:", "NSE:RELI ANCE", ""])
def test_bad_instrument_makes_no_request(monkeypatch, symbol):
    _no_network(monkeypatch)
    assert sdk.get_quote(symbol, config=_config())["status"] == "error"
    assert sdk.get_historical_bars(symbol, config=_config())["status"] == "error"


def test_history_requests_a_dated_window_and_returns_sorted_epoch_bars(monkeypatch):
    seen = []
    _replay(monkeypatch, {"history": "history_live"}, seen)
    result = service.get_history("NSE:SBIN", PROFILE, period="5m", limit=2, **CREDS)
    assert result["status"] == "ok" and result["time_unit"] == "epoch_seconds"
    assert result["interval"] == "5m" and result["currency"] == "INR"
    assert [bar["time"] for bar in result["bars"]] == [1743565500, 1743565800]
    assert result["bars"][-1] == {
        "time": 1743565800,
        "open": 773.2,
        "high": 775.6,
        "low": 772.6,
        "close": 775.15,
        "volume": 227544.0,
        "oi": 0.0,
    }
    body = seen[0][1]
    assert (
        body["symbol"] == "SBIN"
        and body["exchange"] == "NSE"
        and body["interval"] == "5m"
    )
    assert body["start_date"] < body["end_date"] and "source" not in body
    sdk.get_historical_bars("NSE:SBIN", config=_config(), period="1d", limit=90)
    assert seen[1][1]["interval"] == "D"


def test_history_rejects_unsupported_period_and_incomplete_bars(monkeypatch):
    _no_network(monkeypatch)
    assert (
        "unsupported period"
        in sdk.get_historical_bars("NSE:SBIN", config=_config(), period="2h")["error"]
    )
    for row in (
        {"timestamp": "2025-04-01 09:15:00+05:30", "close": 1},
        {"timestamp": 1743565200},
    ):
        body = {"status": "success", "data": [row]}
        _transport(
            monkeypatch, lambda request, body=body: httpx.Response(200, json=body)
        )
        assert (
            sdk.get_historical_bars("NSE:SBIN", config=_config())["status"] == "error"
        )


# --------------------------------------------------------------------------- status, auth and errors


@pytest.mark.parametrize(
    "analyzer, mode", [("analyzer_live", "live"), ("analyzer_analyze", "analyze")]
)
def test_check_status_reports_server_mode_without_books(monkeypatch, analyzer, mode):
    seen = []
    positions = "positionbook_live" if mode == "live" else "positionbook_analyze"
    _replay(
        monkeypatch,
        {"ping": "ping", "analyzer": analyzer, "positionbook": positions},
        seen,
    )
    report = service.check_connection(PROFILE, **CREDS)
    assert report["status"] == "ok" and report["read_verified"] is True
    assert (
        report["analyze_mode"] is (mode == "analyze")
        and report["openalgo_mode"] == mode
    )
    assert report["openalgo_broker"] == "zerodha" and not report["portfolio_eligible"]
    assert [endpoint for endpoint, _ in seen] == ["ping", "analyzer", "positionbook"]
    assert "net_positions" not in report and KEY not in json.dumps(report)


@pytest.mark.parametrize(
    "status, fixture, message",
    [
        (403, "error_invalid_apikey", "API key"),
        (429, "error_broker_busy", "rate limiting"),
        (400, "error_validation", "HTTP 400"),
        (500, "error_invalid_apikey", "HTTP 500"),
        (301, None, "HTTP 301"),
        (200, "error_invalid_apikey", "rejected the read"),
    ],
)
def test_auth_and_server_errors_never_echo_key_or_body(
    monkeypatch, status, fixture, message
):
    def handle(request):
        headers = {"Location": f"https://evil.test/?k={KEY}"}
        if fixture is None:
            return httpx.Response(status, headers=headers, text=KEY)
        return httpx.Response(
            status, headers=headers, json={**FIXTURES[fixture], "echo": KEY}
        )

    _transport(monkeypatch, handle)
    report = sdk.check_status(_config())
    assert report["status"] == "error" and message in report["error"]
    assert KEY not in report["error"] and "evil" not in report["error"]


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {"status": "success"},
        {"status": "success", "data": None},
        {"status": "success", "data": [None]},
        {"status": "success", "data": "[]"},
    ],
)
def test_malformed_replies_are_not_empty_books(monkeypatch, body):
    _transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(sdk.OpenAlgoAPIError):
        sdk.get_positions(_config())
    with pytest.raises(sdk.OpenAlgoAPIError):
        sdk.get_account_snapshot(_config())


def test_network_and_json_failures_are_bounded(monkeypatch):
    def broken(request):
        raise httpx.ConnectError(f"refused {KEY}")

    _transport(monkeypatch, broken)
    report = sdk.check_status(_config())
    assert report["status"] == "error" and KEY not in report["error"]
    _transport(
        monkeypatch, lambda request: httpx.Response(200, text="<html>not json</html>")
    )
    assert "invalid response" in sdk.check_status(_config())["error"]


def test_missing_credentials_make_no_network_call(monkeypatch):
    _no_network(monkeypatch)
    assert "Configure" in sdk.check_status()["error"]
    assert "Configure" in sdk.check_status(sdk.OpenAlgoConfig(host_url=HOST))["error"]
    assert KEY not in repr(_config())


@pytest.mark.parametrize(
    "host_url, allowed",
    [
        ("http://127.0.0.1:5000", True),
        ("http://localhost:5000/", True),
        ("http://[::1]:5000", True),
        ("https://algo.example.in", True),
        ("https://algo.example.in/openalgo", True),
        ("http://192.168.1.20:5000", False),
        ("http://algo.example.in", False),
        ("https://user:pass@algo.example.in", False),
        ("https://algo.example.in/?next=1", False),
        ("ftp://algo.example.in", False),
        ("127.0.0.1:5000", False),
    ],
)
def test_host_url_must_not_send_the_key_in_clear_text(host_url, allowed):
    if allowed:
        assert sdk.OpenAlgoConfig.from_mapping(
            {"host_url": host_url}
        ).host_url == host_url.rstrip("/")
    else:
        with pytest.raises(ValueError):
            sdk.OpenAlgoConfig.from_mapping({"host_url": host_url})


def test_only_the_live_environment_is_accepted():
    with pytest.raises(ValueError, match="only live"):
        sdk.OpenAlgoConfig.from_mapping({"environment": "paper"})
    assert (
        sdk.build_config({}, {"host": "ignored", "port": 1, "host_url": None}).host_url
        == ""
    )


# --------------------------------------------------------------------------- connection store and CLI


def test_vault_connection_supplies_host_and_key_and_cli_renders_books(
    monkeypatch, capsys
):
    from cli import _legacy
    from src.trading import connections

    class Vault:
        def load(self, connection_id, fields):
            assert connection_id == "openalgo-main"
            assert set(fields) == {"host_url", "api_key"}
            return {"host_url": HOST, "api_key": KEY}

    monkeypatch.setattr(
        connections,
        "ConnectionStore",
        lambda: SimpleNamespace(
            get=lambda _: SimpleNamespace(profile_id=PROFILE, id="openalgo-main"),
            credentials=Vault(),
        ),
    )
    _replay(
        monkeypatch,
        {
            "funds": "funds_live",
            "positionbook": "positionbook_live",
            "holdings": "holdings_live",
        },
    )
    assert _legacy.cmd_connector_positions(PROFILE, connection_id="openalgo-main") == 0
    output = capsys.readouterr().out
    assert (
        "net_positions" in output
        and "broker_books_unaggregated" in output
        and "live_broker" in output
    )
    assert _legacy.cmd_connector_account(PROFILE, connection_id="openalgo-main") == 0
    output = capsys.readouterr().out
    assert "available_cash" in output and "320.66" in output
    assert KEY not in output
    with pytest.raises(ValueError, match="OS credential vault"):
        service.get_positions(
            PROFILE, connection_id="openalgo-main", host_url="https://evil.test"
        )


def test_real_connection_store_accepts_reads_but_portfolio_rejects_them(tmp_path):
    from src.portfolio.config import PortfolioSettings, parse_settings, source_catalog
    from src.trading.connections import ConnectionStore, readonly_profile_catalog

    store = ConnectionStore(tmp_path / "connections.json")
    assert store.create("openalgo-main", PROFILE, "OpenAlgo").profile_id == PROFILE
    row = next(row for row in readonly_profile_catalog() if row.get("id") == PROFILE)
    assert row["portfolio_eligible"] is False
    assert source_catalog(PortfolioSettings(), connection_store=store) == []
    with pytest.raises(ValueError, match="not eligible"):
        parse_settings(
            {"sources": [{"connection_id": "openalgo-main"}]}, connection_store=store
        )
