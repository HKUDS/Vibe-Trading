"""Tests for startup preflight checks."""

from __future__ import annotations

import sys

import requests

from src import preflight


def _configure_llm_preflight(monkeypatch) -> None:
    """Install a minimal OpenAI-compatible provider environment for preflight tests."""
    import src.providers.llm as llm

    monkeypatch.setenv("LANGCHAIN_PROVIDER", "openai")
    monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "gpt-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.setattr(llm, "_ensure_dotenv", lambda: None)
    monkeypatch.setattr(llm, "_sync_provider_env", lambda: None)
    monkeypatch.setattr(
        llm,
        "provider_diagnostics",
        lambda: {
            "base_url": "https://example.test/v1",
            "timeout_seconds": 120,
            "max_retries": 2,
            "proxy": {},
        },
    )


def test_llm_preflight_probe_does_not_follow_redirects(monkeypatch) -> None:
    """A redirect response still proves the HTTPS provider base is reachable."""
    _configure_llm_preflight(monkeypatch)
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_get(url: str, **kwargs: object) -> object:
        calls.append((url, kwargs))
        response = requests.Response()
        response.status_code = 307
        return response

    monkeypatch.setattr(requests, "get", fake_get)

    result = preflight._check_llm_provider()

    assert result.status == "ready"
    assert calls == [
        (
            "https://example.test",
            {
                "timeout": 10,
                "allow_redirects": False,
            },
        )
    ]


def test_llm_preflight_probe_reports_request_errors(monkeypatch) -> None:
    """Request failures remain critical errors for the LLM provider check."""
    _configure_llm_preflight(monkeypatch)

    def fake_get(url: str, **kwargs: object) -> object:
        del url, kwargs
        raise requests.Timeout("timed out")

    monkeypatch.setattr(requests, "get", fake_get)

    result = preflight._check_llm_provider()

    assert result.status == "error"
    assert result.critical is True
    assert "Timeout: timed out" in result.message


def test_akshare_check_uses_spec_without_import(monkeypatch) -> None:
    """AKShare's package import is heavy; preflight should only check discovery."""
    monkeypatch.delitem(sys.modules, "akshare", raising=False)
    monkeypatch.setattr(preflight, "find_spec", lambda name: object() if name == "akshare" else None)

    result = preflight._check_akshare()

    assert result.status == "ready"
    assert result.message == "installed"
    assert "akshare" not in sys.modules


def test_akshare_check_skips_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "find_spec", lambda name: None)

    result = preflight._check_akshare()

    assert result.status == "skipped"
    assert result.message == "package not installed"


def test_content_filter_threshold_check(monkeypatch) -> None:
    """Content Filter Threshold row must appear in preflight output."""
    monkeypatch.setenv("CONTENT_FILTER_WARNING_THRESHOLD", "0.10")

    result = preflight._check_content_filter_threshold()

    assert result.name == "Content Filter Threshold"
    assert result.status == "ready"
    assert "10%" in result.message
    assert "CONTENT_FILTER_WARNING_THRESHOLD" in result.message


def test_content_filter_threshold_default(monkeypatch) -> None:
    """Default threshold is 5% when env var is unset."""
    monkeypatch.delenv("CONTENT_FILTER_WARNING_THRESHOLD", raising=False)

    result = preflight._check_content_filter_threshold()

    assert result.name == "Content Filter Threshold"
    assert result.status == "ready"
    assert "5%" in result.message
