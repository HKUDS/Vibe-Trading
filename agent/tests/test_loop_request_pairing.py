"""Provider-request tool pairing is repaired without mutating conversation history."""

from __future__ import annotations


from pathlib import Path
from types import SimpleNamespace

from src.providers.messages import INTERRUPTED_RESULT_CONTENT
from src.providers.messages import repair_provider_messages
from src.agent.runtime import AgentRuntime
from src.product.resources.memory import WorkspaceMemory
from src.agent.tools import BaseTool, ToolRegistry


def test_request_repair_inserts_one_interrupted_result_and_drops_orphan() -> None:
    messages = [
        {"role": "system", "content": "system"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "orphan",
            "name": "read_file",
            "content": "must be dropped",
        },
        {"role": "user", "content": "continue"},
    ]

    repaired = repair_provider_messages(messages)

    assert [m.get("tool_call_id") for m in repaired if m.get("role") == "tool"] == [
        "call-1"
    ]
    assert repaired[2]["content"] == INTERRUPTED_RESULT_CONTENT
    assert messages[2]["tool_call_id"] == "orphan"


def test_request_repair_keeps_completed_pair_and_order() -> None:
    messages = [
        {"role": "user", "content": "inspect"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "name": "read_file",
            "content": '{"status":"ok"}',
        },
    ]

    repaired = repair_provider_messages(messages)

    assert repaired == messages
    assert repaired is not messages


class _NoopTool(BaseTool):
    name = "read_file"
    description = "offline test tool"
    parameters = {"type": "object", "properties": {}}

    def execute(self, **kwargs: object) -> str:
        return '{"status":"ok"}'


class _ScriptedLLM:
    model_name = "offline"

    def __init__(self) -> None:
        self.requests: list[list[dict]] = []

    def stream_chat(self, messages: list[dict], **kwargs: object) -> SimpleNamespace:
        self.requests.append(messages)
        if len(self.requests) == 1:
            return SimpleNamespace(
                content="",
                reasoning_content=None,
                has_tool_calls=True,
                tool_calls=[
                    SimpleNamespace(
                        id="call-1",
                        name="read_file",
                        arguments={},
                    )
                ],
            )
        return SimpleNamespace(
            content="done",
            reasoning_content=None,
            has_tool_calls=False,
            tool_calls=[],
        )


def test_agent_repairs_before_next_provider_request_only(tmp_path: Path, monkeypatch) -> None:
    registry = ToolRegistry()
    registry.register(_NoopTool())
    llm = _ScriptedLLM()
    loop = AgentRuntime(
        registry=registry,
        llm=llm,
        memory=WorkspaceMemory(run_dir=str(tmp_path / "run")),
        max_iterations=3,
    )

    monkeypatch.setattr(loop.tools, "process", lambda *_args: (False, ""))
    result = loop.run("inspect")

    assert result["status"] == "success"
    assert len(llm.requests) == 2
    second_request_tools = [
        message for message in llm.requests[1] if message.get("role") == "tool"
    ]
    assert len(second_request_tools) == 1
    assert second_request_tools[0]["tool_call_id"] == "call-1"
    assert second_request_tools[0]["content"] == INTERRUPTED_RESULT_CONTENT
    original_messages = loop._conversation.turn_messages
    assert original_messages is not None
    assert not any(message.get("role") == "tool" for message in original_messages)


def test_retry_repairs_again_from_canonical_messages(tmp_path: Path, monkeypatch) -> None:
    """A failed provider attempt can mutate its copy without poisoning the retry."""
    from src.kernel.contracts import LLMResponse
    from src.providers.response import ProviderStreamError

    history = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "missing", "function": {"name": "read_file", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "orphan", "content": "outside the block"},
    ]
    seen = []

    def stream_chat(messages, **kwargs):
        results = [message for message in messages if message["role"] == "tool"]
        seen.append([(message["tool_call_id"], message["content"]) for message in results])
        if len(seen) == 1:
            results[0]["content"] = "failed attempt's private copy"
            raise ProviderStreamError(provider="offline", model="test", original=ConnectionResetError())
        return LLMResponse(content="Done.")

    monkeypatch.setattr("src.agent.tuning.STREAM_RETRY_DELAY_S", 0, raising=False)
    runtime = AgentRuntime(
        registry=ToolRegistry(), llm=SimpleNamespace(stream_chat=stream_chat),
        memory=WorkspaceMemory(run_dir=str(tmp_path)), max_iterations=1,
    )
    result = runtime.run("Continue", history=history)

    assert result["status"] == "success"
    assert seen == [[("missing", INTERRUPTED_RESULT_CONTENT)]] * 2
    assert history[1] == {"role": "tool", "tool_call_id": "orphan", "content": "outside the block"}
