"""LANGCHAIN_REASONING_EFFORT delivery per provider.

The setting has two mutually exclusive delivery paths:

* Relays that require an opt-in (OpenRouter, Requesty) receive
  ``extra_body={"reasoning": {"effort": ...}}``.
* ChatOpenAI-compatible providers receive a top-level ``reasoning_effort``. Its ``gpt-5.6-*``
  models reject function tools on ``/v1/chat/completions`` without one::

      Function tools with reasoning_effort are not supported for gpt-5.6-sol
      in /v1/chat/completions. To use function tools, use /v1/responses or set
      reasoning_effort to 'none'.

Any ChatOpenAI-compatible provider/model with an effort and no explicit
transport setting uses Chat Completions; explicit ``true`` selects the
Responses API for endpoints that support it.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import api_server
import src.providers.llm as llm_mod
from src.providers.llm import build_llm, uses_responses_api


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


@pytest.mark.parametrize(
    ("provider", "adapter", "native_available", "expected"),
    [
        ("openai", None, False, True),
        ("anthropic", None, False, False),
        ("openai-codex", None, False, False),
        ("deepseek", "openai-compatible", True, True),
        ("deepseek", "compat", True, True),
        ("deepseek", "native", False, False),
        ("deepseek", "auto", True, False),
        ("deepseek", "auto", False, True),
    ],
)
def test_uses_responses_api_matches_provider_route(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    adapter: str | None,
    native_available: bool,
    expected: bool,
) -> None:
    monkeypatch.setattr(llm_mod, "_native_deepseek_adapter_available", lambda: native_available)

    assert uses_responses_api(provider, True, adapter) is expected


class TestDirectOpenAI:
    def test_explicit_none_is_forwarded(self) -> None:
        """'none' is a real value here, not a synonym for unset."""
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "openai",
                "OPENAI_API_KEY": "sk-test",
                "LANGCHAIN_MODEL_NAME": "gpt-5.6-sol",
                "LANGCHAIN_REASONING_EFFORT": "none",
                "LANGCHAIN_USE_RESPONSES_API": "false",
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
                "LANGCHAIN_USE_RESPONSES_API": "false",
            }
        )

        assert kwargs["reasoning_effort"] == "high"

    def test_foreign_gateway_behind_the_openai_label_is_not_sent_the_field(self) -> None:
        """A base-URL override means the OpenAI label is no longer OpenAI.

        Ollama, LiteLLM and corporate proxies speak the OpenAI wire format
        without promising to accept every OpenAI field, and a strict body
        validator rejects the unknown key outright. The label alone cannot
        authorize it — only the host can.
        """
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "openai",
                "OPENAI_API_KEY": "sk-test",
                "OPENAI_BASE_URL": "https://gateway.example/v1",
                "LANGCHAIN_MODEL_NAME": "gpt-5.6-luna",
                "LANGCHAIN_REASONING_EFFORT": "high",
            }
        )

        assert kwargs["reasoning_effort"] is None

    def test_openai_host_receives_the_field(self) -> None:
        """No override means the request really does reach api.openai.com."""
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "openai",
                "OPENAI_API_KEY": "sk-test",
                "LANGCHAIN_MODEL_NAME": "gpt-5.6-luna",
                "LANGCHAIN_REASONING_EFFORT": "high",
                "LANGCHAIN_USE_RESPONSES_API": "false",
            }
        )

        assert kwargs["reasoning_effort"] == "high"

    def test_deepseek_flash_model_keeps_effort_on_openai_wire(self) -> None:
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "openai",
                "OPENAI_API_KEY": "sk-test",
                "OPENAI_BASE_URL": "https://gateway.example/v1",
                "LANGCHAIN_MODEL_NAME": "deepseek-v4-flash-0731",
                "LANGCHAIN_REASONING_EFFORT": "max",
                "LANGCHAIN_USE_RESPONSES_API": "false",
            }
        )

        assert kwargs["reasoning_effort"] == "max"

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
    def test_deepseek_openai_compatible_receives_top_level_effort(self) -> None:
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "deepseek",
                "DEEPSEEK_API_KEY": "ds-test",
                "DEEPSEEK_BASE_URL": "https://gateway.example/v1",
                "LANGCHAIN_MODEL_NAME": "deepseek-v4-flash",
                "LANGCHAIN_REASONING_EFFORT": "high",
                "VIBE_TRADING_DEEPSEEK_ADAPTER": "openai-compatible",
                "LANGCHAIN_USE_RESPONSES_API": "false",
            }
        )

        assert kwargs["reasoning_effort"] == "high"
        assert kwargs["extra_body"] is None

    def test_gemini_is_not_on_the_allowlist(self) -> None:
        """Gemini's OpenAI-compatible endpoint has not been verified for this field.

        ``top_level_reasoning_effort`` is a positive allowlist: a provider joins
        it once a real request to it has been watched to succeed, not because it
        speaks the OpenAI wire format. Until then the effort is a no-op for
        Gemini, which is the safe failure — the alternative is every request
        failing on a rejected key.
        """
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "gemini",
                "GEMINI_API_KEY": "gm-test",
                "GEMINI_BASE_URL": "https://gateway.example/v1",
                "LANGCHAIN_MODEL_NAME": "gemini-3.5-flash",
                "LANGCHAIN_REASONING_EFFORT": "high",
                "LANGCHAIN_USE_RESPONSES_API": "false",
            }
        )

        assert kwargs["reasoning_effort"] is None
        assert kwargs["extra_body"] is None

    def test_every_allowlisted_provider_has_a_recorded_reason(self) -> None:
        """The allowlist stays short and every entry is accounted for here.

        A new provider flipping ``top_level_reasoning_effort=True`` has to be
        added to this set deliberately, with live evidence, rather than picked
        up by a broad predicate. If this fails, someone widened the allowlist —
        confirm a real request to that endpoint succeeded before updating it.
        """
        from src.providers.capabilities import _PROVIDERS

        allowlisted = {
            name for name, caps in _PROVIDERS.items() if caps.top_level_reasoning_effort
        }
        assert allowlisted == {"openai", "deepseek"}

    def test_explicit_openai_provider_keeps_effort_for_deepseek_model(self) -> None:
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "openai",
                "OPENAI_API_KEY": "sk-test",
                "LANGCHAIN_MODEL_NAME": "deepseek-v4-pro",
                "LANGCHAIN_REASONING_EFFORT": "high",
                "VIBE_TRADING_DEEPSEEK_ADAPTER": "openai-compatible",
                "LANGCHAIN_USE_RESPONSES_API": "false",
            }
        )

        assert kwargs["reasoning_effort"] == "high"

    def test_unknown_openai_compatible_provider_receives_top_level_effort(
        self,
    ) -> None:
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "some-openai-compatible-gateway",
                "OPENAI_API_KEY": "sk-test",
                "LANGCHAIN_MODEL_NAME": "house-model-1",
                "LANGCHAIN_REASONING_EFFORT": "high",
                "LANGCHAIN_USE_RESPONSES_API": "false",
            }
        )

        assert kwargs["reasoning_effort"] == "high"


class TestAnthropicNativeProvider:
    """The native Anthropic adapter takes effort as `reasoning_effort`.

    langchain-anthropic renders that kwarg as ``output_config={'effort': ...}``
    on the wire, which is where the Anthropic API expects it — unlike the
    OpenAI-compatible providers above, which send a top-level field.
    """

    def _capture(self, env: dict[str, str]) -> dict[str, Any]:
        """Run build_llm for the Anthropic provider and return adapter kwargs.

        Patches the temperature-safe subclass factory rather than the module
        attribute, because ``_build_anthropic`` resolves ChatAnthropic lazily
        through ``import_module`` at call time.

        Args:
            env: Full environment for the call; every other variable is cleared.

        Returns:
            Keyword arguments build_llm passed to the adapter.
        """
        if importlib.util.find_spec("langchain_anthropic") is None:
            pytest.skip("langchain-anthropic is not installed")
        captured: dict[str, Any] = {}

        class _FakeChatAnthropic:
            model_fields = {"reasoning_effort": object()}

            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

        with patch.dict(os.environ, env, clear=True):
            with patch.object(
                llm_mod, "_make_temperature_safe_anthropic", lambda _: _FakeChatAnthropic
            ):
                build_llm()
        return captured

    def _env(self, **overrides: str) -> dict[str, str]:
        """Return a minimal Anthropic environment with optional overrides."""
        env = {
            "LANGCHAIN_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "LANGCHAIN_MODEL_NAME": "claude-fable-5",
        }
        env.update(overrides)
        return env

    def test_effort_reaches_the_anthropic_adapter(self) -> None:
        """The gap this closes: the value was read and then dropped."""
        kwargs = self._capture(self._env(LANGCHAIN_REASONING_EFFORT="high"))

        assert kwargs["reasoning_effort"] == "high"

    def test_unset_effort_stays_absent(self) -> None:
        kwargs = self._capture(self._env())

        assert kwargs["reasoning_effort"] is None

    def test_temperature_is_omitted_when_effort_is_sent(self) -> None:
        """Effort enables adaptive thinking, which rejects temperature != 1.

        The platform's default is 0.0, so sending both fails the request with
        `temperature may only be set to 1 when thinking is enabled or in
        adaptive mode`. The pre-existing temperature-safe wrapper does not
        catch this — it handles models that reject temperature outright.
        """
        kwargs = self._capture(self._env(LANGCHAIN_REASONING_EFFORT="high"))

        assert kwargs["temperature"] is None

    def test_temperature_is_preserved_without_effort(self) -> None:
        """No effort means no thinking, so the deterministic default stands."""
        kwargs = self._capture(self._env(LANGCHAIN_TEMPERATURE="0.0"))

        assert kwargs["temperature"] == 0.0

    def test_a_model_that_rejects_effort_is_not_sent_it(self) -> None:
        """Haiku 4.5 answers `This model does not support the effort parameter`.

        This is the case that matters in a swarm: a per-agent model split puts
        cheap models on the data-gathering seats, and a global effort setting
        would fail those workers with a hard 400 rather than a warning.
        """
        kwargs = self._capture(
            self._env(
                LANGCHAIN_MODEL_NAME="claude-haiku-4-5",
                LANGCHAIN_REASONING_EFFORT="high",
            )
        )

        assert kwargs["reasoning_effort"] is None
        assert kwargs["temperature"] == 0.0

    def test_an_unrecognised_model_is_not_sent_it(self) -> None:
        """The allowlist is positive: unknown means no, not maybe.

        Guessing wrong breaks the request outright, while a missing entry only
        leaves the effort setting inert — the same asymmetry that keeps
        `top_level_reasoning_effort` a positive allowlist in capabilities.py.
        """
        kwargs = self._capture(
            self._env(
                LANGCHAIN_MODEL_NAME="some-future-anthropic-model",
                LANGCHAIN_REASONING_EFFORT="high",
            )
        )

        assert kwargs["reasoning_effort"] is None

    def test_an_adapter_without_the_field_is_not_sent_it(self) -> None:
        """pyproject allows langchain-anthropic>=1.3.0, which predates the field.

        ChatAnthropic sets `extra="ignore"`, so an older install would swallow
        the kwarg silently — while the caller still paid the dropped
        temperature. Sending neither is the honest outcome.
        """
        captured: dict[str, Any] = {}

        class _OldChatAnthropic:
            """Stands in for a langchain-anthropic without the field."""

            model_fields: dict[str, Any] = {}

            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

        old_module = SimpleNamespace(ChatAnthropic=_OldChatAnthropic)

        with patch.dict(
            os.environ, self._env(LANGCHAIN_REASONING_EFFORT="high"), clear=True
        ):
            with patch.object(llm_mod, "import_module", lambda _: old_module):
                with patch.object(
                    llm_mod,
                    "_make_temperature_safe_anthropic",
                    lambda _: _OldChatAnthropic,
                ):
                    build_llm()

        assert captured["reasoning_effort"] is None
        assert captured["temperature"] == 0.0

    def test_the_installed_adapter_renders_effort_as_output_config(self) -> None:
        """Guards the assumption the whole change rests on.

        `reasoning_effort` is only worth forwarding because langchain-anthropic
        turns it into the `output_config.effort` field the API reads. If a
        future release renames or drops that mapping, this fails here rather
        than silently at request time.
        """
        if importlib.util.find_spec("langchain_anthropic") is None:
            pytest.skip("langchain-anthropic is not installed")
        from langchain_anthropic import ChatAnthropic
        from langchain_core.messages import HumanMessage

        instance = ChatAnthropic(
            model="claude-fable-5", api_key="sk-ant-test", reasoning_effort="high"
        )
        payload = instance._get_request_payload([HumanMessage(content="hi")])

        assert payload["output_config"]["effort"] == "high"


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
                "LANGCHAIN_USE_RESPONSES_API": "false",
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
                "LANGCHAIN_USE_RESPONSES_API": "false",
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

    def test_deepseek_flash_effort_is_serialized_for_chat_completions(self) -> None:
        if llm_mod.ChatOpenAIWithReasoning is None:
            pytest.skip("langchain-openai is not installed")
        from langchain_core.messages import HumanMessage

        instance = llm_mod.ChatOpenAIWithReasoning(
            model="deepseek-v4-flash-0731",
            api_key="sk-test",
            reasoning_effort="max",
        )

        payload = instance._get_request_payload([HumanMessage(content="hi")])

        assert payload["reasoning_effort"] == "max"


class TestResponsesAPI:
    def test_reasoning_effort_defaults_to_chat_completions(self) -> None:
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "openai",
                "OPENAI_API_KEY": "sk-test",
                "LANGCHAIN_MODEL_NAME": "gpt-5.6-sol",
                "LANGCHAIN_REASONING_EFFORT": "high",
            }
        )

        assert kwargs["use_responses_api"] is False
        assert kwargs["output_version"] is None
        assert kwargs["reasoning"] is None
        assert kwargs["reasoning_effort"] == "high"

    def test_any_provider_and_model_can_opt_into_responses_reasoning(self) -> None:
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "openai",
                "OPENAI_API_KEY": "sk-test",
                "OPENAI_BASE_URL": "https://gateway.example/v1",
                "LANGCHAIN_MODEL_NAME": "arbitrary-reasoning-model",
                "LANGCHAIN_REASONING_EFFORT": "high",
                "LANGCHAIN_USE_RESPONSES_API": "true",
            }
        )

        assert kwargs["use_responses_api"] is True
        assert kwargs["output_version"] == "responses/v1"
        assert kwargs["reasoning"] == {"effort": "high"}
        assert kwargs["reasoning_effort"] is None

    def test_named_deepseek_can_opt_into_responses_reasoning(self) -> None:
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "deepseek",
                "DEEPSEEK_API_KEY": "ds-test",
                "DEEPSEEK_BASE_URL": "https://gateway.example/v1",
                "LANGCHAIN_MODEL_NAME": "deepseek-v4-flash",
                "LANGCHAIN_REASONING_EFFORT": "max",
                "VIBE_TRADING_DEEPSEEK_ADAPTER": "openai-compatible",
                "LANGCHAIN_USE_RESPONSES_API": "true",
            }
        )

        assert kwargs["reasoning"] == {"effort": "max"}
        assert kwargs["reasoning_effort"] is None

    def test_explicit_chat_mode_remains_available_for_legacy_endpoints(self) -> None:
        kwargs = _capture_kwargs(
            {
                "LANGCHAIN_PROVIDER": "some-openai-compatible-gateway",
                "OPENAI_API_KEY": "sk-test",
                "OPENAI_BASE_URL": "https://gateway.example/v1",
                "LANGCHAIN_MODEL_NAME": "arbitrary-reasoning-model",
                "LANGCHAIN_REASONING_EFFORT": "high",
                "LANGCHAIN_USE_RESPONSES_API": "false",
            }
        )

        assert kwargs["use_responses_api"] is False
        assert kwargs["reasoning"] is None

    def test_responses_payload_does_not_assume_chat_messages(self) -> None:
        if llm_mod.ChatOpenAIWithReasoning is None:
            pytest.skip("langchain-openai is not installed")
        from langchain_core.messages import HumanMessage

        instance = llm_mod.ChatOpenAIWithReasoning(
            model="arbitrary-reasoning-model",
            api_key="sk-test",
            use_responses_api=True,
            output_version="responses/v1",
            reasoning={"effort": "high"},
        )

        payload = instance._get_request_payload([HumanMessage(content="hi")])

        assert payload["reasoning"] == {"effort": "high"}

    def test_responses_transport_sends_reasoning_to_the_responses_path(self) -> None:
        if llm_mod.ChatOpenAIWithReasoning is None:
            pytest.skip("langchain-openai is not installed")
        import httpx

        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "id": "resp_test",
                    "object": "response",
                    "created_at": 0,
                    "model": "reasoning-model",
                    "output": [
                        {
                            "id": "msg_test",
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "ok", "annotations": []}],
                        }
                    ],
                    "parallel_tool_calls": True,
                    "tool_choice": "auto",
                },
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            llm = llm_mod.ChatOpenAIWithReasoning(
                model="reasoning-model",
                api_key="sk-test",
                base_url="https://gateway.invalid/v1",
                http_client=client,
                use_responses_api=True,
                output_version="responses/v1",
                reasoning={"effort": "max"},
            )
            assert llm.invoke("hi").content

        assert seen["path"] == "/v1/responses"
        assert seen["body"]["reasoning"] == {"effort": "max"}

    def test_chat_transport_sends_reasoning_effort_to_chat_completions(self) -> None:
        if llm_mod.ChatOpenAIWithReasoning is None:
            pytest.skip("langchain-openai is not installed")
        import httpx

        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl_test",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "reasoning-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            llm = llm_mod.ChatOpenAIWithReasoning(
                model="reasoning-model",
                api_key="sk-test",
                base_url="https://gateway.invalid/v1",
                http_client=client,
                reasoning_effort="max",
            )
            assert llm.invoke("hi").content == "ok"

        assert seen["path"] == "/v1/chat/completions"
        assert seen["body"]["reasoning_effort"] == "max"


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
