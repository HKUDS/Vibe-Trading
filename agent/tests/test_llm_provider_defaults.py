"""Regression coverage for current provider default model IDs."""

from __future__ import annotations

import json
from pathlib import Path

import cli
from cli.onboard import PROVIDERS as ONBOARD_PROVIDERS
from src.providers.capabilities import (
    _provider_default_base_urls,
    get_llm_credentials,
)


EXPECTED_PROVIDER_DEFAULTS = {
    "openrouter": "deepseek/deepseek-v4-pro",
    "requesty": "openai/gpt-4o-mini",
    "openai": "gpt-5.5",
    "anthropic": "claude-sonnet-4-6",
    "openai-codex": "openai-codex/gpt-5.4",
    "deepseek": "deepseek-v4-pro",
    "siliconflow-cn": "deepseek-ai/DeepSeek-V3.1-Terminus",
    "siliconflow-global": "deepseek-ai/DeepSeek-V3.1-Terminus",
    "nvidia": "nvidia/nemotron-3-ultra-550b-a55b",
    "gemini": "gemini-3.5-flash",
    "groq": "meta-llama/llama-4-maverick-17b-128e-instruct",
    "dashscope": "qwen-plus-latest",
    "qwen": "qwen-plus-latest",
    "zhipu": "glm-5.1",
    "glm": "glm-5.1",
    "moonshot": "kimi-k2.6",
    "minimax": "MiniMax-M3",
    "mimo": "MiMo-72B-A27B",
    "spark": "4.0Ultra",
    "zai": "glm-5.1",
    "modelscope": "Qwen/Qwen3.5-27B",
}


def test_llm_provider_registry_uses_current_default_models() -> None:
    providers_path = Path(__file__).resolve().parents[1] / "src" / "providers" / "llm_providers.json"
    providers = json.loads(providers_path.read_text(encoding="utf-8"))
    defaults = {item["name"]: item["default_model"] for item in providers}

    for provider, model in EXPECTED_PROVIDER_DEFAULTS.items():
        assert defaults[provider] == model

    assert defaults["openai"] != "gpt-5.5-instant"


def test_minimax_provider_lists_regional_endpoints() -> None:
    providers_path = Path(__file__).resolve().parents[1] / "src" / "providers" / "llm_providers.json"
    providers = json.loads(providers_path.read_text(encoding="utf-8"))
    minimax = next(item for item in providers if item["name"] == "minimax")

    assert minimax["base_url_options"] == [
        "https://api.minimax.io/v1",
        "https://api.minimaxi.com/v1",
    ]


def test_interactive_onboard_openai_defaults_to_available_model() -> None:
    provider = next(provider for provider in ONBOARD_PROVIDERS if provider.key == "openai")

    assert provider.default_model == "gpt-5.5"
    assert provider.suggested_models[0] == "gpt-5.5"
    assert "gpt-5.5-pro" in provider.suggested_models
    assert "gpt-5.5-instant" in provider.suggested_models
    assert provider.default_model != "gpt-5.5-instant"


def test_interactive_onboard_codex_defaults_to_supported_model() -> None:
    provider = next(provider for provider in ONBOARD_PROVIDERS if provider.key == "openai-codex")

    assert provider.default_model == "openai-codex/gpt-5.4"
    assert provider.key_env is None
    assert provider.base_env == "OPENAI_CODEX_BASE_URL"
    assert provider.suggested_models[0] == "openai-codex/gpt-5.4"


def test_legacy_cli_provider_choices_match_registry_defaults() -> None:
    legacy_defaults = {
        str(item["provider"]): item["model"]
        for item in cli._PROVIDER_CHOICES
        if item["provider"] in EXPECTED_PROVIDER_DEFAULTS
    }

    for provider, model in legacy_defaults.items():
        assert model == EXPECTED_PROVIDER_DEFAULTS[provider]

    assert legacy_defaults["openai"] == "gpt-5.5"


