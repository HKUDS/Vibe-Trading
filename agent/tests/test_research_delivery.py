"""Research delivery preserves the model's answer without a prose gate."""

from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config

import pytest

from src.agent.runtime import AgentRuntime
from src.agent.loop_streaming import TurnStream
from src.agent.tools import ToolRegistry
from src.kernel.contracts import LLMResponse, ToolCallRequest
from src.swarm.models import SwarmAgentSpec, SwarmTask
import src.swarm.node as worker


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
    agent = AgentRuntime(registry=ToolRegistry(policy=ToolPolicy.from_config(get_env_config())), llm=llm, max_iterations=3,
                      event_callback=lambda event, data: events.append((event, data)))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    agent.memory.run_dir = str(run_dir)
    result = agent.run("Analyze the supplied report and give a conclusion.")
    assert result["status"] == "success", result
    assert not result.get("degraded")
    assert result["content"] == answer
    assert llm.calls == 1
    assert "".join(data["delta"] for event, data in events if event == "item.delta" and data.get("kind") == "text.delta") == answer
    assert not any(event == "grounding_status" for event, _ in events)


def test_stream_does_not_pause_at_a_number_or_fence():
    events = []
    stream = TurnStream(emit=lambda event, data: events.append((event, data)), iteration=1,
                        heartbeat_interval=lambda: 1, reasoning_interval=lambda: 1)
    for chunk in ["Oct ", "13", ": $", "96.22", "B\n```python\n", "x = 3\n```"]:
        stream.on_text(chunk)
        assert events[-1] == ("item.delta", {"kind": "text.delta", "live_id": stream.live_id, "delta": chunk, "iter": 1})


@pytest.mark.parametrize("answer", [
    "Hold.", "No mock data was used. Hold based on the supplied statements.",
    "## Plan\nAnalysis complete. Hold the existing 3% position.",
    '{"ok":true,"content":"Hold"}',
])
def test_worker_delivers_without_tools_files_or_risk_table(tmp_path, monkeypatch, answer):
    llm = AnswerModel(answer)
    monkeypatch.setattr(worker, "ChatLLM", lambda **kw: llm)
    monkeypatch.setattr(worker, "build_swarm_registry", lambda *a, **kw: ToolRegistry(policy=ToolPolicy.from_config(get_env_config())))
    result = worker.run_node(
        SwarmAgentSpec(id="pm", role="PM", system_prompt="Decide.", tools=["get_market_data"]),
        SwarmTask(id="decision", agent_id="pm", prompt_template="Use the supplied report."),
        {"report": "Revenue USD 96.22B."}, {}, tmp_path,
        policy=ToolPolicy.from_config(get_env_config()),
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
    monkeypatch.setattr(worker, "build_swarm_registry", lambda *a, **kw: ToolRegistry(policy=ToolPolicy.from_config(get_env_config())))
    result = worker.run_node(
        SwarmAgentSpec(id="pm", role="PM", system_prompt="Decide."),
        SwarmTask(id="decision", agent_id="pm", prompt_template="Review."), {}, {}, tmp_path,
        policy=ToolPolicy.from_config(get_env_config()),
    )
    assert result.status == expected
    assert result.summary == answer


@pytest.mark.parametrize("reason", ["length", "max_tokens", "max_output_tokens"])
def test_agent_preserves_truncated_text_without_success(tmp_path, reason):
    """Keep partial text while reporting a failed delivery.

    Args:
        tmp_path: Scratch workspace for the turn.
        reason: Provider finish reason indicating an output limit.
    """
    llm = AnswerModel("The position should be", finish_reason=reason)
    agent = AgentRuntime(registry=ToolRegistry(policy=ToolPolicy.from_config(get_env_config())), llm=llm, max_iterations=3)
    agent.memory.run_dir = str(tmp_path / "run")
    result = agent.run("Summarize the supplied research.")
    assert result["status"] == "failed"
    assert result["content"] == llm.answer
    assert "truncated" in result["reason"]
    assert llm.calls == 1


@pytest.mark.parametrize("status", ["completed", "incomplete"])
def test_responses_terminal_event_controls_agent_delivery(tmp_path, status):
    """Replay the terminal SSE event through the Responses SDK and main runtime.

    Args:
        tmp_path: Scratch workspace for the turn.
        status: Terminal status carried by the Responses event.
    """
    import json

    import httpx

    from src.providers.adapters.openai import ChatOpenAIWithReasoning
    from tests.provider_helpers import chat_with_adapter

    answer = "The position should be"
    response = {
        "id": "resp_test", "object": "response", "created_at": 0, "model": "gpt-test",
        "status": status, "output": [],
    }
    if status == "incomplete":
        response["incomplete_details"] = {"reason": "max_output_tokens"}
    events = [
        {"type": "response.output_text.delta", "sequence_number": 0,
         "item_id": "msg_test", "output_index": 0, "content_index": 0, "delta": answer},
        {"type": f"response.{status}", "sequence_number": 1, "response": response},
    ]

    def respond(request):
        assert request.url.path == "/v1/responses"
        body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        return httpx.Response(200, text=body, headers={"Content-Type": "text/event-stream"})

    policy = ToolPolicy.from_config(get_env_config())
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        adapter = ChatOpenAIWithReasoning(
            model="gpt-test", api_key="offline", base_url="https://example.invalid/v1",
            http_client=client, use_responses_api=True, max_retries=0,
        )
        agent = AgentRuntime(registry=ToolRegistry(policy=policy), llm=chat_with_adapter(adapter))
        agent.memory.run_dir = str(tmp_path / "run")
        result = agent.run("Summarize the supplied research.")

    assert result["status"] == ("failed" if status == "incomplete" else "success")
    assert result["content"] == answer
    if status == "incomplete":
        assert "truncated (max_output_tokens)" in result["reason"]


def test_worker_iteration_exhaustion_keeps_partial_output(tmp_path, monkeypatch):
    class WorkingModel(AnswerModel):
        def stream_chat(self, messages, **kwargs):
            return LLMResponse(content="I am still working on the calculation.",
                               tool_calls=[ToolCallRequest("c1", "missing_tool", {})])
    monkeypatch.setattr(worker, "ChatLLM", lambda **kw: WorkingModel(""))
    monkeypatch.setattr(worker, "build_swarm_registry", lambda *a, **kw: ToolRegistry(policy=ToolPolicy.from_config(get_env_config())))
    result = worker.run_node(
        SwarmAgentSpec(id="pm", role="PM", system_prompt="Decide.", max_iterations=1),
        SwarmTask(id="decision", agent_id="pm", prompt_template="Review."), {}, {}, tmp_path,
        policy=ToolPolicy.from_config(get_env_config()),
    )
    assert result.status == "incomplete"
    assert "iteration limit" in result.error
    assert "still working" in result.summary


def test_truncated_tool_call_is_never_executed(tmp_path, monkeypatch):
    class PartialCall(AnswerModel):
        def stream_chat(self, messages, **kwargs):
            return LLMResponse(content="Partial analysis", finish_reason="length",
                               tool_calls=[ToolCallRequest("c1", "missing_tool", {})])
    registry = ToolRegistry(policy=ToolPolicy.from_config(get_env_config()))
    def forbidden(*args, **kwargs):
        pytest.fail("a truncated response cannot execute tools")
    monkeypatch.setattr(registry, "execute", forbidden)
    agent = AgentRuntime(registry=registry, llm=PartialCall(""), max_iterations=3)
    agent.memory.run_dir = str(tmp_path / "run")
    result = agent.run("Analyze the supplied numbers.")
    assert result["status"] == "failed"
    assert result["content"] == "Partial analysis"
