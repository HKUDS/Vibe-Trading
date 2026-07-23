"""Tests for LLM provider mapping and JSON extraction."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.providers.capabilities import (
    get_llm_credentials,
    get_provider_capabilities,
    provider_env_names,
)
from src.providers.llm import _sync_provider_env, build_llm


class TestProviderCapabilityAliases:
    """Provider aliases and model-name inference."""

    def test_glm_alias_uses_zhipu_capabilities(self) -> None:
        glm_caps = get_provider_capabilities("glm")
        zhipu_caps = get_provider_capabilities("zhipu")

        assert (
            glm_caps.name,
            glm_caps.api_key_env,
            glm_caps.base_url_env,
        ) == (
            zhipu_caps.name,
            zhipu_caps.api_key_env,
            zhipu_caps.base_url_env,
        )

    @pytest.mark.parametrize("model", ["glm-4.6", "glm-5.1", "glm-5.2"])
    def test_glm_model_inference_uses_zhipu(self, model: str) -> None:
        caps = get_provider_capabilities(provider=None, model=model)

        assert caps.name == "zhipu"

    def test_glm_provider_env_names_use_zhipu_env(self) -> None:
        assert provider_env_names("glm") == ("ZHIPU_API_KEY", "ZHIPU_BASE_URL")

    def test_zhipu_captures_reasoning_without_replay(self) -> None:
        """GLM thinking models put chain-of-thought in ``reasoning_content`` (#458).

        Capture must be on so reasoning survives the ChatOpenAI boundary, but
        replay stays off (DeepSeek posture) until verified live against bigmodel.
        """
        for alias in ("zhipu", "glm"):
            caps = get_provider_capabilities(alias)
            assert caps.capture_reasoning is True
            assert caps.send_reasoning_content is False
            assert caps.normalize_assistant_content is False

    def test_anthropic_uses_native_env_namespace(self) -> None:
        caps = get_provider_capabilities("anthropic")

        assert caps.name == "anthropic"
        assert provider_env_names("anthropic") == (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_BASE_URL",
        )
        assert caps.native_adapter_package == "langchain-anthropic"

    def test_kimi_coding_uses_own_env_namespace(self) -> None:
        caps = get_provider_capabilities("kimi-coding")

        assert caps.name == "kimi-coding"
        assert provider_env_names("kimi-coding") == (
            "KIMI_CODING_API_KEY",
            "KIMI_CODING_BASE_URL",
        )

    @pytest.mark.parametrize("provider", ["opencode-zen", "opencode-go"])
    def test_opencode_providers_use_openai_compatible_env(self, provider: str) -> None:
        assert provider_env_names(provider) == ("OPENAI_API_KEY", "OPENAI_BASE_URL")

    @pytest.mark.parametrize("model", ["", "something-unknown"])
    def test_unknown_or_empty_model_without_provider_falls_back_to_openai(
        self,
        model: str,
    ) -> None:
        caps = get_provider_capabilities(provider=None, model=model)

        assert caps.name == "openai"

    @pytest.mark.parametrize(
        "provider,model,expected",
        [
            # Gateway providers — explicit choice must never be overridden.
            ("openrouter", "deepseek/deepseek-v4-pro", "openrouter"),
            ("requesty", "deepseek/deepseek-v4-pro", "requesty"),
            ("openrouter", "gemini-3.5-flash", "openrouter"),
            ("openrouter", "glm-4.6", "openrouter"),
        ],
    )
    def test_gateway_provider_not_inferred_from_model(
        self, provider: str, model: str, expected: str
    ) -> None:
        """Gateway providers (OpenRouter/Requesty) must never be overridden. (#549)

        Their model names contain direct-provider prefixes like ``deepseek/``
        that would trigger inference, but the explicit gateway choice must win.
        """
        caps = get_provider_capabilities(provider=provider, model=model)
        assert caps.name == expected

    def test_default_openai_provider_with_glm_model_infers_zhipu(self) -> None:
        """Default provider='openai' + model='glm-4.6' → zhipu (backward compat)."""
        caps = get_provider_capabilities(provider="openai", model="glm-4.6")
        assert caps.name == "zhipu"
        assert caps.api_key_env == "ZHIPU_API_KEY"

    def test_uninferable_model_with_empty_provider_falls_back_to_openai(self) -> None:
        """Unknown model + empty provider → openai fallback (no inference match)."""
        caps = get_provider_capabilities(provider="", model="unknown-model-xyz")
        assert caps.name == "openai"


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

        clean = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(
                (
                    "OPENAI_",
                    "LANGCHAIN_",
                    "DEEPSEEK_",
                    "GROQ_",
                    "OLLAMA_",
                    "DASHSCOPE_",
                    "ZAI_",
                    "SILICONFLOW_",
                )
            )
        }
        clean.update(env)
        with patch.dict(os.environ, clean, clear=True):
            _sync_provider_env()
            return {
                "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
                "OPENAI_API_BASE": os.environ.get("OPENAI_API_BASE", ""),
                "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL", ""),
            }

    def test_openai_default(self) -> None:
        result = self._run_sync(
            {
                "OPENAI_API_KEY": "sk-test",
            }
        )
        assert result["OPENAI_API_KEY"] == "sk-test"

    def test_openai_codex_provider_does_not_map_oauth_token_to_api_key(self) -> None:
        result = self._run_sync(
            {
                "LANGCHAIN_PROVIDER": "openai-codex",
                "OPENAI_CODEX_BASE_URL": "https://chatgpt.com/backend-api/codex/responses",
            }
        )
        assert result["OPENAI_API_KEY"] == ""
        assert (
            result["OPENAI_API_BASE"]
            == "https://chatgpt.com/backend-api/codex/responses"
        )

    def test_deepseek_provider(self) -> None:
        result = self._run_sync(
            {
                "LANGCHAIN_PROVIDER": "deepseek",
                "DEEPSEEK_API_KEY": "ds-key-123",
                "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
            }
        )
        assert result["OPENAI_API_KEY"] == "ds-key-123"
        assert result["OPENAI_API_BASE"] == "https://api.deepseek.com/v1"

    @pytest.mark.parametrize(
        ("provider", "key_env", "base_env", "base_url"),
        [
            (
                "siliconflow-cn",
                "SILICONFLOW_API_KEY",
                "SILICONFLOW_BASE_URL",
                "https://api.siliconflow.cn/v1",
            ),
            (
                "siliconflow-global",
                "SILICONFLOW_GLOBAL_API_KEY",
                "SILICONFLOW_GLOBAL_BASE_URL",
                "https://api.siliconflow.com/v1",
            ),
        ],
    )
    def test_siliconflow_providers(
        self,
        provider: str,
        key_env: str,
        base_env: str,
        base_url: str,
    ) -> None:
        result = self._run_sync({
            "LANGCHAIN_PROVIDER": provider,
            key_env: "sf-key-123",
            base_env: base_url,
        })

        assert result["OPENAI_API_KEY"] == "sf-key-123"
        assert result["OPENAI_API_BASE"] == base_url

    def test_groq_provider(self) -> None:
        result = self._run_sync(
            {
                "LANGCHAIN_PROVIDER": "groq",
                "GROQ_API_KEY": "gsk-test",
                "GROQ_BASE_URL": "https://api.groq.com/openai/v1",
            }
        )
        assert result["OPENAI_API_KEY"] == "gsk-test"
        assert "groq" in result["OPENAI_API_BASE"]

    def test_ollama_no_key_required(self) -> None:
        result = self._run_sync(
            {
                "LANGCHAIN_PROVIDER": "ollama",
                "OLLAMA_BASE_URL": "http://localhost:11434/v1",
            }
        )
        # Ollama uses "ollama" as fallback key
        assert result["OPENAI_API_KEY"] in ("ollama", "")
        assert result["OPENAI_API_BASE"] == "http://localhost:11434/v1"

    def test_ollama_base_url_appends_v1(self) -> None:
        result = self._run_sync(
            {
                "LANGCHAIN_PROVIDER": "ollama",
                "OLLAMA_BASE_URL": "http://23.152.56.42:11434/",
            }
        )
        assert result["OPENAI_API_BASE"] == "http://23.152.56.42:11434/v1"
        assert result["OPENAI_BASE_URL"] == "http://23.152.56.42:11434/v1"

    def test_qwen_alias_to_dashscope(self) -> None:
        result = self._run_sync(
            {
                "LANGCHAIN_PROVIDER": "qwen",
                "DASHSCOPE_API_KEY": "qwen-key",
                "DASHSCOPE_BASE_URL": "https://dashscope.aliyuncs.com/v1",
            }
        )
        assert result["OPENAI_API_KEY"] == "qwen-key"

    def test_zai_provider(self) -> None:
        result = self._run_sync(
            {
                "LANGCHAIN_PROVIDER": "zai",
                "ZAI_API_KEY": "zai-key-test",
                "ZAI_BASE_URL": "https://api.z.ai/api/coding/paas/v4",
            }
        )
        assert result["OPENAI_API_KEY"] == "zai-key-test"
        assert result["OPENAI_API_BASE"] == "https://api.z.ai/api/coding/paas/v4"

    def test_unknown_provider_falls_back_to_openai(self) -> None:
        result = self._run_sync(
            {
                "LANGCHAIN_PROVIDER": "unknown_provider_xyz",
                "OPENAI_API_KEY": "sk-fallback",
            }
        )
        assert result["OPENAI_API_KEY"] == "sk-fallback"

    def test_provider_key_fallback_to_openai_key(self) -> None:
        """If provider-specific key is missing, fall back to OPENAI_API_KEY."""
        result = self._run_sync(
            {
                "LANGCHAIN_PROVIDER": "deepseek",
                "OPENAI_API_KEY": "sk-shared",
            }
        )
        assert result["OPENAI_API_KEY"] == "sk-shared"

    def test_provider_base_url_replaces_stale_openai_url(self) -> None:
        result = self._run_sync(
            {
                "LANGCHAIN_PROVIDER": "openrouter",
                "OPENROUTER_API_KEY": "openrouter-key",
                "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
                "OPENAI_BASE_URL": "https://stale-provider.example/v1",
            }
        )

        assert result["OPENAI_API_BASE"] == "https://openrouter.ai/api/v1"
        assert result["OPENAI_BASE_URL"] == "https://openrouter.ai/api/v1"

    def test_minimax_provider(self) -> None:
        result = self._run_sync(
            {
                "LANGCHAIN_PROVIDER": "minimax",
                "MINIMAX_API_KEY": "minimax-key-123",
                "MINIMAX_BASE_URL": "https://api.minimax.io/v1",
            }
        )
        assert result["OPENAI_API_KEY"] == "minimax-key-123"
        assert result["OPENAI_API_BASE"] == "https://api.minimax.io/v1"

    def test_minimax_base_url_in_openai_base_url(self) -> None:
        result = self._run_sync(
            {
                "LANGCHAIN_PROVIDER": "minimax",
                "MINIMAX_API_KEY": "minimax-key",
                "MINIMAX_BASE_URL": "https://api.minimax.io/v1",
            }
        )
        assert "minimax.io" in result["OPENAI_BASE_URL"]


def test_build_anthropic_uses_messages_api_proxy() -> None:
    import src.providers.llm as llm_mod

    llm_mod._dotenv_loaded = True
    captured: dict[str, object] = {}

    class _FakeChatAnthropic:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    env = {
        "LANGCHAIN_PROVIDER": "anthropic",
        "LANGCHAIN_MODEL_NAME": "claude-sonnet-4-6[1M]",
        "LANGCHAIN_TEMPERATURE": "0",
        "ANTHROPIC_API_KEY": "PROXY_MANAGED",
        "ANTHROPIC_BASE_URL": "http://host.docker.internal:15721",
        "ANTHROPIC_MAX_TOKENS": "16384",
        "TIMEOUT_SECONDS": "600",
        "MAX_RETRIES": "2",
    }
    with patch.dict(os.environ, env, clear=True):
        with patch.object(
            llm_mod,
            "import_module",
            return_value=SimpleNamespace(ChatAnthropic=_FakeChatAnthropic),
        ):
            result = build_llm()

    assert isinstance(result, _FakeChatAnthropic)
    assert captured["model"] == "claude-sonnet-4-6[1M]"
    assert captured["api_key"] == "PROXY_MANAGED"
    assert captured["base_url"] == "http://host.docker.internal:15721"
    assert captured["max_tokens"] == 16384
    assert captured["timeout"] == 600
    assert captured["max_retries"] == 2


# ---------------------------------------------------------------------------
# MiniMax temperature clamping
# ---------------------------------------------------------------------------


class TestMinimaxTemperature:
    """MiniMax requires temperature > 0; build_llm should clamp the default."""

    def test_minimax_temperature_clamped_from_zero(self) -> None:
        """When LANGCHAIN_TEMPERATURE=0.0 and provider=minimax, temperature must be clamped to 0.01."""
        import src.providers.llm as llm_mod

        llm_mod._dotenv_loaded = True

        captured: dict[str, float] = {}

        class _FakeChatOpenAI:
            def __init__(self, **kwargs: object) -> None:
                captured["temperature"] = float(kwargs.get("temperature", -1))

        env = {
            "LANGCHAIN_PROVIDER": "minimax",
            "MINIMAX_API_KEY": "minimax-key",
            "MINIMAX_BASE_URL": "https://api.minimax.io/v1",
            "LANGCHAIN_MODEL_NAME": "MiniMax-M3",
            "LANGCHAIN_TEMPERATURE": "0.0",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(llm_mod, "ChatOpenAIWithReasoning", _FakeChatOpenAI):
                build_llm()
        assert (
            captured["temperature"] == 0.01
        ), "MiniMax temperature must be clamped to 0.01 when 0.0 is configured"

    def test_minimax_positive_temperature_preserved(self) -> None:
        """When an explicit positive temperature is set, it should be preserved."""
        import src.providers.llm as llm_mod

        llm_mod._dotenv_loaded = True

        captured: dict[str, float] = {}

        class _FakeChatOpenAI:
            def __init__(self, **kwargs: object) -> None:
                captured["temperature"] = float(kwargs.get("temperature", -1))

        env = {
            "LANGCHAIN_PROVIDER": "minimax",
            "MINIMAX_API_KEY": "minimax-key",
            "MINIMAX_BASE_URL": "https://api.minimax.io/v1",
            "LANGCHAIN_MODEL_NAME": "MiniMax-M3",
            "LANGCHAIN_TEMPERATURE": "0.7",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(llm_mod, "ChatOpenAIWithReasoning", _FakeChatOpenAI):
                build_llm()
        assert captured["temperature"] == 0.7


# ---------------------------------------------------------------------------
# Kimi K-series temperature forcing
# ---------------------------------------------------------------------------


class TestKimiTemperature:
    """Kimi reasoning models reject any temperature other than 1."""

    def _capture_temperature(self, model: str, configured_temp: str) -> float:
        import src.providers.llm as llm_mod
        llm_mod._dotenv_loaded = True

        captured: dict[str, float] = {}

        class _FakeChatOpenAI:
            def __init__(self, **kwargs: object) -> None:
                captured["temperature"] = float(kwargs.get("temperature", -1))

        env = {
            "LANGCHAIN_PROVIDER": "moonshot",
            "MOONSHOT_API_KEY": "moonshot-key",
            "MOONSHOT_BASE_URL": "https://api.kimi.com/coding/v1",
            "LANGCHAIN_MODEL_NAME": model,
            "LANGCHAIN_TEMPERATURE": configured_temp,
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(llm_mod, "ChatOpenAIWithReasoning", _FakeChatOpenAI):
                build_llm()
        return captured["temperature"]

    def test_kimi_k3_temperature_forced_to_one(self) -> None:
        """kimi-k3 must be forced to 1.0 (API rejects other values)."""
        assert self._capture_temperature("kimi-k3", "0.0") == 1.0

    def test_kimi_k2_temperature_forced_to_one(self) -> None:
        """Regression: kimi-k2.x keeps the existing forcing behavior."""
        assert self._capture_temperature("kimi-k2.6", "0.0") == 1.0

    def test_kimi_for_coding_temperature_forced_to_one(self) -> None:
        """Regression: kimi-for-coding alias keeps the existing behavior."""
        assert self._capture_temperature("kimi-for-coding", "0.5") == 1.0

    def test_non_k_series_temperature_preserved(self) -> None:
        """Non-reasoning Moonshot models keep the configured temperature."""
        assert self._capture_temperature("moonshot-v1-8k", "0.0") == 0.0


class TestReasoningEffortPassthrough:
    """LANGCHAIN_REASONING_EFFORT is forwarded as extra_body.reasoning.effort
    to the underlying OpenAI-compatible client. Used for OpenRouter-style
    relays that require opt-in to enable thinking."""

    def _capture(self, env: dict[str, str]) -> dict:
        import src.providers.llm as llm_mod

        llm_mod._dotenv_loaded = True

        captured: dict = {}

        class _FakeChatOpenAI:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

        with patch.dict(os.environ, env, clear=True):
            with patch.object(llm_mod, "ChatOpenAIWithReasoning", _FakeChatOpenAI):
                build_llm()
        return captured

    def test_effort_unset_leaves_extra_body_none(self) -> None:
        captured = self._capture(
            {
                "LANGCHAIN_PROVIDER": "openai",
                "OPENAI_API_KEY": "sk-test",
                "LANGCHAIN_MODEL_NAME": "gpt-4",
            }
        )
        assert captured["extra_body"] is None

    def test_effort_medium_forwarded_as_extra_body(self) -> None:
        captured = self._capture(
            {
                "LANGCHAIN_PROVIDER": "openrouter",
                "OPENROUTER_API_KEY": "or-test",
                "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
                "LANGCHAIN_MODEL_NAME": "moonshotai/kimi-k2-thinking",
                "LANGCHAIN_REASONING_EFFORT": "medium",
            }
        )
        assert captured["extra_body"] == {"reasoning": {"effort": "medium"}}

    def test_effort_case_insensitive(self) -> None:
        captured = self._capture(
            {
                "LANGCHAIN_PROVIDER": "openrouter",
                "OPENROUTER_API_KEY": "or-test",
                "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
                "LANGCHAIN_MODEL_NAME": "moonshotai/kimi-k2-thinking",
                "LANGCHAIN_REASONING_EFFORT": "HIGH",
            }
        )
        assert captured["extra_body"]["reasoning"]["effort"] == "high"

    def test_openai_responses_api_opt_in(self) -> None:
        captured = self._capture(
            {
                "LANGCHAIN_PROVIDER": "openai",
                "LANGCHAIN_MODEL_NAME": "gpt-5.6",
                "OPENAI_API_KEY": "test-key",
                "OPENAI_BASE_URL": "http://219.223.200.237:8080/v1",
                "VIBE_OPENAI_USE_RESPONSES_API": "1",
            }
        )

        assert captured["model"] == "gpt-5.6"
        assert captured["use_responses_api"] is True

    def test_openai_responses_payload_bypasses_chat_message_rewrite(self) -> None:
        import src.providers.llm as llm_mod

        llm_mod._dotenv_loaded = True
        env = {
            "LANGCHAIN_PROVIDER": "openai",
            "LANGCHAIN_MODEL_NAME": "gpt-5.6",
            "OPENAI_API_KEY": "test-key",
            "OPENAI_BASE_URL": "http://gateway.example/v1",
            "VIBE_OPENAI_USE_RESPONSES_API": "1",
        }
        with patch.dict(os.environ, env, clear=True):
            model = build_llm()
            payload = model._get_request_payload("probe")

        assert "input" in payload
        assert "messages" not in payload


class TestKimiCodingProvider:
    """Kimi for Coding is a distinct provider with Moonshot-compatible behavior."""

    def test_reuses_moonshot_wire_behaviour(self) -> None:
        kimi = get_provider_capabilities("kimi-coding")
        moonshot = get_provider_capabilities("moonshot")

        assert kimi.capture_reasoning is True
        assert kimi.send_reasoning_content is True
        assert kimi.normalize_assistant_content is True
        assert kimi.default_headers.get("User-Agent") == moonshot.default_headers.get(
            "User-Agent"
        )

    def test_env_mapping_to_openai_vars(self) -> None:
        import src.providers.llm as llm_mod

        llm_mod._dotenv_loaded = True

        clean = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("OPENAI_", "LANGCHAIN_", "KIMI_CODING_", "MOONSHOT_"))
        }
        clean.update(
            {
                "LANGCHAIN_PROVIDER": "kimi-coding",
                "KIMI_CODING_API_KEY": "sk-kimi-test",
                "KIMI_CODING_BASE_URL": "https://api.kimi.com/coding/v1",
            }
        )
        with patch.dict(os.environ, clean, clear=True):
            _sync_provider_env()

            assert os.environ.get("OPENAI_API_KEY") == "sk-kimi-test"
            assert os.environ.get("OPENAI_API_BASE") == "https://api.kimi.com/coding/v1"

    def _build_and_capture(self, temperature: str) -> dict:
        import src.providers.llm as llm_mod

        llm_mod._dotenv_loaded = True

        captured: dict = {}

        class _FakeChatOpenAI:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

        env = {
            "LANGCHAIN_PROVIDER": "kimi-coding",
            "KIMI_CODING_API_KEY": "sk-kimi-test",
            "KIMI_CODING_BASE_URL": "https://api.kimi.com/coding/v1",
            "LANGCHAIN_MODEL_NAME": "kimi-for-coding",
            "LANGCHAIN_TEMPERATURE": temperature,
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(llm_mod, "ChatOpenAIWithReasoning", _FakeChatOpenAI):
                build_llm()
        return captured

    def test_kimi_for_coding_temperature_forced_to_one(self) -> None:
        captured = self._build_and_capture("0.0")
        assert float(captured["temperature"]) == 1.0

    def test_sets_kimi_user_agent_header(self) -> None:
        captured = self._build_and_capture("1.0")
        assert captured["default_headers"]["User-Agent"].startswith("Vibe-Trading/")


class TestGetLlmCredentials:
    """Centralized credential resolution (#553)."""

    def test_openrouter_with_deepseek_model_returns_openrouter_key(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "or-test-key"}, clear=True):
            creds = get_llm_credentials("openrouter", "deepseek/deepseek-v4-pro")
            assert creds["api_key"] == "or-test-key"
            assert creds["provider"] == "openrouter"

    def test_empty_provider_with_deepseek_model_infers_deepseek(self) -> None:
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "ds-test-key"}, clear=True):
            creds = get_llm_credentials("", "deepseek/deepseek-v4-pro")
            assert creds["api_key"] == "ds-test-key"

    def test_explicit_openai_with_glm_model_uses_openai_key(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "oa-test-key"}, clear=True):
            creds = get_llm_credentials("openai", "glm-4.6")
            assert creds["api_key"] == "oa-test-key"

    def test_none_provider_with_glm_model_infers_zhipu(self) -> None:
        with patch.dict(os.environ, {"ZHIPU_API_KEY": "zh-test-key"}, clear=True):
            creds = get_llm_credentials(None, "glm-4.6")
            assert creds["api_key"] == "zh-test-key"

    def test_ollama_provider_uses_ollama_default_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            creds = get_llm_credentials("ollama", "llama3")
            assert creds["api_key"] == "ollama"

    def test_base_url_uses_provider_specific_env(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1"},
            clear=True,
        ):
            creds = get_llm_credentials("openrouter", "deepseek/deepseek-v4-pro")
            assert creds["base_url"] == "https://openrouter.ai/api/v1"

    def test_base_url_falls_back_to_openai_base_url(self) -> None:
        with patch.dict(
            os.environ, {"OPENAI_BASE_URL": "https://fallback.example/v1"}, clear=True
        ):
            creds = get_llm_credentials("deepseek", "deepseek-v4-pro")
            assert creds["base_url"] == "https://fallback.example/v1"

    def test_base_url_falls_back_to_openai_api_base(self) -> None:
        with patch.dict(
            os.environ, {"OPENAI_API_BASE": "https://legacy.example/v1"}, clear=True
        ):
            creds = get_llm_credentials("deepseek", "deepseek-v4-pro")
            assert creds["base_url"] == "https://legacy.example/v1"
