"""Live-API smoke tests for the Anthropic Claude provider.

**Opt-in only**: every test is skipped unless ``ANTHROPIC_API_KEY`` is set in
the environment. CI does not need credentials — the tests just skip.

Covers the three contracts mo asked for evidence on (PR #105):

1. ``LANGCHAIN_PROVIDER=anthropic`` returns a usable text response.
2. The agent-loop primitive (``ChatLLM.chat`` with ``tools=[...]``) produces a
   well-formed ``tool_calls`` response from Claude.
3. ``LANGCHAIN_REASONING_EFFORT=medium`` enables extended thinking and the
   wrapper surfaces the thinking trace via ``reasoning_content``.

Each test prints the model + a short snippet of the response so the captured
output is grep-friendly for attaching to a PR.

Run:
    export ANTHROPIC_API_KEY=sk-ant-...
    python -m pytest agent/tests/integration/test_anthropic_smoke.py -v --no-header -s
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest


pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping live Anthropic smokes",
)


# Both 4.x models that DO support extended thinking. We default to Sonnet
# because it has both extended thinking AND adaptive thinking — the broadest
# behavior surface.
SMOKE_MODEL = os.getenv("ANTHROPIC_SMOKE_MODEL", "claude-sonnet-4-6")


def _build_env(extra: dict | None = None) -> dict[str, str]:
    """Build a clean env that pins LANGCHAIN_* + ANTHROPIC_* to the smoke values."""
    base = {
        "LANGCHAIN_PROVIDER": "anthropic",
        "LANGCHAIN_MODEL_NAME": SMOKE_MODEL,
        "ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"],
        # 8k cap is enough for any smoke prompt and bounds the worst-case spend.
        "ANTHROPIC_MAX_TOKENS": "8192",
    }
    if "ANTHROPIC_BASE_URL" in os.environ:
        base["ANTHROPIC_BASE_URL"] = os.environ["ANTHROPIC_BASE_URL"]
    if extra:
        base.update(extra)
    return base


def test_basic_chat_returns_text_and_usage() -> None:
    """Contract 1: round-trip a single message through ``LANGCHAIN_PROVIDER=anthropic``."""
    import src.providers.llm as llm_mod
    llm_mod._dotenv_loaded = True
    from src.providers.chat import ChatLLM

    with patch.dict(os.environ, _build_env(), clear=True):
        client = ChatLLM()
        response = client.chat([
            {"role": "user", "content": "In one sentence, what is 2 + 2?"},
        ])

    assert response.content, "expected non-empty content from Claude"
    assert isinstance(response.content, str), "wrapper must flatten content to str"
    assert response.has_tool_calls is False
    assert response.usage_metadata is not None, "usage_metadata must flow through"
    assert response.usage_metadata.get("input_tokens", 0) > 0
    assert response.usage_metadata.get("output_tokens", 0) > 0
    print(f"\n[basic_chat] model={SMOKE_MODEL} usage={response.usage_metadata} content[:120]={response.content[:120]!r}")


def test_agent_loop_tool_call() -> None:
    """Contract 2: agent-loop primitive surfaces a well-formed tool call.

    This exercises the exact code path the ReAct loop uses: ``ChatLLM.chat``
    with a tools list, then reading ``response.tool_calls``. A pass here
    means the wrapper's content-flatten + finish_reason mapping leaves tool
    calls intact (which is what regression-tests the bug
    ``has_tool_calls`` originally guarded — see PR #105 review).
    """
    import src.providers.llm as llm_mod
    llm_mod._dotenv_loaded = True
    from src.providers.chat import ChatLLM

    weather_tool = {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a given location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City name, e.g. 'Bangkok' or 'San Francisco'.",
                    },
                },
                "required": ["location"],
            },
        },
    }

    with patch.dict(os.environ, _build_env(), clear=True):
        client = ChatLLM()
        response = client.chat(
            [
                {
                    "role": "user",
                    "content": "What's the weather in Bangkok? Use the get_weather tool.",
                },
            ],
            tools=[weather_tool],
        )

    assert response.has_tool_calls, "Claude must call the bound tool"
    call = response.tool_calls[0]
    assert call.name == "get_weather"
    assert isinstance(call.arguments, dict)
    assert "location" in call.arguments
    assert response.finish_reason == "tool_calls", (
        f"expected finish_reason='tool_calls' after stop_reason mapping, "
        f"got {response.finish_reason!r}"
    )
    # content can be empty string (Claude went straight to tool call) — that's fine.
    assert isinstance(response.content, str), "content must be a str even with tool calls"
    print(f"\n[tool_call] model={SMOKE_MODEL} finish={response.finish_reason} call.name={call.name} args={call.arguments}")


def test_extended_thinking_surfaces_reasoning_content() -> None:
    """Contract 3: ``LANGCHAIN_REASONING_EFFORT=medium`` produces thinking output.

    Verifies:
    - The wrapper's flatten path correctly extracts thinking blocks.
    - ``additional_kwargs["reasoning_content"]`` makes it to ``LLMResponse.reasoning_content``.
    - The visible text answer is still a string (not a list-of-blocks).
    """
    import src.providers.llm as llm_mod
    llm_mod._dotenv_loaded = True
    from src.providers.chat import ChatLLM

    env = _build_env({"LANGCHAIN_REASONING_EFFORT": "medium"})
    with patch.dict(os.environ, env, clear=True):
        client = ChatLLM()
        response = client.chat([
            {
                "role": "user",
                "content": (
                    "If a train leaves Tokyo at 10:00 traveling east at 200 km/h, and another "
                    "leaves Osaka at 11:30 traveling west at 180 km/h on the same 515 km track, "
                    "at what clock time do they meet? Explain your reasoning step by step."
                ),
            },
        ])

    assert isinstance(response.content, str), "wrapper must flatten content to str"
    assert response.content, "expected non-empty visible answer"
    assert response.reasoning_content, (
        "expected non-empty reasoning_content when extended thinking is enabled — "
        "wrapper failed to surface the thinking block(s)"
    )
    assert response.usage_metadata is not None
    print(
        f"\n[thinking] model={SMOKE_MODEL} effort=medium "
        f"thinking_chars={len(response.reasoning_content)} "
        f"answer_chars={len(response.content)} "
        f"usage={response.usage_metadata}"
    )
    print(f"[thinking] first 200 chars of reasoning: {response.reasoning_content[:200]!r}")
