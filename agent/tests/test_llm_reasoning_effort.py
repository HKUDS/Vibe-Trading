"""LANGCHAIN_REASONING_EFFORT delivery per provider.

The setting has two mutually exclusive delivery paths:

* Relays that require an opt-in (OpenRouter, Requesty) receive
  ``extra_body={"reasoning": {"effort": ...}}``.
* Direct OpenAI receives a top-level ``reasoning_effort``. Its ``gpt-5.6-*``
  models reject function tools on ``/v1/chat/completions`` without one::

      Function tools with reasoning_effort are not supported for gpt-5.6-sol
      in /v1/chat/completions. To use function tools, use /v1/responses or set
      reasoning_effort to 'none'.

Every other OpenAI-compatible provider must receive neither, because a stale
global effort value would otherwise ride along on payloads that can reject the
unknown field (DeepSeek is the documented case in ``test_provider_diagnostics``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import api_server
import src.providers.llm as llm_mod
from src.providers.llm import build_llm


@pytest.fixture(autouse=True)
def _pin_dotenv_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mark the dotenv as loaded so build_llm never reads a real .env.

    Without this, ``build_llm()`` under a patched environment can load the
    developer's own ``~/.vibe-trading/.env`` and leak real provider settings
    into the assertions. ``monkeypatch`` restores the module flag afterwards.
    """
    monkeypatch.setattr(llm_mod, "_dotenv_loaded", True)


@pytest.fixture
def settings_env_path(tmp_path: Path) -> Path:
    """Return the throwaway ``.env`` the settings endpoint writes to."""
    return tmp_path / ".env"


@pytest.fixture
def settings_client(
    tmp_path: Path, settings_env_path: Path, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    """Serve the settings API against a throwaway .env pair in tmp_path."""
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "\n".join(
            [
                "LANGCHAIN_PROVIDER=openai",
                "LANGCHAIN_MODEL_NAME=gpt-5.6-sol",
                "OPENAI_API_KEY=sk-xxx",
                "LANGCHAIN_REASONING_EFFORT=",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(api_server, "ENV_PATH", settings_env_path)
    monkeypatch.setattr(
        api_server, "LEGACY_ENV_PATH", tmp_path / "legacy" / ".env", raising=False
    )
    monkeypatch.setattr(api_server, "ENV_EXAMPLE_PATH", env_example)
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _settings_payload(effort: str) -> dict[str, Any]:
    """Return a valid LLM settings body carrying the given reasoning effort."""
    return {
        "provider": "openai",
        "model_name": "gpt-5.6-sol",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-endpoint-test",
        "temperature": 0.0,
        "timeout_seconds": 120,
        "max_retries": 2,
        "reasoning_effort": effort,
    }


def _capture_kwargs(env: dict[str, str]) -> dict[str, Any]:
    """Run build_llm in a replaced environment and return the adapter kwargs.

    Args:
        env: Full environment for the call; every other variable is cleared.

    Returns:
        Keyword arguments build_llm passed to the ChatOpenAI subclass.
    """
    captured: dict[str, Any] = {}

    class _FakeChatOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    with patch.dict(os.environ, env, clear=True):
        with patch.object(llm_mod, "ChatOpenAIWithReasoning", _FakeChatOpenAI):
            build_llm()
    return captured


class TestDirectOpenAI:
    """Direct OpenAI is the one provider verified to take the top-level field."""

    def test_explicit_none_is_forwarded(self) -> None:
        """'none' is a real value here, not a synonym for unset."""
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "openai",
                "OPENAI_API_KEY": "sk-test",
                "LANGCHAIN_MODEL_NAME": "gpt-5.6-sol",
                "LANGCHAIN_REASONING_EFFORT": "none",
            }
        )

        assert kwargs["reasoning_effort"] == "none"
        assert kwargs["extra_body"] is None

    def test_graded_effort_is_forwarded(self) -> None:
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "openai",
                "OPENAI_API_KEY": "sk-test",
                "LANGCHAIN_MODEL_NAME": "gpt-5.6-sol",
                "LANGCHAIN_REASONING_EFFORT": "high",
            }
        )

        assert kwargs["reasoning_effort"] == "high"

    def test_unset_effort_stays_absent(self) -> None:
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "openai",
                "OPENAI_API_KEY": "sk-test",
                "LANGCHAIN_MODEL_NAME": "gpt-5.6-sol",
            }
        )

        assert kwargs["reasoning_effort"] is None
        assert kwargs["extra_body"] is None


