"""Tests for the Claude Code (claude-agent-sdk) provider adapter.

Mirrors :mod:`tests.test_openai_codex` in shape: mock the SDK boundary, cover
env wiring, build_llm dispatch, the documented v1 tool-calling limitation,
and the response-shape contract :class:`ChatLLM._parse_response` depends on.

No live calls. The opt-in smoke harness lives at
``agent/tests/integration/test_claude_code_smoke.py``.
"""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from src.providers import llm as llm_mod


def _install_fake_sdk(monkeypatch: pytest.MonkeyPatch, *, assistant_text: str,
                      thinking: str = "", stop_reason: str = "end_turn",
                      usage: dict | None = None, captured: dict | None = None) -> types.ModuleType:
    """Install a stand-in ``claude_agent_sdk`` module that yields a fixed reply.

    Returns the fake module so individual tests can inspect call args.
    Mutates the captured dict (if provided) with ``options`` + ``prompt``
    seen by the most recent ``query`` call — this is how we assert that
    ``_build_options`` produces an isolated, no-tools, strict-MCP session.
    """
    captured = captured if captured is not None else {}

    class _TextBlock:
        def __init__(self, text: str) -> None:
            self.text = text

    class _ThinkingBlock:
        def __init__(self, thinking: str) -> None:
            self.thinking = thinking

    class _AssistantMessage:
        def __init__(self, content, usage_in=None) -> None:
            self.content = content
            self.usage = usage_in

    class _ResultMessage:
        def __init__(self, stop_reason_in: str, usage_in: dict | None) -> None:
            self.stop_reason = stop_reason_in
            self.usage = usage_in

    class _Options:
        # Use a plain class to allow attribute assignment; the real SDK uses a
        # dataclass — what we care about is "did the adapter set these
        # attributes correctly?", not the precise type.
        def __init__(self, **kwargs) -> None:
            self.__dict__.update(kwargs)

    async def _fake_query(*, prompt, options):
        captured["prompt"] = prompt
        captured["options"] = options
        blocks = []
        if thinking:
            blocks.append(_ThinkingBlock(thinking))
        if assistant_text:
            blocks.append(_TextBlock(assistant_text))
        yield _AssistantMessage(content=blocks, usage_in=usage)
        yield _ResultMessage(stop_reason_in=stop_reason, usage_in=usage)

    fake = types.ModuleType("claude_agent_sdk")
    fake.query = _fake_query
    fake.AssistantMessage = _AssistantMessage
    fake.TextBlock = _TextBlock
    fake.ThinkingBlock = _ThinkingBlock
    fake.ResultMessage = _ResultMessage
    fake.ClaudeAgentOptions = _Options

    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake)
    # The provider module caches the import at top-level — patch its reference too.
    from src.providers import claude_code as cc_mod
    monkeypatch.setattr(cc_mod, "_cas", fake)
    return fake


# ---------------------------------------------------------------------------
# llm_providers.json: claude-code entry shape
# ---------------------------------------------------------------------------


def test_claude_code_listed_in_llm_providers_json() -> None:
    providers_path = Path(__file__).resolve().parents[1] / "src" / "providers" / "llm_providers.json"
    providers = json.loads(providers_path.read_text(encoding="utf-8"))
    entry = next((p for p in providers if p["name"] == "claude-code"), None)

    assert entry is not None
    # Subscription-backed: no API key path.
    assert entry["api_key_env"] is None
    assert entry["api_key_required"] is False
    # Settings UI distinguishes this from api_key auth so it can prompt the
    # `claude login` command instead of asking for a key.
    assert entry["auth_type"] == "oauth"
    assert entry["login_command"] == "claude login"
    # Subscription-managed endpoint — no user-configurable base URL.
    assert entry["base_url_env"] == ""
    assert entry["default_base_url"] == ""


# ---------------------------------------------------------------------------
# _sync_provider_env: claude-code short-circuit
# ---------------------------------------------------------------------------


class TestClaudeCodeProviderEnv:
    """The claude-code branch must NOT touch OPENAI_API_KEY. Mirrors the
    isolation rule the openai-codex provider already enforces — leaking any
    key into OPENAI_API_KEY would route it to OpenAI-compat clients on a
    later provider switch within the same process.
    """

    def _run_sync(self, env: dict[str, str]) -> dict[str, str]:
        llm_mod._dotenv_loaded = True
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI_", "LANGCHAIN_"))}
        clean.update(env)
        with patch.dict(os.environ, clean, clear=True):
            llm_mod._sync_provider_env()
            return {
                "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
                "OPENAI_API_BASE": os.environ.get("OPENAI_API_BASE", ""),
                "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL", ""),
            }

    def test_claude_code_does_not_touch_openai_envs(self) -> None:
        result = self._run_sync({"LANGCHAIN_PROVIDER": "claude-code"})
        assert result["OPENAI_API_KEY"] == ""
        assert result["OPENAI_API_BASE"] == ""

    def test_underscore_alias_routes_to_claude_code_branch(self) -> None:
        result = self._run_sync({"LANGCHAIN_PROVIDER": "claude_code"})
        assert result["OPENAI_API_KEY"] == ""

    def test_preexisting_openai_key_not_clobbered_under_claude_code(self) -> None:
        # The short-circuit returns before the projection block, so an OPENAI_API_KEY
        # the user happens to have set stays exactly where it was.
        result = self._run_sync({
            "LANGCHAIN_PROVIDER": "claude-code",
            "OPENAI_API_KEY": "sk-leftover-from-earlier",
        })
        assert result["OPENAI_API_KEY"] == "sk-leftover-from-earlier"


