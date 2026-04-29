"""Tests for loader registry and fallback chain logic."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from backtest.loaders.base import DataLoaderProtocol, NoAvailableSourceError
from backtest.loaders.registry import (
    FALLBACK_CHAINS,
    LOADER_REGISTRY,
    get_loader_cls_with_fallback,
    register,
    resolve_loader,
)


# ---------------------------------------------------------------------------
# Helpers — fake loaders
# ---------------------------------------------------------------------------


class _FakeAvailableLoader:
    name = "fake_available"
    markets = {"a_share"}
    requires_auth = False

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {}


class _FakeUnavailableLoader:
    name = "fake_unavailable"
    markets = {"a_share"}
    requires_auth = True

    def is_available(self) -> bool:
        return False

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {}


class _FakeInitErrorLoader:
    """Mimics Tushare with a missing token: blows up inside ``__init__``."""

    name = "fake_init_error"
    markets = {"a_share"}
    requires_auth = True

    def __init__(self) -> None:
        raise RuntimeError("api init error — TUSHARE_TOKEN not set")

    def is_available(self) -> bool:  # pragma: no cover — never reached
        return False

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {}


class _FakeCryptoLoader:
    name = "fake_crypto"
    markets = {"crypto"}
    requires_auth = False

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {}


# ---------------------------------------------------------------------------
# @register decorator
# ---------------------------------------------------------------------------


class TestRegisterDecorator:
    def test_register_adds_to_registry(self) -> None:
        # Use a patched registry to avoid polluting global state
        with patch.dict(LOADER_REGISTRY, {}, clear=True):
            register(_FakeAvailableLoader)
            assert "fake_available" in LOADER_REGISTRY
            assert LOADER_REGISTRY["fake_available"] is _FakeAvailableLoader

    def test_register_returns_class_unchanged(self) -> None:
        with patch.dict(LOADER_REGISTRY, {}, clear=True):
            result = register(_FakeAvailableLoader)
            assert result is _FakeAvailableLoader


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_fake_loader_satisfies_protocol(self) -> None:
        assert isinstance(_FakeAvailableLoader(), DataLoaderProtocol)

    def test_missing_method_fails_protocol(self) -> None:
        class BadLoader:
            name = "bad"

        assert not isinstance(BadLoader(), DataLoaderProtocol)


# ---------------------------------------------------------------------------
# FALLBACK_CHAINS
# ---------------------------------------------------------------------------


class TestFallbackChains:
    def test_all_expected_markets_present(self) -> None:
        expected = {"a_share", "us_equity", "hk_equity", "crypto", "futures", "fund", "macro", "forex"}
        assert expected == set(FALLBACK_CHAINS.keys())

    def test_chains_are_non_empty(self) -> None:
        for market, chain in FALLBACK_CHAINS.items():
            assert len(chain) > 0, f"Fallback chain for {market} is empty"


# ---------------------------------------------------------------------------
# resolve_loader
# ---------------------------------------------------------------------------


class TestResolveLoader:
    def test_returns_first_available(self) -> None:
        with patch.dict(LOADER_REGISTRY, {
            "fake_unavailable": _FakeUnavailableLoader,
            "fake_available": _FakeAvailableLoader,
        }, clear=True):
            with patch.dict(FALLBACK_CHAINS, {
                "a_share": ["fake_unavailable", "fake_available"],
            }):
                loader = resolve_loader("a_share")
                assert loader.name == "fake_available"

    def test_raises_when_none_available(self) -> None:
        with patch.dict(LOADER_REGISTRY, {
            "fake_unavailable": _FakeUnavailableLoader,
        }, clear=True):
            with patch.dict(FALLBACK_CHAINS, {
                "a_share": ["fake_unavailable"],
            }):
                with pytest.raises(NoAvailableSourceError):
                    resolve_loader("a_share")

    def test_unknown_market_raises(self) -> None:
        with patch.dict(LOADER_REGISTRY, {}, clear=True):
            with pytest.raises(NoAvailableSourceError):
                resolve_loader("martian_stocks")


# ---------------------------------------------------------------------------
# get_loader_cls_with_fallback
# ---------------------------------------------------------------------------


class TestGetLoaderWithFallback:
    def test_returns_requested_if_available(self) -> None:
        with patch.dict(LOADER_REGISTRY, {
            "fake_available": _FakeAvailableLoader,
        }, clear=True):
            cls = get_loader_cls_with_fallback("fake_available")
            assert cls is _FakeAvailableLoader

    def test_falls_back_when_unavailable(self) -> None:
        with patch.dict(LOADER_REGISTRY, {
            "fake_unavailable": _FakeUnavailableLoader,
            "fake_available": _FakeAvailableLoader,
        }, clear=True):
            with patch.dict(FALLBACK_CHAINS, {
                "a_share": ["fake_unavailable", "fake_available"],
            }):
                cls = get_loader_cls_with_fallback("fake_unavailable")
                assert cls is _FakeAvailableLoader

    def test_unknown_source_raises(self) -> None:
        with patch.dict(LOADER_REGISTRY, {}, clear=True):
            with pytest.raises(NoAvailableSourceError):
                get_loader_cls_with_fallback("nonexistent")

    def test_no_fallback_raises(self) -> None:
        with patch.dict(LOADER_REGISTRY, {
            "fake_unavailable": _FakeUnavailableLoader,
        }, clear=True):
            with patch.dict(FALLBACK_CHAINS, {"a_share": ["fake_unavailable"]}):
                with pytest.raises(NoAvailableSourceError):
                    get_loader_cls_with_fallback("fake_unavailable")


# ---------------------------------------------------------------------------
# Issue #50 — loaders that explode in __init__ (e.g. Tushare with no token)
# must not poison the fallback chain.
# ---------------------------------------------------------------------------


class TestInitErrorFallback:
    def test_resolve_loader_skips_init_error(self) -> None:
        with patch.dict(LOADER_REGISTRY, {
            "fake_init_error": _FakeInitErrorLoader,
            "fake_available": _FakeAvailableLoader,
        }, clear=True):
            with patch.dict(FALLBACK_CHAINS, {
                "a_share": ["fake_init_error", "fake_available"],
            }):
                loader = resolve_loader("a_share")
                assert loader.name == "fake_available"

    def test_get_loader_cls_falls_back_when_requested_init_errors(self) -> None:
        with patch.dict(LOADER_REGISTRY, {
            "fake_init_error": _FakeInitErrorLoader,
            "fake_available": _FakeAvailableLoader,
        }, clear=True):
            with patch.dict(FALLBACK_CHAINS, {
                "a_share": ["fake_init_error", "fake_available"],
            }):
                cls = get_loader_cls_with_fallback("fake_init_error")
                assert cls is _FakeAvailableLoader
