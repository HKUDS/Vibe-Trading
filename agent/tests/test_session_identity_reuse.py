"""Only already settled exact identities can avoid a network resolver call."""

from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from src.agent.instrument_identity import IdentityLedger
from src.agent.loop import AgentLoop
from src.agent.tools import ToolRegistry
from src.tools.symbol_search_tool import SymbolSearchTool
from tests.test_agent_loop_deterministic_cache import _drive


@pytest.mark.parametrize("symbol", ["00700.HK", "BTC-USDT"])
def test_reuse_keeps_user_assertion_and_ledger_version_unchanged(tmp_path, symbol):
    ledger = IdentityLedger(run_dir=tmp_path, user_message=f"Compare {symbol}")
    before = ledger.identity_summary()
    result = json.loads(ledger.reusable_resolution({"query": symbol}))
    assert result["reused"] and not result["network_lookup_performed"]
    assert result["data"]["candidates"][0]["source"] == ["user_message"]
    assert result["data"]["candidates"][0]["symbol"] == symbol
    assert ledger.identity_summary() == before


@pytest.mark.parametrize("arguments", [
    {"query": "AAPL"}, {"query": "00700"}, {"query": "00700.HK Tencent"},
    {"query": "00700.HK", "refresh": True}, {"query": "7203.T"},
])
def test_bare_new_enriched_or_explicit_fresh_queries_use_resolver(tmp_path, arguments):
    ledger = IdentityLedger(run_dir=tmp_path, user_message="Read 00700.HK")
    assert ledger.reusable_resolution(arguments) is None


@pytest.mark.parametrize("status", ["ambiguous", "conflicting", "invalidated", "unresolved", "not_found"])
def test_unsettled_identity_never_reuses(tmp_path, status):
    ledger = IdentityLedger(run_dir=tmp_path, user_message="Read 00700.HK")
    key = next(iter(ledger._identities))
    ledger._identities[key] = replace(ledger._identities[key], status=status)
    assert ledger.reusable_resolution({"query": "00700.HK"}) is None


def test_context_constraints_still_require_resolver(tmp_path, monkeypatch):
    ledger = IdentityLedger(run_dir=tmp_path, user_message="Read 00700.HK")
    monkeypatch.setattr(type(ledger.resolution_context), "constraints_for", lambda *args: (object(),))
    assert ledger.reusable_resolution({"query": "00700.HK"}) is None


@pytest.mark.parametrize("mode", ["reuse", "refresh", "denied"])
def test_actual_loop_reuses_without_bypassing_policy_or_identity(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    tool = SymbolSearchTool()
    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        return json.dumps({"ok": True, "data": {"query": "00700.HK", "candidates": [{"symbol": "00700.HK"}], "sources": {"fixture": "ok"}}})

    monkeypatch.setattr(tool, "execute", execute)
    registry = ToolRegistry()
    registry.register(tool)
    agent = AgentLoop(registry=registry, llm=SimpleNamespace(), max_iterations=3)
    agent.memory.run_dir = str(tmp_path)
    agent._identity = IdentityLedger(run_dir=tmp_path, user_message="Read 00700.HK")
    before = agent._identity.identity_summary()
    if mode == "denied":
        monkeypatch.setattr("src.providers.tool_policy._deny_prefixes", lambda **kwargs: ("search_symbol",))
    args = {"query": "00700.HK", **({"refresh": True} if mode == "refresh" else {})}
    messages, trace = _drive(agent, "search_symbol", tmp_path, [args])
    result = json.loads(messages[-1]["content"])
    if mode == "reuse":
        assert not calls and result["reused"]
        assert agent._identity.identity_summary() == before
        assert any(row["type"] == "identity_reused" for row in trace)
    elif mode == "refresh":
        assert len(calls) == 1 and not result.get("reused")
    else:
        assert not calls and result["status"] == "error"
