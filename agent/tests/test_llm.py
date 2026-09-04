"""Tests for LLM provider mapping and JSON extraction."""

from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from src.providers.capabilities import (
    get_llm_credentials,
    get_provider_capabilities,
    provider_env_names,
)
from src.providers.llm import ChatOpenAIWithReasoning, _sync_provider_env, build_llm


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

    def test_modelscope_provider(self) -> None:
        result = self._run_sync({
            "LANGCHAIN_PROVIDER": "modelscope",
            "MODELSCOPE_API_KEY": "ms-key-123",
            "MODELSCOPE_BASE_URL": "https://api-inference.modelscope.cn/v1",
        })
        assert result["OPENAI_API_KEY"] == "ms-key-123"
        assert result["OPENAI_API_BASE"] == "https://api-inference.modelscope.cn/v1"

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
# Anthropic temperature self-heal (next-gen models deprecate `temperature`)
# ---------------------------------------------------------------------------


def _make_fake_anthropic_base():
    """A minimal ChatAnthropic stand-in mimicking payload + generate wiring."""

    class _FakeAnthropicBase:
        def __init__(self, **kwargs: object) -> None:
            self.model = kwargs.get("model")
            self.temperature = kwargs.get("temperature")
            self.calls: list[dict] = []

        def _get_request_payload(self, *args: object, **kwargs: object) -> dict:
            # Mirrors ChatAnthropic: temperature only present when not None.
            payload: dict = {"model": self.model, "messages": []}
            if self.temperature is not None:
                payload["temperature"] = self.temperature
            return payload

        def _generate(self, *args: object, **kwargs: object):
            payload = self._get_request_payload(*args, **kwargs)
            self.calls.append(dict(payload))
            if self.model == "deprecates-temp" and "temperature" in payload:
                raise RuntimeError("`temperature` is deprecated for this model.")
            return SimpleNamespace(payload=payload)

    return _FakeAnthropicBase


def test_anthropic_temperature_self_heal_drops_and_retries() -> None:
    import src.providers.llm as llm_mod

    llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED.discard("deprecates-temp")
    base = _make_fake_anthropic_base()
    safe_cls = llm_mod._make_temperature_safe_anthropic(base)
    inst = safe_cls(model="deprecates-temp", temperature=0.0)

    result = inst._generate([])

    # First attempt carried temperature (and failed); retry dropped it.
    assert len(inst.calls) == 2
    assert "temperature" in inst.calls[0]
    assert "temperature" not in inst.calls[1]
    assert "temperature" not in result.payload
    # Model is remembered so later calls omit temperature up front.
    assert "deprecates-temp" in llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED


def test_anthropic_temperature_preserved_for_supported_model() -> None:
    import src.providers.llm as llm_mod

    llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED.discard("supports-temp")
    base = _make_fake_anthropic_base()
    safe_cls = llm_mod._make_temperature_safe_anthropic(base)
    inst = safe_cls(model="supports-temp", temperature=0.0)

    result = inst._generate([])

    # Deterministic temperature preserved; no retry, nothing remembered.
    assert len(inst.calls) == 1
    assert result.payload.get("temperature") == 0.0
    assert "supports-temp" not in llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED


def test_is_anthropic_temperature_unsupported_error_matching() -> None:
    from src.providers.llm import _is_anthropic_temperature_unsupported_error

    assert _is_anthropic_temperature_unsupported_error(
        RuntimeError("`temperature` is deprecated for this model.")
    )
    assert _is_anthropic_temperature_unsupported_error(
        ValueError("temperature is not supported")
    )
    # Unrelated errors must not trigger the temperature retry path.
    assert not _is_anthropic_temperature_unsupported_error(
        RuntimeError("max_tokens is required")
    )
    assert not _is_anthropic_temperature_unsupported_error(
        RuntimeError("rate limit exceeded")
    )


# ---------------------------------------------------------------------------
# OpenAI-compatible branch temperature self-heal (issue #1223)
# ---------------------------------------------------------------------------


_ANTHROPIC_OPENAI_COMPAT_TEMPERATURE_ERROR = {
    "error": {
        "code": "invalid_request_error",
        "message": "`temperature` is deprecated for this model.",
        "type": "invalid_request_error",
        "param": None,
    }
}


