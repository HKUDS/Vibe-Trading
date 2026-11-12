"""Exercise the reported failures through the worker and shadow runner paths."""

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from src.agent.tools import BaseTool, ToolRegistry
from src.providers.chat import LLMResponse, ToolCallRequest
from src.swarm.presets import build_run_from_preset
from src.swarm.worker import run_worker
import src.swarm.worker as worker


class _ObservationTool(BaseTool):
    name = "get_market_data"
    description = "Offline observation."
    parameters = {"type": "object", "properties": {}}

    def __init__(self, calls):
        self.calls = calls

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return json.dumps({"status": "ok", "close": 100.0})


class _Replies:
    def __init__(self, responses):
        self.responses = iter(responses)

    def stream_chat(self, *args, **kwargs):
        return next(self.responses)

    def close(self):
        pass


def _committee_role(role):
    run = build_run_from_preset("investment_committee", {"target": "NVDA", "market": "US"})
    return next(a for a in run.agents if a.id == role), next(t for t in run.tasks if t.agent_id == role)


@pytest.mark.parametrize("reason", ["length", "max_tokens", "max_output_tokens", "stop"])
@pytest.mark.parametrize("partial_call", [False, True])
def test_worker_truncation_after_successful_data_call(tmp_path, monkeypatch, reason, partial_call):
    calls = []
    registry = ToolRegistry()
    registry.register(_ObservationTool(calls))
    request = ToolCallRequest(id="c1", name="get_market_data", arguments={})
    llm = _Replies([
        LLMResponse(content=None, tool_calls=[request], finish_reason="tool_calls"),
        LLMResponse(
            content="My final position size should be" if reason != "stop" else "The evidence supports holding the existing position.",
            tool_calls=[request] if partial_call and reason != "stop" else [],
            finish_reason=reason,
        ),
    ])
    monkeypatch.setattr(worker, "ChatLLM", lambda **kw: llm)
    monkeypatch.setattr(worker, "build_swarm_registry", lambda *args, **kw: registry)
    spec, task = _committee_role("risk_officer")
    result = run_worker(spec, task, {}, {"target": "NVDA", "market": "US"}, tmp_path)
    assert result.status == ("completed" if reason == "stop" else "token_limit")
    assert len(calls) == 1  # Never execute a truncated response's partial call.
    if reason != "stop":
        assert "truncated" in result.error
        saved = list(tmp_path.rglob("messages.json"))
        assert saved and "My final position size should be" in saved[0].read_text()


@pytest.mark.parametrize("upstream,expected", [
    ({"full_debate": "Bull: durable demand. Bear: stretched valuation. Risk: retain existing exposure."}, "completed"),
    ({}, "incomplete"),
    ({"full_debate": " "}, "incomplete"),
    ({"wrong_key": "A complete but unmapped report."}, "incomplete"),
    ({"full_debate": "### Phase 1 — Plan\nFirst, I'll fetch the data."}, "incomplete"),
])
def test_committee_pm_synthesis_requires_mapped_reports(tmp_path, monkeypatch, upstream, expected):
    spec, task = _committee_role("portfolio_manager")
    assert spec.evidence_mode == "upstream"
    answer = "Decision: HOLD. Retain existing exposure because valuation offsets durable demand; review after earnings."
    monkeypatch.setattr(worker, "ChatLLM", lambda **kw: _Replies([
        LLMResponse(content=answer, tool_calls=[], finish_reason="stop"),
    ]))
    monkeypatch.setattr(worker, "build_swarm_registry", lambda *args, **kw: ToolRegistry())
    result = run_worker(spec, task, upstream, {"target": "NVDA", "market": "US"}, tmp_path)
    assert result.status == expected


