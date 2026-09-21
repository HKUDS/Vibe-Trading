"""Regression (#735): connector CLI renderers must tolerate broker_sdk schemas.

The shared ``connector positions`` / ``connector account`` renderers were written
for the IBKR result shape (``position``/``avg_cost``/``sec_type``/``summary``).
Longbridge (and other ``broker_sdk`` connectors) return ``quantity``/``cost_price``/
``market``/``balances``, so every non-matching key rendered as an empty cell.
"""

from __future__ import annotations

from types import SimpleNamespace
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


def test_connector_account_renders_ccxt_asset_balances(capsys) -> None:
    """#1539: Binance spot rows are asset/free/used/total, not Longbridge's keys."""
    from src.trading.connectors.binance.shaping import nonzero_balances

    ccxt_balance = {
        "info": {},
        "BTC": {"free": 0.5, "used": 0.125, "total": 0.625},
        "USDT": {"free": 1000.0, "used": 0.0, "total": 1000.0},
        "DUST": {"free": 0.0, "used": 0.0, "total": 0.0},
        "free": {}, "used": {}, "total": {},
    }
    binance_account = {
        "status": "ok",
        "profile": "paper",
        "profile_id": "binance-paper-trade",
        "is_testnet": True,
        "balances": nonzero_balances(ccxt_balance),
    }

    rc = _legacy._print_connector_account(binance_account)

    assert rc == _legacy.EXIT_SUCCESS
    out = capsys.readouterr().out
    assert "Net Assets" not in out, "a coin quantity must not be labelled net assets"
    btc = next(line for line in out.splitlines() if "BTC" in line)
    assert "0.5" in btc and "0.125" in btc and "0.625" in btc
    assert any("USDT" in line and "1000.0" in line for line in out.splitlines())
    assert "DUST" not in out
    assert "2 non-zero balances" in out


def test_connector_account_renders_futu_assets(capsys) -> None:
    """#1539: Futu's accinfo_query rows arrive as ``assets``, not ``balances``."""
    from src.trading.connectors.futu.sdk import _account_to_dict

    futu_account = {
        "status": "ok",
        "profile_id": "futu-paper-trade",
        "trd_env": "SIMULATE",
        "acc_id": 1,
        "assets": [
            _account_to_dict(
                {
                    "power": 250000.0,
                    "total_assets": 123456.0,
                    "cash": 23456.0,
                    "market_val": 100000.0,
                    "available_funds": 20000.0,
                    "securities_assets": 123456.0,
                    "currency": "hkd",
                }
            )
        ],
    }

    rc = _legacy._print_connector_account(futu_account)

    assert rc == _legacy.EXIT_SUCCESS
    out = capsys.readouterr().out
    assert "No account summary returned." not in out
    row = next(line for line in out.splitlines() if "HKD" in line)
    for value in ("123456.0", "23456.0", "100000.0", "20000.0", "250000.0"):
        assert value in row


def test_connector_account_renders_trading212_cash_and_metadata(capsys) -> None:
    """#1539: Trading 212 splits the account into ``cash`` and ``metadata`` mappings."""
    trading212_account = {
        "status": "ok",
        "profile_id": "trading212-live-readonly",
        "cash": {"free": 1000.5, "total": 1500.25, "invested": 499.75, "ppl": 12.5, "blocked": 0.0},
        "metadata": {"currencyCode": "EUR", "id": 4242},
    }

    rc = _legacy._print_connector_account(trading212_account)

    assert rc == _legacy.EXIT_SUCCESS
    out = capsys.readouterr().out
    assert "No account summary returned." not in out
    assert "cash.free" in out and "1000.5" in out
    assert "cash.total" in out and "1500.25" in out
    assert "metadata.currencyCode" in out and "EUR" in out


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


def test_connector_account_renders_direct_sdk_account_mapping(capsys) -> None:
    alpaca_account = {
        "status": "ok",
        "profile_id": "alpaca-paper-trade",
        "profile": "paper",
        "account": {
            "account_number": "PA123",
            "status": "AccountStatus.ACTIVE",
            "currency": "USD",
            "cash": "100000",
            "equity": "100000",
            "buying_power": "400000",
            "pattern_day_trader": False,
            "trading_blocked": False,
        },
    }

    rc = _legacy._print_connector_account(alpaca_account)

    assert rc == _legacy.EXIT_SUCCESS
    out = capsys.readouterr().out
    assert "No account summary returned." not in out
    assert "PA123" in out
    assert "USD" in out
    assert "buying_power" in out
    assert "400000" in out
    assert "trading_blocked" in out
    assert "False" in out