def _openai_compat_completion_body(model: str) -> dict:
    return {
        "id": "chatcmpl-temperature-test",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _openai_compat_sse(text: str, model: str) -> bytes:
    chunk = {
        "id": "chatcmpl-temperature-test",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": "stop"}],
    }
    return (f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n").encode("utf-8")


@pytest.mark.skipif(
    ChatOpenAIWithReasoning is None,
    reason="langchain-openai is not installed",
)
def test_openai_compat_temperature_self_heal_drops_and_retries() -> None:
    """A 400 on `temperature` gets one retry without it, remembered for later calls."""
    import src.providers.llm as llm_mod

    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        calls.append(body)
        if "temperature" in body:
            return httpx.Response(400, json=_ANTHROPIC_OPENAI_COMPAT_TEMPERATURE_ERROR)
        return httpx.Response(200, json=_openai_compat_completion_body(model))

    model = "claude-opus-4-8"
    llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED.discard(model)
    try:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            llm = ChatOpenAIWithReasoning(
                model=model,
                api_key="sk-test",
                base_url="https://api.anthropic.invalid/v1/",
                temperature=0.0,
                http_client=client,
                vibe_provider="openai",
                vibe_api_key="sk-test",
            )
            result = llm.invoke("hello")
            assert result.content == "ok"
            # First attempt carried temperature and failed; the retry dropped it.
            assert len(calls) == 2
            assert "temperature" in calls[0]
            assert calls[0]["temperature"] == 0.0
            assert "temperature" not in calls[1]
            assert model in llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED

            # Remembered: the second invoke skips the doomed attempt entirely.
            llm.invoke("hello again")
            assert len(calls) == 3
            assert "temperature" not in calls[2]
    finally:
        llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED.discard(model)


@pytest.mark.skipif(
    ChatOpenAIWithReasoning is None,
    reason="langchain-openai is not installed",
)
def test_openai_compat_temperature_preserved_for_supported_model() -> None:
    """Models that accept `temperature` keep it; nothing is remembered."""
    import src.providers.llm as llm_mod

    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        calls.append(body)
        return httpx.Response(200, json=_openai_compat_completion_body(model))

    model = "claude-sonnet-4-5"
    llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED.discard(model)
    try:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            llm = ChatOpenAIWithReasoning(
                model=model,
                api_key="sk-test",
                base_url="https://api.anthropic.invalid/v1/",
                temperature=0.0,
                http_client=client,
                vibe_provider="openai",
                vibe_api_key="sk-test",
            )
            result = llm.invoke("hello")

        assert result.content == "ok"
        assert len(calls) == 1
        assert calls[0]["temperature"] == 0.0
        assert model not in llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED
    finally:
        llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED.discard(model)


@pytest.mark.skipif(
    ChatOpenAIWithReasoning is None,
    reason="langchain-openai is not installed",
)
def test_openai_compat_stream_temperature_self_heals_and_is_remembered() -> None:
    """A streaming 400 on `temperature` retries without it; later streams skip it."""
    import src.providers.llm as llm_mod

    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        calls.append(body)
        if "temperature" in body:
            return httpx.Response(400, json=_ANTHROPIC_OPENAI_COMPAT_TEMPERATURE_ERROR)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_openai_compat_sse("ok", model),
        )

    model = "claude-opus-4-8"
    llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED.discard(model)
    try:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            llm = ChatOpenAIWithReasoning(
                model=model,
                api_key="sk-test",
                base_url="https://api.anthropic.invalid/v1/",
                temperature=0.0,
                http_client=client,
                vibe_provider="openai",
                vibe_api_key="sk-test",
            )
            first = "".join(chunk.content for chunk in llm.stream("hello"))

        assert first == "ok"
        # The temperature-unsupported error surfaces before the first chunk, so
        # the retry cannot duplicate output.
        assert len(calls) == 2
        assert "temperature" in calls[0]
        assert "temperature" not in calls[1]
        assert model in llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED
    finally:
        llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED.discard(model)


@pytest.mark.skipif(
    ChatOpenAIWithReasoning is None,
    reason="langchain-openai is not installed",
)
def test_openai_compat_agenerate_temperature_self_heals() -> None:
    """The async generate path mirrors the sync temperature self-heal."""
    import src.providers.llm as llm_mod

    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        calls.append(body)
        if "temperature" in body:
            return httpx.Response(400, json=_ANTHROPIC_OPENAI_COMPAT_TEMPERATURE_ERROR)
        return httpx.Response(200, json=_openai_compat_completion_body(model))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            llm = ChatOpenAIWithReasoning(
                model=model,
                api_key="sk-test",
                base_url="https://api.anthropic.invalid/v1/",
                temperature=0.0,
                http_async_client=client,
                vibe_provider="openai",
                vibe_api_key="sk-test",
            )
            return await llm.ainvoke("hello")

    model = "claude-opus-4-8"
    llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED.discard(model)
    try:
        result = asyncio.run(run())

        assert result.content == "ok"
        assert len(calls) == 2
        assert "temperature" in calls[0]
        assert "temperature" not in calls[1]
        assert model in llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED
    finally:
        llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED.discard(model)


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


class TestDisableHttpProxy:
    """The proxy opt-out must cover both OpenAI SDK execution paths."""

    def test_build_llm_passes_sync_and_async_direct_clients(self) -> None:
        import src.providers.llm as llm_mod

        llm_mod._dotenv_loaded = True
        captured: dict[str, object] = {}
        sync_client = object()
        async_client = object()

        class _FakeChatOpenAI:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

        env = {
            "LANGCHAIN_PROVIDER": "openai",
            "OPENAI_API_KEY": "sk-test",
            "LANGCHAIN_MODEL_NAME": "gpt-4o-mini",
            "VIBE_TRADING_DISABLE_HTTP_PROXY": "1",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(
                llm_mod,
                "_build_proxy_free_http_clients",
                return_value=(sync_client, async_client),
            ) as build_clients:
                with patch.object(llm_mod, "ChatOpenAIWithReasoning", _FakeChatOpenAI):
                    build_llm()

        build_clients.assert_called_once_with()
        assert captured["http_client"] is sync_client
        assert captured["http_async_client"] is async_client
        assert captured["vibe_owned_http_clients"] == (sync_client, async_client)
        assert "http_socket_options" not in captured

    def test_build_llm_leaves_default_transport_when_disabled(self) -> None:
        import src.providers.llm as llm_mod

        llm_mod._dotenv_loaded = True
        captured: dict[str, object] = {}

        class _FakeChatOpenAI:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

        env = {
            "LANGCHAIN_PROVIDER": "openai",
            "OPENAI_API_KEY": "sk-test",
            "LANGCHAIN_MODEL_NAME": "gpt-4o-mini",
            "VIBE_TRADING_DISABLE_HTTP_PROXY": "0",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(llm_mod, "ChatOpenAIWithReasoning", _FakeChatOpenAI):
                build_llm()

        assert "http_client" not in captured
        assert "http_async_client" not in captured
        assert "vibe_owned_http_clients" not in captured

    def test_direct_clients_do_not_install_environment_proxy_mounts(self) -> None:
        import asyncio
        import src.providers.llm as llm_mod

        env = {
            "HTTP_PROXY": "http://proxy.invalid:8080",
            "HTTPS_PROXY": "http://proxy.invalid:8080",
            "ALL_PROXY": "socks5://proxy.invalid:1080",
        }
        with patch.dict(os.environ, env, clear=False):
            sync_client, async_client = llm_mod._build_proxy_free_http_clients()
        try:
            assert sync_client._mounts == {}
            assert async_client._mounts == {}
        finally:
            sync_client.close()
            asyncio.run(async_client.aclose())


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
    relays that require opt-in to enable thinking when Chat Completions is
    selected explicitly."""

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
                "LANGCHAIN_USE_RESPONSES_API": "false",
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
                "LANGCHAIN_USE_RESPONSES_API": "false",
            }
        )
        assert captured["extra_body"]["reasoning"]["effort"] == "high"


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

    @pytest.mark.parametrize(
        "configured_url",
        [
            "http://localhost:11434",
            "http://localhost:11434/",
            "http://localhost:11434/v1",
            "http://localhost:11434/v1/",
        ],
    )
    def test_ollama_base_url_is_normalized_at_credentials_boundary(
        self,
        configured_url: str,
    ) -> None:
        with patch.dict(
            os.environ,
            {"OLLAMA_BASE_URL": configured_url},
            clear=True,
        ):
            creds = get_llm_credentials("ollama", "llama3")

        assert creds["base_url"] == "http://localhost:11434/v1"

    def test_build_llm_receives_normalized_ollama_base_url(self) -> None:
        """The runtime constructor must not reintroduce Ollama's raw root (#1069)."""
        import src.providers.llm as llm_mod

        llm_mod._dotenv_loaded = True
        captured: dict[str, object] = {}

        class _FakeChatOpenAI:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

        env = {
            "LANGCHAIN_PROVIDER": "ollama",
            "LANGCHAIN_MODEL_NAME": "qwen2.5:3b",
            "OLLAMA_BASE_URL": "http://localhost:11434",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(llm_mod, "ChatOpenAIWithReasoning", _FakeChatOpenAI):
                build_llm()

        assert captured["base_url"] == "http://localhost:11434/v1"

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


# ---------------------------------------------------------------------------
# Anthropic temperature self-heal: SDK >= 1 relocates sampling params
# ---------------------------------------------------------------------------


def _make_relocating_anthropic_base():
    """ChatAnthropic stand-in for langchain-anthropic >= 1.4 on anthropic >= 1.

    ``anthropic>=1`` dropped ``temperature`` from ``Messages.create``, so
    langchain-anthropic moves it into ``extra_body`` (which the SDK merges into
    the request JSON as-is). The API rejects it from either location, so the
    self-heal must strip both — popping the top-level key alone retried with
    ``extra_body={"temperature": 0.0}`` and failed a second time.
    """

    class _RelocatingAnthropicBase:
        def __init__(self, **kwargs: object) -> None:
            self.model = kwargs.get("model")
            self.temperature = kwargs.get("temperature")
            self.extra_body = kwargs.get("extra_body")
            self.calls: list[dict] = []

        def _get_request_payload(self, *args: object, **kwargs: object) -> dict:
            payload: dict = {"model": self.model, "messages": []}
            relocated = (
                {"temperature": self.temperature}
                if self.temperature is not None
                else {}
            )
            merged = {**relocated, **(self.extra_body or {})}
            if merged:
                payload["extra_body"] = merged
            return payload

        @staticmethod
        def _has_temperature(payload: dict) -> bool:
            return "temperature" in payload or "temperature" in (
                payload.get("extra_body") or {}
            )

        def _generate(self, *args: object, **kwargs: object):
            payload = self._get_request_payload(*args, **kwargs)
            self.calls.append(
                {**payload, "extra_body": dict(payload.get("extra_body") or {})}
            )
            if self.model == "deprecates-temp" and self._has_temperature(payload):
                raise RuntimeError("`temperature` is deprecated for this model.")
            return SimpleNamespace(payload=payload)

    return _RelocatingAnthropicBase


def test_anthropic_temperature_self_heal_strips_relocated_extra_body() -> None:
    import src.providers.llm as llm_mod

    llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED.discard("deprecates-temp")
    safe_cls = llm_mod._make_temperature_safe_anthropic(
        _make_relocating_anthropic_base()
    )
    inst = safe_cls(model="deprecates-temp", temperature=0.0)

    result = inst._generate([])

    assert len(inst.calls) == 2
    assert inst.calls[0]["extra_body"] == {"temperature": 0.0}
    # The retry must not carry temperature anywhere, and an emptied extra_body
    # must not be sent as `{}`.
    assert "temperature" not in inst.calls[1]
    assert (
        "extra_body" not in inst.calls[1]
        or "temperature" not in inst.calls[1]["extra_body"]
    )
    assert "extra_body" not in result.payload
    assert "deprecates-temp" in llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED


def test_anthropic_temperature_self_heal_keeps_other_extra_body_keys() -> None:
    import src.providers.llm as llm_mod

    llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED.discard("deprecates-temp")
    safe_cls = llm_mod._make_temperature_safe_anthropic(
        _make_relocating_anthropic_base()
    )
    inst = safe_cls(model="deprecates-temp", temperature=0.0, extra_body={"top_k": 40})

    result = inst._generate([])

    assert len(inst.calls) == 2
    assert result.payload["extra_body"] == {"top_k": 40}


def test_anthropic_relocated_temperature_preserved_for_supported_model() -> None:
    import src.providers.llm as llm_mod

    llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED.discard("supports-temp")
    safe_cls = llm_mod._make_temperature_safe_anthropic(
        _make_relocating_anthropic_base()
    )
    inst = safe_cls(model="supports-temp", temperature=0.0)

    result = inst._generate([])

    assert len(inst.calls) == 1
    assert result.payload["extra_body"] == {"temperature": 0.0}
    assert "supports-temp" not in llm_mod._ANTHROPIC_TEMPERATURE_UNSUPPORTED
