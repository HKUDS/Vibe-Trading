"""Tests for LANGCHAIN_REASONING_EFFORT pass-through to OpenAI-compatible providers.

OpenAI's gpt-5.6-* models reject function tools on /v1/chat/completions
unless the request carries an explicit ``reasoning_effort`` — including the
literal ``'none'``::

    Function tools with reasoning_effort are not supported for gpt-5.6-sol
    in /v1/chat/completions. To use function tools, use /v1/responses or set
    reasoning_effort to 'none'.

Previously the setting only fed the OpenRouter ``extra_body`` opt-in and
never reached ``ChatOpenAI`` for direct providers, so these models were
unusable as the agent LLM.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from src.config.accessor import reset_env_config
from src.providers.llm import build_llm


def _build_with_env(env: dict[str, str]) -> MagicMock:
    """Run build_llm under a patched environment and return the LLM mock."""
    base = {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI_", "LANGCHAIN_", "OPENROUTER_"))}
    base.update({"OPENAI_API_KEY": "sk-test"})
    base.update(env)
    mock_cls = MagicMock(name="ChatOpenAIWithReasoning")
    with patch.dict(os.environ, base, clear=True):
        reset_env_config()
        try:
            with patch("src.providers.llm.ChatOpenAIWithReasoning", mock_cls):
                build_llm(model_name="gpt-5.6-sol")
        finally:
            reset_env_config()
    return mock_cls


class TestReasoningEffortPassThrough:
    """Direct (non-relay) providers forward the configured effort."""

    def test_openai_effort_none_is_forwarded(self) -> None:
        mock_cls = _build_with_env(
            {
                "LANGCHAIN_PROVIDER": "openai",
                "LANGCHAIN_REASONING_EFFORT": "none",
            }
        )
        kwargs = mock_cls.call_args.kwargs
        assert kwargs["reasoning_effort"] == "none"
        assert kwargs["extra_body"] is None

    def test_openai_effort_unset_stays_absent(self) -> None:
        mock_cls = _build_with_env({"LANGCHAIN_PROVIDER": "openai"})
        kwargs = mock_cls.call_args.kwargs
        assert kwargs["reasoning_effort"] is None

    def test_openrouter_keeps_extra_body_opt_in(self) -> None:
        mock_cls = _build_with_env(
            {
                "LANGCHAIN_PROVIDER": "openrouter",
                "OPENROUTER_API_KEY": "or-test",
                "LANGCHAIN_REASONING_EFFORT": "high",
            }
        )
        kwargs = mock_cls.call_args.kwargs
        assert kwargs["extra_body"] == {"reasoning": {"effort": "high"}}
        assert kwargs["reasoning_effort"] is None


class TestSettingsAcceptNone:
    """The settings API allowlist admits the explicit 'none' value."""

    def test_none_is_a_valid_reasoning_effort(self) -> None:
        from src.api.settings_routes import LLM_REASONING_EFFORTS

        assert "none" in LLM_REASONING_EFFORTS
