"""OpenCode Go / Zen provider: catalog entry and x-opencode-session header."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from src.providers.capabilities import get_llm_credentials, get_provider_capabilities
from src.providers.llm import ChatOpenAIWithReasoning, _targets_opencode
from src.providers.session_context import (
    bind_llm_session_id,
    current_llm_session_id,
    reset_llm_session_id,
)

_PROVIDERS_JSON = (
    Path(__file__).resolve().parents[1] / "src" / "providers" / "llm_providers.json"
)
_GO_URL = "https://opencode.ai/zen/go/v1"


def _completion_body(model: str) -> dict:
    return {
        "id": "chatcmpl-test",
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


# ---------------------------------------------------------------------------
# Registration surfaces
# ---------------------------------------------------------------------------


def test_catalog_lists_opencode_with_go_default_and_zen_option() -> None:
    catalog = {
        item["name"]: item
        for item in json.loads(_PROVIDERS_JSON.read_text(encoding="utf-8"))
    }
    entry = catalog["opencode"]
    assert entry["api_key_env"] == "OPENCODE_API_KEY"
    assert entry["base_url_env"] == "OPENCODE_BASE_URL"
    assert entry["default_base_url"] == _GO_URL
    assert "https://opencode.ai/zen/v1" in entry["base_url_options"]
    assert entry["api_key_required"] is True


def test_capabilities_resolve_opencode_provider() -> None:
    caps = get_provider_capabilities("opencode", "deepseek-v4.1-flash")
    assert caps.name == "opencode"
    assert caps.api_key_env == "OPENCODE_API_KEY"
    assert caps.base_url_env == "OPENCODE_BASE_URL"
    assert caps.capture_reasoning is True
    assert caps.default_headers["User-Agent"].startswith("Vibe-Trading/")


@pytest.mark.parametrize("name", ["opencode-go", "opencode-zen"])
def test_legacy_opencode_spellings_keep_openai_env(name: str) -> None:
    """Upstream contract: the older names ride the OPENAI_* variables."""
    caps = get_provider_capabilities(name, "deepseek-v4.1-flash")
    assert caps.name == name
    assert (caps.api_key_env, caps.base_url_env) == (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
    )


def test_credentials_fall_back_to_go_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "OPENCODE_BASE_URL",
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-opencode-test")
    creds = get_llm_credentials("opencode", "deepseek-v4.1-flash")
    assert creds["api_key"] == "sk-opencode-test"
    assert creds["base_url"] == _GO_URL


def test_swarm_public_provider_allowlist_includes_opencode() -> None:
    from src.swarm.models import _PUBLIC_PROVIDERS

    assert "opencode" in _PUBLIC_PROVIDERS


def test_cli_onboarding_surfaces_agree() -> None:
    import cli
    from cli.onboard import PROVIDERS

    onboard = next(p for p in PROVIDERS if p.key == "opencode")
    legacy = next(
        item for item in cli._PROVIDER_CHOICES if item["provider"] == "opencode"
    )
    assert onboard.key_env == legacy["key_env"] == "OPENCODE_API_KEY"
    assert onboard.base_env == legacy["base_env"] == "OPENCODE_BASE_URL"
    assert onboard.base_url == legacy["base_url"] == _GO_URL
    assert onboard.default_model == legacy["model"]


# ---------------------------------------------------------------------------
# Endpoint detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("provider", "base_url", "expected"),
    [
        ("opencode", None, True),
        ("opencode-go", "", True),
        ("opencode_zen", "https://example.invalid/v1", True),
        ("deepseek", _GO_URL, True),
        ("openai", "https://opencode.ai/zen/v1", True),
        ("openai", "opencode.ai/zen/go/v1", True),
        ("deepseek", "https://api.deepseek.com/v1", False),
        ("openai", "https://api.openai.com/v1", False),
        ("openai", "https://notopencode.ai/v1", False),
        ("openai", None, False),
    ],
)
def test_targets_opencode(provider: str, base_url: str | None, expected: bool) -> None:
    assert _targets_opencode(provider, base_url) is expected


# ---------------------------------------------------------------------------
# Session context
# ---------------------------------------------------------------------------


def test_session_binding_is_scoped_and_reset() -> None:
    assert current_llm_session_id() == ""
    token = bind_llm_session_id("  sess-1  ")
    try:
        assert current_llm_session_id() == "sess-1"
        inner = bind_llm_session_id(None)
        assert current_llm_session_id() == ""
        reset_llm_session_id(inner)
        assert current_llm_session_id() == "sess-1"
    finally:
        reset_llm_session_id(token)
    assert current_llm_session_id() == ""


# ---------------------------------------------------------------------------
# Wire behaviour
# ---------------------------------------------------------------------------

pytestmark_wire = pytest.mark.skipif(
    ChatOpenAIWithReasoning is None, reason="langchain-openai is not installed"
)


def _adapter(
    client: httpx.Client, *, provider: str, base_url: str
) -> ChatOpenAIWithReasoning:
    return ChatOpenAIWithReasoning(
        model="deepseek-v4.1-flash",
        api_key="sk-test",
        base_url=base_url,
        temperature=0.0,
        http_client=client,
        default_headers={"User-Agent": "Vibe-Trading/test"},
        vibe_provider=provider,
        vibe_api_key="sk-test",
    )


@pytestmark_wire
def test_bound_session_id_is_sent_to_opencode() -> None:
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return httpx.Response(200, json=_completion_body("deepseek-v4.1-flash"))

    token = bind_llm_session_id("vibe-session-42")
    try:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            llm = _adapter(client, provider="opencode", base_url=_GO_URL)
            assert llm.invoke("hello").content == "ok"
            assert llm.invoke("hello again").content == "ok"
    finally:
        reset_llm_session_id(token)

    assert len(seen) == 2
    for headers in seen:
        assert headers["x-opencode-session"] == "vibe-session-42"
        assert headers["user-agent"].startswith("Vibe-Trading/")


@pytestmark_wire
def test_unbound_requests_share_a_stable_fallback_id() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["x-opencode-session"])
        return httpx.Response(200, json=_completion_body("deepseek-v4.1-flash"))

    assert current_llm_session_id() == ""
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = _adapter(client, provider="opencode-go", base_url=_GO_URL)
        first.invoke("a")
        first.invoke("b")
        second = _adapter(client, provider="opencode-go", base_url=_GO_URL)
        second.invoke("c")

    assert seen[0] == seen[1]
    assert seen[2] != seen[0]
    assert all(len(value) >= 16 for value in seen)


@pytestmark_wire
def test_deepseek_label_pointed_at_opencode_still_gets_header() -> None:
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return httpx.Response(200, json=_completion_body("deepseek-v4.1-flash"))

    token = bind_llm_session_id("legacy-config")
    try:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            _adapter(client, provider="deepseek", base_url=_GO_URL).invoke("hi")
    finally:
        reset_llm_session_id(token)

    assert seen[0]["x-opencode-session"] == "legacy-config"


@pytestmark_wire
def test_non_opencode_endpoints_do_not_get_header() -> None:
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return httpx.Response(200, json=_completion_body("deepseek-v4.1-flash"))

    token = bind_llm_session_id("should-not-leak")
    try:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            _adapter(
                client, provider="deepseek", base_url="https://api.deepseek.com/v1"
            ).invoke("hi")
    finally:
        reset_llm_session_id(token)

    assert "x-opencode-session" not in seen[0]


@pytestmark_wire
def test_explicit_extra_header_wins_over_injected_session() -> None:
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return httpx.Response(200, json=_completion_body("deepseek-v4.1-flash"))

    token = bind_llm_session_id("bound")
    try:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            llm = _adapter(client, provider="opencode", base_url=_GO_URL)
            llm.invoke("hi", extra_headers={"X-OpenCode-Session": "caller-wins"})
    finally:
        reset_llm_session_id(token)

    assert seen[0]["x-opencode-session"] == "caller-wins"
