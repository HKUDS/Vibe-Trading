"""Tests for WebSearchTool: multi-backend fallback, retry, and error handling.

Covers issue #231 — a single rate-limited engine (DuckDuckGo) should no longer
fail the whole search. All tests mock ``ddgs.DDGS`` so no network calls are made.
"""
import json
import sys
from contextlib import contextmanager
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from src.tools.web_search_tool import WebSearchTool


def _make_ddgs_module(text_impl):
    """Build a fake ``ddgs`` module whose DDGS().text delegates to text_impl."""
    module = ModuleType("ddgs")

    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def text(self, query, max_results=5, **kwargs):
            return text_impl(query, max_results=max_results, **kwargs)

    module.DDGS = FakeDDGS
    return module


@contextmanager
def _patch_ddgs(monkeypatch, text_impl):
    monkeypatch.setitem(sys.modules, "ddgs", _make_ddgs_module(text_impl))
    yield


@pytest.fixture(autouse=True)
def _clear_backend_env(monkeypatch):
    monkeypatch.delenv("VIBE_TRADING_SEARCH_BACKENDS", raising=False)
    monkeypatch.delenv("VIBE_TRADING_SEARCH_BING_FALLBACK", raising=False)
    monkeypatch.delenv("ALIYUN_IQS_API_KEY", raising=False)
    monkeypatch.setattr("src.tools.web_search_tool._sogou_search", MagicMock(return_value=[]))
    monkeypatch.setattr("src.tools.web_search_tool._bing_cn_search", MagicMock(return_value=[]))


def test_returns_results_and_passes_backend_list(monkeypatch):
    """Happy path: results mapped to title/url/snippet and the backend list is forwarded."""
    seen = {}

    def text_impl(query, max_results, **kwargs):
        seen.update(kwargs)
        return [{"title": "T1", "href": "http://a", "body": "snippet1"}]

    with _patch_ddgs(monkeypatch, text_impl):
        out = json.loads(WebSearchTool().execute(query="nvidia"))

    assert out["status"] == "ok"
    assert out["results"][0] == {"title": "T1", "url": "http://a", "snippet": "snippet1"}
    # The default multi-engine list is forwarded so a throttled engine falls through.
    assert seen.get("backend") == "duckduckgo, google, bing, brave, mojeek, yahoo"


def test_env_overrides_backends(monkeypatch):
    """VIBE_TRADING_SEARCH_BACKENDS overrides the default engine list."""
    monkeypatch.setenv("VIBE_TRADING_SEARCH_BACKENDS", "google, bing")
    seen = {}

    def text_impl(query, max_results, **kwargs):
        seen.update(kwargs)
        return [{"title": "T", "href": "http://x", "body": "b"}]

    with _patch_ddgs(monkeypatch, text_impl):
        out = json.loads(WebSearchTool().execute(query="aapl"))

    assert out["status"] == "ok"
    assert seen.get("backend") == "google, bing"


