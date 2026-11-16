"""Regression coverage for current provider default model IDs."""

from __future__ import annotations

import json

import pytest
from pathlib import Path

import cli
from cli.onboard import PROVIDERS as ONBOARD_PROVIDERS
from src.providers.settings import get_llm_credentials
from src.providers.registry import get_provider_capabilities
from src.providers.registry import provider_catalog


EXPECTED_PROVIDER_DEFAULTS = {
    "openrouter": "deepseek/deepseek-v4-pro",
    "opencode": "deepseek-v4.1-flash",
    "kimi-coding": "kimi-for-coding",
    "ollama": "qwen2.5:32b",
    "copilot": "claude-sonnet-5",
    "claude-cli": "claude-opus-5-5",
    "openai": "gpt-5.5",
    "anthropic": "claude-sonnet-4-6",
    "openai-codex": "openai-codex/gpt-6-sol",
    "deepseek": "deepseek-v4-pro",
    "siliconflow-cn": "deepseek-ai/DeepSeek-V3.1-Terminus",
    "siliconflow-global": "deepseek-ai/DeepSeek-V3.1-Terminus",
    "nvidia": "nvidia/nemotron-3-ultra-550b-a55b",
    "gemini": "gemini-3.5-flash",
    "groq": "meta-llama/llama-4-maverick-17b-128e-instruct",
    "novita": "moonshotai/kimi-k3",
    "dashscope": "qwen-plus-latest",
    "qwen": "qwen-plus-latest",
    "zhipu": "glm-5.1",
    "glm": "glm-5.1",
    "moonshot": "kimi-k2.6",
    "minimax": "MiniMax-M3.1-Flash",
    "mimo": "MiMo-72B-A27B",
    "spark": "4.0Ultra",
    "zai": "glm-5.1",
    "modelscope": "Qwen/Qwen3.5-27B",
}


def test_catalog_defaults_and_connections_reach_every_surface():
    from src.api.settings_routes import LLM_PROVIDERS

    rows = {row["name"]: row for row in provider_catalog()}
    assert {name: row["default_model"] for name, row in rows.items()} == EXPECTED_PROVIDER_DEFAULTS
    assert {p.name for p in LLM_PROVIDERS} == set(rows)
    for name, row in rows.items():
        caps = get_provider_capabilities(name)
        assert (caps.api_key_env, caps.base_url_env) == (row.get("api_key_env"), row["base_url_env"])
        endpoint = row["default_base_url"]
        if name == "ollama":
            endpoint += "/v1"
        assert get_llm_credentials(name, row["default_model"], environment={})["base_url"] == endpoint
    legacy = {p["provider"]: p for p in cli._PROVIDER_CHOICES}
    onboard = {p.key: p for p in ONBOARD_PROVIDERS}
    assert set(onboard) == {
        "openrouter", "openai", "anthropic", "openai-codex", "deepseek", "opencode",
        "siliconflow-cn", "siliconflow-global", "nvidia", "modelscope", "ollama",
    }
    assert {"openai", "nvidia", "siliconflow-cn", "siliconflow-global"} <= legacy.keys()
    for name, p in legacy.items():
        row = rows[name]
        assert (p["model"], p["base_url"], p["key_env"], p["base_env"]) == (
            row["default_model"], row["default_base_url"], row.get("api_key_env"), row["base_url_env"])
    for name, p in onboard.items():
        row = rows[name]
        assert (p.default_model, p.base_url, p.key_env, p.base_env) == (
            row["default_model"], row["default_base_url"], row.get("api_key_env"), row["base_url_env"])
        assert p.suggested_models[0] == EXPECTED_PROVIDER_DEFAULTS[name]


def test_minimax_provider_lists_regional_endpoints() -> None:
    providers_path = Path(__file__).resolve().parents[1] / "src" / "providers" / "llm_providers.json"
    providers = json.loads(providers_path.read_text(encoding="utf-8"))
    minimax = next(item for item in providers if item["name"] == "minimax")

    assert minimax["base_url_options"] == [
        "https://api.minimax.io/v1",
        "https://api.minimaxi.com/v1",
    ]


