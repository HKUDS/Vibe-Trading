"""Read-path regressions for cash disclosures and sanitized connector errors."""

import cli.commands.connectors as _cmd_connectors
import cli.commands.portfolio as _cmd_portfolio

from decimal import Decimal
import json

import pytest

from src.portfolio.config import PortfolioSettingsStore
from src.portfolio.service import PortfolioService, _portfolio_error_details
from src.portfolio.store import PortfolioStore


def _service(tmp_path, broker, reader, progress=None):
    settings = PortfolioSettingsStore(tmp_path / "settings.json")
    profile = f"{broker}-live-sdk-readonly"
    settings.connection_store.ensure(broker, profile, broker)
    settings.save({"display_currency": "USD", "sources": [{"connection_id": broker}]})
    return PortfolioService(
        PortfolioStore(tmp_path / "portfolio.sqlite"),
        settings_store=settings,
        get_account=reader,
        get_positions=lambda *args, **kwargs: {"positions": []},
        get_quote=lambda *args, **kwargs: {},
        fx_fetcher=lambda: (Decimal("7.2"), Decimal("7.8"), "2026-10-23T00:00:00Z"),
        progress_callback=progress,
    )


@pytest.mark.parametrize(
    "message",
    [
        "request https://api.example/read?signature=synthetic-signature&api_key=synthetic-key",
        "Authorization: Bearer synthetic-bearer",
        '{"api_key": "synthetic-key", "signature": "synthetic-signature"}',
        "failed https://user:synthetic-password@api.example/read",
    ],
)
def test_errors_use_shared_credential_redaction(message):
    code, error = _portfolio_error_details(message)
    assert code == "ConnectorReadError"
    for secret in ("synthetic-signature", "synthetic-key", "synthetic-bearer", "synthetic-password"):
        assert secret not in error
    assert _portfolio_error_details(error)[1] == error


def test_binance_restriction_is_distinct_from_other_failures():
    assert (
        _portfolio_error_details("HTTP 451 restricted location", broker="binance")[0] == "binance_restricted_location"
    )
    for text, broker in [
        ("HTTP 451 other error", "binance"),
        ("HTTP 401 eligibility", "binance"),
        ("HTTP 451 eligibility", "other"),
    ]:
        assert _portfolio_error_details(text, broker=broker)[0] == "ConnectorReadError"


def test_failed_reads_progress_and_old_snapshots_are_sanitized(tmp_path):
    message = "HTTP 500 https://api.example/read?signature=synthetic-signature Authorization: Bearer synthetic-bearer"

    def fail(*args, **kwargs):
        raise RuntimeError(message)

    progress = []
    service = _service(tmp_path, "binance", fail, lambda *args: progress.append(args))
    snapshot = service.refresh()
    assert not snapshot["complete"]
    assert "synthetic-" not in json.dumps(
        [snapshot, progress, service.latest(), service.snapshot_by_id(snapshot["snapshot_id"])]
    )
    # Simulate an immutable snapshot persisted before the sanitization fix.
    snapshot["snapshot_id"] = "legacy-errors"
    snapshot["accounts"][0]["error"] = message
    service.store.save_snapshot(snapshot)
    assert "synthetic-" not in json.dumps(service.snapshot_by_id("legacy-errors"))
    assert "synthetic-signature" in service.store.get("legacy-errors")["accounts"][0]["error"]


def test_longbridge_cash_survives_store_api_context_and_cli(tmp_path, capsys, monkeypatch):
    account = {
        "balances": [
            {
                "currency": "HKD",
                "net_assets": 7800,
                "total_cash": 7300,
                "max_finance_amount": 5000,
                "remaining_finance_amount": 0,
                "cash_infos": [
                    {
                        "currency": "USD",
                        "available_cash": 1000,
                        "withdraw_cash": None,
                        "frozen_cash": 0,
                        "settling_cash": 0,
                    },
                    {
                        "currency": "HKD",
                        "available_cash": -500,
                        "withdraw_cash": -600,
                        "frozen_cash": 500,
                        "settling_cash": -200,
                    },
                ],
            }
        ]
    }
    service = _service(tmp_path, "longbridge", lambda *args, **kwargs: account)
    snapshot = service.refresh()
    assert snapshot["complete"]
    assert snapshot["totals"]["usd"] == 1000
    details = snapshot["accounts"][0]["balance_details"]
    assert details[0]["cash_infos"][1]["available_cash"] == -500
    assert details[0]["cash_infos"][0]["withdraw_cash"] is None
    assert details[0]["remaining_finance_amount"] == 0
    assert service.latest()["accounts"][0]["balance_details"] == details
    assert service.analysis_context()["account_allocation"][0]["balance_details"] == details

    from src.tools import portfolio_tool

    monkeypatch.setattr(portfolio_tool, "PortfolioService", lambda: service)
    result = json.loads(portfolio_tool.PortfolioSummaryTool().execute())
    assert result["context"]["account_allocation"][0]["balance_details"] == details


    _cmd_connectors._print_connector_balances(account)
    _cmd_portfolio.cmd_portfolio_show(service=service)
    output = capsys.readouterr().out
    assert "-500" in output and "Remaining financing" in output and "USD" in output

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.api import portfolio_routes

    monkeypatch.setattr(portfolio_routes, "PortfolioService", lambda **kwargs: service)
    app = FastAPI()
    app.dependency_overrides[portfolio_routes.require_auth] = lambda: None
    portfolio_routes.register_portfolio_routes(app)
    with TestClient(app) as client:
        response = client.get("/api/portfolio")
    assert response.status_code == 200
    assert response.json()["snapshot"]["accounts"][0]["balance_details"] == details
