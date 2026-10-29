"""Regression tests for ChatGPT Codex OAuth model discovery (no live credentials)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from src.api import settings_routes
from src.providers import openai_codex


REAL_ASYNC_CLIENT = httpx.AsyncClient
PROVIDER = settings_routes.LLM_PROVIDER_BY_NAME["openai-codex"]


def _run(monkeypatch: pytest.MonkeyPatch, handler, *, token=None):
    """Run discovery against a mock HTTP transport with a fake OAuth session."""
    real_client = REAL_ASYNC_CLIENT
    calls = []

    def get_token(**kwargs):
        calls.append(kwargs)
        return token or SimpleNamespace(access="fake-test-access", account_id="fake-account")

    monkeypatch.setattr(openai_codex, "_get_codex_token", get_token)
    monkeypatch.setattr(
        settings_routes.httpx, "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = asyncio.run(settings_routes._list_openai_codex_models(PROVIDER))
    return result, calls


def test_catalog_parses_visible_supported_models_and_efforts(monkeypatch):
    payload = {
        "models": [
            {
                "slug": "gpt-6-sol",
                "display_name": "GPT-6 Sol",
                "visibility": "list",
                "supported_in_api": True,
                "default_reasoning_level": "medium",
                "supported_reasoning_levels": [
                    {"effort": "low", "description": "Low"},
                    {"effort": "medium", "description": "Medium"},
                    {"effort": "ultra", "description": "Ultra"},
                ],
            },
            {"slug": "gpt-reserve", "visibility": "hide", "supported_in_api": True},
            {"slug": "oauth-only", "visibility": "list", "supported_in_api": False},
            {"slug": "gpt-6-sol", "visibility": "list", "supported_in_api": True},
            {"slug": "bad/name", "visibility": "list", "supported_in_api": True},
        ],
    }

    def handler(request):
        assert request.method == "GET"
        assert str(request.url) == (
            "https://chatgpt.com/backend-api/codex/models?client_version=0.159.0"
        )
        assert request.headers["authorization"] == "Bearer fake-test-access"
        assert request.headers["chatgpt-account-id"] == "fake-account"
        assert request.headers["originator"] == "vibe-trading"
        return httpx.Response(200, json=payload)

    result, calls = _run(monkeypatch, handler)
    assert calls == [{}]
    assert result.source == "provider"
    assert result.warning_code is None
    assert result.models == ["openai-codex/gpt-6-sol", "openai-codex/oauth-only"]
    assert result.model_labels == {"openai-codex/gpt-6-sol": "GPT-6 Sol"}
    assert result.default_effort_levels == {"openai-codex/gpt-6-sol": "medium"}
    assert result.effort_levels == {
        "openai-codex/gpt-6-sol": ["low", "medium", "ultra"]
    }


@pytest.mark.parametrize(
    "payload",
    [{}, {"models": "incorrect"}, {"models": []}, {"models": [{"slug": "hidden", "visibility": "hide", "supported_in_api": True}]}],
)
def test_unusable_catalog_falls_back_without_exposing_payload(monkeypatch, payload):
    result, _ = _run(monkeypatch, lambda _: httpx.Response(200, json=payload))
    assert result.source == "default"
    assert result.warning_code == "model_list_unavailable"
    assert result.models == [PROVIDER.default_model]
    assert result.model_labels is None


def test_refreshes_once_after_401_with_rejected_token(monkeypatch):
    seen = []
    def handler(request):
        seen.append(request.headers["authorization"])
        if len(seen) == 1:
            return httpx.Response(401, text="do not expose response body")
        return httpx.Response(200, json={
            "models": [{"slug": "gpt-6-sol", "visibility": "list", "supported_in_api": True}]
        })

    real_client = REAL_ASYNC_CLIENT
    calls = []
    def get_token(**kwargs):
        calls.append(kwargs)
        if kwargs.get("force_refresh"):
            return SimpleNamespace(access="new-access", account_id="fake-account")
        return SimpleNamespace(access="old-access", account_id="fake-account")

    monkeypatch.setattr(openai_codex, "_get_codex_token", get_token)
    monkeypatch.setattr(settings_routes.httpx, "AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    result = asyncio.run(settings_routes._list_openai_codex_models(PROVIDER))
    assert result.source == "provider"
    assert seen == ["Bearer old-access", "Bearer new-access"]
    assert calls == [{}, {"force_refresh": True, "rejected_access": "old-access"}]


def test_missing_oauth_session_returns_safe_fallback(monkeypatch):
    def missing(**kwargs):
        raise RuntimeError("private-token-must-never-be-logged")
    monkeypatch.setattr(openai_codex, "_get_codex_token", missing)
    result = asyncio.run(settings_routes._list_openai_codex_models(PROVIDER))
    assert result.warning_code == "model_list_unavailable"
    assert "private-token" not in str(result.model_dump())


def test_transport_failure_and_redirect_never_leave_codex_host(monkeypatch):
    for status_code in (302, 403, 500):
        def handler(request, status_code=status_code):
            return httpx.Response(
                status_code,
                headers={"location": "https://example.org/should-never-follow"}
            )
        result, _ = _run(monkeypatch, handler)
        assert result.warning_code == "model_list_unavailable"


def test_codex_provider_accepts_announced_extended_efforts():
    assert settings_routes.LLM_PROVIDER_BY_NAME["openai-codex"].reasoning_efforts == [
        "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra", "persistent"
    ]


def test_bad_effort_entry_does_not_discard_other_catalog_models(monkeypatch):
    payload = {"models": [{
        "slug": "valid", "visibility": "list",
        "supported_reasoning_levels": [
            {"effort": ["malformed"]}, {"effort": "high"},
        ],
        "default_reasoning_level": "ultra",
    }]}
    result, _ = _run(monkeypatch, lambda _: httpx.Response(200, json=payload))
    assert result.models == ["openai-codex/valid"]
    assert result.effort_levels == {"openai-codex/valid": ["high"]}
    assert result.default_effort_levels == {}
