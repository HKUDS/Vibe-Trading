"""Tests for connector CLI renderers with schema-tolerant key fallbacks.

Refs #735 — Longbridge connector returns its own key schema
(quantity/cost_price/market/balances) instead of the IBKR-style keys
(position/avg_cost/sec_type/summary) assumed by the CLI renderers.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# _print_connector_account — balances fallback
# ---------------------------------------------------------------------------

class TestPrintConnectorAccount:
    def test_renders_ibkr_summary(self, capsys: pytest.CaptureFixture[str]) -> None:
        """IBKR-style summary rows render as before."""
        from cli._legacy import EXIT_SUCCESS, _print_connector_account

        result = {
            "accounts": ["U1234567"],
            "summary": [
                {"account": "U1234567", "tag": "NetLiquidation", "value": "100000.00", "currency": "USD"},
                {"account": "U1234567", "tag": "Cash", "value": "5000.00", "currency": "USD"},
            ],
            "profile_id": "ibkr-test",
        }
        assert _print_connector_account(result) == EXIT_SUCCESS
        out = capsys.readouterr().out
        assert "U1234567" in out
        assert "NetLiquidation" in out
        assert "100000.00" in out

    def test_renders_longbridge_balances(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Longbridge-style balances rows render as a balances table."""
        from cli._legacy import EXIT_SUCCESS, _print_connector_account

        result = {
            "status": "ok",
            "profile": "longbridge-paper-trade",
            "paper_guard": "config_declared",
            "profile_id": "longbridge-paper-trade",
            "balances": [
                {"currency": "USD", "total_cash": "5000.00", "net_assets": "50000.00",
                 "buy_power": "10000.00", "init_margin": "0.00", "maintenance_margin": "0.00"},
                {"currency": "HKD", "total_cash": "100000.00", "net_assets": "200000.00",
                 "buy_power": "200000.00", "init_margin": "0.00", "maintenance_margin": "0.00"},
            ],
        }
        assert _print_connector_account(result) == EXIT_SUCCESS
        out = capsys.readouterr().out
        assert "Balances" in out
        assert "USD" in out
        assert "HKD" in out
        assert "5000.00" in out
        assert "50000.00" in out
        assert "Total Cash" in out
        assert "Net Assets" in out

    def test_renders_no_data_message_when_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        """When neither summary nor balances is present, show the no-data message."""
        from cli._legacy import EXIT_SUCCESS, _print_connector_account

        result = {
            "accounts": [],
            "profile_id": "empty-test",
        }
        assert _print_connector_account(result) == EXIT_SUCCESS
        out = capsys.readouterr().out
        assert "No account summary returned" in out

    def test_balances_show_accounts_label(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Balances rendering still shows the Accounts line."""
        from cli._legacy import _print_connector_account

        result = {
            "accounts": [],
            "profile_id": "test",
            "balances": [{"currency": "USD"}],
        }
        _print_connector_account(result)
        out = capsys.readouterr().out
        assert "Accounts:" in out


# ---------------------------------------------------------------------------
# cmd_connector_positions — key-aliased rendering
# ---------------------------------------------------------------------------

_SERVICE_PATH = "src.trading.service.get_positions"


class TestCmdConnectorPositions:
    def test_renders_ibkr_keys(self, capsys: pytest.CaptureFixture[str]) -> None:
        """IBKR-style position keys render as before (backward compat)."""
        from cli._legacy import EXIT_SUCCESS, cmd_connector_positions

        ibkr_positions = {
            "status": "ok",
            "profile_id": "ibkr-test",
            "positions": [
                {"account": "U1234567", "symbol": "AAPL", "local_symbol": "AAPL",
                 "sec_type": "STK", "position": "100", "avg_cost": "150.00", "currency": "USD"},
            ],
        }
        with patch(_SERVICE_PATH, return_value=ibkr_positions):
            assert cmd_connector_positions("ibkr-test") == EXIT_SUCCESS
        out = capsys.readouterr().out
        assert "AAPL" in out
        assert "100" in out
        assert "150.00" in out
        assert "STK" in out

    def test_renders_longbridge_keys(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Longbridge-style keys (quantity/cost_price/market) render through fallback aliases."""
        from cli._legacy import EXIT_SUCCESS, cmd_connector_positions

        longbridge_positions = {
            "status": "ok",
            "profile_id": "longbridge-paper-trade",
            "positions": [
                {"symbol": "AAPL.US", "symbol_name": "Apple Inc", "quantity": 20.0,
                 "available_quantity": 20.0, "cost_price": 185.50,
                 "currency": "USD", "market": "US"},
                {"symbol": "0700.HK", "symbol_name": "Tencent", "quantity": 100.0,
                 "available_quantity": 100.0, "cost_price": 350.0,
                 "currency": "HKD", "market": "HK"},
            ],
        }
        with patch(_SERVICE_PATH, return_value=longbridge_positions):
            assert cmd_connector_positions("longbridge-paper-trade") == EXIT_SUCCESS
        out = capsys.readouterr().out
        assert "AAPL.US" in out
        assert "0700.HK" in out
        assert "20.0" in out
        assert "100.0" in out
        assert "185.5" in out
        assert "350.0" in out
        assert "HK" in out  # market fallback for sec_type
        assert "US" in out

    def test_renders_symbol_fallback_for_local_symbol(self, capsys: pytest.CaptureFixture[str]) -> None:
        """When local_symbol is missing, symbol is used."""
        from cli._legacy import cmd_connector_positions

        result = {
            "status": "ok",
            "profile_id": "test",
            "positions": [
                {"symbol": "TSLA", "sec_type": "STK", "position": "50",
                 "avg_cost": "200.00", "currency": "USD"},
            ],
        }
        with patch(_SERVICE_PATH, return_value=result):
            cmd_connector_positions("test")
        out = capsys.readouterr().out
        assert "TSLA" in out

    def test_empty_positions_shows_no_data_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Empty positions list renders the no-data message."""
        from cli._legacy import cmd_connector_positions

        result = {"status": "ok", "profile_id": "test", "positions": []}
        with patch(_SERVICE_PATH, return_value=result):
            cmd_connector_positions("test")
        out = capsys.readouterr().out
        assert "No positions returned" in out

    def test_error_status_renders_error_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Error status renders the error text."""
        from cli._legacy import EXIT_RUN_FAILED, cmd_connector_positions

        result = {"status": "error", "error": "Connection refused"}
        with patch(_SERVICE_PATH, return_value=result):
            assert cmd_connector_positions("test") == EXIT_RUN_FAILED
        out = capsys.readouterr().out
        assert "Connection refused" in out
