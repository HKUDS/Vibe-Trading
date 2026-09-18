"""Robinhood live trading is bound to one account (#1442).

One Robinhood login reaches several accounts. The mandate names the one the
user picked at commit, and the runner reads, the runner's own orders, the
pre-trade gate reads, the gate's forwarded order and the ceiling fetch all use
that account. Nothing falls back to a default account. Replies are the #1428
shapes from ``tests/robinhood_mcp_helpers.py``.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

import api_server
import src.live.paths as paths
from src.live import order_guard
from src.live.mandate.store import load_mandate
from src.tools.propose_mandate_tool import ProposeMandateProfilesTool
from tests import robinhood_mcp_helpers as rh
from tests.test_mandate_enforcement import _mandate, _spec, _write_mandate

pytestmark = pytest.mark.unit

ACCOUNT = "5QR12345"


# --------------------------------------------------------------------------- #
# Pre-trade gate                                                               #
# --------------------------------------------------------------------------- #


@pytest.fixture
def live_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "get_runtime_root", lambda: tmp_path)
    return tmp_path


class _GateBroker:
    """Answers the gate's reads and records the forwarded order."""

    def __init__(self, *, positions: list[dict] | None = None, portfolio: dict | None = None) -> None:
        self.server_name = "robinhood"
        self.positions = rh.positions(positions or [])
        self.portfolio = portfolio or rh.portfolio()
        self.reads: list[tuple[str, dict]] = []
        self.order_calls: list[dict[str, Any]] = []

    def call_tool(self, remote_name: str, arguments: dict, *, local_name: str | None = None) -> dict:
        if remote_name == "get_equity_positions":
            self.reads.append((remote_name, dict(arguments)))
            return self.positions
        if remote_name == "get_portfolio":
            self.reads.append((remote_name, dict(arguments)))
            return self.portfolio
        if remote_name == "get_equity_quotes":
            return {"status": "error", "error": "quote shape unmapped"}
        self.order_calls.append(dict(arguments))
        return {"status": "ok", "order_id": "rh_1", "state": "accepted"}


def _bound_mandate(account_ref: str = ACCOUNT, **caps: Any):
    mandate = _mandate(**caps)
    return replace(mandate, consent=replace(mandate.consent, account_ref=account_ref))


def _guard(adapter: _GateBroker) -> order_guard.LiveOrderGuardTool:
    return order_guard.LiveOrderGuardTool(adapter, _spec(), broker="robinhood", session_id="s1")


def _order(guard: order_guard.LiveOrderGuardTool, **extra: Any) -> dict:
    return json.loads(guard.execute(symbol="AAPL", side="buy", instrument_type="equity", notional_usd=100.0, **extra))


def test_gate_stamps_the_mandate_account_on_reads_and_the_order(live_runtime: Path) -> None:
    _write_mandate(live_runtime, _bound_mandate())
    broker = _GateBroker()

    out = _order(_guard(broker))

    assert out["status"] == "ok"
    assert broker.reads == [
        ("get_equity_positions", {"account_number": ACCOUNT}),
        ("get_portfolio", {"account_number": ACCOUNT}),
    ]
    assert broker.order_calls[0]["account_number"] == ACCOUNT


def test_gate_refuses_every_order_when_the_mandate_names_no_account(live_runtime: Path) -> None:
    _write_mandate(live_runtime, _bound_mandate(account_ref=""))
    broker = _GateBroker()

    out = _order(_guard(broker))

    assert out["status"] == "blocked"
    assert "not bound to an account" in out["reason"]
    assert broker.reads == [] and broker.order_calls == []


@pytest.mark.parametrize("key", ["account_number", "account"])
def test_gate_refuses_an_order_naming_another_account(live_runtime: Path, key: str) -> None:
    _write_mandate(live_runtime, _bound_mandate())
    broker = _GateBroker()

    out = _order(_guard(broker), **{key: "5QR99999"})

    assert out["status"] == "blocked"
    assert "different account" in out["reason"]
    assert broker.order_calls == []


def test_gate_accepts_an_order_naming_the_bound_account_without_duplicating_it(live_runtime: Path) -> None:
    _write_mandate(live_runtime, _bound_mandate())
    broker = _GateBroker()

    out = _order(_guard(broker), account=ACCOUNT)

    assert out["status"] == "ok"
    assert broker.order_calls[0]["account_number"] == ACCOUNT
    assert "account" not in broker.order_calls[0]


