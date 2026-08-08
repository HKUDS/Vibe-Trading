"""Coverage for the official GitHub Copilot SDK provider."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

import api_server  # noqa: F401
from src.api import settings_routes
from src.providers import capabilities as caps_mod
from src.providers import copilot_auth
from src.providers.capabilities import (
    get_llm_credentials,
    get_provider_capabilities,
)


@pytest.fixture(autouse=True)
def _clear_token_cache():
    caps_mod._gh_cli_token.cache_clear()
    yield
    caps_mod._gh_cli_token.cache_clear()


@pytest.fixture
def no_ambient_credentials(monkeypatch):
    for name in (
        copilot_auth.COPILOT_TOKEN_ENV,
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "COPILOT_BASE_URL",
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(copilot_auth, "gh_cli_token", lambda: "")


def _copilot_entry() -> dict:
    providers_path = (
        Path(__file__).resolve().parents[1] / "src" / "providers" / "llm_providers.json"
    )
    entries = {
        item["name"]: item
        for item in json.loads(providers_path.read_text(encoding="utf-8"))
    }
    return entries["copilot"]


def test_copilot_is_registered_as_sdk_provider() -> None:
    entry = _copilot_entry()

    assert entry["label"] == "GitHub Copilot SDK"
    assert entry["default_base_url"] == "https://api.githubcopilot.com"
    assert entry["api_key_required"] is False


def test_copilot_has_no_editor_impersonation_headers() -> None:
    caps = get_provider_capabilities("copilot", "claude-sonnet-5")

    assert caps.name == "copilot"
    assert caps.default_headers == {}


def test_copilot_alias_resolves_to_same_capabilities() -> None:
    assert (
        get_provider_capabilities("github-copilot", "claude-sonnet-5").name
        == get_provider_capabilities("copilot", "claude-sonnet-5").name
        == "copilot"
    )


def test_token_type_validation_rejects_classic_pat() -> None:
    assert copilot_auth.is_supported_token("gho_abc")
    assert copilot_auth.is_supported_token("ghu_abc")
    assert copilot_auth.is_supported_token("github_pat_abc")
    assert not copilot_auth.is_supported_token("ghp_classic")
    assert not copilot_auth.is_supported_token("")


def test_resolution_prefers_copilot_then_gh_environment(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghu_actions")
    monkeypatch.setenv("GH_TOKEN", "gho_gh")
    monkeypatch.setenv(copilot_auth.COPILOT_TOKEN_ENV, "gho_copilot")

    assert copilot_auth.resolve_copilot_token() == (
        "gho_copilot",
        copilot_auth.COPILOT_TOKEN_ENV,
    )

    monkeypatch.delenv(copilot_auth.COPILOT_TOKEN_ENV)
    assert copilot_auth.resolve_copilot_token() == ("gho_gh", "GH_TOKEN")


def test_resolution_falls_back_to_gh_cli(no_ambient_credentials, monkeypatch) -> None:
    monkeypatch.setattr(copilot_auth, "gh_cli_token", lambda: "gho_cli")

    assert copilot_auth.resolve_copilot_token() == ("gho_cli", "gh auth token")


def test_no_credential_is_left_for_sdk_resolution(no_ambient_credentials) -> None:
    assert copilot_auth.resolve_copilot_token() == ("", "")


def test_sdk_client_options_keep_stored_cli_credentials_enabled(
    no_ambient_credentials, monkeypatch
) -> None:
    assert copilot_auth._client_options() == {}

    monkeypatch.setenv(copilot_auth.COPILOT_TOKEN_ENV, "gho_explicit")
    assert copilot_auth._client_options() == {"github_token": "gho_explicit"}


def test_credentials_do_not_require_openai_base_url(
    no_ambient_credentials, monkeypatch
) -> None:
    monkeypatch.setenv(copilot_auth.COPILOT_TOKEN_ENV, "gho_explicit")

    creds = get_llm_credentials("copilot", "claude-sonnet-5")

    assert creds["api_key"] == "gho_explicit"
    assert creds["base_url"] == "https://api.githubcopilot.com"


def test_sdk_adapter_maps_tool_calls(monkeypatch) -> None:
    async def fake_run(**_kwargs):
        return copilot_auth._CopilotResult(
            model="claude-sonnet-5",
            tool_calls=[
                {
                    "id": "call_1",
                    "name": "quote",
                    "args": {"symbol": "AAPL"},
                    "type": "tool_call",
                }
            ],
        )

    monkeypatch.setattr(copilot_auth, "_run_copilot", fake_run)

    message = copilot_auth.CopilotSDKLLM(model="claude-sonnet-5").bind_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "quote",
                    "description": "Get a quote",
                    "parameters": {"type": "object"},
                },
            }
        ]
    ).invoke([{"role": "user", "content": "Price?"}])

    assert message.tool_calls == [
        {
            "name": "quote",
            "args": {"symbol": "AAPL"},
            "id": "call_1",
            "type": "tool_call",
        }
    ]
    assert message.response_metadata["finish_reason"] == "tool_calls"


def test_sdk_adapter_streams_text(monkeypatch) -> None:
    async def fake_run(*, emit, **_kwargs):
        emit("text", "hello ")
        emit("text", "world")
        return copilot_auth._CopilotResult(content="hello world")

    monkeypatch.setattr(copilot_auth, "_run_copilot", fake_run)

    chunks = list(
        copilot_auth.CopilotSDKLLM(model="claude-sonnet-5").stream(
            [{"role": "user", "content": "Hello"}]
        )
    )

    assert "".join(chunk.content for chunk in chunks) == "hello world"
    assert chunks[-1].response_metadata["finish_reason"] == "stop"


def test_sdk_stream_close_cancels_background_session(monkeypatch) -> None:
    cancelled = threading.Event()

    async def fake_run(*, emit, cancel_event, **_kwargs):
        emit("text", "hello")
        while not cancel_event.is_set():
            await copilot_auth.asyncio.sleep(0.01)
        cancelled.set()
        return copilot_auth._CopilotResult(content="hello")

    monkeypatch.setattr(copilot_auth, "_run_copilot", fake_run)
    stream = copilot_auth.CopilotSDKLLM(model="claude-sonnet-5").stream(
        [{"role": "user", "content": "Hello"}]
    )

    assert next(stream).content == "hello"
    stream.close()

    assert cancelled.wait(1)


def test_message_conversion_keeps_system_and_tool_history() -> None:
    system, prompt = copilot_auth._convert_messages(
        [
            {"role": "system", "content": "Be concise."},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1"}]},
            {"role": "tool", "tool_call_id": "call_1", "content": "123"},
        ]
    )

    assert system == "Be concise."
    assert '"tool_call_id": "call_1"' in prompt
    assert '"role": "tool"' in prompt


def test_settings_report_explicit_copilot_credential(monkeypatch) -> None:
    monkeypatch.setattr(
        copilot_auth,
        "get_copilot_auth_status",
        lambda: (True, "authenticated via GH_TOKEN"),
    )

    response = settings_routes._build_llm_settings_response(
        {"LANGCHAIN_PROVIDER": "copilot"}
    )

    assert response.api_key_configured is True
    assert response.api_key_hint == "authenticated via GH_TOKEN"


def test_settings_allow_sdk_managed_credentials(monkeypatch) -> None:
    monkeypatch.setattr(
        copilot_auth,
        "get_copilot_auth_status",
        lambda: (True, "authenticated via Copilot CLI"),
    )

    response = settings_routes._build_llm_settings_response(
        {"LANGCHAIN_PROVIDER": "copilot"}
    )

    assert response.api_key_required is False
    assert response.api_key_configured is True
    assert response.api_key_hint == "authenticated via Copilot CLI"
