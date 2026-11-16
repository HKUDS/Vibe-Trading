"""Option reads acquire identity before authorization without weakening the gate."""

from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from src.agent.context import ContextBuilder
from src.agent.instrument_identity import IdentityLedger
from src.agent.loop import AgentLoop
from src.agent.tools import BaseTool, ToolRegistry
from src.agent.trace import TraceWriter
from src.providers.chat import ToolCallRequest
from src.tools.options_chain_tool import OptionsChainTool
from src.tools.symbol_search_tool import SymbolSearchTool


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    events = []
    registry = ToolRegistry()
    resolver = SymbolSearchTool()
    options = OptionsChainTool()
    response = {"ok": True, "data": {"query": "AAPL", "sources": {"fixture": "ok"}, "candidates": [{"symbol": "AAPL.US", "market": "us"}]}}
    agent = AgentLoop(registry=registry, llm=SimpleNamespace(), max_iterations=4)
    agent.memory.run_dir = str(tmp_path)
    agent._identity = IdentityLedger(run_dir=tmp_path, user_message="AAPL options and 00700.HK bars")

    def resolve(**kwargs):
        events.append(("resolve", kwargs["query"]))
        if "data" in response:
            response["data"]["query"] = kwargs["query"]
        return json.dumps(response)

    def chain(**kwargs):
        assert agent._identity.identity_status == "locked"
        assert "AAPL.US" in agent._identity.authorized_symbols
        events.append(("options", kwargs["ticker"]))
        return '{"ok":true,"data":{"ticker":"AAPL","calls":[],"puts":[]}}'

    monkeypatch.setattr(resolver, "execute", resolve)
    monkeypatch.setattr(options, "execute", chain)
    registry.register(resolver)
    registry.register(options)
    messages, react_trace = [], []
    trace = TraceWriter(tmp_path)

    def run(calls):
        agent._process_tool_calls(calls, ContextBuilder, messages, trace, react_trace, 1)
        return messages

    yield SimpleNamespace(agent=agent, events=events, response=response, run=run, messages=messages,
                          registry=registry, path=tmp_path, trace=trace)
    trace.close()


def option(identifier="options1", **kwargs):
    return ToolCallRequest(id=identifier, name="get_options_chain", arguments={"ticker": "AAPL", **kwargs})


@pytest.mark.parametrize("ticker", ["AAPL", "AAPL.US"])
def test_missing_prerequisite_runs_before_first_option_and_keeps_protocol_ids(runtime, ticker):
    r = runtime
    messages = r.run([option(ticker=ticker)])
    assert r.events == [("resolve", ticker), ("options", ticker)]
    assert len(messages) == 1 and messages[0]["tool_call_id"] == "options1"
    assert json.loads(messages[0]["content"])["ok"]
    records = [json.loads(line) for line in (r.path / "trace.jsonl").read_text().splitlines()]
    link = next(row for row in records if row["type"] == "identity_dependency")
    assert link["parent_call_id"] == "options1"
    assert not any(row.get("status") == "error" for row in records)


def test_matching_explicit_resolver_is_reordered_and_only_runs_once(runtime):
    messages = runtime.run([option(), ToolCallRequest(id="search1", name="search_symbol", arguments={"query": "AAPL"})])
    assert runtime.events == [("resolve", "AAPL"), ("options", "AAPL")]
    assert [message["tool_call_id"] for message in messages] == ["search1", "options1"]


@pytest.mark.parametrize("failure", ["ambiguous", "empty", "network", "wrong_symbol", "denied"])
def test_failed_dependency_never_starts_options_or_auto_retries(runtime, monkeypatch, failure):
    r = runtime
    if failure == "ambiguous":
        r.response["data"]["candidates"].append({"symbol": "AAPL.L", "market": "uk"})
    elif failure == "empty":
        r.response["data"]["candidates"] = []
    elif failure == "network":
        r.response.clear()
        r.response.update(ok=False, error="upstream unavailable")
    elif failure == "wrong_symbol":
        r.response["data"]["candidates"] = [{"symbol": "MSFT.US", "market": "us"}]
    else:
        monkeypatch.setattr("src.providers.tool_policy._deny_prefixes", lambda **kwargs: ("search_symbol",))
    messages = r.run([option()])
    refusal = json.loads(messages[-1]["content"])
    assert refusal["status"] == "error" and "identity_resolution" in refusal
    assert not any(name == "options" for name, _ in r.events)
    count = len(r.events)
    r.run([option("options2")])
    assert len(r.events) == count


def test_known_identity_needs_no_resolver(runtime):
    runtime.agent._identity = IdentityLedger(run_dir=runtime.path, user_message="Read AAPL.US options")
    runtime.run([option()])
    assert runtime.events == [("options", "AAPL")]


def test_two_option_reads_share_one_resolver(runtime):
    runtime.run([option(near_spot_count=2), option("second", near_spot_count=4)])
    assert runtime.events[0] == ("resolve", "AAPL")
    assert sum(name == "resolve" for name, _ in runtime.events) == 1
    assert sum(name == "options" for name, _ in runtime.events) == 2


def test_cross_venue_mismatch_is_not_automatically_resolved(runtime):
    runtime.agent._identity = IdentityLedger(run_dir=runtime.path, user_message="Read AAPL.L")
    runtime.run([option(ticker="AAPL.US")])
    assert runtime.events == []
    assert json.loads(runtime.messages[-1]["content"])["error_code"] == "identity_mismatch"


def test_existing_conflict_is_not_re_resolved(runtime):
    ledger = runtime.agent._identity
    key = next(iter(ledger._identities))
    ledger._identities[key] = replace(ledger._identities[key], status="conflicting")
    runtime.run([option()])
    assert runtime.events == []
    assert json.loads(runtime.messages[-1]["content"])["error_code"] == "identity_conflict"


def test_cancel_before_dependencies_performs_no_work(runtime):
    runtime.agent._cancel_event.set()
    assert runtime.run([option()]) == []
    assert runtime.events == []


class _Mutation(BaseTool):
    name = "fixture_mutation"
    is_readonly = False
    parameters = {"type": "object", "properties": {}}

    def __init__(self, events):
        self.events = events

    def execute(self, **kwargs):
        self.events.append(("mutation", "done"))
        return '{"status":"ok"}'


def test_prerequisite_does_not_overtake_prior_mutation(runtime):
    runtime.registry.register(_Mutation(runtime.events))
    runtime.run([ToolCallRequest(id="m", name="fixture_mutation", arguments={}), option()])
    assert runtime.events == [("mutation", "done"), ("resolve", "AAPL"), ("options", "AAPL")]


def test_unavailable_resolver_cannot_enable_options(runtime):
    runtime.registry._tools.pop("search_symbol")
    runtime.run([option()])
    assert runtime.events == []
    assert json.loads(runtime.messages[-1]["content"])["status"] == "error"


def test_denied_consumer_does_not_trigger_a_dependency(runtime, monkeypatch):
    monkeypatch.setattr("src.providers.tool_policy._deny_prefixes", lambda **kwargs: ("get_options_chain",))
    runtime.run([option()])
    assert runtime.events == []


def test_cancellation_during_resolution_stops_before_options(runtime, monkeypatch):
    resolver = runtime.registry.get("search_symbol")
    original = resolver.execute

    def cancel(**kwargs):
        result = original(**kwargs)
        runtime.agent._cancel_event.set()
        return result

    monkeypatch.setattr(resolver, "execute", cancel)
    runtime.run([option()])
    assert runtime.events == [("resolve", "AAPL")]