def test_gate_prices_held_positions_so_exposure_is_enforced(
    live_runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 20 AAPL at $200 = $4,000 already held; a $750 buy would take gross
    # exposure to $4,750 — inside a $5,000 cap, outside a $4,500 one.
    monkeypatch.setattr(order_guard, "last_price_usd", lambda symbol, asset_class: 200.0)
    held = [rh.position("AAPL", "20")]

    _write_mandate(live_runtime, _bound_mandate(max_total_exposure_usd=5000.0))
    broker = _GateBroker(positions=held)
    out = json.loads(
        _guard(broker).execute(symbol="AAPL", side="buy", instrument_type="equity", notional_usd=750.0)
    )
    assert out["status"] == "ok", out

    _write_mandate(live_runtime, _bound_mandate(max_total_exposure_usd=4500.0))
    broker = _GateBroker(positions=held)
    out = json.loads(
        _guard(broker).execute(symbol="AAPL", side="buy", instrument_type="equity", notional_usd=750.0)
    )
    assert out["status"] == "blocked"
    assert out["breach"]["limit"] == "max_total_exposure_usd"
    assert out["breach"]["attempted_value"] == 4750.0


def test_gate_fails_closed_when_a_held_position_cannot_be_priced(
    live_runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(order_guard, "last_price_usd", lambda symbol, asset_class: None)
    _write_mandate(live_runtime, _bound_mandate())
    broker = _GateBroker(positions=[rh.position("MSFT", "3")])

    out = _order(_guard(broker))

    assert out["status"] == "blocked"
    assert "current positions could not be read" in out["breach"]["detail"]
    assert broker.order_calls == []


def test_gate_fails_closed_on_a_first_page_of_positions(live_runtime: Path) -> None:
    _write_mandate(live_runtime, _bound_mandate())
    broker = _GateBroker()
    broker.positions = rh.positions([rh.position("AAPL", "1")], next_page="cursor-2")

    out = _order(_guard(broker))

    assert out["status"] == "blocked"
    assert broker.order_calls == []


# --------------------------------------------------------------------------- #
# Runner                                                                       #
# --------------------------------------------------------------------------- #


class _SessionService:
    session_id = "live-sess"
    event_bus = SimpleNamespace(emit=lambda *a, **k: None)

    def create_session(self, title=""):
        return self

    async def send_message(self, sid, content, **kw):
        return {"message_id": "m1", "attempt_id": "a1"}


class _RunnerBroker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, name: str, args: dict) -> dict:
        self.calls.append((name, dict(args)))
        if name == "get_equity_positions":
            return rh.positions([rh.position("NVDA", "3")])
        if name == "get_equity_orders":
            return rh.envelope("get_equity_orders", {"orders": []})
        if name == "get_portfolio":
            return rh.portfolio()
        return {"status": "ok"}


def _runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, broker: _RunnerBroker, account: dict):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path), raising=False)
    monkeypatch.setattr(api_server, "_runner_factory", None, raising=False)
    monkeypatch.setattr(api_server, "_live_broker_adapter", lambda name: broker)
    monkeypatch.setattr(api_server, "_get_session_service", lambda: _SessionService())
    monkeypatch.setattr(api_server, "_mandate_account_ref", lambda name: account["ref"])
    return api_server._build_live_runner("robinhood")


def test_runner_refuses_to_build_for_a_mandate_without_an_account(tmp_path, monkeypatch) -> None:
    with pytest.raises(api_server.LiveRunnerUnavailable, match="not bound to an account"):
        _runner(tmp_path, monkeypatch, _RunnerBroker(), {"ref": ""})


def test_runner_reads_and_submits_for_the_current_mandate_account(tmp_path, monkeypatch) -> None:
    broker = _RunnerBroker()
    account = {"ref": ACCOUNT}
    runner = _runner(tmp_path, monkeypatch, broker, account)

    runner._read_positions()
    runner._submit_fn({"action": "close", "symbol": "NVDA", "side": "sell", "qty": 3.0, "account_number": "OTHER"})
    account["ref"] = "5QR77777"  # re-committed to another account while running
    runner._read_balance()

    assert broker.calls == [
        ("get_equity_positions", {"account_number": ACCOUNT}),
        (
            "place_equity_order",
            {"action": "close", "symbol": "NVDA", "side": "sell", "qty": 3.0, "account_number": ACCOUNT},
        ),
        ("get_portfolio", {"account_number": "5QR77777"}),
    ]


def test_runner_stops_calling_the_broker_once_the_account_is_gone(tmp_path, monkeypatch) -> None:
    broker = _RunnerBroker()
    account = {"ref": ACCOUNT}
    runner = _runner(tmp_path, monkeypatch, broker, account)
    account["ref"] = ""

    with pytest.raises(RuntimeError, match="not bound to an account"):
        runner._read_open_orders()
    assert broker.calls == []


