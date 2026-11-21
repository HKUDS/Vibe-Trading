"""Prompt routing, cache stability, and opt-in turn pacing coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.context import ContextBuilder
from src.agent.loop import AgentLoop
from src.agent.memory import WorkspaceMemory
from src.agent.skills import SkillsLoader
from src.agent.tool_loading import loading_policy
from src.agent.tools import BaseTool, ToolRegistry
from src.providers.chat import LLMResponse, ToolCallRequest
from src.config.accessor import get_env_config, reset_env_config

pytestmark = pytest.mark.unit


def test_request_triage_and_routing_are_short_and_explicit() -> None:
    prompt = ContextBuilder(ToolRegistry(), WorkspaceMemory()).build_system_prompt()

    assert prompt.index("## Request Triage") < prompt.index("## Output Principles")
    assert "question" in prompt and "task" in prompt
    assert "one line naming possible next steps" in prompt
    assert 'load_skill("financial-facts")' in prompt
    assert 'load_skill("trading-plan")' in prompt
    assert 'load_skill("shadow-account") as the FIRST tool call' in prompt
    assert "Post-backtest attribution" not in prompt


def test_lazy_initial_tools_include_market_and_indicator_tools() -> None:
    assert "get_market_data" in loading_policy()["initial_tools"]
    assert "technical_indicators" in loading_policy()["initial_tools"]


def test_quantlib_index_is_available_through_the_normal_skill_loader() -> None:
    loader = SkillsLoader()
    content = loader.get_content("quantlib-index")
    assert "# quantlib_call function index" in content
    assert "`risk`" in content
    assert "`historical_var" in content


def test_moved_workflow_rules_live_in_their_skills() -> None:
    loader = SkillsLoader()
    prompt = ContextBuilder(ToolRegistry(), WorkspaceMemory(), skills_loader=loader).build_system_prompt()
    assert "Original issuer or regulatory HTTPS" not in prompt
    assert "shadow_pnl" not in prompt
    assert "financial-facts/v1" in loader.get_content("financial-facts")
    assert "shadow_pnl" in loader.get_content("shadow-account")
    assert "observed prices for every symbol" in loader.get_content("trading-plan")
    assert "Layer 1 — Trade Attribution" in loader.get_content("strategy-generate")


def test_pacing_knobs_are_disabled_by_default_and_env_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VIBE_TRADING_MID_TURN_NUDGE_ROUNDS", raising=False)
    monkeypatch.delenv("VIBE_TRADING_WRAP_UP_NUDGE_REMAINING", raising=False)
    reset_env_config()
    assert get_env_config().agent_tuning.vibe_trading_mid_turn_nudge_rounds == 0
    assert get_env_config().agent_tuning.vibe_trading_wrap_up_nudge_remaining == 0

    monkeypatch.setenv("VIBE_TRADING_MID_TURN_NUDGE_ROUNDS", "2")
    monkeypatch.setenv("VIBE_TRADING_WRAP_UP_NUDGE_REMAINING", "4")
    reset_env_config()
    config = get_env_config().agent_tuning
    assert config.vibe_trading_mid_turn_nudge_rounds == 2
    assert config.vibe_trading_wrap_up_nudge_remaining == 4


class _MarketObservation(BaseTool):
    name = "get_market_data"
    description = "Return a test market observation."
    parameters = {"type": "object", "properties": {"symbol": {"type": "string"}}}
    is_readonly = True
    repeatable = True

    def execute(self, symbol: str = "AAPL.US", **kwargs: object) -> str:
        return json.dumps({"ok": True, "symbol": symbol, "close": 100.0})


class _ScriptedLLM:
    model_name = "offline"

    def __init__(self) -> None:
        self.responses = [
            LLMResponse(tool_calls=[ToolCallRequest(id="c1", name="get_market_data", arguments={"symbol": "AAPL.US"})]),
            LLMResponse(tool_calls=[ToolCallRequest(id="c2", name="get_market_data", arguments={"symbol": "MSFT.US"})]),
            LLMResponse(content="The answer is ready."),
        ]
        self.requests = []

    def stream_chat(self, messages, **kwargs):
        self.requests.append(messages)
        return self.responses.pop(0)


def test_enabled_mid_turn_nudge_is_injected_after_data_without_commentary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_MID_TURN_NUDGE_ROUNDS", "2")
    monkeypatch.setenv("VIBE_TRADING_WRAP_UP_NUDGE_REMAINING", "0")
    reset_env_config()
    registry = ToolRegistry()
    registry.register(_MarketObservation())
    llm = _ScriptedLLM()
    loop = AgentLoop(registry=registry, llm=llm, max_iterations=4)
    loop.memory.run_dir = str(tmp_path)

    result = loop.run("Compare the two observations.")

    assert result["status"] == "success"
    trace = (Path(result["run_dir"]) / "trace.jsonl").read_text(encoding="utf-8")
    assert '"type": "mid_turn_nudge"' in trace
    assert any(
        isinstance(message.get("content"), str)
        and "Evidence is already in hand" in message["content"]
        for request in llm.requests
        for message in request
    )
