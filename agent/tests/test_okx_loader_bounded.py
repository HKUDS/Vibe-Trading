"""Regression tests for the OKX loader — session-based, dual-endpoint,
proxy-aware, with bounded retry and wall-clock budget.

The loader now uses a ``requests.Session`` (with optional proxy) and tries
both ``/market/history-candles`` and ``/market/candles`` endpoints.
Tests mock the session or the helper that creates it.
"""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

import backtest.loaders.okx as okx
from backtest.loaders.base import DEFAULT_MAX_RETRIES
from backtest.loaders.okx import DataLoader

S = int(pd.Timestamp("2026-05-01").timestamp() * 1000)
E = int((pd.Timestamp("2026-05-05") + pd.Timedelta(days=1)).timestamp() * 1000)


def _ok_page():
    """One short page (< _MAX_PER_PAGE) so the loop breaks after one call."""
    ts = int(pd.Timestamp("2026-05-02").timestamp() * 1000)
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "code": "0",
        "data": [[ts, "1", "2", "0.5", "1.5", "10", "0", "0", "1"]],
    }
    return resp


class _Seq:
    """Callable that returns items from *script* in order; raises if
    the item is an exception."""

    def __init__(self, script):
        self.script = script
        self.calls = 0

    def __call__(self, *a, **k):
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(okx.time, "sleep", lambda *_a, **_k: None)


# ---------------------------------------------------------------------------
# _paginate (core request loop with retry_with_budget)
# ---------------------------------------------------------------------------


def test_transient_then_success(monkeypatch):
    """Transient errors are retried; after retrying, the page succeeds."""
    session = MagicMock()
    seq = _Seq(
        [requests.ConnectionError("blip"), requests.ConnectionError("blip"), _ok_page()]
    )
    session.get = seq
    df = DataLoader()._paginate(session, okx.CANDLES_PATH, "BTC-USDT", S, E, "1D", 20)
    assert seq.calls >= 3
    assert df is not None and not df.empty


def test_persistent_disconnect_is_bounded(monkeypatch):
    session = MagicMock()
    seq = _Seq([requests.ConnectionError("down")])
    session.get = seq
    with pytest.raises(TimeoutError):
        DataLoader()._paginate(session, okx.CANDLES_PATH, "BTC-USDT", S, E, "1D", 20)
    assert seq.calls == DEFAULT_MAX_RETRIES + 1  # bounded, not max_pages/forever


def test_non_network_error_not_retried(monkeypatch):
    session = MagicMock()
    seq = _Seq([KeyError("logic bug")])
    session.get = seq
    with pytest.raises(KeyError):
        DataLoader()._paginate(session, okx.CANDLES_PATH, "BTC-USDT", S, E, "1D", 20)
    assert seq.calls == 1


def test_happy_path_single_call(monkeypatch):
    session = MagicMock()
    seq = _Seq([_ok_page()])
    session.get = seq
    df = DataLoader()._paginate(session, okx.CANDLES_PATH, "BTC-USDT", S, E, "1D", 20)
    assert seq.calls == 1
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_wallclock_budget_enforced(monkeypatch):
    seq = iter([1000.0, 1000.0, 1_000_000.0])
    monkeypatch.setattr(okx.time, "monotonic", lambda: next(seq, 1_000_000.0))
    session = MagicMock()
    session.get = _Seq([requests.ConnectionError("slow")])
    with pytest.raises(TimeoutError):
        DataLoader()._paginate(session, okx.CANDLES_PATH, "BTC-USDT", S, E, "1D", 20)


# ---------------------------------------------------------------------------
# _fetch_candles (dual-endpoint fallback)
# ---------------------------------------------------------------------------


def test_fetch_candles_tries_history_then_recent(monkeypatch):
    """When prefer_history=True and history fails, candles endpoint is tried."""
    loader = DataLoader()

    paginate_calls: list[str] = []
    original_paginate = DataLoader._paginate

    def _fake_paginate(self, session, endpoint, *args, **kwargs):
        paginate_calls.append(endpoint)
        if endpoint == okx.HISTORY_CANDLES_PATH:
            raise requests.RequestException("history down")
        # Use the real _paginate for the working endpoint
        return original_paginate(self, session, endpoint, *args, **kwargs)

    monkeypatch.setattr(DataLoader, "_paginate", _fake_paginate)
    session = MagicMock()
    session.get = _Seq([_ok_page()])
    df = loader._fetch_candles(session, "BTC-USDT", S, E, "1D", 20, prefer_history=True)
    # history was tried first, then candles
    assert okx.HISTORY_CANDLES_PATH in paginate_calls[0]
    assert df is not None


def test_fetch_candles_returns_none_when_both_endpoints_fail(monkeypatch):
    loader = DataLoader()

    def _fail_paginate(*a, **kw):
        raise requests.RequestException("both down")

    monkeypatch.setattr(DataLoader, "_paginate", _fail_paginate)
    session = MagicMock()
    df = loader._fetch_candles(session, "BTC-USDT", S, E, "1D", 20, prefer_history=True)
    assert df is None


# ---------------------------------------------------------------------------
# Env var handling
# ---------------------------------------------------------------------------


def test_invalid_timeout_env_values_fall_back_on_reload(monkeypatch, caplog):
    monkeypatch.setenv("OKX_TIMEOUT_S", "abc")
    monkeypatch.setenv("OKX_FETCH_BUDGET_S", "nope")
    try:
        with caplog.at_level("WARNING", logger="backtest.loaders.base"):
            module = importlib.reload(okx)

        assert module._OKX_TIMEOUT in {15, 20}  # 15 was original, 20 is new default
        assert module._OKX_FETCH_BUDGET_S in {60.0, 90.0}  # 60 was original, 90 is new
        assert "OKX_TIMEOUT_S" in caplog.text
        assert "OKX_FETCH_BUDGET_S" in caplog.text
    finally:
        monkeypatch.delenv("OKX_TIMEOUT_S", raising=False)
        monkeypatch.delenv("OKX_FETCH_BUDGET_S", raising=False)
        importlib.reload(okx)


def test_valid_timeout_env_values_are_honored_on_reload(monkeypatch):
    monkeypatch.setenv("OKX_TIMEOUT_S", "7")
    monkeypatch.setenv("OKX_FETCH_BUDGET_S", "2.5")
    try:
        module = importlib.reload(okx)

        assert module._OKX_TIMEOUT == 7
        assert module._OKX_FETCH_BUDGET_S == 2.5
    finally:
        monkeypatch.delenv("OKX_TIMEOUT_S", raising=False)
        monkeypatch.delenv("OKX_FETCH_BUDGET_S", raising=False)
        importlib.reload(okx)


# ---------------------------------------------------------------------------
# _okx_proxy_config / _okx_session
# ---------------------------------------------------------------------------


def test_proxy_config_from_env(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:10808")
    try:
        cfg = okx._okx_proxy_config()
        assert cfg.get("https") == "http://127.0.0.1:10808"
    finally:
        monkeypatch.delenv("HTTPS_PROXY", raising=False)


def test_okx_session_has_proxies_when_configured(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy:8080")
    try:
        s = okx._okx_session()
        assert "http" in s.proxies
    finally:
        monkeypatch.delenv("HTTP_PROXY", raising=False)


def test_okx_session_empty_without_proxy(monkeypatch):
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(key, raising=False)
    s = okx._okx_session()
    assert not s.proxies