def test_retries_transient_failure_then_succeeds(monkeypatch):
    """A transient exception is retried (with backoff) and a later attempt wins."""
    monkeypatch.setattr("src.tools.web_search_tool.time.sleep", lambda *_: None)
    calls = {"n": 0}

    def text_impl(query, max_results, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Ratelimit 202")
        return [{"title": "ok", "href": "http://ok", "body": "b"}]

    with _patch_ddgs(monkeypatch, text_impl):
        out = json.loads(WebSearchTool().execute(query="msft"))

    assert out["status"] == "ok"
    assert calls["n"] == 2


def test_no_results_is_ok_empty_not_error(monkeypatch):
    """Empty answers from all enabled sources remain an ok+empty envelope."""
    monkeypatch.setattr("src.tools.web_search_tool.time.sleep", lambda *_: None)

    def text_impl(query, max_results, **kwargs):
        raise RuntimeError("No results found.")

    with _patch_ddgs(monkeypatch, text_impl):
        out = json.loads(WebSearchTool().execute(query="zzzz-no-such-thing"))

    assert out["status"] == "ok"
    assert out["results"] == []
    assert "note" in out


@pytest.mark.parametrize("raises_empty", [False, True])
def test_empty_ddgs_tries_existing_fallbacks(monkeypatch, raises_empty):
    """An empty ddgs answer does not establish that other sources are empty."""
    calls = []

    def text_impl(query, max_results, **kwargs):
        calls.append("ddgs")
        if raises_empty:
            raise RuntimeError("No results found.")
        return []

    def sogou(query, max_results):
        calls.append("sogou")
        return []

    def bing(query, max_results):
        calls.append("bing_cn")
        return [{"title": "Earnings", "href": "https://example.test/earnings", "body": "Report"}]

    monkeypatch.setattr("src.tools.web_search_tool._sogou_search", sogou)
    monkeypatch.setattr("src.tools.web_search_tool._bing_cn_search", bing)
    with _patch_ddgs(monkeypatch, text_impl):
        out = json.loads(WebSearchTool().execute(query="quarterly earnings"))

    assert calls == ["ddgs", "sogou", "bing_cn"]
    assert out["status"] == "ok"
    assert out["backends"] == "bing_cn_fallback"
    assert out["results"][0]["url"] == "https://example.test/earnings"


def test_empty_ddgs_respects_disabled_fallbacks(monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_SEARCH_BING_FALLBACK", "0")
    forbidden = MagicMock(side_effect=AssertionError("fallback disabled"))
    monkeypatch.setattr("src.tools.web_search_tool._sogou_search", forbidden)
    monkeypatch.setattr("src.tools.web_search_tool._bing_cn_search", forbidden)
    with _patch_ddgs(monkeypatch, lambda *a, **kw: []):
        out = json.loads(WebSearchTool().execute(query="unmatched query"))
    assert out["status"] == "ok"
    assert out["results"] == []
    forbidden.assert_not_called()


def test_empty_ddgs_does_not_hide_a_fallback_outage(monkeypatch):
    unavailable = MagicMock(side_effect=RuntimeError("Connection timed out"))
    monkeypatch.setattr("src.tools.web_search_tool._sogou_search", unavailable)
    with _patch_ddgs(monkeypatch, lambda *a, **kw: []):
        out = json.loads(WebSearchTool().execute(query="quarterly earnings"))
    unavailable.assert_called_once()
    assert out["status"] == "error"
    assert "Connection timed out" in out["error"]


def test_nonempty_ddgs_does_not_invoke_fallbacks(monkeypatch):
    forbidden = MagicMock(side_effect=AssertionError("already have results"))
    monkeypatch.setattr("src.tools.web_search_tool._sogou_search", forbidden)
    monkeypatch.setattr("src.tools.web_search_tool._bing_cn_search", forbidden)
    with _patch_ddgs(monkeypatch, lambda *a, **kw: [{"title": "result", "href": "https://example.test"}]):
        out = json.loads(WebSearchTool().execute(query="quarterly earnings"))
    assert out["status"] == "ok"
    forbidden.assert_not_called()


def test_backend_compatibility_failure_is_not_empty_success(monkeypatch):
    def text_impl(query, max_results, **kwargs):
        raise TypeError("unsupported client signature")

    with _patch_ddgs(monkeypatch, text_impl):
        out = json.loads(WebSearchTool().execute(query="quarterly earnings"))
    assert out["status"] == "error"
    assert "unsupported client signature" in out["error"]


def test_persistent_failure_returns_actionable_error(monkeypatch):
    """When every attempt fails, the error names the retry/env/read_url remedies."""
    monkeypatch.setenv("VIBE_TRADING_SEARCH_BING_FALLBACK", "0")
    monkeypatch.setattr("src.tools.web_search_tool.time.sleep", lambda *_: None)
    calls = {"n": 0}

    def text_impl(query, max_results, **kwargs):
        calls["n"] += 1
        raise RuntimeError("Ratelimit 429")

    with _patch_ddgs(monkeypatch, text_impl):
        out = json.loads(WebSearchTool().execute(query="tsla"))

    assert out["status"] == "error"
    assert calls["n"] == 3  # exhausted all attempts
    assert "VIBE_TRADING_SEARCH_BACKENDS" in out["error"]
    assert "read_url" in out["error"]


def test_persistent_failure_uses_cn_fallback_without_network(monkeypatch):
    """Persistent ddgs failures can fall back to CN search without touching real network in tests."""
    monkeypatch.setattr("src.tools.web_search_tool.time.sleep", lambda *_: None)
    calls = {"ddgs": 0, "sogou": 0, "bing_cn": 0}

    def text_impl(query, max_results, **kwargs):
        calls["ddgs"] += 1
        raise RuntimeError("Ratelimit 429")

    def fake_sogou(query, max_results=5):
        calls["sogou"] += 1
        return [{"title": "fallback", "href": "https://example.test/f", "body": "ok"}]

    def fake_bing_cn(query, max_results=5):
        calls["bing_cn"] += 1
        return [{"title": "backup", "href": "https://example.test/b", "body": "ok"}]

    monkeypatch.setattr("src.tools.web_search_tool._sogou_search", fake_sogou)
    monkeypatch.setattr("src.tools.web_search_tool._bing_cn_search", fake_bing_cn)

    with _patch_ddgs(monkeypatch, text_impl):
        out = json.loads(WebSearchTool().execute(query="tsla"))

    assert out["status"] == "ok"
    assert out["backends"] == "sogou_fallback"
    assert out["results"][0]["url"] == "https://example.test/f"
    assert calls == {"ddgs": 3, "sogou": 1, "bing_cn": 0}


def test_network_failure_fast_fails_to_cn_fallback(monkeypatch):
    """Network-style ddgs failures skip extra retries and go straight to fallback."""
    monkeypatch.setattr("src.tools.web_search_tool.time.sleep", lambda *_: None)
    calls = {"ddgs": 0}

    def text_impl(query, max_results, **kwargs):
        calls["ddgs"] += 1
        raise RuntimeError("Connection timed out")

    monkeypatch.setattr(
        "src.tools.web_search_tool._sogou_search",
        lambda query, max_results=5: [
            {"title": "fallback", "href": "https://example.test/f", "body": "ok"}
        ],
    )
    monkeypatch.setattr("src.tools.web_search_tool._bing_cn_search", lambda *_args, **_kwargs: [])

    with _patch_ddgs(monkeypatch, text_impl):
        out = json.loads(WebSearchTool().execute(query="maotai"))

    assert out["status"] == "ok"
    assert out["backends"] == "sogou_fallback"
    assert calls["ddgs"] == 1


def test_max_results_capped_at_10(monkeypatch):
    """max_results is clamped to 10."""
    seen = {}

    def text_impl(query, max_results, **kwargs):
        seen["max_results"] = max_results
        return []

    with _patch_ddgs(monkeypatch, text_impl):
        WebSearchTool().execute(query="q", max_results=50)

    assert seen["max_results"] == 10
