"""Coverage for the GitHub Copilot provider.

Copilot needs two things no other OpenAI-compatible provider needs:

1. Editor-identification headers -- the endpoint rejects requests without
   ``Copilot-Integration-Id`` / ``Editor-Version``.
2. A credential sourced from the ``gh`` CLI rather than an API-key env var.
   The long-lived ``gho_``/``ghu_`` token is used directly as the Bearer
   credential; the ``copilot_internal/v2/token`` JWT exchange is NOT used
   (it 403s for individual accounts), so there is no refresh path to break.

These tests assert those invariants without any network access.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.providers import capabilities as caps_mod
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
    # Copilot authenticates through the gh CLI, so no key is required up front.
    assert entry["api_key_required"] is False


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


def test_copilot_credentials_fall_back_to_gh_cli(monkeypatch) -> None:
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("COPILOT_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.setattr(caps_mod, "_gh_cli_token", lambda: "gho_faketoken")

    creds = get_llm_credentials("copilot", "claude-sonnet-4.6")

    assert creds["api_key"] == "gho_faketoken"
    assert creds["base_url"] == "https://api.githubcopilot.com"


def test_copilot_explicit_env_key_wins_over_gh_cli(monkeypatch) -> None:
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "gho_explicit")
    monkeypatch.setattr(caps_mod, "_gh_cli_token", lambda: "gho_from_cli")

    assert get_llm_credentials("copilot", "claude-sonnet-4.6")["api_key"] == "gho_explicit"


def test_copilot_without_gh_cli_yields_empty_key(monkeypatch) -> None:
    """No gh CLI must fail loud (empty key), never silently borrow another key."""
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(caps_mod, "_gh_cli_token", lambda: "")

    assert get_llm_credentials("copilot", "claude-sonnet-4.6")["api_key"] == ""