class TestUnsupportedProviders:
    """A configured effort must never leak onto unverified providers."""

    def test_deepseek_never_receives_top_level_effort(self) -> None:
        """DeepSeek's documented invariant covers both delivery paths."""
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "deepseek",
                "DEEPSEEK_API_KEY": "ds-test",
                "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
                "LANGCHAIN_MODEL_NAME": "deepseek-v4-pro",
                "LANGCHAIN_REASONING_EFFORT": "high",
                "VIBE_TRADING_DEEPSEEK_ADAPTER": "openai-compatible",
            }
        )

        assert kwargs["reasoning_effort"] is None
        assert kwargs["extra_body"] is None

    def test_gemini_never_receives_top_level_effort(self) -> None:
        """Second unsupported provider: Gemini's OpenAI-compatible endpoint."""
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "gemini",
                "GEMINI_API_KEY": "gm-test",
                "GEMINI_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai",
                "LANGCHAIN_MODEL_NAME": "gemini-3.5-flash",
                "LANGCHAIN_REASONING_EFFORT": "high",
            }
        )

        assert kwargs["reasoning_effort"] is None
        assert kwargs["extra_body"] is None

    def test_model_inferred_provider_wins_over_openai_default(self) -> None:
        """provider=openai + a deepseek model resolves to DeepSeek, not OpenAI."""
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "openai",
                "OPENAI_API_KEY": "sk-test",
                "LANGCHAIN_MODEL_NAME": "deepseek-v4-pro",
                "LANGCHAIN_REASONING_EFFORT": "high",
                "VIBE_TRADING_DEEPSEEK_ADAPTER": "openai-compatible",
            }
        )

        assert kwargs["reasoning_effort"] is None

    def test_unknown_provider_does_not_inherit_openai_fallback(self) -> None:
        """Unknown names fall back to OpenAI capabilities but stay unverified."""
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "some-openai-compatible-gateway",
                "OPENAI_API_KEY": "sk-test",
                "LANGCHAIN_MODEL_NAME": "house-model-1",
                "LANGCHAIN_REASONING_EFFORT": "high",
            }
        )

        assert kwargs["reasoning_effort"] is None


class TestRelayOptIn:
    """OpenRouter/Requesty keep the pre-existing extra_body opt-in."""

    def test_openrouter_keeps_extra_body_and_no_top_level_field(self) -> None:
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "openrouter",
                "OPENROUTER_API_KEY": "or-test",
                "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
                "LANGCHAIN_MODEL_NAME": "deepseek/deepseek-v4-pro",
                "LANGCHAIN_REASONING_EFFORT": "high",
            }
        )

        assert kwargs["extra_body"] == {"reasoning": {"effort": "high"}}
        assert kwargs["reasoning_effort"] is None

    def test_requesty_keeps_extra_body_and_no_top_level_field(self) -> None:
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "requesty",
                "REQUESTY_API_KEY": "rq-test",
                "REQUESTY_BASE_URL": "https://router.requesty.ai/v1",
                "LANGCHAIN_MODEL_NAME": "openai/gpt-4o-mini",
                "LANGCHAIN_REASONING_EFFORT": "medium",
            }
        )

        assert kwargs["extra_body"] == {"reasoning": {"effort": "medium"}}
        assert kwargs["reasoning_effort"] is None


class TestRequestPayload:
    """The kwarg has to survive as a top-level chat-completions request field."""

    def _payload(self, effort: str | None) -> dict[str, Any]:
        """Serialize a one-message request with the given effort kwarg."""
        if llm_mod.ChatOpenAIWithReasoning is None:
            pytest.skip("langchain-openai is not installed")
        from langchain_core.messages import HumanMessage

        instance = llm_mod.ChatOpenAIWithReasoning(
            model="gpt-5.6-sol", api_key="sk-test", reasoning_effort=effort
        )
        return instance._get_request_payload([HumanMessage(content="hi")])

    def test_explicit_none_reaches_the_request(self) -> None:
        assert self._payload("none")["reasoning_effort"] == "none"

    def test_absent_effort_is_dropped_from_the_request(self) -> None:
        """None must not serialize as a null field on unsupported providers."""
        assert "reasoning_effort" not in self._payload(None)


class TestSettingsAllowlist:
    """The settings API admits the explicit 'none' value and says so."""

    def test_none_is_a_valid_reasoning_effort(self) -> None:
        from src.api.settings_routes import LLM_REASONING_EFFORTS

        assert "none" in LLM_REASONING_EFFORTS
        assert "" in LLM_REASONING_EFFORTS, "empty still means 'leave unset'"

    def test_none_persists_through_the_settings_endpoint(
        self, settings_client: TestClient, settings_env_path: Path
    ) -> None:
        response = settings_client.put("/settings/llm", json=_settings_payload("none"))

        assert response.status_code == 200
        assert "LANGCHAIN_REASONING_EFFORT=none" in settings_env_path.read_text(
            encoding="utf-8"
        )

    def test_rejection_message_lists_every_accepted_value(
        self, settings_client: TestClient
    ) -> None:
        """A rejected caller must not be told that only low..max are valid."""
        response = settings_client.put("/settings/llm", json=_settings_payload("bogus"))

        assert response.status_code == 400
        detail = response.json()["detail"]
        for value in ("none", "low", "medium", "high", "max"):
            assert value in detail, f"{value} missing from validation message"
