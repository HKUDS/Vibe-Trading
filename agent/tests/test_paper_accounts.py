"""Forward account clocks, real matching, persistence and concurrent writes."""

import inspect
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import paper_trade_routes as routes
from src.tools.paper_trade.accounts import AccountConflict, PaperAccounts
from src.tools.paper_trade.tool import run_paper_trade_step


class RawLoader:
    name = "sina"

    def fetch(self, codes, *args, **kwargs):
        return {
            code: pd.DataFrame(
                {
                    "open": [10.0, 11.0],
                    "high": [10.0, 11.0],
                    "low": [10.0, 11.0],
                    "close": [10.0, 11.0],
                    "volume": [1000.0, 1000.0],
                },
                index=pd.to_datetime(["2026-10-19", "2026-10-20"]),
            )
            for code in codes
        }


def matching(payload):
    return run_paper_trade_step(payload, loader=RawLoader(), _orders_at_end=True)


@pytest.fixture
def service(tmp_path):
    return PaperAccounts(
        tmp_path / "accounts.db",
        clock=lambda: datetime(2026, 10, 20, 22, tzinfo=timezone.utc),
        step=matching,
    )


def create(service, **kwargs):
    return service.create(
        label="Research",
        market="us",
        account_state={"cash": 1000, "positions": []},
        **kwargs,
    )


def test_real_step_persists_and_prevents_replay(service):
    account = create(service)
    reply = service.advance(
        account["id"],
        expected_revision=0,
        to_date="2026-10-20",
        orders=[{"symbol": "AAPL.US", "side": "buy", "qty": 10}],
    )
    assert reply["committed"]
    assert reply["account"]["account_state"]["cash"] == 889.01
    assert service.get(account["id"])["revision"] == 1
    assert service.history(account["id"])[0]["fills"][0]["price"] == 11
    with pytest.raises(AccountConflict):
        service.advance(
            account["id"], expected_revision=0, to_date="2026-10-20", orders=[]
        )
    with pytest.raises(ValueError, match="Execution date"):
        service.advance(
            account["id"], expected_revision=1, to_date="2026-10-20", orders=[]
        )


def test_no_backdating_future_or_incomplete_session(service):
    account = create(service)
    for day in ("2026-10-19", "2026-10-21"):
        with pytest.raises(ValueError, match="Execution date"):
            service.advance(account["id"], expected_revision=0, to_date=day, orders=[])
    service.clock = lambda: datetime(2026, 10, 20, 20, 10, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="completed session"):
        service.advance(
            account["id"], expected_revision=0, to_date="2026-10-20", orders=[]
        )
    assert service.get(account["id"])["revision"] == 0


def test_an_account_with_no_settled_session_says_so_instead_of_an_inverted_range(service):
    account = create(service)
    service.clock = lambda: datetime(2026, 10, 20, 20, 10, tzinfo=timezone.utc)
    with pytest.raises(ValueError) as caught:
        service.advance(account["id"], expected_revision=0, to_date="2026-10-20", orders=[])
    message = str(caught.value)
    assert "No completed session to settle yet" in message
    assert "Execution dates start at 2026-10-20" in message
    assert "16:30 America/New_York" in message
    assert "between" not in message


def test_next_session_start_uses_market_timezone_and_skips_weekend(service):
    service.clock = lambda: datetime(
        2026, 10, 24, 1, tzinfo=timezone.utc
    )  # Friday in NY
    account = create(service, start="next_session")
    assert account["start_on"] == "2026-10-26"


def test_failure_does_not_save_or_consume_revision(service):
    account = create(service)
    service.step = lambda _: json.dumps(
        {"status": "error", "code": "PAPER_DATA_NOT_READY"}
    )
    reply = service.advance(
        account["id"], expected_revision=0, to_date="2026-10-20", orders=[]
    )
    assert not reply["committed"]
    assert service.get(account["id"]) == account
    assert service.history(account["id"]) == []


def test_advance_stays_v1_1_and_cannot_ask_for_an_interval(service):
    account = create(service)
    seen: list[dict] = []

    def step(payload: dict) -> str:
        seen.append(payload)
        return matching(payload)

    service.step = step
    signature = inspect.signature(PaperAccounts.advance).parameters
    assert "interval" not in signature
    assert not any(param.kind is inspect.Parameter.VAR_KEYWORD for param in signature.values())

    with pytest.raises(TypeError):
        service.advance(
            account["id"],
            expected_revision=0,
            to_date="2026-10-20",
            orders=[],
            interval="5m",
        )
    assert seen == []

    reply = service.advance(
        account["id"],
        expected_revision=0,
        to_date="2026-10-20",
        orders=[],
    )
    assert seen and set(seen[0]).isdisjoint({"interval", "session", "path_model", "fill_model"})
    assert reply["committed"] is True
    assert reply["account"]["revision"] == 1
    assert reply["result"]["schema_version"] == "pt-v1.1"
    assert [row["date"] for row in reply["result"]["nav_series"]] == ["2026-10-20"]
    assert "engine_fingerprint" not in reply["result"]
    assert "interval" not in reply["result"]


