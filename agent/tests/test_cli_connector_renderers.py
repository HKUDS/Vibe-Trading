"""Regression (#735): connector CLI renderers must tolerate broker_sdk schemas.

The shared ``connector positions`` / ``connector account`` renderers were written
for the IBKR result shape (``position``/``avg_cost``/``sec_type``/``summary``).
Longbridge (and other ``broker_sdk`` connectors) return ``quantity``/``cost_price``/
``market``/``balances``, so every non-matching key rendered as an empty cell.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cli import _legacy

pytestmark = pytest.mark.unit


def test_first_present_keeps_zero_and_skips_none() -> None:
    row = {"position": 0.0, "quantity": 5.0}
    # A real zero position must win over the fallback key, not be skipped.
    assert _legacy._first_present(row, "position", "quantity") == 0.0
    assert _legacy._first_present({"quantity": 5.0}, "position", "quantity") == 5.0
    assert _legacy._first_present({"position": None, "quantity": 5.0}, "position", "quantity") == 5.0
    assert _legacy._first_present({}, "position", "quantity") is None


def test_connector_positions_renders_longbridge_schema(capsys) -> None:
    longbridge_result = {
        "status": "ok",
        "profile_id": "longbridge-paper-trade",
        "positions": [
            {
                "symbol": "AAPL.US",
                "symbol_name": "Apple",
                "quantity": 20.0,
                "available_quantity": 20.0,
                "cost_price": 321.5,
                "currency": "USD",
                "market": "US",
            }
        ],
    }
    with patch("src.trading.service.get_positions", return_value=longbridge_result):
        rc = _legacy.cmd_connector_positions("longbridge-paper-trade")

    assert rc == _legacy.EXIT_SUCCESS
    out = capsys.readouterr().out
    assert "AAPL.US" in out
    assert "20" in out       # quantity → Qty
    assert "321.5" in out    # cost_price → Avg Cost
    assert "US" in out       # market → Type


def test_connector_account_renders_balances_table(capsys) -> None:
    longbridge_account = {
        "status": "ok",
        "profile_id": "longbridge-paper-trade",
        "balances": [
            {
                "currency": "USD",
                "total_cash": 10_000.0,
                "net_assets": 12_345.0,
                "buy_power": 20_000.0,
                "init_margin": 0.0,
                "maintenance_margin": 0.0,
            }
        ],
    }
    rc = _legacy._print_connector_account(longbridge_account)

    assert rc == _legacy.EXIT_SUCCESS
    out = capsys.readouterr().out
    assert "No account summary returned." not in out
    assert "USD" in out
    assert "12" in out and "345" in out  # net_assets 12,345 rendered


def test_account_summary_rows_keep_zero_and_skip_none() -> None:
    rows = _legacy._account_summary_rows({"cash": "0", "pattern_day_trader": None, "pnl": {"equity": 1.5}})
    # A 0 cash balance is a real figure here, unlike in the remote-MCP flattener.
    assert rows == [("cash", "0"), ("pnl.equity", "1.5")]


def test_connector_account_renders_alpaca_account_mapping(capsys) -> None:
    """Regression (#1064): Alpaca reports its fields under ``account``."""
    alpaca_account = {
        "status": "ok",
        "profile_id": "alpaca-paper-trade",
        "profile": "paper",
        "is_paper": True,
        "host": "https://paper-api.alpaca.markets",
        "account": {
            "account_number": "PA12345678",
            "status": "AccountStatus.ACTIVE",
            "currency": "USD",
            "cash": "100000",
            "equity": "100000",
            "buying_power": "400000",
            "portfolio_value": "100000",
            "pattern_day_trader": None,
            "trading_blocked": False,
        },
    }
    rc = _legacy._print_connector_account(alpaca_account)

    assert rc == _legacy.EXIT_SUCCESS
    out = capsys.readouterr().out
    assert "No account summary returned." not in out
    assert "PA12345678" in out
    assert "buying_power" in out and "400000" in out
    assert "pattern_day_trader" not in out


def test_connector_account_ignores_a_non_mapping_account_field(capsys) -> None:
    """Tiger reports a plain account id in ``account``, not a field map."""
    tiger_account = {"status": "ok", "profile_id": "tiger-paper-sdk", "account": "20240101"}
    rc = _legacy._print_connector_account(tiger_account)

    assert rc == _legacy.EXIT_SUCCESS
    assert "No account summary returned." in capsys.readouterr().out


def test_connector_account_still_handles_ibkr_summary(capsys) -> None:
    ibkr_account = {
        "status": "ok",
        "profile_id": "ibkr-local",
        "accounts": ["DU123"],
        "summary": [{"account": "DU123", "tag": "NetLiquidation", "value": "50000", "currency": "USD"}],
    }
    rc = _legacy._print_connector_account(ibkr_account)

    assert rc == _legacy.EXIT_SUCCESS
    out = capsys.readouterr().out
    assert "NetLiquidation" in out
    assert "50000" in out


def _profile(transport: str):
    from src.trading.types import TradingProfile

    return TradingProfile(
        id=f"probe-{transport}",
        connector="alpaca",
        label="Probe",
        environment="paper",
        transport=transport,
        capabilities=("account.read",),
        readonly=True,
    )


def test_connector_check_hides_remote_mcp_rows_for_broker_sdk(capsys) -> None:
    """Regression (#1064): a broker_sdk report has no OAuth/capability state."""
    report = {"status": "ok", "host": "https://paper-api.alpaca.markets"}
    with patch.object(_legacy, "_selected_profile_or", return_value=_profile("broker_sdk")):
        with patch("src.trading.service.check_connection", return_value=report):
            rc = _legacy.cmd_connector_check("probe-broker_sdk")

    assert rc == _legacy.EXIT_SUCCESS
    out = capsys.readouterr().out
    assert "Connector profile is ready." in out
    for label in ("Configured", "OAuth token", "Capabilities"):
        assert label not in out


def test_connector_check_still_reports_remote_mcp_authorization(capsys) -> None:
    report = {"status": "ok", "configured": True, "oauth_token_present": True, "capabilities": ["account.read"]}
    with patch.object(_legacy, "_selected_profile_or", return_value=_profile("remote_mcp")):
        with patch("src.trading.service.check_connection", return_value=report):
            rc = _legacy.cmd_connector_check("probe-remote_mcp")

    assert rc == _legacy.EXIT_SUCCESS
    out = capsys.readouterr().out
    assert "OAuth token" in out and "present" in out
    assert "account.read" in out
