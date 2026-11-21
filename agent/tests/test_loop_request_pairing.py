"""Provider-request tool pairing is repaired without mutating conversation history."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.agent.loop_streaming import repair_provider_messages
from src.agent.loop import AgentLoop
from src.agent.memory import WorkspaceMemory
from src.agent.tools import BaseTool, ToolRegistry
from src.session.thread import INTERRUPTED_RESULT_CONTENT


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


class _NoopDispatchLoop(AgentLoop):
    def _process_tool_calls(self, *args: object, **kwargs: object) -> tuple[bool, str]:
        return False, ""


def test_agent_repairs_before_next_provider_request_only(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(_NoopTool())
    llm = _ScriptedLLM()
    loop = _NoopDispatchLoop(
        registry=registry,
        llm=llm,
        memory=WorkspaceMemory(run_dir=str(tmp_path / "run")),
        max_iterations=3,
    )

    result = loop.run("inspect")

    assert result["status"] == "success"
    assert len(llm.requests) == 2
    second_request_tools = [
        message for message in llm.requests[1] if message.get("role") == "tool"
    ]
    assert len(second_request_tools) == 1
    assert second_request_tools[0]["tool_call_id"] == "call-1"
    assert second_request_tools[0]["content"] == INTERRUPTED_RESULT_CONTENT
    original_messages = loop._turn_messages
    assert original_messages is not None
    assert not any(message.get("role") == "tool" for message in original_messages)
