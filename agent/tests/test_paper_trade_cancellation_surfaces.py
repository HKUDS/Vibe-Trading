"""Agent and real registered MCP schema for the paper-only cancellation input."""

from __future__ import annotations

import argparse
import inspect
import json

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from cli.commands import paper_trade as cli
from src.api import paper_trade_routes as routes

from src.tools.paper_trade import tool as tool_module
from tests.test_paper_trade_5m_partial_fills import (
    _DAY,
    _SYM,
    _FakeCalendarClient,
    _FakeChClient,
    _FakeLoader,
    _intraday,
)
from tests.test_paper_trade_cancellation import _cancel, _payload
from tests.test_paper_trade_tool import _mcp_wrapper


def test_agent_schema_advertises_the_optional_schedule_and_order_id():
    parameters = tool_module.PaperTradeStepTool.parameters
    properties = parameters["properties"]
    assert "cancel_schedule" in properties
    assert "cancel_schedule" not in parameters["required"]
    assert properties["cancel_schedule"]["type"] == ["array", "null"]
    assert set(properties["cancel_schedule"]["items"]["required"]) == {"order_id", "at"}
    assert "order_id" in properties["orders"]["items"]["properties"]


@pytest.mark.asyncio
async def test_registered_mcp_schema_advertises_an_optional_cancel_schedule():
    server, _ = _mcp_wrapper()
    registered = await server.mcp.get_tool("paper_trade_step")
    parameters = registered.to_mcp_tool().inputSchema
    assert "cancel_schedule" in parameters["properties"]
    assert "cancel_schedule" not in parameters["required"]


def _offline_step(monkeypatch):
    original = tool_module.run_paper_trade_step
    five = _intraday(_DAY, ((10.2, 10.3, 9.8, 10.2, 1000.0),) * 3)
    loader = _FakeLoader({_SYM: five})

    def injected(payload):
        return original(
            payload,
            loader=loader,
            ch_client=_FakeChClient(),
            calendar_client=_FakeCalendarClient(frozenset({_DAY})),
            limits_client=None,
        )

    monkeypatch.setattr(tool_module, "run_paper_trade_step", injected)
    return injected


def test_mcp_callback_runs_the_same_offline_matcher(monkeypatch):
    _, wrapper = _mcp_wrapper()
    assert "cancel_schedule" in inspect.signature(wrapper).parameters
    injected = _offline_step(monkeypatch)
    payload = _payload(cancel_schedule=[_cancel()])
    document = wrapper(**payload)
    assert document == injected(payload)
    decoded = json.loads(document)
    assert [row["qty"] for row in decoded["fills"]] == [100]
    assert decoded["cancel_results"][0]["order_id"] == "alpha"


def test_mcp_omits_null_schedule_but_preserves_an_explicit_empty_array(monkeypatch):
    _, wrapper = _mcp_wrapper()
    assert "cancel_schedule" in inspect.signature(wrapper).parameters
    observed = []
    monkeypatch.setattr(
        tool_module,
        "run_paper_trade_step",
        lambda payload: observed.append(payload) or "{}",
    )
    payload = _payload()
    wrapper(**payload, cancel_schedule=None)
    wrapper(**payload, cancel_schedule=[])
    assert "cancel_schedule" not in observed[0]
    assert observed[1]["cancel_schedule"] == []


def test_saved_account_execution_flag_cannot_silently_drop_cancellation():
    five = _intraday(_DAY, ((10.2, 10.3, 9.8, 10.2, 1000.0),) * 3)
    loader = _FakeLoader({_SYM: five})
    document = json.loads(
        tool_module.run_paper_trade_step(
            _payload(cancel_schedule=[_cancel()]),
            loader=loader,
            ch_client=_FakeChClient(),
            calendar_client=_FakeCalendarClient(frozenset({_DAY})),
            limits_client=None,
            _orders_at_end=True,
        )
    )
    assert document.get("code") == "INVALID_REQUEST"
    assert loader.calls == []


def test_cli_parser_and_dispatch_preserve_the_caller_payload(
    monkeypatch, tmp_path, capsys
):
    injected = _offline_step(monkeypatch)
    payload = _payload(cancel_schedule=[_cancel()])
    path = tmp_path / "step.json"
    path.write_text(json.dumps(payload))
    parser = argparse.ArgumentParser()
    cli.add_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["paper", "step", str(path)])
    assert cli.dispatch(args) == 0
    document = json.loads(capsys.readouterr().out)
    assert document == json.loads(injected(payload))
    assert document["cancel_results"][0]["remaining"] == 200


def test_http_step_preserves_the_payload_through_the_registered_route(monkeypatch):
    injected = _offline_step(monkeypatch)
    app = FastAPI()
    routes.register_paper_trade_routes(app)
    app.dependency_overrides[routes.require_settings_write_auth] = lambda: None
    payload = _payload(cancel_schedule=[_cancel()])
    try:
        with TestClient(app) as client:
            response = client.post("/api/paper-trade/step", json=payload)
        assert response.status_code == 200
        assert response.json() == json.loads(injected(payload))
        assert response.json()["cancel_results"][0]["remaining"] == 200
    finally:
        app.dependency_overrides.clear()


def test_http_step_still_obeys_the_write_dependency(monkeypatch):
    def must_not_match(*args, **kwargs):
        pytest.fail("write denial must run before matching")

    def refuse():
        raise HTTPException(403, "synthetic write denial")

    monkeypatch.setattr(tool_module, "run_paper_trade_step", must_not_match)
    app = FastAPI()
    routes.register_paper_trade_routes(app)
    app.dependency_overrides[routes.require_auth] = lambda: None
    app.dependency_overrides[routes.require_settings_write_auth] = refuse
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/paper-trade/step", json=_payload(cancel_schedule=[_cancel()])
            )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_http_rejects_an_escaped_unpaired_id_as_an_input_error(monkeypatch):
    _offline_step(monkeypatch)
    app = FastAPI()
    routes.register_paper_trade_routes(app)
    app.dependency_overrides[routes.require_settings_write_auth] = lambda: None
    payload = _payload()
    payload["orders"][0]["order_id"] = chr(0xD800)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/paper-trade/step",
                content=json.dumps(payload),
                headers={"Content-Type": "application/json"},
            )
        assert response.status_code == 200
        assert response.json()["code"] == "INVALID_REQUEST"
    finally:
        app.dependency_overrides.clear()
