"""Coverage for the GitHub Copilot provider.

Copilot needs three things no other OpenAI-compatible provider needs:

1. Editor-identification headers -- the endpoint rejects requests without
   ``Copilot-Integration-Id`` / ``Editor-Version``.
2. A credential resolved from several local sources rather than a single API
   key env var. The long-lived ``gho_``/``ghu_`` token is used directly as the
   Bearer credential; the ``copilot_internal/v2/token`` JWT exchange is NOT
   used (it 403s for individual accounts), so there is no refresh path.
3. A device code login, so the GitHub CLI is never a hard requirement.

These tests assert those invariants without any network access.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# `settings_routes._host()` resolves the `api_server` module at call time, so
# it must be imported for the settings helpers to work outside the app.
import api_server  # noqa: F401
from src.api import settings_routes
from src.providers import capabilities as caps_mod
from src.providers import copilot_auth
from src.providers.capabilities import (
    get_llm_credentials,
    get_provider_capabilities,
)


REQUIRED_COPILOT_HEADERS = {
    "Editor-Version",
    "Copilot-Integration-Id",
    "Openai-Intent",
    "x-initiator",
}


@pytest.fixture(autouse=True)
def _clear_token_cache():
    """The resolved token is process-cached; reset it around every test."""
    caps_mod._gh_cli_token.cache_clear()
    yield
    caps_mod._gh_cli_token.cache_clear()


@pytest.fixture
def no_ambient_credentials(monkeypatch):
    """Neutralize every credential source so tests never see the real machine."""
    monkeypatch.delenv(copilot_auth.COPILOT_TOKEN_ENV, raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("COPILOT_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.setattr(copilot_auth, "gh_cli_token", lambda: "")
    monkeypatch.setattr(copilot_auth, "copilot_apps_json_token", lambda: "")


# --- Registration and wire format -----------------------------------------


def test_copilot_is_registered_in_provider_catalog() -> None:
    providers_path = (
        Path(__file__).resolve().parents[1] / "src" / "providers" / "llm_providers.json"
    )
    entries = {
        item["name"]: item
        for item in json.loads(providers_path.read_text(encoding="utf-8"))
    }

    assert "copilot" in entries
    entry = entries["copilot"]
    assert entry["default_base_url"] == "https://api.githubcopilot.com"
    # Copilot authenticates through a local token source, not an up-front key.
    assert entry["api_key_required"] is False


def test_copilot_default_model_supports_chat_completions() -> None:
    """The default must work on /chat/completions.

    Several Copilot models (the gpt-5.5 / gpt-5.6-* family) are exposed only
    on the /responses endpoint and return HTTP 400 through the OpenAI-
    compatible chat path this provider uses. Defaulting to one would ship a
    provider that fails on first use.
    """
    providers_path = (
        Path(__file__).resolve().parents[1] / "src" / "providers" / "llm_providers.json"
    )
    entries = {
        item["name"]: item
        for item in json.loads(providers_path.read_text(encoding="utf-8"))
    }
    default_model = entries["copilot"]["default_model"]

    responses_only_families = ("gpt-5.5", "gpt-5.6", "gpt-5.3-codex", "gpt-5.4-mini")
    assert not default_model.startswith(responses_only_families), (
        f"{default_model} is /responses-only and cannot serve /chat/completions"
    )


def test_copilot_sends_editor_identification_headers() -> None:
    caps = get_provider_capabilities("copilot", "claude-sonnet-4.6")

    assert caps.name == "copilot"
    assert REQUIRED_COPILOT_HEADERS <= set(caps.default_headers)
    assert caps.default_headers["Copilot-Integration-Id"] == "vscode-chat"


def test_copilot_alias_resolves_to_same_capabilities() -> None:
    assert (
        get_provider_capabilities("github-copilot", "claude-sonnet-4.6").name
        == get_provider_capabilities("copilot", "claude-sonnet-4.6").name
        == "copilot"
    )


# --- Credential resolution -------------------------------------------------


def test_token_type_validation_rejects_classic_pat() -> None:
    """Classic PATs are rejected by the Copilot API, so reject them early."""
    assert copilot_auth.is_supported_token("gho_abc")
    assert copilot_auth.is_supported_token("ghu_abc")
    assert copilot_auth.is_supported_token("github_pat_abc")
    assert not copilot_auth.is_supported_token("ghp_classic")
    assert not copilot_auth.is_supported_token("")


def test_resolution_prefers_env_then_gh_cli_then_editor_config(monkeypatch) -> None:
    monkeypatch.setattr(copilot_auth, "gh_cli_token", lambda: "gho_from_cli")
    monkeypatch.setattr(copilot_auth, "copilot_apps_json_token", lambda: "ghu_from_app")

    monkeypatch.setenv(copilot_auth.COPILOT_TOKEN_ENV, "gho_from_env")
    assert copilot_auth.resolve_copilot_token() == (
        "gho_from_env",
        copilot_auth.COPILOT_TOKEN_ENV,
    )

    monkeypatch.delenv(copilot_auth.COPILOT_TOKEN_ENV, raising=False)
    assert copilot_auth.resolve_copilot_token()[0] == "gho_from_cli"

    monkeypatch.setattr(copilot_auth, "gh_cli_token", lambda: "")
    assert copilot_auth.resolve_copilot_token()[0] == "ghu_from_app"


def test_resolution_works_without_gh_cli(no_ambient_credentials, monkeypatch) -> None:
    """The gh CLI must never be a hard requirement."""
    monkeypatch.setattr(copilot_auth, "copilot_apps_json_token", lambda: "ghu_editor")

    token, source = copilot_auth.resolve_copilot_token()

    assert token == "ghu_editor"
    assert "apps.json" in source


def test_credentials_fall_back_to_local_token(no_ambient_credentials, monkeypatch) -> None:
    monkeypatch.setattr(copilot_auth, "gh_cli_token", lambda: "gho_faketoken")

    creds = get_llm_credentials("copilot", "claude-sonnet-4.6")

    assert creds["api_key"] == "gho_faketoken"
    assert creds["base_url"] == "https://api.githubcopilot.com"


def test_explicit_env_key_wins_over_local_sources(monkeypatch) -> None:
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "gho_explicit")
    monkeypatch.setattr(copilot_auth, "gh_cli_token", lambda: "gho_from_cli")

    assert get_llm_credentials("copilot", "claude-sonnet-4.6")["api_key"] == "gho_explicit"


def test_no_credential_yields_empty_key(no_ambient_credentials) -> None:
    """Fail loud rather than silently borrowing another provider's key."""
    assert get_llm_credentials("copilot", "claude-sonnet-4.6")["api_key"] == ""