@pytest.mark.parametrize("name,key,base,url", [
    ("nvidia", "NVIDIA_API_KEY", "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
    ("siliconflow-cn", "SILICONFLOW_API_KEY", "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
    ("siliconflow-global", "SILICONFLOW_GLOBAL_API_KEY", "SILICONFLOW_GLOBAL_BASE_URL", "https://api.siliconflow.com/v1"),
    ("openai-codex", None, "OPENAI_CODEX_BASE_URL", "https://chatgpt.com/backend-api/codex/responses"),
])
def test_pinned_connection_contracts(name, key, base, url):
    row = next(p for p in provider_catalog() if p["name"] == name)
    assert (row["api_key_env"], row["base_url_env"], row["default_base_url"]) == (key, base, url)


@pytest.mark.parametrize("environment,endpoint", [
    ({}, "https://api.z.ai/api/coding/paas/v4"),
    ({"ZAI_BASE_URL": "https://direct.invalid", "OPENAI_BASE_URL": "https://relay.invalid"}, "https://direct.invalid"),
    ({"OPENAI_BASE_URL": "https://relay.invalid"}, "https://relay.invalid"),
])
def test_endpoint_precedence(environment, endpoint):
    assert get_llm_credentials("zai", "glm-5.1", environment=environment)["base_url"] == endpoint


def test_env_example_default_matches_provider_registry():
    agent_root = Path(__file__).resolve().parents[1]
    assignments = dict(line.split("=", 1) for line in
                       (agent_root / ".env.example").read_text().splitlines()
                       if line.startswith(("LANGCHAIN_PROVIDER=", "LANGCHAIN_MODEL_NAME=")))
    providers = json.loads((agent_root / "src/providers/llm_providers.json").read_text())
    provider = next(p for p in providers if p["name"] == assignments["LANGCHAIN_PROVIDER"])
    assert assignments["LANGCHAIN_MODEL_NAME"] == provider["default_model"]


@pytest.mark.parametrize("name,required,obsolete", [
    ("openai", {"gpt-5.5", "gpt-5.5-pro", "gpt-5.5-instant"}, set()),
    ("deepseek", {"deepseek-flash"}, {"deepseek-v4-flash"}),
    ("openrouter", {"deepseek/deepseek-v4.1-flash"}, {"deepseek/deepseek-v4-flash"}),
])
def test_curated_models(name, required, obsolete):
    models = next(p.suggested_models for p in ONBOARD_PROVIDERS if p.key == name)
    assert required <= set(models)
    assert not obsolete.intersection(models)


def test_codex_models_offered_are_ones_the_codex_backend_publishes() -> None:
    """Every Codex model we default to or suggest is in the published list.

    ``openai-codex/gpt-5.4`` was the default and the Codex backend answers it
    with 400 "not supported when using Codex with a ChatGPT account"; its
    ``-mini`` sibling was suggested beside it. ``context_windows.json`` holds
    the models the Codex backend lists (with their source), so a default
    outside that pattern is a model nobody verified.
    """
    import json
    import re
    from pathlib import Path

    catalog = json.loads(
        (Path(__file__).resolve().parents[1] / "src" / "providers" / "context_windows.json").read_text()
    )
    patterns = [e["pattern"] for e in catalog["models"] if e.get("provider") == "openai-codex"]
    onboard = next(provider for provider in ONBOARD_PROVIDERS if provider.key == "openai-codex")
    offered = {EXPECTED_PROVIDER_DEFAULTS["openai-codex"], onboard.default_model, *onboard.suggested_models}
    for model in offered:
        assert any(re.search(pattern, model) for pattern in patterns), model


def test_documented_direct_deepseek_pair_matches_registry():
    import re

    text = (Path(__file__).resolve().parents[1] / ".env.example").read_text()
    headers = list(re.finditer(r"(?m)^# --- DeepSeek ---.*$", text))
    assert len(headers) == 1
    block = re.split(r"(?m)^# --- ", text[headers[0].end():], maxsplit=1)[0]
    providers = re.findall(r"(?m)^#\s*LANGCHAIN_PROVIDER=(\S+)", block)
    models = re.findall(r"(?m)^#\s*LANGCHAIN_MODEL_NAME=(\S+)", block)
    assert providers == ["deepseek"]
    assert models == [EXPECTED_PROVIDER_DEFAULTS["deepseek"]]
