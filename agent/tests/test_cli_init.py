from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import cli


def _provider_choice_number(provider: str) -> int:
    """Resolve a CLI menu choice by provider identity, not list position."""
    matches = [
        index
        for index, option in enumerate(cli._PROVIDER_CHOICES, start=1)
        if option["provider"] == provider
    ]
    assert len(matches) == 1, f"expected one CLI choice for {provider!r}, got {len(matches)}"
    return matches[0]


class TestCliInit:
    def test_render_env_content_openrouter(self) -> None:
        content = cli._render_env_content(
            {
                "LANGCHAIN_TEMPERATURE": "0.0",
                "LANGCHAIN_PROVIDER": "openrouter",
                "OPENROUTER_API_KEY": "sk-or-test",
                "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
                "LANGCHAIN_MODEL_NAME": "deepseek/deepseek-v4-pro",
                "TIMEOUT_SECONDS": "120",
                "MAX_RETRIES": "2",
                "TUSHARE_TOKEN": "ts-token",
            }
        )

        assert "LANGCHAIN_PROVIDER=openrouter" in content
        assert "OPENROUTER_API_KEY=sk-or-test" in content
        assert "OPENROUTER_BASE_URL=https://openrouter.ai/api/v1" in content
        assert "LANGCHAIN_MODEL_NAME=deepseek/deepseek-v4-pro" in content
        assert "TUSHARE_TOKEN=ts-token" in content
        assert "TIMEOUT_SECONDS=120" in content
        assert "MAX_RETRIES=2" in content

    def test_render_env_content_gemini(self) -> None:
        content = cli._render_env_content(
            {
                "LANGCHAIN_TEMPERATURE": "0.0",
                "LANGCHAIN_PROVIDER": "gemini",
                "GEMINI_API_KEY": "gem-key",
                "GEMINI_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "LANGCHAIN_MODEL_NAME": "gemini-3.5-flash",
                "TIMEOUT_SECONDS": "120",
                "MAX_RETRIES": "2",
            }
        )

        assert "LANGCHAIN_PROVIDER=gemini" in content
        assert "GEMINI_API_KEY=gem-key" in content
        assert "GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/" in content
        assert "LANGCHAIN_MODEL_NAME=gemini-3.5-flash" in content

    def test_validate_api_key_prefix(self) -> None:
        assert cli._validate_api_key("sk-or-abc", "sk-or-") is True
        assert cli._validate_api_key("bad-key", "sk-or-") is False
        assert cli._validate_api_key("anything", None) is True

    def test_cmd_init_writes_agent_env_for_openrouter(self, tmp_path: Path) -> None:
        env_path = tmp_path / ".env"

        with patch.object(cli, "_INIT_ENV_PATH", env_path), \
             patch.object(
                 cli.IntPrompt,
                 "ask",
                 return_value=_provider_choice_number("openrouter"),
             ), \
             patch.object(
                 cli.Prompt,
                 "ask",
                 side_effect=[
                     "sk-or-test-key",
                     "https://openrouter.ai/api/v1",
                     "deepseek/deepseek-v4-pro",
                     "ts-token",
                 ],
             ):
            result = cli.cmd_init()

        assert result == 0
        content = env_path.read_text(encoding="utf-8")
        assert "LANGCHAIN_PROVIDER=openrouter" in content
        assert "OPENROUTER_API_KEY=sk-or-test-key" in content
        assert "OPENROUTER_BASE_URL=https://openrouter.ai/api/v1" in content
        assert "LANGCHAIN_MODEL_NAME=deepseek/deepseek-v4-pro" in content
        assert "TUSHARE_TOKEN=ts-token" in content

    def test_cmd_init_ollama_skips_api_key(self, tmp_path: Path) -> None:
        env_path = tmp_path / ".env"

        with patch.object(cli, "_INIT_ENV_PATH", env_path), \
             patch.object(
                 cli.IntPrompt,
                 "ask",
                 return_value=_provider_choice_number("ollama"),
             ), \
             patch.object(
                 cli.Prompt,
                 "ask",
                 side_effect=[
                     "http://localhost:11434",
                     "qwen2.5:32b",
                     "",
                     "",
                 ],
             ):
            result = cli.cmd_init()

        assert result == 0
        content = env_path.read_text(encoding="utf-8")
        assert "LANGCHAIN_PROVIDER=ollama" in content
        assert "OLLAMA_BASE_URL=http://localhost:11434" in content
        assert "LANGCHAIN_MODEL_NAME=qwen2.5:32b" in content
        assert "OPENAI_API_KEY=" not in content
        assert "OPENROUTER_API_KEY=" not in content

    def test_cmd_init_openai_codex_uses_supported_default_and_oauth(self, tmp_path: Path) -> None:
        env_path = tmp_path / ".env"

        with patch.object(cli, "_INIT_ENV_PATH", env_path), \
             patch.object(
                 cli.IntPrompt,
                 "ask",
                 return_value=_provider_choice_number("openai-codex"),
             ), \
             patch.object(
                 cli.Prompt,
                 "ask",
                 side_effect=[
                     "https://chatgpt.com/backend-api/codex/responses",
                     "openai-codex/gpt-5.4",
                     "",
                 ],
             ):
            result = cli.cmd_init()

        assert result == 0
        content = env_path.read_text(encoding="utf-8")
        assert "LANGCHAIN_PROVIDER=openai-codex" in content
        assert "OPENAI_CODEX_BASE_URL=https://chatgpt.com/backend-api/codex/responses" in content
        assert "LANGCHAIN_MODEL_NAME=openai-codex/gpt-5.4" in content
        assert "OPENAI_API_KEY=" not in content

    def test_cmd_init_anyrouter_uses_responses_provider(self, tmp_path: Path) -> None:
        env_path = tmp_path / ".env"

        with patch.object(cli, "_INIT_ENV_PATH", env_path), \
             patch.object(
                 cli.IntPrompt,
                 "ask",
                 return_value=_provider_choice_number("anyrouter"),
             ), \
             patch.object(
                 cli.Prompt,
                 "ask",
                 side_effect=[
                     "sk-test-key",
                     "https://region.example/v1",
                     "gpt-5.6-sol",
                     "",
                 ],
             ):
            result = cli.cmd_init()

        assert result == 0
        content = env_path.read_text(encoding="utf-8")
        assert "LANGCHAIN_PROVIDER=anyrouter" in content
        assert "ANYROUTER_API_KEY=sk-test-key" in content
        assert "ANYROUTER_BASE_URL=https://region.example/v1" in content
        assert "LANGCHAIN_MODEL_NAME=gpt-5.6-sol" in content
