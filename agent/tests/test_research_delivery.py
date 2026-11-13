"""Research delivery preserves the model's answer without a prose gate."""
import pytest

from src.agent.loop import AgentLoop
from src.agent.loop_streaming import TurnStream
from src.agent.tools import ToolRegistry
from src.providers.chat import LLMResponse, ToolCallRequest
from src.swarm.models import SwarmAgentSpec, SwarmTask
import src.swarm.worker as worker


class AnswerModel:
    def __init__(self, answer, *, stream=True, finish_reason="stop"):
        self.answer = answer
        self.stream = stream
        self.finish_reason = finish_reason
        self.calls = 0

    def stream_chat(self, messages, **kwargs):
        self.calls += 1
        if self.stream and kwargs.get("on_text_chunk"):
            for offset in range(0, len(self.answer), 7):
                kwargs["on_text_chunk"](self.answer[offset:offset + 7])
        return LLMResponse(content=self.answer, finish_reason=self.finish_reason)

    def close(self):
        pass


@pytest.mark.parametrize("answer", [
    "On Oct 13, revenue was USD 96.22B, up 13%. Hold the existing position.",
    "## Plan\nAnalysis complete. Hold. No mock data was used.",
    '{"ok": true, "content": "Hold", "weight": 0.03}',
    "The proposed weight is 3%; a 12.4% decline would cost 0.372% NAV.",
])
@pytest.mark.parametrize("stream", [True, False])
def test_final_answer_is_delivered_verbatim(tmp_path, monkeypatch, answer, stream):
    events = []
    llm = AnswerModel(answer, stream=stream)
    agent = AgentLoop(registry=ToolRegistry(), llm=llm, max_iterations=3,
                      event_callback=lambda event, data: events.append((event, data)))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    agent.memory.run_dir = str(run_dir)
    result = agent.run("Analyze the supplied report and give a conclusion.")
    assert result["status"] == "success", result
    assert not result.get("degraded")
    assert result["content"] == answer
    assert llm.calls == 1
    assert "".join(data["delta"] for event, data in events if event == "text_delta") == answer
    assert not any(event == "grounding_status" for event, _ in events)


def test_stream_does_not_pause_at_a_number_or_fence():
    events = []
    stream = TurnStream(emit=lambda event, data: events.append((event, data)), iteration=1,
                        heartbeat_interval=lambda: 1, reasoning_interval=lambda: 1)
    for chunk in ["Oct ", "13", ": $", "96.22", "B\n```python\n", "x = 3\n```"]:
        stream.on_text(chunk)
        assert events[-1] == ("text_delta", {"delta": chunk, "iter": 1})


@pytest.mark.parametrize("answer", [
    "Hold.", "No mock data was used. Hold based on the supplied statements.",
    "## Plan\nAnalysis complete. Hold the existing 3% position.",
    '{"ok":true,"content":"Hold"}',
])
def test_worker_delivers_without_tools_files_or_risk_table(tmp_path, monkeypatch, answer):
    llm = AnswerModel(answer)
    monkeypatch.setattr(worker, "ChatLLM", lambda **kw: llm)
    monkeypatch.setattr(worker, "build_swarm_registry", lambda *a, **kw: ToolRegistry())
    result = worker.run_worker(
        SwarmAgentSpec(id="pm", role="PM", system_prompt="Decide.", tools=["get_market_data"]),
        SwarmTask(id="decision", agent_id="pm", prompt_template="Use the supplied report."),
        {"report": "Revenue USD 96.22B."}, {}, tmp_path,
    )
    assert result.status == "completed"
    assert result.summary == answer
    assert llm.calls == 1
    assert not list(tmp_path.rglob("report.md"))


@pytest.mark.parametrize("reason,answer,expected", [
    ("length", "My conclusion is", "token_limit"),
    ("max_tokens", "My conclusion is", "token_limit"),
    ("stop", "", "incomplete"),
])
def test_worker_actual_delivery_failure_is_not_success(tmp_path, monkeypatch, reason, answer, expected):
    llm = AnswerModel(answer, finish_reason=reason)
    monkeypatch.setattr(worker, "ChatLLM", lambda **kw: llm)
    monkeypatch.setattr(worker, "build_swarm_registry", lambda *a, **kw: ToolRegistry())
    result = worker.run_worker(
        SwarmAgentSpec(id="pm", role="PM", system_prompt="Decide."),
        SwarmTask(id="decision", agent_id="pm", prompt_template="Review."), {}, {}, tmp_path,
    )
    assert result.status == expected
    assert result.summary == answer


@pytest.mark.parametrize("reason", ["length", "max_tokens"])
def test_agent_preserves_truncated_text_without_success(tmp_path, reason):
    llm = AnswerModel("The position should be", finish_reason=reason)
    agent = AgentLoop(registry=ToolRegistry(), llm=llm, max_iterations=3)
    agent.memory.run_dir = str(tmp_path / "run")
    result = agent.run("Summarize the supplied research.")
    assert result["status"] == "failed"
    assert result["content"] == llm.answer
    assert "truncated" in result["reason"]
    assert llm.calls == 1


def test_worker_iteration_exhaustion_keeps_partial_output(tmp_path, monkeypatch):
    class WorkingModel(AnswerModel):
        def stream_chat(self, messages, **kwargs):
            return LLMResponse(content="I am still working on the calculation.",
                               tool_calls=[ToolCallRequest("c1", "missing_tool", {})])
    monkeypatch.setattr(worker, "ChatLLM", lambda **kw: WorkingModel(""))
    monkeypatch.setattr(worker, "build_swarm_registry", lambda *a, **kw: ToolRegistry())
    result = worker.run_worker(
        SwarmAgentSpec(id="pm", role="PM", system_prompt="Decide.", max_iterations=1),
        SwarmTask(id="decision", agent_id="pm", prompt_template="Review."), {}, {}, tmp_path,
    )
    assert result.status == "incomplete"
    assert "iteration limit" in result.error
    assert "still working" in result.summary


def test_truncated_tool_call_is_never_executed(tmp_path, monkeypatch):
    class PartialCall(AnswerModel):
        def stream_chat(self, messages, **kwargs):
            return LLMResponse(content="Partial analysis", finish_reason="length",
                               tool_calls=[ToolCallRequest("c1", "missing_tool", {})])
    registry = ToolRegistry()
    def forbidden(*args, **kwargs):
        pytest.fail("a truncated response cannot execute tools")
    monkeypatch.setattr(registry, "execute", forbidden)
    agent = AgentLoop(registry=registry, llm=PartialCall(""), max_iterations=3)
    agent.memory.run_dir = str(tmp_path / "run")
    result = agent.run("Analyze the supplied numbers.")
    assert result["status"] == "failed"
    assert result["content"] == "Partial analysis"
