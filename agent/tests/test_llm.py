"""Tests for LLM provider mapping and JSON extraction."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from src.providers.llm import _extract_balanced_json, _sync_provider_env


# ---------------------------------------------------------------------------
# _sync_provider_env
# ---------------------------------------------------------------------------


class TestSyncProviderEnv:
    """Provider-specific env vars → OPENAI_* mapping."""

    def _run_sync(self, env: dict[str, str]) -> dict[str, str]:
        """Run _sync_provider_env with a clean env and return relevant keys."""
        # Reset the dotenv guard so it doesn't skip
        import src.providers.llm as llm_mod
        llm_mod._dotenv_loaded = True  # pretend already loaded

        clean = {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI_", "LANGCHAIN_", "DEEPSEEK_", "GROQ_", "OLLAMA_", "DASHSCOPE_", "ZAI_"))}
        clean.update(env)
        with patch.dict(os.environ, clean, clear=True):
            _sync_provider_env()
            return {
                "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
                "OPENAI_API_BASE": os.environ.get("OPENAI_API_BASE", ""),
                "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL", ""),
            }

    def test_openai_default(self) -> None:
        result = self._run_sync({
            "OPENAI_API_KEY": "sk-test",
        })
        assert result["OPENAI_API_KEY"] == "sk-test"

    def test_deepseek_provider(self) -> None:
        result = self._run_sync({
            "LANGCHAIN_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "ds-key-123",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        })
        assert result["OPENAI_API_KEY"] == "ds-key-123"
        assert result["OPENAI_API_BASE"] == "https://api.deepseek.com/v1"

    def test_groq_provider(self) -> None:
        result = self._run_sync({
            "LANGCHAIN_PROVIDER": "groq",
            "GROQ_API_KEY": "gsk-test",
            "GROQ_BASE_URL": "https://api.groq.com/openai/v1",
        })
        assert result["OPENAI_API_KEY"] == "gsk-test"
        assert "groq" in result["OPENAI_API_BASE"]

    def test_ollama_no_key_required(self) -> None:
        result = self._run_sync({
            "LANGCHAIN_PROVIDER": "ollama",
            "OLLAMA_BASE_URL": "http://localhost:11434/v1",
        })
        # Ollama uses "ollama" as fallback key
        assert result["OPENAI_API_KEY"] in ("ollama", "")
        assert "localhost" in result["OPENAI_API_BASE"]

    def test_qwen_alias_to_dashscope(self) -> None:
        result = self._run_sync({
            "LANGCHAIN_PROVIDER": "qwen",
            "DASHSCOPE_API_KEY": "qwen-key",
            "DASHSCOPE_BASE_URL": "https://dashscope.aliyuncs.com/v1",
        })
        assert result["OPENAI_API_KEY"] == "qwen-key"

    def test_zai_provider(self) -> None:
        result = self._run_sync({
            "LANGCHAIN_PROVIDER": "zai",
            "ZAI_API_KEY": "zai-key-test",
            "ZAI_BASE_URL": "https://api.z.ai/api/coding/paas/v4",
        })
        assert result["OPENAI_API_KEY"] == "zai-key-test"
        assert result["OPENAI_API_BASE"] == "https://api.z.ai/api/coding/paas/v4"

    def test_unknown_provider_falls_back_to_openai(self) -> None:
        result = self._run_sync({
            "LANGCHAIN_PROVIDER": "unknown_provider_xyz",
            "OPENAI_API_KEY": "sk-fallback",
        })
        assert result["OPENAI_API_KEY"] == "sk-fallback"

    def test_provider_key_fallback_to_openai_key(self) -> None:
        """If provider-specific key is missing, fall back to OPENAI_API_KEY."""
        result = self._run_sync({
            "LANGCHAIN_PROVIDER": "deepseek",
            "OPENAI_API_KEY": "sk-shared",
        })
        assert result["OPENAI_API_KEY"] == "sk-shared"


# ---------------------------------------------------------------------------
# _extract_balanced_json
# ---------------------------------------------------------------------------


class TestExtractBalancedJson:
    def test_simple_json(self) -> None:
        result = _extract_balanced_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_embedded_in_text(self) -> None:
        text = 'Here is the config: {"a": 1, "b": 2} and some more text.'
        result = _extract_balanced_json(text)
        assert result == {"a": 1, "b": 2}

    def test_nested_json(self) -> None:
        text = '{"outer": {"inner": [1, 2, 3]}}'
        result = _extract_balanced_json(text)
        assert result["outer"]["inner"] == [1, 2, 3]

    def test_escaped_quotes(self) -> None:
        text = r'{"msg": "he said \"hello\""}'
        result = _extract_balanced_json(text)
        assert result is not None
        assert "hello" in result["msg"]

    def test_no_json(self) -> None:
        assert _extract_balanced_json("no json here") is None

    def test_empty_string(self) -> None:
        assert _extract_balanced_json("") is None

    def test_braces_in_strings(self) -> None:
        text = '{"pattern": "if (x > 0) { return x; }"}'
        result = _extract_balanced_json(text)
        assert result is not None
        assert "return x" in result["pattern"]

    def test_multiple_objects_returns_first(self) -> None:
        text = '{"a": 1} {"b": 2}'
        result = _extract_balanced_json(text)
        assert result == {"a": 1}