def test_auto_data_role_still_requires_own_evidence(tmp_path, monkeypatch):
    spec, task = _committee_role("risk_officer")
    monkeypatch.setattr(worker, "ChatLLM", lambda **kw: _Replies([
        LLMResponse(content="Hold the current exposure based on the supplied reports.", tool_calls=[], finish_reason="stop"),
    ]))
    monkeypatch.setattr(worker, "build_swarm_registry", lambda *args, **kw: ToolRegistry())
    result = run_worker(spec, task, {k: "A complete upstream report." for k in task.input_from},
                        {"target": "NVDA", "market": "US"}, tmp_path)
    assert result.status == "incomplete"


@pytest.mark.parametrize("value,expected", [("96.221B", True), ("96.22B", True), ("97.22B", False)])
def test_formatted_revenue_keeps_its_evidence_reference(tmp_path, value, expected):
    from src.agent.grounding import GroundingLedger

    ledger = GroundingLedger(run_dir=tmp_path, user_message="Report revenue")
    ledger.ingest_tool_result(tool_name="financial_data", arguments={}, call_id="c1", success=True,
                              result=json.dumps({"revenue": 96221000000}))
    answer = f"Revenue was {value}.\n```figures\n{value} | observed | Revenue | c1::revenue\n```"
    assert ledger.validate_final_answer(answer).valid is expected


def test_native_anthropic_budget_is_explicit_by_default(monkeypatch):
    from src.config.env_schema import LLMConfig

    monkeypatch.delenv("ANTHROPIC_MAX_TOKENS", raising=False)
    assert LLMConfig().anthropic_max_tokens == 16384
    monkeypatch.setenv("ANTHROPIC_MAX_TOKENS", "2048")
    assert LLMConfig().anthropic_max_tokens == 2048


@pytest.mark.parametrize("capital", [10000.0, 2500000.0])
def test_shadow_zero_trades_preserves_requested_cash(tmp_path, monkeypatch, capital):
    """Run generated code in the real backtest subprocess on frozen prices."""
    from src.shadow_account import ShadowProfile, ShadowRule, run_shadow_backtest
    from src.tools.backtest_tool import run_backtest

    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path / "runtime"))
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    rule = ShadowRule(rule_id="never", human_text="Impossible return threshold",
        entry_condition={"market": "us", "prior_5d_return": {"min": 1000}},
        exit_condition={}, holding_days_range=(2, 5), support_count=3,
        coverage_rate=1.0, sample_trades=())
    profile = ShadowProfile(shadow_id="cash_regression", created_at="2026-01-01T00:00:00Z",
        journal_hash="synthetic", source_market="us", profitable_roundtrips=3,
        total_roundtrips=3, date_range=("2026-01-05", "2026-03-27"),
        profile_text="Synthetic cash regression", rules=(rule,), preferred_markets=("us",),
        typical_holding_days=(2, 5))

    def execute(run_dir):
        directory = Path(run_dir)
        config = json.loads((directory / "config.json").read_text())
        frames = {}
        for index, code in enumerate(config["codes"]):
            frame = pd.DataFrame({"open": 100., "high": 101., "low": 99., "close": 100., "volume": 1e6},
                                 index=pd.bdate_range("2026-01-05", periods=60))
            path = directory / f"synthetic-{index}.csv"
            frame.to_csv(path)
            frames[code] = {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            "attrs": {"price_caliber": "qfq", "source": "synthetic-test"}}
        manifest = directory / "frozen.json"
        manifest.write_text(json.dumps({"schema_version": 1, "interval": "1D", "frames": frames}))
        config["frozen_data_manifest"] = str(manifest)
        (directory / "config.json").write_text(json.dumps(config))
        payload = run_backtest(run_dir)
        assert json.loads(payload)["status"] == "ok", payload
        return payload

    result = run_shadow_backtest(profile, window_start="2026-01-05", window_end="2026-03-27",
        markets=("us",), per_market_count=1, source="local", initial_capital=capital,
        run_backtest_fn=execute)
    assert result.combined["trade_count"] == 0
    assert result.combined["final_value"] == pytest.approx(capital)
    assert result.shadow_total_pnl == pytest.approx(0)
    assert result.delta_pnl == pytest.approx(0)
