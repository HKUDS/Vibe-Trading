"""Live smoke test for ``LANGCHAIN_PROVIDER=claude-code``.

**Opt-in only.** Skipped unless ``VIBE_TRADING_CLAUDE_CODE_SMOKE=1`` is
exported AND the optional ``claude-agent-sdk`` dependency is installed
AND the user has previously run ``claude login`` so the SDK can use their
Claude Pro/Max subscription.

Run:
    pip install 'vibe-trading-ai[claude-code]'
    claude login
    export VIBE_TRADING_CLAUDE_CODE_SMOKE=1
    python -m pytest agent/tests/integration/test_claude_code_smoke.py -v --no-header -s
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


def _sdk_importable() -> bool:
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return False
    return True


pytestmark = [
    pytest.mark.skipif(
        os.getenv("VIBE_TRADING_CLAUDE_CODE_SMOKE") != "1",
        reason="VIBE_TRADING_CLAUDE_CODE_SMOKE=1 not set — opt-in only",
    ),
    pytest.mark.skipif(
        not _sdk_importable(),
        reason="claude-agent-sdk not installed (pip install 'vibe-trading-ai[claude-code]')",
    ),
]


def test_basic_chat_via_claude_code_subscription() -> None:
    """End-to-end through the real SDK: verify the adapter's response-shape
    contract against the actual ``claude-agent-sdk`` runtime.

    Asserts the four guarantees ``ChatLLM._parse_response`` depends on:
    - ``response.content`` is a non-empty str.
    - ``response.has_tool_calls`` is False (we don't pass any tools).
    - ``response.finish_reason`` is the OpenAI-style ``"stop"`` (mapped from
      Anthropic's ``"end_turn"``).
    - ``response.usage_metadata`` is populated.
    """
    import src.providers.llm as llm_mod
    llm_mod._dotenv_loaded = True
    from src.providers.chat import ChatLLM

    env = {
        "LANGCHAIN_PROVIDER": "claude-code",
        "LANGCHAIN_MODEL_NAME": os.getenv("VIBE_TRADING_CLAUDE_CODE_SMOKE_MODEL", ""),
        "TIMEOUT_SECONDS": "180",
    }
    with patch.dict(os.environ, env, clear=False):
        client = ChatLLM()
        response = client.chat([
            {"role": "system", "content": "Reply in exactly one short sentence."},
            {"role": "user", "content": "In one sentence: what is 2 + 2?"},
        ])

    assert isinstance(response.content, str), "content must be a str (wrapper flatten contract)"
    assert response.content, "expected non-empty response from Claude"
    assert response.has_tool_calls is False
    assert response.finish_reason in {"stop", "length"}, (
        f"unexpected finish_reason {response.finish_reason!r} — stop_reason mapping may be off"
    )
    assert response.usage_metadata is not None, "usage_metadata must flow through"
    assert response.usage_metadata.get("input_tokens", 0) > 0
    assert response.usage_metadata.get("output_tokens", 0) > 0

    print(
        f"\n[claude-code smoke] finish={response.finish_reason} "
        f"usage={response.usage_metadata} "
        f"content[:140]={response.content[:140]!r}"
    )
