"""Tests for env-configurable per-market source-order overrides.

Covers the registry machinery behind ``MARKET_DATA_ORDER_<MARKET>`` env
vars: snapshot-gated refresh, in-place chain reassignment (visible through
both by-name imports and attribute access), validation (permutation-only),
reset-to-default, and the guarantee that override-free environments never
touch :data:`FALLBACK_CHAINS` (existing ``patch.dict``/``setitem`` tests
depend on that).
"""

from __future__ import annotations

import logging
import os

import pytest
from unittest.mock import patch

import backtest.loaders.registry as registry
from backtest.loaders.registry import (
    FALLBACK_CHAINS,
    parse_source_order,
    refresh_source_order_overrides,
    source_order_env_var,
)

_MISSING = object()
_ALL_ORDER_ENV_VARS = [
    source_order_env_var(market) for market in registry._DEFAULT_CHAINS
]


@pytest.fixture(autouse=True)
def _clean_order_env():
    """Scrub order env vars and restore default chains around each test.

    Teardown re-scrubs *before* refreshing (not relying on monkeypatch undo
    order), so chains always return to defaults even if the test patched
    env via monkeypatch, and the saved shell values are put back afterwards
    for fixtures further out.
    """
    saved = {var: os.environ.get(var, _MISSING) for var in _ALL_ORDER_ENV_VARS}
    for var in _ALL_ORDER_ENV_VARS:
        os.environ.pop(var, None)
    refresh_source_order_overrides()
    try:
        yield
    finally:
        for var in _ALL_ORDER_ENV_VARS:
            os.environ.pop(var, None)
        refresh_source_order_overrides()
        for var, value in saved.items():
            if value is not _MISSING:
                os.environ[var] = value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_source_order_env_var() -> None:
    assert source_order_env_var("a_share") == "MARKET_DATA_ORDER_A_SHARE"
    assert (
        source_order_env_var("vietnam_equity")
        == "MARKET_DATA_ORDER_VIETNAM_EQUITY"
    )


def test_parse_source_order_strips_lowercases_and_drops_empty() -> None:
    assert parse_source_order(" TUSHARE, tencent ,, ") == ["tushare", "tencent"]
    assert parse_source_order("") == []


def test_is_valid_source_order_requires_exact_permutation() -> None:
    assert registry.is_valid_source_order(
        "crypto", ["local", "okx", "binance", "ccxt", "yfinance"]
    )
    assert not registry.is_valid_source_order("crypto", ["okx"])  # subset
    assert not registry.is_valid_source_order("crypto", ["okx"] * 5)  # dupes
    assert not registry.is_valid_source_order(
        "crypto", ["okx", "binance", "ccxt", "yfinance", "stooq"]
    )  # foreign member
    assert not registry.is_valid_source_order("no_such_market", ["okx"])


def test_get_default_source_order_returns_copy() -> None:
    chain = registry.get_default_source_order("us_equity")
    chain.append("mutated")
    assert "mutated" not in registry._DEFAULT_CHAINS["us_equity"]
    assert (
        registry.get_default_source_order("us_equity")
        == registry._DEFAULT_CHAINS["us_equity"]
    )
    assert registry.get_default_source_order("no_such_market") == []


# ---------------------------------------------------------------------------
# Refresh behavior
# ---------------------------------------------------------------------------


def test_import_time_refresh_left_defaults_intact() -> None:
    for market, chain in FALLBACK_CHAINS.items():
        assert chain == registry._DEFAULT_CHAINS[market]
    assert registry.get_source_order_override("a_share") is None


def test_no_env_overrides_refresh_is_noop_for_patched_chains() -> None:
    """Regression guard: override-free env must never touch FALLBACK_CHAINS.

    test_ui_services monkeypatches individual chain entries; a refresh that
    blindly reassigned from defaults would wipe those patches.
    """
    with patch.dict(
        registry.FALLBACK_CHAINS, {"ca_equity": ["yfinance", "yahoo", "local"]}
    ):
        refresh_source_order_overrides()
        assert registry.FALLBACK_CHAINS["ca_equity"] == [
            "yfinance", "yahoo", "local",
        ]