def test_connector_check_uses_sdk_diagnostics_without_oauth_rows(capsys) -> None:
    profile = SimpleNamespace(
        id="alpaca-paper-trade",
        connector="alpaca",
        environment="paper",
        transport="broker_sdk",
    )
    report = {
        "status": "ok",
        "sdk": {"package": "alpaca-py", "installed": True},
        "tap": False,
    }

    with (
        patch("cli._legacy._selected_profile_or", return_value=profile),
        patch("src.trading.service.check_connection", return_value=report),
    ):
        rc = _legacy.cmd_connector_check("alpaca-paper-trade")

    assert rc == _legacy.EXIT_SUCCESS
    out = capsys.readouterr().out
    assert "Connector profile is ready." in out
    assert "alpaca-py" in out
    assert "installed" in out
    assert "OAuth token" not in out
    assert "Configured" not in out
    assert "Capabilities" not in out


# --- #1150: `connector orders` had no coverage at all -------------------------
#
# `cmd_connector_orders` was written against the IBKR row shape
# (``{"contract": ..., "order": ..., "status": {"status": ...}}``). broker_sdk
# connectors return a flat row with ``symbol``/``side``/``quantity`` and a
# plain-string ``status``, so every column but Account rendered empty. The
# renderer had no test, which is why the whole column set could go blank
# unnoticed.


def test_enum_text_strips_sdk_enum_reprs_but_keeps_symbols_and_numbers() -> None:
    # SDK enums arrive already stringified by the broker_sdk layer.
    assert _legacy._enum_text("OrderSide.BUY") == "BUY"
    assert _legacy._enum_text("OrderStatus.PARTIALLY_FILLED") == "PARTIALLY_FILLED"
    # A class-name prefix must look like CamelCase, so class-B tickers survive.
    assert _legacy._enum_text("BRK.B") == "BRK.B"
    assert _legacy._enum_text("BRK.A") == "BRK.A"
    # Decimals and already-plain values are returned untouched.
    assert _legacy._enum_text("716.64") == "716.64"
    assert _legacy._enum_text("BUY") == "BUY"
    assert _legacy._enum_text(None) == ""


def test_connector_orders_renders_flat_broker_sdk_row(capsys) -> None:
    alpaca_result = {
        "status": "ok",
        "profile_id": "alpaca-paper-trade",
        "open_orders": [
            {
                "account": "PA3ABCD",
                "symbol": "AAPL",
                "side": "OrderSide.BUY",
                "order_type": "OrderType.LIMIT",
                "quantity": 10,
                "limit_price": 187.5,
                "status": "OrderStatus.NEW",
            }
        ],
    }
    with patch("src.trading.service.get_open_orders", return_value=alpaca_result):
        rc = _legacy.cmd_connector_orders("alpaca-paper-trade")

    assert rc == _legacy.EXIT_SUCCESS
    out = capsys.readouterr().out
    assert "AAPL" in out       # symbol on the flat row, not under contract
    assert "BUY" in out        # side → Action, enum prefix stripped
    assert "LIMIT" in out      # order_type enum prefix stripped
    assert "10" in out         # quantity → Qty
    assert "187.5" in out      # limit_price
    assert "NEW" in out        # plain-string status, enum prefix stripped
    assert "OrderSide" not in out
    assert "OrderStatus" not in out


def test_connector_orders_keeps_class_b_ticker_intact(capsys) -> None:
    result = {
        "status": "ok",
        "profile_id": "alpaca-paper-trade",
        "open_orders": [
            {
                "account": "PA3ABCD",
                "symbol": "BRK.B",
                "side": "OrderSide.SELL",
                "order_type": "OrderType.MARKET",
                "quantity": 1,
                "status": "OrderStatus.NEW",
            }
        ],
    }
    with patch("src.trading.service.get_open_orders", return_value=result):
        rc = _legacy.cmd_connector_orders("alpaca-paper-trade")

    assert rc == _legacy.EXIT_SUCCESS
    out = capsys.readouterr().out
    assert "BRK.B" in out  # must not be stripped to "B"
    assert "SELL" in out


def test_connector_orders_still_renders_the_nested_ibkr_row(capsys) -> None:
    ibkr_result = {
        "status": "ok",
        "profile_id": "ibkr-local",
        "open_orders": [
            {
                "contract": {"local_symbol": "MSFT", "symbol": "MSFT"},
                "order": {
                    "account": "DU123",
                    "action": "BUY",
                    "order_type": "LMT",
                    "total_quantity": 100,
                    "limit_price": 401.25,
                },
                "status": {"status": "PreSubmitted"},
            }
        ],
    }
    with patch("src.trading.service.get_open_orders", return_value=ibkr_result):
        rc = _legacy.cmd_connector_orders("ibkr-local")

    assert rc == _legacy.EXIT_SUCCESS
    out = capsys.readouterr().out
    assert "MSFT" in out
    assert "DU123" in out
    assert "LMT" in out
    assert "100" in out
    assert "401.25" in out
    assert "PreSubmitted" in out  # the dict branch must survive the flat-row fix
