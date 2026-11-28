"""AgentRuntime regressions for active research goal context."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

from src.tools.path_utils import FileRoots


from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


from pathlib import Path
from typing import Any, Callable

from src.agent.runtime import AgentRuntime
from src.goal import GoalStore


class _AnswerResponse:
    def __init__(self, content: str = "done", total_tokens: int = 0) -> None:
        self.content = content
        self.tool_calls: list[Any] = []
        self.reasoning_content: str | None = None
        self.has_tool_calls = False
        self.usage_metadata = {"total_tokens": total_tokens} if total_tokens else {}


class _CapturingLLM:
    def __init__(self, total_tokens: int = 0) -> None:
        self.total_tokens = total_tokens
        self.messages: list[dict[str, Any]] = []
        self.calls: list[list[dict[str, Any]]] = []

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[Any] | None = None,
        on_text_chunk: Callable[[str], None] | None = None,
        on_reasoning_chunk: Callable[[str], None] | None = None,
        timeout: int | None = None,
        idle_timeout_s: float | None = None,
        should_cancel: Callable[[], bool] | None = None,
        on_waiting_chunk=None, **_callbacks) -> _AnswerResponse:
        del tools, on_text_chunk, on_reasoning_chunk
        self.messages = messages
        self.calls.append([dict(item) for item in messages])
        return _AnswerResponse(total_tokens=self.total_tokens)

    def chat(self, messages: list[dict[str, Any]], **_: Any) -> _AnswerResponse:
        self.messages = messages
        return _AnswerResponse(total_tokens=self.total_tokens)


def _agent(llm: _CapturingLLM, run_dir: Path) -> AgentRuntime:
    from src.memory.persistent import PersistentMemory
    from src.tools import build_registry

    pm = PersistentMemory()
    agent = AgentRuntime(
        registry=build_registry(policy=ToolPolicy.from_config(get_env_config()), persistent_memory=pm, include_shell_tools=False),
        llm=llm,
        max_iterations=2,
        persistent_memory=pm,
    )
    run_dir.mkdir(parents=True)
    agent.memory.run_dir = str(run_dir)
    return agent


def test_agent_loop_injects_active_goal_context(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("src.agent.tuning.GOAL_MAX_CONTINUATIONS", 0, raising=False)
    monkeypatch.setenv("VIBE_TRADING_GOAL_DB_PATH", str(tmp_path / "goals.db"))
    store = GoalStore()
    goal = store.replace_goal(
        session_id="session-1",
        objective="Evaluate NVDA momentum.",
        criteria=["Define thesis", "Check price action"],
    )
    llm = _CapturingLLM()

    result = _agent(llm, tmp_path / "run").run(
        user_message="Continue the analysis.",
        session_id="session-1",
    )

    user_message = llm.messages[-1]["content"]
    assert result["status"] == "success"
    assert "<current-research-goal>" in user_message
    assert goal.goal_id in user_message
    assert "expected_goal_id" in user_message
    assert "Evaluate NVDA momentum." in user_message
    assert "Continue the analysis." in user_message


def test_agent_loop_accounts_goal_token_and_turn_usage(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("src.agent.tuning.GOAL_MAX_CONTINUATIONS", 0, raising=False)
    monkeypatch.setenv("VIBE_TRADING_GOAL_DB_PATH", str(tmp_path / "goals.db"))
    store = GoalStore()
    goal = store.replace_goal(
        session_id="session-1",
        objective="Evaluate NVDA momentum.",
        criteria=["Define thesis"],
        token_budget=100,
        turn_budget=5,
    )
    llm = _CapturingLLM(total_tokens=17)

    _agent(llm, tmp_path / "run").run(
        user_message="Continue the analysis.",
        session_id="session-1",
    )

    updated = store.get_goal(goal.goal_id)
    assert updated is not None
    assert updated.tokens_used == 17
    assert updated.turns_used == 1


def test_detached_swarm_usage_stays_with_the_originating_goal_and_run(tmp_path, monkeypatch):
    monkeypatch.setattr("src.agent.tuning.GOAL_MAX_CONTINUATIONS", 0, raising=False)
    monkeypatch.setenv("VIBE_TRADING_GOAL_DB_PATH", str(tmp_path / "goals.db"))
    store = GoalStore()
    session_id = "swarm-session"
    goal = store.replace_goal(session_id=session_id, objective="Evaluate momentum.", criteria=["Define thesis"])
    run_dir = tmp_path / "original"
    agent = _agent(_CapturingLLM(total_tokens=17), run_dir)
    agent.run("Start research.", session_id=session_id)
    charge = agent.usage.capture_swarm_usage()
    assert charge is not None

    next_dir = tmp_path / "next"
    next_dir.mkdir()
    agent.memory.run_dir = str(next_dir)
    agent.run("Continue research.", session_id=session_id)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(charge, [{"input_tokens": 10, "output_tokens": 2}] * 8))

    updated = store.get_goal(goal.goal_id)
    assert updated.tokens_used == 130
    assert updated.turns_used == 2
    original_receipt = run_dir / "llm_usage.json"
    original_usage = json.loads(original_receipt.read_text())
    assert original_usage["totals"]["total_tokens"] == 113
    assert original_usage["totals"]["calls"] == 9
    assert json.loads((next_dir / "llm_usage.json").read_text())["totals"]["total_tokens"] == 17

    replacement = store.replace_goal(session_id=session_id, objective="Review risk.", criteria=["Review exposure"])
    charge({"total_tokens": 99})
    assert store.get_goal(replacement.goal_id).tokens_used == 0
    assert store.get_goal(goal.goal_id).tokens_used == 130
    assert json.loads(original_receipt.read_text()) == original_usage


def test_run_swarm_charges_usage_after_returning_run_id(tmp_path, monkeypatch):
    from src.kernel.contracts import LLMResponse
    from src.swarm import runtime, store, node
    from src.swarm.models import SwarmAgentSpec, SwarmTask
    from src.tools import swarm_tool

    monkeypatch.setattr("src.agent.tuning.GOAL_MAX_CONTINUATIONS", 0, raising=False)
    monkeypatch.setenv("VIBE_TRADING_GOAL_DB_PATH", str(tmp_path / "goals.db"))
    goals = GoalStore()
    goal = goals.replace_goal(session_id="swarm-tool", objective="Evaluate momentum.", criteria=["Define thesis"])
    agent = _agent(_CapturingLLM(total_tokens=17), tmp_path / "parent")
    agent.run("Start research.", session_id="swarm-tool")

    release = threading.Event()
    finished = threading.Event()

    class SwarmLLM:
        def close(self):
            pass

        def stream_chat(self, *_args, **_kwargs):
            assert release.wait(10)
            return LLMResponse(
                content="Momentum remains positive based on the available observations.",
                usage_metadata={"input_tokens": 10, "output_tokens": 2},
            )

    monkeypatch.setattr(node, "ChatLLM", lambda **_: SwarmLLM())
    monkeypatch.setattr(store, "swarm_runs_root", lambda: tmp_path / "swarms")
    monkeypatch.setattr(swarm_tool, "_max_wait_seconds", lambda: 0)
    monkeypatch.setattr(runtime.SwarmRuntime, "_prefetch_grounding_data", lambda *_: None)

    def preset(name, variables, **options):
        run = build_preset(name, variables, **options)
        run.agents = [SwarmAgentSpec(id="analyst", role="Analyst", system_prompt="Analyze.", max_retries=0)]
        run.tasks = [
            SwarmTask(id=task, agent_id="analyst", prompt_template="Evaluate momentum.")
            for task in ("first", "second")
        ]
        return run

    build_preset = runtime.build_run_from_preset
    monkeypatch.setattr(runtime, "build_run_from_preset", preset)
    tool = agent.registry.get("run_swarm")
    tool._event_callback = lambda _, data: (
        finished.set() if data.get("event", {}).get("type") == "run_completed" else None
    )
    try:
        payload = json.loads(tool.execute(prompt="Evaluate momentum.", preset_name="risk_committee"))
        assert payload.get("run_id"), payload
        assert goals.get_goal(goal.goal_id).tokens_used == 17
    finally:
        release.set()
    assert finished.wait(10)
    run = store.SwarmStore(tmp_path / "swarms").load_run(payload["run_id"])
    assert (run.total_input_tokens, run.total_output_tokens) == (20, 4)
    assert goals.get_goal(goal.goal_id).tokens_used == 41
    usage = json.loads((tmp_path / "parent" / "llm_usage.json").read_text())
    assert usage["totals"]["total_tokens"] == 41


def test_agent_loop_continues_active_incomplete_goal(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("src.agent.tuning.GOAL_MAX_CONTINUATIONS", 1, raising=False)
    monkeypatch.setenv("VIBE_TRADING_GOAL_DB_PATH", str(tmp_path / "goals.db"))
    store = GoalStore()
    store.replace_goal(
        session_id="session-1",
        objective="Evaluate NVDA momentum.",
        criteria=["Define thesis", "Check price action"],
    )
    llm = _CapturingLLM()

    result = _agent(llm, tmp_path / "run").run(
        user_message="Start the goal.",
        session_id="session-1",
    )

    assert result["status"] == "success"
    assert len(llm.calls) == 2
    assert "<goal-continuation>" in llm.calls[1][-1]["content"]
    assert "criteria_snapshot:" in llm.calls[1][-1]["content"]
    assert "recent_evidence_snapshot:" in llm.calls[1][-1]["content"]
    assert "Check price action" in llm.calls[1][-1]["content"]


def test_agent_loop_continues_active_covered_goal_to_force_audit(tmp_path: Path, monkeypatch) -> None:
    """Covered criteria still need a terminal status audit before the loop stops."""
    from src.goal import EvidenceInput

    monkeypatch.setattr("src.agent.tuning.GOAL_MAX_CONTINUATIONS", 1, raising=False)
    monkeypatch.setenv("VIBE_TRADING_GOAL_DB_PATH", str(tmp_path / "goals.db"))
    store = GoalStore()
    goal = store.replace_goal(
        session_id="session-1",
        objective="Evaluate NVDA momentum.",
        criteria=["Define thesis"],
    )
    criterion = store.list_criteria(goal.goal_id)[0]
    store.append_evidence(
        roots=FileRoots.from_config(get_env_config().api),
        session_id="session-1",
        goal_id=goal.goal_id,
        expected_goal_id=goal.goal_id,
        evidence=EvidenceInput(
            criterion_id=criterion.criterion_id,
            text="Thesis evidence exists, but the goal is not terminal yet.",
            run_id="missing-run-is-ok-for-coverage",
        ),
    )
    llm = _CapturingLLM()

    result = _agent(llm, tmp_path / "run").run(
        user_message="Finish the goal.",
        session_id="session-1",
    )

    assert result["status"] == "success"
    assert len(llm.calls) == 2
    continuation = llm.calls[1][-1]["content"]
    assert "<goal-continuation>" in continuation
    assert "All criteria appear covered; audit evidence" in continuation
    assert "status: active" in continuation
