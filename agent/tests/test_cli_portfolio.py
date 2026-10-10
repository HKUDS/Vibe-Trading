"""CLI surface for the read-only portfolio: ``vibe-trading portfolio show|refresh|sources``.

The Web UI and the ``portfolio_summary`` tool already expose the snapshot; the
CLI is the third surface the project's full-stack rule asks for. These tests
drive the renderers through a stub service so no connector, network or runtime
directory is touched.
"""

from __future__ import annotations

from argparse import Namespace

import pytest

from cli import _legacy

pytestmark = pytest.mark.unit


class _Service:
    """Minimal stand-in for ``PortfolioService``."""

    def __init__(self, snapshot=None, sources=(), refresh_error=None) -> None:
        self._snapshot = snapshot
        self._sources = list(sources)
        self._refresh_error = refresh_error
        self.refresh_calls = 0

    def latest(self):
        """Return the scripted snapshot (``None`` when nothing is stored)."""
        return self._snapshot

    def snapshot_by_id(self, snapshot_id):
        return self._snapshot if self._snapshot and self._snapshot["snapshot_id"] == snapshot_id else None

    def refresh(self):
        """Return the scripted snapshot or raise the scripted error."""
        self.refresh_calls += 1
        if self._refresh_error is not None:
            raise self._refresh_error
        return self._snapshot

    def sources(self):
        """Return the scripted source catalog rows."""
        return list(self._sources)


_SNAPSHOT = {
    "snapshot_id": "abc",
    "created_at": "2026-08-22T05:00:00+00:00",
    "complete": False,
    "totals": {"usd": 1500.0, "cny": 10800.0},
    "accounts": [
        {
            "source_id": "ibkr",
            "label": "IBKR",
            "broker": "ibkr",
            "status": "ok",
            "total_usd": 1500.0,
            "last_success_at": "2026-08-22T05:00:00+00:00",
        },
        {
            "source_id": "binance",
            "label": "Binance",
            "broker": "binance",
            "status": "error",
            "error": "ConnectionError",
            "total_usd": None,
            "last_success_at": None,
        },
    ],
    "combined_holdings": [
        {
            "symbol": "AAPL",
            "asset_type": "stock",
            "market_value_usd": 1500.0,
            "unrealized_pnl_usd": 250.0,
            "sources": ["IBKR"],
        }
    ],
    "warnings": ["These sources failed to refresh and their value is excluded: Binance."],
}


def test_show_prints_totals_sources_holdings_and_warnings(capsys) -> None:
    rc = _legacy.cmd_portfolio_show(service=_Service(snapshot=_SNAPSHOT))
    out = capsys.readouterr().out
    assert rc == _legacy.EXIT_SUCCESS
    assert "INCOMPLETE" in out
    assert "1,500.00" in out
    assert "IBKR" in out and "Binance" in out
    assert "excluded" in out  # the failed source has no total
    assert "AAPL" in out and "100.0%" in out
    assert "failed to refresh" in out


def test_show_without_snapshot_points_at_refresh(capsys) -> None:
    rc = _legacy.cmd_portfolio_show(service=_Service(snapshot=None))
    out = capsys.readouterr().out
    assert rc == _legacy.EXIT_SUCCESS
    assert "portfolio refresh" in out


def test_show_pinned_snapshot_and_missing_id_never_falls_back(capsys) -> None:
    service = _Service(snapshot=_SNAPSHOT)
    assert _legacy.cmd_portfolio_show(service, snapshot_id="abc") == _legacy.EXIT_SUCCESS
    assert "AAPL" in capsys.readouterr().out
    assert _legacy.cmd_portfolio_show(service, snapshot_id="gone") == _legacy.EXIT_RUN_FAILED
    assert "unavailable" in capsys.readouterr().out


def test_refresh_prints_and_exits_nonzero_when_incomplete(capsys) -> None:
    service = _Service(snapshot=_SNAPSHOT)
    rc = _legacy.cmd_portfolio_refresh(service=service)
    out = capsys.readouterr().out
    assert service.refresh_calls == 1
    assert rc == _legacy.EXIT_RUN_FAILED
    assert "INCOMPLETE" in out


def test_refresh_exits_zero_for_a_complete_snapshot() -> None:
    complete = {**_SNAPSHOT, "complete": True, "accounts": _SNAPSHOT["accounts"][:1], "warnings": []}
    assert _legacy.cmd_portfolio_refresh(service=_Service(snapshot=complete)) == _legacy.EXIT_SUCCESS


def test_refresh_reports_a_runtime_error_instead_of_crashing(capsys) -> None:
    rc = _legacy.cmd_portfolio_refresh(
        service=_Service(refresh_error=RuntimeError("Add and enable at least one read-only account"))
    )
    out = capsys.readouterr().out
    assert rc == _legacy.EXIT_RUN_FAILED
    assert "at least one read-only account" in out


def test_sources_marks_selected_and_credentialed_rows(capsys) -> None:
    rows = [
        {
            "connection_id": "ibkr-live",
            "label": "IBKR main",
            "connector": "ibkr",
            "environment": "live",
            "transport": "local_tws",
            "selected": True,
            "credentials_configured": False,
        },
        {
            "connection_id": "mybroker-live",
            "label": "Plugin",
            "connector": "mybroker",
            "environment": "live",
            "transport": "local_plugin",
            "selected": False,
            "credentials_configured": True,
        },
    ]
    rc = _legacy.cmd_portfolio_sources(service=_Service(sources=rows))
    out = capsys.readouterr().out
    assert rc == _legacy.EXIT_SUCCESS
    assert "ibkr-live" in out and "mybroker-live" in out
    assert "local_plugin" in out
    assert "*" in out  # the selected marker


def test_sources_without_connections_explains_where_to_create_one(capsys) -> None:
    _legacy.cmd_portfolio_sources(service=_Service(sources=[]))
    assert "No local connections yet" in capsys.readouterr().out


def test_dispatch_defaults_to_show_and_routes_subcommands(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(_legacy, "cmd_portfolio_show", lambda **kwargs: calls.append(kwargs.get("snapshot_id") or "show") or 0)
    monkeypatch.setattr(_legacy, "cmd_portfolio_refresh", lambda: calls.append("refresh") or 0)
    monkeypatch.setattr(_legacy, "cmd_portfolio_sources", lambda: calls.append("sources") or 0)
    assert _legacy._dispatch_portfolio(Namespace(portfolio_command=None)) == 0
    assert _legacy._dispatch_portfolio(Namespace(portfolio_command="refresh")) == 0
    assert _legacy._dispatch_portfolio(Namespace(portfolio_command="sources")) == 0
    assert calls == ["show", "refresh", "sources"]
    assert _legacy._dispatch_portfolio(Namespace(portfolio_command="show", snapshot_id="abc")) == 0
    assert calls[-1] == "abc"
    assert _legacy._dispatch_portfolio(Namespace(portfolio_command="bogus")) == _legacy.EXIT_USAGE_ERROR


def test_parser_registers_the_portfolio_subcommands() -> None:
    parser = _legacy._build_parser()
    assert parser.parse_args(["portfolio"]).portfolio_command is None
    assert parser.parse_args(["portfolio", "show", "--snapshot-id", "abc"]).snapshot_id == "abc"
    for sub in ("show", "refresh", "sources"):
        args = parser.parse_args(["portfolio", sub])
        assert args.command == "portfolio" and args.portfolio_command == sub