# --- Device code login -----------------------------------------------------


def test_device_login_returns_token_after_pending_poll(monkeypatch) -> None:
    responses = [
        {"device_code": "dc", "user_code": "ABCD-1234", "interval": 0},
        {"error": "authorization_pending"},
        {"access_token": "gho_device_token"},
    ]

    class _FakeResponse:
        def __init__(self, payload): self._payload = payload
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return json.dumps(self._payload).encode()

    monkeypatch.setattr(
        copilot_auth.urllib.request,
        "urlopen",
        lambda *_a, **_k: _FakeResponse(responses.pop(0)),
    )
    monkeypatch.setattr(copilot_auth.time, "sleep", lambda _s: None)

    printed: list[str] = []
    token = copilot_auth.login_copilot(print_fn=printed.append)

    assert token == "gho_device_token"
    # The user must be shown where to go and what to type.
    assert any("ABCD-1234" in line for line in printed)
    # The secret must never be echoed.
    assert not any("gho_device_token" in line for line in printed)


def test_device_login_returns_none_on_denial(monkeypatch) -> None:
    responses = [
        {"device_code": "dc", "user_code": "ABCD-1234", "interval": 0},
        {"error": "access_denied"},
    ]

    class _FakeResponse:
        def __init__(self, payload): self._payload = payload
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return json.dumps(self._payload).encode()

    monkeypatch.setattr(
        copilot_auth.urllib.request,
        "urlopen",
        lambda *_a, **_k: _FakeResponse(responses.pop(0)),
    )
    monkeypatch.setattr(copilot_auth.time, "sleep", lambda _s: None)

    assert copilot_auth.login_copilot(print_fn=lambda _t: None) is None


# --- Web UI settings -------------------------------------------------------


def test_settings_report_copilot_configured_without_env_var(monkeypatch) -> None:
    """A gh-CLI-only install must not display as unconfigured."""
    monkeypatch.setattr(
        copilot_auth, "resolve_copilot_token", lambda: ("gho_tok", "gh auth token")
    )

    response = settings_routes._build_llm_settings_response(
        {"LANGCHAIN_PROVIDER": "copilot"}
    )

    assert response.provider == "copilot"
    assert response.api_key_configured is True
    # The source is named; the secret is not.
    assert response.api_key_hint == "via gh auth token"
    assert "gho_tok" not in (response.api_key_hint or "")


def test_settings_report_copilot_unconfigured_when_no_token(monkeypatch) -> None:
    monkeypatch.setattr(copilot_auth, "resolve_copilot_token", lambda: ("", ""))

    response = settings_routes._build_llm_settings_response(
        {"LANGCHAIN_PROVIDER": "copilot"}
    )

    assert response.api_key_configured is False
    assert response.api_key_hint is None


def test_settings_do_not_use_codex_login_status_for_copilot(monkeypatch) -> None:
    """Regression: auth_type dispatch must not assume oauth == codex."""
    monkeypatch.setattr(copilot_auth, "resolve_copilot_token", lambda: ("gho_tok", "env"))

    def _explode():
        raise AssertionError("copilot must not consult the codex login status")

    monkeypatch.setattr(
        "src.providers.openai_codex.get_openai_codex_login_status", _explode
    )

    response = settings_routes._build_llm_settings_response(
        {"LANGCHAIN_PROVIDER": "copilot"}
    )
    assert response.api_key_configured is True
