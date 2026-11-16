"""Task 17 gate: one MCP ``paper_trade_step`` with branch-aware arguments.

The hand-written wrapper is replaced by a specialized ``FunctionTool`` that
publishes ``PaperTradeStepTool.parameters`` (the legacy/portfolio ``oneOf``)
and selects the branch from the raw ``mode`` value. These tests pin:

* the catalogue: exactly one ``paper_trade_step``, the oneOf schema, and an
  unchanged total tool count;
* happy paths: valid legacy and portfolio calls return their own documents,
  with portfolio needing none of the legacy arguments and both accepting
  JSON-string containers;
* failures: missing branch-required arguments and undeclared keys fail
  deterministically, while an invalid mode returns the in-band
  ``INVALID_REQUEST`` envelope from the same core.

Market data is always fake; nothing here reaches a broker or a network.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from queue import Empty, Queue
from typing import Any

import pandas as pd
import pytest
from fastmcp.exceptions import ToolError

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = REPO_ROOT / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

# Baseline before task 17: replacing the hand-written wrapper with a mirrored
# registration must not add or remove a tool.
EXPECTED_MCP_TOOL_COUNT = 83

_DAY = "2026-11-13"
_PRIOR = "2026-11-12"
_LEGACY_ONLY_FIELDS = {"market", "account_state", "from_date", "to_date"}


# ---------------------------------------------------------------------------
# Offline data
# ---------------------------------------------------------------------------


class FakeLoader:
    """Minimal loader protocol used by the paper-trade data seam."""

    def __init__(self, frames: dict[str, pd.DataFrame], name: str = "sina") -> None:
        self.name = name
        self._frames = frames

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {code: self._frames[code] for code in codes if code in self._frames}


def _frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    records = [
        {
            "trade_date": day,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1000.0,
        }
        for day, close in rows
    ]
    frame = pd.DataFrame(records)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")[["open", "high", "low", "close", "volume"]]


def _legacy_arguments(**overrides: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "account_id": "mcp-legacy",
        "market": "us",
        "account_state": {"cash": 100000.0, "positions": []},
        "from_date": _DAY,
        "to_date": _DAY,
        "orders": [{"symbol": "AAPL.US", "side": "buy", "qty": 10}],
    }
    arguments.update(overrides)
    return arguments


def _portfolio_arguments(**overrides: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "tool": "paper_trade_step",
        "schema_version": "pt-v2.0",
        "mode": "portfolio",
        "account_id": "mcp-portfolio",
        "base_currency": "USD",
        "trade_date": _DAY,
        "planning_at": f"{_DAY}T12:00:00+00:00",
        "valuation_at": f"{_DAY}T21:00:00+00:00",
        "interval": "1d",
        "fill_model": "all_or_none",
        "portfolio_state": {
            "buckets": [
                {
                    "bucket_id": "us",
                    "market": "us",
                    "currency": "USD",
                    "cash": "25000.00",
                    "positions": [],
                }
            ]
        },
        "sessions": [
            {
                "market": "us",
                "status": "open",
                "source": "caller-calendar",
                "as_of": f"{_DAY}T01:00:00+00:00",
            }
        ],
        "orders": [
            {
                "order_id": "us-buy-1",
                "bucket_id": "us",
                "symbol": "AAPL.US",
                "currency": "USD",
                "side": "buy",
                "qty": 2,
            }
        ],
        "fx_snapshots": [],
        "fx_conversions": [],
    }
    arguments.update(overrides)
    return arguments


def _offline_run(real_step, payload: Any, **kwargs: Any) -> str:
    """Run the real core with fake loaders; never touch a provider."""
    if isinstance(payload, dict) and payload.get("mode") == "portfolio":
        return real_step(
            payload,
            loader={
                "us": FakeLoader(
                    {"AAPL.US": _frame([(_PRIOR, 340.0), (_DAY, 343.46)])}
                )
            },
            ch_client=None,
            calendar_client=None,
        )
    return real_step(payload, loader=FakeLoader({"AAPL.US": _frame([(_DAY, 343.46)])}))


def _install_offline_core() -> None:
    """Patch the tool module's entry point with the offline core wrapper."""
    from src.tools.paper_trade import tool as tool_module

    real_step = tool_module.run_paper_trade_step
    tool_module.run_paper_trade_step = lambda payload, **kwargs: _offline_run(
        real_step, payload, **kwargs
    )