def test_concurrent_match_commits_only_once(service):
    account = create(service)
    barrier = Barrier(2)

    def step(payload):
        result = matching(payload)
        barrier.wait(timeout=10)
        return result

    def advance():
        another = PaperAccounts(service.path, clock=service.clock, step=step)
        try:
            return another.advance(
                account["id"], expected_revision=0, to_date="2026-10-20", orders=[]
            )
        except AccountConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: advance(), range(2)))
    assert results.count("conflict") == 1
    assert len(service.history(account["id"])) == 1


def test_api_and_cli_share_saved_account(service, monkeypatch, capsys, tmp_path):
    from cli.commands import paper_trade as cli
    import argparse

    monkeypatch.setattr(routes, "PaperAccounts", lambda: service)
    monkeypatch.setattr(cli, "PaperAccounts", lambda: service)
    app = FastAPI()
    routes.register_paper_trade_routes(app)
    app.dependency_overrides[routes.require_auth] = lambda: None
    app.dependency_overrides[routes.require_settings_write_auth] = lambda: None
    client = TestClient(app)
    created = client.post(
        "/api/paper-accounts",
        json={
            "label": "Web account",
            "market": "us",
            "account_state": {"cash": 500, "positions": []},
        },
    )
    assert created.status_code == 200
    account = created.json()
    parser = argparse.ArgumentParser()
    cli.add_parser(parser.add_subparsers(dest="command"))
    assert cli.dispatch(parser.parse_args(["paper", "show", account["id"]])) == 0
    assert json.loads(capsys.readouterr().out)["label"] == "Web account"
    reply = client.post(
        f'/api/paper-accounts/{account["id"]}/advance',
        json={"expected_revision": 0, "to_date": "2026-10-20", "orders": []},
    )
    assert reply.status_code == 200 and reply.json()["committed"]
    assert (
        client.post(
            f'/api/paper-accounts/{account["id"]}/advance',
            json={"expected_revision": 0, "to_date": "2026-10-20", "orders": []},
        ).status_code
        == 409
    )
    assert (
        client.get(f'/api/paper-accounts/{account["id"]}/history').json()[0][
            "end_state"
        ]["cash"]
        == 500
    )


def test_api_write_auth_cannot_be_bypassed_by_read_auth(service, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(routes, "PaperAccounts", lambda: service)
    app = FastAPI()
    routes.register_paper_trade_routes(app)
    app.dependency_overrides[routes.require_auth] = lambda: None

    def refuse():
        raise HTTPException(403, "write denied")

    app.dependency_overrides[routes.require_settings_write_auth] = refuse
    client = TestClient(app)
    assert client.get("/api/paper-accounts").status_code == 200
    assert (
        client.post(
            "/api/paper-accounts",
            json={"label": "x", "market": "us", "account_state": {"cash": 1}},
        ).status_code
        == 403
    )
    assert client.post("/api/paper-trade/step", json={}).status_code == 403


def test_saved_account_scans_intervening_days_before_applying_target_orders(service):
    service.clock = lambda: datetime(2026, 10, 19, 22, tzinfo=timezone.utc)
    account = create(service)
    service.clock = lambda: datetime(2026, 10, 20, 22, tzinfo=timezone.utc)
    reply = service.advance(
        account["id"],
        expected_revision=0,
        to_date="2026-10-20",
        orders=[{"symbol": "AAPL.US", "side": "buy", "qty": 1}],
    )
    assert [n["date"] for n in reply["result"]["nav_series"]] == [
        "2026-10-19",
        "2026-10-20",
    ]
    assert [f["trade_date"] for f in reply["result"]["fills"]] == ["2026-10-20"]


def test_account_cannot_skip_over_an_unverified_split(service):
    class SplitLoader:
        name = "sina"

        def fetch(self, codes, *args, **kwargs):
            return {
                code: pd.DataFrame(
                    {
                        "open": [100.0, 25.0, 26.0],
                        "high": [100.0, 25.0, 26.0],
                        "low": [100.0, 25.0, 26.0],
                        "close": [100.0, 25.0, 26.0],
                        "volume": [1000.0, 4000.0, 4000.0],
                    },
                    index=pd.to_datetime(["2026-10-19", "2026-10-20", "2026-10-21"]),
                )
                for code in codes
            }

    service.clock = lambda: datetime(2026, 10, 19, 22, tzinfo=timezone.utc)
    account = service.create(
        label="Split check",
        market="us",
        account_state={
            "cash": 1000,
            "positions": [{"symbol": "AAPL.US", "qty": 100, "avg_cost": 100}],
        },
    )
    service.clock = lambda: datetime(2026, 10, 21, 22, tzinfo=timezone.utc)
    service.step = lambda payload: run_paper_trade_step(
        payload, loader=SplitLoader(), _orders_at_end=True
    )
    result = service.advance(
        account["id"], expected_revision=0, to_date="2026-10-21", orders=[]
    )
    assert not result["committed"]
    assert result["result"]["code"] == "PAPER_DATA_NOT_READY"
    assert service.get(account["id"]) == account