def test_interactive_onboard_suggests_current_primary_models() -> None:
    onboard_defaults = {provider.key: provider.default_model for provider in ONBOARD_PROVIDERS}

    assert onboard_defaults["openrouter"] == "deepseek/deepseek-v4-pro"
    assert onboard_defaults["openai"] == "gpt-5.5"
    assert onboard_defaults["anthropic"] == "claude-sonnet-4-6"
    assert onboard_defaults["openai-codex"] == "openai-codex/gpt-5.4"
    assert onboard_defaults["deepseek"] == "deepseek-v4-pro"
    assert onboard_defaults["siliconflow-cn"] == "deepseek-ai/DeepSeek-V3.1-Terminus"
    assert onboard_defaults["siliconflow-global"] == "deepseek-ai/DeepSeek-V3.1-Terminus"
    assert onboard_defaults["modelscope"] == "Qwen/Qwen3.5-27B"
    assert onboard_defaults["nvidia"] == "nvidia/nemotron-3-ultra-550b-a55b"


def test_nvidia_is_available_in_both_cli_onboarding_surfaces() -> None:
    onboard = next(provider for provider in ONBOARD_PROVIDERS if provider.key == "nvidia")
    legacy = next(item for item in cli._PROVIDER_CHOICES if item["provider"] == "nvidia")

    assert onboard.key_env == legacy["key_env"] == "NVIDIA_API_KEY"
    assert onboard.base_env == legacy["base_env"] == "NVIDIA_BASE_URL"
    assert onboard.base_url == legacy["base_url"] == "https://integrate.api.nvidia.com/v1"


def test_siliconflow_is_available_in_both_cli_onboarding_surfaces() -> None:
    expected = {
        "siliconflow-cn": (
            "SILICONFLOW_API_KEY",
            "SILICONFLOW_BASE_URL",
            "https://api.siliconflow.cn/v1",
        ),
        "siliconflow-global": (
            "SILICONFLOW_GLOBAL_API_KEY",
            "SILICONFLOW_GLOBAL_BASE_URL",
            "https://api.siliconflow.com/v1",
        ),
    }

    for provider, (key_env, base_env, base_url) in expected.items():
        onboard = next(item for item in ONBOARD_PROVIDERS if item.key == provider)
        legacy = next(item for item in cli._PROVIDER_CHOICES if item["provider"] == provider)

        assert onboard.key_env == legacy["key_env"] == key_env
        assert onboard.base_env == legacy["base_env"] == base_env
        assert onboard.base_url == legacy["base_url"] == base_url


# ---------------------------------------------------------------------------
# #758: backend credential resolution falls back to the catalog default_base_url
# when no *_BASE_URL is set, so CLI / manual-.env users reach the right endpoint.
# ---------------------------------------------------------------------------


def test_zai_base_url_falls_back_to_catalog_default(monkeypatch) -> None:
    """With no *_BASE_URL set, zai resolves to its catalog endpoint instead of
    silently defaulting to api.openai.com (which 404s glm-5.1)."""
    for var in ("ZAI_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE"):
        monkeypatch.delenv(var, raising=False)
    creds = get_llm_credentials("zai", "glm-5.1")
    assert creds["base_url"] == "https://api.z.ai/api/coding/paas/v4"


def test_explicit_provider_base_url_overrides_catalog_default(monkeypatch) -> None:
    monkeypatch.setenv("ZAI_BASE_URL", "https://custom.example/v1")
    creds = get_llm_credentials("zai", "glm-5.1")
    assert creds["base_url"] == "https://custom.example/v1"


def test_openai_base_url_env_overrides_catalog_default(monkeypatch) -> None:
    monkeypatch.delenv("ZAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://proxy.example/v1")
    creds = get_llm_credentials("zai", "glm-5.1")
    assert creds["base_url"] == "https://proxy.example/v1"


def test_credential_fallback_map_matches_provider_catalog() -> None:
    """The base-URL fallback map must stay in sync with llm_providers.json."""
    providers_path = (
        Path(__file__).resolve().parents[1] / "src" / "providers" / "llm_providers.json"
    )
    catalog = {
        item["name"]: item["default_base_url"]
        for item in json.loads(providers_path.read_text(encoding="utf-8"))
    }
    assert _provider_default_base_urls() == catalog