def install_stdio_stub() -> None:
    """Entry point for the stdio subprocess: fake data, real core and server."""
    _install_offline_core()


# ---------------------------------------------------------------------------
# In-process MCP helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mcp_server():
    if "mcp_server" in sys.modules:
        return sys.modules["mcp_server"]
    return importlib.import_module("mcp_server")


def _tools(mcp_server) -> list[Any]:
    return asyncio.run(mcp_server.mcp.list_tools())


def _text(result: Any) -> str:
    content = getattr(result, "content", None) or []
    return content[0].text if content else str(result)


def _call(mcp_server, arguments: dict[str, Any]) -> str:
    return _text(asyncio.run(mcp_server.mcp.call_tool("paper_trade_step", arguments)))


def _stub_core(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.tools.paper_trade import tool as tool_module

    real_step = tool_module.run_paper_trade_step
    monkeypatch.setattr(
        tool_module,
        "run_paper_trade_step",
        lambda payload, **kwargs: _offline_run(real_step, payload, **kwargs),
    )


# ---------------------------------------------------------------------------
# Catalogue: one tool, oneOf schema, unchanged count
# ---------------------------------------------------------------------------


def test_catalog_has_one_paper_trade_step_with_the_oneof_schema(mcp_server) -> None:
    from src.tools.paper_trade.tool import PaperTradeStepTool

    tools = _tools(mcp_server)
    matching = [tool for tool in tools if tool.name == "paper_trade_step"]

    assert len(matching) == 1, f"expected one paper_trade_step, found {len(matching)}"
    assert len(tools) == EXPECTED_MCP_TOOL_COUNT
    assert not [tool.name for tool in tools if "paper_trade_step_" in tool.name]

    tool = matching[0]
    assert tool.description == PaperTradeStepTool.description
    assert tool.parameters["type"] == "object"
    assert len(tool.parameters["oneOf"]) == 2
    # fastmcp inlines the packaged ``$defs`` before publishing; the contract
    # is the same two branches, not a byte copy of the class dictionary.
    published = json.dumps(tool.parameters)
    assert "$ref" not in published

    legacy = next(
        branch
        for branch in tool.parameters["oneOf"]
        if branch["properties"]["mode"].get("const") == "single"
    )
    declared_legacy = next(
        branch
        for branch in PaperTradeStepTool.parameters["oneOf"]
        if branch["properties"]["mode"].get("const") == "single"
    )
    portfolio = next(
        branch
        for branch in tool.parameters["oneOf"]
        if branch["properties"]["mode"].get("const") == "portfolio"
    )
    declared_portfolio = next(
        branch
        for branch in PaperTradeStepTool.parameters["oneOf"]
        if branch["properties"]["mode"].get("const") == "portfolio"
    )
    assert legacy == declared_legacy
    assert portfolio["required"] == declared_portfolio["required"]
    assert portfolio["properties"]["portfolio_state"]["type"] == "object"
    assert portfolio["properties"]["sessions"]["type"] == "array"
    assert portfolio["properties"]["orders"]["type"] == "array"
    assert _LEGACY_ONLY_FIELDS.isdisjoint(portfolio["required"])
    assert _LEGACY_ONLY_FIELDS.isdisjoint(portfolio["properties"])


# ---------------------------------------------------------------------------
# Happy: both branches return their own documents
# ---------------------------------------------------------------------------


def test_valid_legacy_call_returns_the_legacy_document(
    mcp_server, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_core(monkeypatch)
    arguments = _legacy_arguments()
    # The legacy wrapper's lenient JSON-string containers still work through
    # the specialized registration.
    arguments["account_state"] = json.dumps(arguments["account_state"])
    arguments["orders"] = json.dumps(arguments["orders"])

    document = json.loads(_call(mcp_server, arguments))

    assert document["schema_version"] == "pt-v1.1"
    assert document["account_id"] == "mcp-legacy"
    assert document["market"] == "us"
    assert document["fills"][0]["symbol"] == "AAPL.US"
    assert "error" not in document


def test_valid_portfolio_call_needs_no_legacy_arguments(
    mcp_server, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_core(monkeypatch)
    arguments = _portfolio_arguments()
    assert set(arguments).isdisjoint(_LEGACY_ONLY_FIELDS)
    # Portfolio containers are decoded from JSON strings just like legacy ones.
    arguments["portfolio_state"] = json.dumps(arguments["portfolio_state"])
    arguments["sessions"] = json.dumps(arguments["sessions"])
    arguments["orders"] = json.dumps(arguments["orders"])
    arguments["fx_snapshots"] = json.dumps(arguments["fx_snapshots"])

    document = json.loads(_call(mcp_server, arguments))

    assert document["status"] == "success"
    assert document["schema_version"] == "pt-v2.0"
    assert document["mode"] == "portfolio"
    assert document["account_id"] == "mcp-portfolio"
    assert document["complete"] is True
    assert [fill["plan_order_id"] for fill in document["fills"]] == ["us-buy-1"]
    assert document["errors"] == []


# ---------------------------------------------------------------------------
# Failure: invalid mode stays in-band; argument errors are deterministic
# ---------------------------------------------------------------------------


def test_invalid_mode_returns_in_band_invalid_request(mcp_server) -> None:
    from src.tools.paper_trade.portfolio.wire import compute_raw_input_hash

    payload = {"mode": "batch", "account_id": "x"}
    document = json.loads(_call(mcp_server, payload))

    assert document["status"] == "error"
    assert document["schema_version"] == "pt-v2.0"
    assert document["code"] == "INVALID_REQUEST"
    assert (document["error"]["reason"], document["error"]["path"]) == (
        "invalid_mode",
        "mode",
    )
    assert document["error"]["detail"].count("input_sha256=") == 1
    assert document["error"]["detail"].endswith(
        f"; input_sha256={compute_raw_input_hash(payload)}"
    )
    assert "end_portfolio" not in document and "fills" not in document


@pytest.mark.parametrize(
    ("arguments", "missing"),
    [
        (_legacy_arguments(account_state=None), "account_state"),
        (_legacy_arguments(orders=[], from_date=None), "from_date"),
        (_portfolio_arguments(base_currency=None), "base_currency"),
        (_portfolio_arguments(sessions=None), "sessions"),
    ],
)
def test_missing_branch_required_arguments_fail_deterministically(
    mcp_server, monkeypatch: pytest.MonkeyPatch, arguments: dict[str, Any], missing: str
) -> None:
    from src.tools.paper_trade import tool as tool_module

    def _must_not_run(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("missing required arguments must not reach the core")

    monkeypatch.setattr(tool_module, "run_paper_trade_step", _must_not_run)

    with pytest.raises(ToolError) as excinfo:
        asyncio.run(mcp_server.mcp.call_tool("paper_trade_step", arguments))

    message = str(excinfo.value)
    assert missing in message
    assert "required" in message


@pytest.mark.parametrize("factory", [_legacy_arguments, _portfolio_arguments])
def test_undeclared_arguments_fail_deterministically(
    mcp_server, monkeypatch: pytest.MonkeyPatch, factory
) -> None:
    from src.tools.paper_trade import tool as tool_module

    def _must_not_run(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("undeclared arguments must not reach the core")

    monkeypatch.setattr(tool_module, "run_paper_trade_step", _must_not_run)
    arguments = factory()
    arguments["dummy_legacy_field"] = "not declared by either branch"

    with pytest.raises(ToolError) as excinfo:
        asyncio.run(mcp_server.mcp.call_tool("paper_trade_step", arguments))

    message = str(excinfo.value)
    assert "dummy_legacy_field" in message
    assert "undeclared" in message


# ---------------------------------------------------------------------------
# _paper_trade_call_params unit contract
# ---------------------------------------------------------------------------


def test_call_params_gather_properties_across_both_branches(mcp_server) -> None:
    from src.tools.paper_trade.tool import PaperTradeStepTool

    arguments = _legacy_arguments(portfolio_state={"buckets": []})
    params = mcp_server._paper_trade_call_params(
        PaperTradeStepTool.parameters, arguments
    )

    assert params["portfolio_state"] == {"buckets": []}


def test_call_params_decode_legacy_containers_from_json_strings(mcp_server) -> None:
    from src.tools.paper_trade.tool import PaperTradeStepTool

    arguments = _legacy_arguments(
        account_state='{"cash": 1000.0, "positions": []}',
        orders='[{"symbol": "AAPL.US", "side": "buy", "qty": 1}]',
        fee_model='{"commission_min": 1.0}',
    )
    params = mcp_server._paper_trade_call_params(
        PaperTradeStepTool.parameters, arguments
    )

    assert params["account_state"] == {"cash": 1000.0, "positions": []}
    assert params["orders"] == [{"symbol": "AAPL.US", "side": "buy", "qty": 1}]
    assert params["fee_model"] == {"commission_min": 1.0}


def test_call_params_decode_portfolio_container_refs(mcp_server) -> None:
    from src.tools.paper_trade.tool import PaperTradeStepTool

    arguments = _portfolio_arguments()
    arguments["portfolio_state"] = json.dumps(arguments["portfolio_state"])
    arguments["sessions"] = json.dumps(arguments["sessions"])
    arguments["orders"] = json.dumps(arguments["orders"])
    arguments["fx_snapshots"] = json.dumps([])

    params = mcp_server._paper_trade_call_params(
        PaperTradeStepTool.parameters, arguments
    )

    assert isinstance(params["portfolio_state"], dict)
    assert isinstance(params["sessions"], list)
    assert isinstance(params["orders"], list)
    assert params["fx_snapshots"] == []


def test_call_params_leave_string_properties_alone_and_drop_nulls(mcp_server) -> None:
    from src.tools.paper_trade.tool import PaperTradeStepTool

    arguments = _legacy_arguments(account_id='["not", "an", "array"]', interval=None)
    params = mcp_server._paper_trade_call_params(
        PaperTradeStepTool.parameters, arguments
    )

    assert params["account_id"] == '["not", "an", "array"]'
    assert "interval" not in params


def test_call_params_forward_invalid_mode_without_branch_checks(mcp_server) -> None:
    from src.tools.paper_trade.tool import PaperTradeStepTool

    arguments = {"mode": "batch", "account_id": "x", "unexpected": 1}
    params = mcp_server._paper_trade_call_params(
        PaperTradeStepTool.parameters, arguments
    )

    # The core's pre-parse gate owns the canonical INVALID_REQUEST envelope.
    assert params == arguments


def test_malformed_json_container_strings_stay_in_band(mcp_server) -> None:
    from src.tools.paper_trade.portfolio.wire import compute_raw_input_hash

    legacy = json.loads(_call(mcp_server, _legacy_arguments(account_state="not-json")))
    portfolio_payload = _portfolio_arguments(portfolio_state="not-json")
    portfolio = json.loads(_call(mcp_server, portfolio_payload))

    assert (legacy["status"], legacy["code"]) == ("error", "INVALID_REQUEST")
    assert "account_state must be an object" in legacy["message"]
    assert (portfolio["status"], portfolio["code"]) == ("error", "INVALID_REQUEST")
    assert portfolio["error"]["path"] == "portfolio_state"
    assert portfolio["error"]["detail"].endswith(
        f"; input_sha256={compute_raw_input_hash(portfolio_payload)}"
    )


def test_repeated_calls_do_not_reuse_a_branch_or_payload(
    mcp_server, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_core(monkeypatch)
    legacy = json.loads(_call(mcp_server, _legacy_arguments(account_id="first")))
    portfolio = json.loads(_call(mcp_server, _portfolio_arguments(account_id="second")))
    legacy_again = json.loads(_call(mcp_server, _legacy_arguments(account_id="third")))

    assert (legacy["schema_version"], legacy["account_id"]) == ("pt-v1.1", "first")
    assert (portfolio["schema_version"], portfolio["account_id"]) == (
        "pt-v2.0",
        "second",
    )
    assert (legacy_again["schema_version"], legacy_again["account_id"]) == (
        "pt-v1.1",
        "third",
    )


# ---------------------------------------------------------------------------
# Real stdio round-trip with fake data
# ---------------------------------------------------------------------------


def _spawn_stub_server() -> tuple[subprocess.Popen, Queue]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(AGENT_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    code = (
        "from tests.test_mcp_paper_trade_portfolio import install_stdio_stub;"
        "install_stdio_stub();"
        "from mcp_server import main; main()"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
        env=env,
        cwd=str(AGENT_DIR),
    )
    queue: Queue = Queue()
    reader = threading.Thread(target=_read_lines, args=(proc.stdout, queue), daemon=True)
    reader.start()
    return proc, queue


def _read_lines(stream, queue: Queue) -> None:
    try:
        for line in iter(stream.readline, b""):
            queue.put(line)
    finally:
        queue.put(None)


def _send(proc: subprocess.Popen, obj: dict[str, Any]) -> None:
    proc.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
    proc.stdin.flush()


def _wait_for_id(queue: Queue, want_id: int, timeout: float) -> dict[str, Any] | None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            line = queue.get(timeout=0.25)
        except Empty:
            continue
        if line is None:
            return None
        try:
            obj = json.loads(line.decode("utf-8", errors="replace"))
        except Exception:
            continue
        if obj.get("id") == want_id:
            return obj
    return None


def _stdio_text(response: dict[str, Any]) -> str:
    result = response.get("result") or {}
    content = result.get("content") or []
    assert content, f"tools/call response has no content: {response}"
    return content[0].get("text", "")


def test_stdio_list_and_both_calls_without_live_data() -> None:
    timeout = 30.0
    proc, queue = _spawn_stub_server()
    try:
        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "task-17", "version": "1"},
                },
            },
        )
        assert _wait_for_id(queue, 1, timeout) is not None
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listed = _wait_for_id(queue, 2, timeout)
        assert listed is not None
        tools = listed["result"]["tools"]
        matching = [tool for tool in tools if tool["name"] == "paper_trade_step"]
        assert len(tools) == EXPECTED_MCP_TOOL_COUNT
        assert len(matching) == 1
        assert len(matching[0]["inputSchema"]["oneOf"]) == 2

        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "paper_trade_step",
                    "arguments": _legacy_arguments(),
                },
            },
        )
        legacy_response = _wait_for_id(queue, 3, timeout)
        assert legacy_response is not None
        legacy = json.loads(_stdio_text(legacy_response))
        assert legacy["schema_version"] == "pt-v1.1"
        assert legacy["account_id"] == "mcp-legacy"

        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "paper_trade_step",
                    "arguments": _portfolio_arguments(),
                },
            },
        )
        portfolio_response = _wait_for_id(queue, 4, timeout)
        assert portfolio_response is not None
        portfolio = json.loads(_stdio_text(portfolio_response))
        assert portfolio["status"] == "success"
        assert portfolio["schema_version"] == "pt-v2.0"
        assert portfolio["mode"] == "portfolio"
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