def test_refresh_gated_on_env_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "MARKET_DATA_ORDER_CRYPTO", "binance,okx,ccxt,yfinance,local"
    )
    refresh_source_order_overrides()
    first = registry.FALLBACK_CHAINS["crypto"]
    assert first == ["binance", "okx", "ccxt", "yfinance", "local"]

    # Unchanged env -> no-op, entry object untouched.
    refresh_source_order_overrides()
    assert registry.FALLBACK_CHAINS["crypto"] is first

    # Changed env -> reassignment (new list object).
    monkeypatch.setenv(
        "MARKET_DATA_ORDER_CRYPTO", "ccxt,okx,binance,yfinance,local"
    )
    refresh_source_order_overrides()
    assert registry.FALLBACK_CHAINS["crypto"] is not first
    assert registry.FALLBACK_CHAINS["crypto"][0] == "ccxt"


def test_override_reorders_in_place_for_byname_importers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """runner.py/market_data.py do ``from ...registry import FALLBACK_CHAINS``.

    The reassignment must be a setitem on the same dict object so those
    by-name references observe the new order.
    """
    monkeypatch.setenv("MARKET_DATA_ORDER_FUTURES", "local,akshare")
    refresh_source_order_overrides()
    assert FALLBACK_CHAINS["futures"] == ["local", "akshare"]

    override = registry.get_source_order_override("futures")
    assert override == ["local", "akshare"]
    # Returned copies — callers cannot corrupt internal state.
    override.append("zzz")
    assert registry.get_source_order_override("futures") == ["local", "akshare"]


@pytest.mark.parametrize(
    "raw",
    [
        "tushare,akshare",  # dropped 'local'
        "tushare,akshare,local,ccxt",  # extra member
        "tushare,tushare,akshare,local",  # duplicate
        "tushare,akshare,local,yahoo",  # member of another market
    ],
)
def test_invalid_values_keep_default_and_warn(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    raw: str,
) -> None:
    monkeypatch.setenv("MARKET_DATA_ORDER_FUND", raw)
    with caplog.at_level(logging.WARNING):
        refresh_source_order_overrides()
    assert registry.FALLBACK_CHAINS["fund"] == ["tushare", "akshare", "local"]
    assert registry.get_source_order_override("fund") is None
    assert any("MARKET_DATA_ORDER_FUND" in r.message for r in caplog.records)


def test_empty_string_resets_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "MARKET_DATA_ORDER_A_SHARE",
        "tushare,tencent,mootdx,eastmoney,baostock,akshare,gildata,local",
    )
    refresh_source_order_overrides()
    assert registry.FALLBACK_CHAINS["a_share"][0] == "tushare"

    monkeypatch.setenv("MARKET_DATA_ORDER_A_SHARE", "")
    refresh_source_order_overrides()
    assert registry.FALLBACK_CHAINS["a_share"] == registry.get_default_source_order("a_share")
    assert registry.get_source_order_override("a_share") is None


def test_default_snapshot_never_aliased(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MARKET_DATA_ORDER_MACRO", "tushare,akshare,local")
    refresh_source_order_overrides()
    assert registry._DEFAULT_CHAINS["macro"] == ["akshare", "tushare", "local"]

    monkeypatch.delenv("MARKET_DATA_ORDER_MACRO")
    refresh_source_order_overrides()
    assert registry._DEFAULT_CHAINS["macro"] == ["akshare", "tushare", "local"]
    assert registry.FALLBACK_CHAINS["macro"] == ["akshare", "tushare", "local"]


def test_ensure_registered_rechecks_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refresh hook sits before the ``_registered`` early return."""
    monkeypatch.setenv(
        "MARKET_DATA_ORDER_KR_EQUITY", "yahoo,pykrx,yfinance,local"
    )
    registry._ensure_registered()
    assert registry.FALLBACK_CHAINS["kr_equity"][0] == "yahoo"