# ---------------------------------------------------------------------------
# build_llm: dispatch + error paths
# ---------------------------------------------------------------------------


class TestClaudeCodeBuildLlm:
    def setup_method(self) -> None:
        llm_mod._dotenv_loaded = True

    def test_build_llm_returns_claude_code_adapter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_sdk(monkeypatch, assistant_text="ok")
        env = {
            "LANGCHAIN_PROVIDER": "claude-code",
            "LANGCHAIN_MODEL_NAME": "claude-sonnet-4-6",
        }
        with patch.dict(os.environ, env, clear=True):
            adapter = llm_mod.build_llm()

        from src.providers.claude_code import ClaudeCodeLLM
        assert isinstance(adapter, ClaudeCodeLLM)
        assert adapter.model == "claude-sonnet-4-6"

    def test_build_llm_allows_empty_model_for_claude_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Unlike every other provider, an empty LANGCHAIN_MODEL_NAME is valid
        # here — the SDK falls back to the Claude Code CLI's default model.
        _install_fake_sdk(monkeypatch, assistant_text="ok")
        env = {"LANGCHAIN_PROVIDER": "claude-code"}
        with patch.dict(os.environ, env, clear=True):
            adapter = llm_mod.build_llm()
        assert adapter.model is None

    def test_build_llm_still_requires_model_name_for_other_providers(self) -> None:
        env = {"LANGCHAIN_PROVIDER": "openai"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError, match="LANGCHAIN_MODEL_NAME is not set"):
                llm_mod.build_llm()

    def test_missing_sdk_raises_install_hint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.providers import claude_code as cc_mod
        monkeypatch.setattr(cc_mod, "_cas", None)
        with patch.dict(os.environ, {"LANGCHAIN_PROVIDER": "claude-code"}, clear=True):
            with pytest.raises(RuntimeError, match=r"claude-agent-sdk is not installed"):
                llm_mod.build_llm()


# ---------------------------------------------------------------------------
# ClaudeCodeLLM.invoke: response shape + isolation guards
# ---------------------------------------------------------------------------


