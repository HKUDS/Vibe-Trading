"""Tests for the JSONP fallback in the throttled JSON GET helper.

Eastmoney's search endpoints answer with a ``callback(...)`` envelope instead of
a JSON body when they distrust the caller (see issue #2081), which
``response.json()`` cannot parse. These tests pin the fallback at the HTTP
boundary so every caller of :func:`backtest.loaders._http.throttled_get_json`
benefits, and pin that a genuinely malformed body keeps raising.

No request leaves the process: :func:`backtest.loaders._http.throttled_get` is
mocked with a stand-in response object.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from backtest.loaders import _http


class _FakeResponse:
    """Minimal stand-in for ``requests.Response`` at the HTTP boundary."""

    def __init__(self, body: str) -> None:
        self.text = body

    def raise_for_status(self) -> None:
        """No-op: these tests never model a non-2xx status."""

    def json(self) -> Any:
        """Mimic ``requests``: undecodable bodies raise ``ValueError``."""
        return json.loads(self.text)


def _call(body: str) -> Any:
    """Run ``throttled_get_json`` against a canned response body."""
    with patch.object(_http, "throttled_get", return_value=_FakeResponse(body)):
        return _http.throttled_get_json(
            "https://search-api-web.eastmoney.com/search/jsonp",
            host_key="eastmoney",
            min_interval=0,
            params={"cb": ""},
        )


class TestJsonpFallback:
    def test_jsonp_envelope_is_decoded(self) -> None:
        body = 'jQuery3700123_456({"code": 0, "result": {"hitsTotal": 1}})'
        assert _call(body) == {"code": 0, "result": {"hitsTotal": 1}}

    def test_dotted_callback_identifier_is_decoded(self) -> None:
        body = 'window.jQuery.cb({"code": 0});'
        assert _call(body) == {"code": 0}

    def test_plain_json_still_parses(self) -> None:
        assert _call('{"code": 0, "result": {}}') == {"code": 0, "result": {}}

    def test_plain_json_with_parens_in_values_is_not_mangled(self) -> None:
        body = '{"title": "公司(600519)发布三季报(更新)"}'
        assert _call(body) == {"title": "公司(600519)发布三季报(更新)"}

    def test_unparseable_body_still_raises(self) -> None:
        with pytest.raises(ValueError):
            _call("<html>blocked</html>")


def test_browser_transport_obeys_the_same_throttle_and_decodes_jsonp(monkeypatch):
    from curl_cffi import requests

    calls = []

    class Session:
        def __init__(self, **kwargs):
            assert kwargs == {"impersonate": "chrome"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return _FakeResponse('callback({"result":{"cmsArticleWebOld":[]}})')

    monkeypatch.setattr(requests, "Session", Session)
    waits = []
    monkeypatch.setattr(_http._THROTTLE, "wait", lambda *args: waits.append(args))
    assert _http.throttled_browser_get_json("https://example.invalid/news", host_key="eastmoney", min_interval=0.5) == {
        "result": {"cmsArticleWebOld": []}
    }
    assert waits == [("eastmoney", 0.5)]
    assert calls[0][1]["timeout"] == 15.0