def test_runner_positions_carry_qty_for_the_halt_sweep(tmp_path, monkeypatch) -> None:
    runner = _runner(tmp_path, monkeypatch, _RunnerBroker(), {"ref": ACCOUNT})

    assert runner._read_positions()[0]["qty"] == "3"


# --------------------------------------------------------------------------- #
# Commit + account listing                                                     #
# --------------------------------------------------------------------------- #


class _CommitBroker:
    def __init__(self, accounts: list[dict]) -> None:
        self.accounts = accounts
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, name: str, args: dict) -> dict:
        self.calls.append((name, dict(args)))
        if name == "get_accounts":
            return rh.accounts(self.accounts)
        if name == "get_portfolio":
            return rh.portfolio(buying_power="5000.00")
        raise AssertionError(f"unexpected tool {name}")


def _commit_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, broker: _CommitBroker) -> TestClient:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path), raising=False)
    monkeypatch.setattr(api_server, "_live_broker_adapter", lambda name: broker)
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _proposal_id() -> str:
    raw = ProposeMandateProfilesTool().execute(
        broker="robinhood",
        ceilings={
            "account_funding_usd": 5000.0,
            "max_order_usd": 1500.0,
            "max_total_exposure_usd": 5000.0,
            "daily_trade_cap": 10,
            "leverage": "none",
            "instruments": ["equity"],
        },
    )
    return json.loads(raw)["proposal_id"]


def _commit(client: TestClient, account_ref: str) -> Any:
    return client.post(
        "/mandate/commit",
        json={
            "broker": "robinhood",
            "proposal_id": _proposal_id(),
            "selected_ordinal": 1,
            "consent_ack": True,
            "account_ref": account_ref,
        },
    )


def test_commit_binds_the_mandate_to_a_listed_agentic_account(tmp_path, monkeypatch) -> None:
    broker = _CommitBroker([rh.account(ACCOUNT, nickname="Main")])
    client = _commit_client(tmp_path, monkeypatch, broker)

    response = _commit(client, ACCOUNT)

    assert response.status_code == 200, response.text
    assert load_mandate("robinhood").consent.account_ref == ACCOUNT
    assert broker.calls == [("get_accounts", {}), ("get_portfolio", {"account_number": ACCOUNT})]


@pytest.mark.parametrize(
    ("accounts", "account_ref", "detail"),
    [
        ([rh.account(ACCOUNT)], "", "choose the robinhood account"),
        ([rh.account("5QR00009")], ACCOUNT, "not one of the accounts"),
        ([rh.account(ACCOUNT, deactivated=True)], ACCOUNT, "deactivated"),
        ([rh.account(ACCOUNT, agentic_allowed=False)], ACCOUNT, "does not allow agentic trading"),
    ],
)
def test_commit_refuses_an_account_the_mandate_cannot_trade(
    tmp_path, monkeypatch, accounts: list, account_ref: str, detail: str
) -> None:
    client = _commit_client(tmp_path, monkeypatch, _CommitBroker(accounts))

    response = _commit(client, account_ref)

    assert response.status_code == 400
    assert detail in response.json()["detail"]
    assert load_mandate("robinhood") is None


def test_commit_reports_an_unreadable_account_list_as_503(tmp_path, monkeypatch) -> None:
    broker = _CommitBroker([])
    broker.call_tool = lambda name, args: {"status": "error", "error": "token expired"}  # type: ignore[method-assign]
    client = _commit_client(tmp_path, monkeypatch, broker)

    response = _commit(client, ACCOUNT)

    assert response.status_code == 503
    assert "token expired" in response.json()["detail"]
    assert load_mandate("robinhood") is None


def test_live_accounts_route_says_which_brokers_bind_an_account(tmp_path, monkeypatch) -> None:
    broker = _CommitBroker([rh.account(ACCOUNT, is_default=True)])
    client = _commit_client(tmp_path, monkeypatch, broker)

    listed = client.get("/live/accounts", params={"broker": "robinhood"})
    unbound = client.get("/live/accounts", params={"broker": "ibkr"})

    assert listed.status_code == 200
    assert listed.json()["account_selection_required"] is True
    assert listed.json()["accounts"][0]["account_ref"] == ACCOUNT
    assert unbound.json() == {"status": "ok", "broker": "ibkr", "account_selection_required": False, "accounts": []}
    assert broker.calls == [("get_accounts", {})]