class TestClaudeCodeInvoke:
    def setup_method(self) -> None:
        llm_mod._dotenv_loaded = True

    def test_invoke_returns_flattened_text_and_finish_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_sdk(
            monkeypatch,
            assistant_text="Hello from Claude.",
            stop_reason="end_turn",
            usage={"input_tokens": 12, "output_tokens": 5},
        )
        from src.providers.claude_code import ClaudeCodeLLM
        adapter = ClaudeCodeLLM(model="claude-sonnet-4-6")

        msg = adapter.invoke([
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "Say hi."},
        ])

        assert msg.content == "Hello from Claude."
        assert msg.response_metadata["finish_reason"] == "stop"
        assert msg.usage_metadata == {"input_tokens": 12, "output_tokens": 5, "total_tokens": 17}
        assert msg.tool_calls == []

    def test_invoke_surfaces_thinking_via_reasoning_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_sdk(
            monkeypatch,
            assistant_text="42.",
            thinking="Let me reason step by step...",
            stop_reason="end_turn",
        )
        from src.providers.claude_code import ClaudeCodeLLM
        adapter = ClaudeCodeLLM(model="claude-sonnet-4-6")

        msg = adapter.invoke([{"role": "user", "content": "what is the answer?"}])

        assert msg.content == "42."
        assert msg.additional_kwargs["reasoning_content"] == "Let me reason step by step..."

    def test_invoke_maps_stop_reason_tool_use_to_tool_calls_finish_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_sdk(monkeypatch, assistant_text="...", stop_reason="tool_use")
        from src.providers.claude_code import ClaudeCodeLLM
        adapter = ClaudeCodeLLM()

        msg = adapter.invoke([{"role": "user", "content": "x"}])
        assert msg.response_metadata["finish_reason"] == "tool_calls"

    def test_invoke_maps_max_tokens_to_length(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_sdk(monkeypatch, assistant_text="...", stop_reason="max_tokens")
        from src.providers.claude_code import ClaudeCodeLLM
        adapter = ClaudeCodeLLM()
        msg = adapter.invoke([{"role": "user", "content": "x"}])
        assert msg.response_metadata["finish_reason"] == "length"

    def test_invoke_with_empty_messages_returns_empty_without_calling_sdk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}
        _install_fake_sdk(monkeypatch, assistant_text="should not be called", captured=captured)
        from src.providers.claude_code import ClaudeCodeLLM
        adapter = ClaudeCodeLLM()

        msg = adapter.invoke([{"role": "system", "content": "system only, no user turn"}])
        assert msg.content == ""
        assert "prompt" not in captured  # SDK was never called

    def test_options_disable_builtin_tools_and_strict_mcp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Isolation guarantee: the SDK MUST be configured so the user's
        # Claude Code plugins / MCP servers / CLAUDE.md cannot bleed in.
        captured: dict = {}
        _install_fake_sdk(monkeypatch, assistant_text="ok", captured=captured)
        from src.providers.claude_code import ClaudeCodeLLM
        adapter = ClaudeCodeLLM(model="claude-sonnet-4-6")

        adapter.invoke([{"role": "user", "content": "hi"}])

        opts = captured["options"]
        assert opts.tools == []
        assert opts.allowed_tools == []
        assert opts.mcp_servers == {}
        assert opts.strict_mcp_config is True
        assert opts.max_turns == 1
        assert opts.permission_mode == "dontAsk"
        assert opts.model == "claude-sonnet-4-6"

    def test_options_carry_system_prompt_from_system_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}
        _install_fake_sdk(monkeypatch, assistant_text="ok", captured=captured)
        from src.providers.claude_code import ClaudeCodeLLM
        adapter = ClaudeCodeLLM()

        adapter.invoke([
            {"role": "system", "content": "You are a trading agent."},
            {"role": "user", "content": "buy BTC"},
        ])

        opts = captured["options"]
        assert opts.system_prompt == "You are a trading agent."
        assert "[USER]" in captured["prompt"]
        assert "buy BTC" in captured["prompt"]

    def test_cwd_defaults_to_temp_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # An isolated cwd is the second half of the no-bleed guarantee — if
        # the SDK ran in the user's project root, their CLAUDE.md would be
        # auto-included in the system prompt.
        import tempfile
        captured: dict = {}
        _install_fake_sdk(monkeypatch, assistant_text="ok", captured=captured)
        from src.providers.claude_code import ClaudeCodeLLM
        adapter = ClaudeCodeLLM()

        adapter.invoke([{"role": "user", "content": "hi"}])

        opts = captured["options"]
        assert opts.cwd == tempfile.gettempdir()

    def test_custom_cwd_passed_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}
        _install_fake_sdk(monkeypatch, assistant_text="ok", captured=captured)
        from src.providers.claude_code import ClaudeCodeLLM
        adapter = ClaudeCodeLLM(cwd="/tmp/custom-cc-cwd")

        adapter.invoke([{"role": "user", "content": "hi"}])

        assert captured["options"].cwd == "/tmp/custom-cc-cwd"


# ---------------------------------------------------------------------------
# bind_tools: v1 must reject tools with a clear hint
# ---------------------------------------------------------------------------


class TestBindToolsRejection:
    def test_bind_tools_with_tools_raises_not_implemented(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_sdk(monkeypatch, assistant_text="ok")
        from src.providers.claude_code import ClaudeCodeLLM, SUPPORTS_TOOL_CALLS_HINT
        adapter = ClaudeCodeLLM()

        with pytest.raises(NotImplementedError, match="tool calling"):
            adapter.bind_tools([{"type": "function", "function": {"name": "x"}}])
        assert "Claude Agent SDK" in SUPPORTS_TOOL_CALLS_HINT

    def test_bind_tools_with_empty_list_returns_self(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # ``ChatLLM.chat(..., tools=None)`` never calls ``bind_tools``, but
        # ``bind_tools([])`` should still work as a no-op so callers don't have
        # to special-case empty lists.
        _install_fake_sdk(monkeypatch, assistant_text="ok")
        from src.providers.claude_code import ClaudeCodeLLM
        adapter = ClaudeCodeLLM()
        assert adapter.bind_tools([]) is adapter


# ---------------------------------------------------------------------------
# Stream wrapper: yields one aggregated message
# ---------------------------------------------------------------------------


class TestStream:
    def test_stream_yields_single_completed_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # v1 simplification: stream() yields the fully aggregated message as
        # one chunk so the stream-then-aggregate code path in chat.py still
        # works without provider-specific branching.
        _install_fake_sdk(monkeypatch, assistant_text="Hi.", stop_reason="end_turn")
        from src.providers.claude_code import ClaudeCodeLLM
        adapter = ClaudeCodeLLM()

        chunks = list(adapter.stream([{"role": "user", "content": "hi"}]))
        assert len(chunks) == 1
        assert chunks[0].content == "Hi."
        assert chunks[0].response_metadata["finish_reason"] == "stop"
