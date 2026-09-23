"""Tests for loader registry and fallback chain logic."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
import importlib
from threading import Event
from types import ModuleType
from unittest.mock import patch

import pytest

from backtest.loaders import registry
from backtest.loaders.base import DataLoaderProtocol, NoAvailableSourceError
from backtest.loaders.registry import (
    _ensure_registered,
    FALLBACK_CHAINS,
    LOADER_REGISTRY,
    VALID_SOURCES,
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


class _FakeLocalLoader:
    """Mimics the real local loader: broad ``markets``, unavailable when the
    user has no Data Bridge config."""

    name = "local"
    markets = {"a_share", "us_equity", "crypto"}
    requires_auth = False

    def is_available(self) -> bool:
        return False

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


@pytest.mark.parametrize("entrypoint", ["market", "source"])
def test_concurrent_cold_readers_wait_for_registration(
    monkeypatch: pytest.MonkeyPatch, entrypoint: str
) -> None:
    """Cold readers must wait for one complete import pass, including skips."""
    importing = Event()
    release = Event()
    reader_started = Event()
    imports: list[str] = []
    real_import = importlib.import_module

    def controlled_import(name: str, package: str | None = None) -> ModuleType:
        if not name.startswith("backtest.loaders."):
            return real_import(name, package)
        imports.append(name)
        if name == "backtest.loaders.tushare":
            importing.set()
            if not release.wait(5):
                raise RuntimeError("loader import was never released")
        if name == "backtest.loaders.okx":
            raise ImportError("optional dependency unavailable")
        if name == "backtest.loaders.local_loader":
            register(_FakeAvailableLoader)
        return ModuleType(name)

    def read_loader() -> type:
        reader_started.set()
        if entrypoint == "source":
            return get_loader_cls_with_fallback(_FakeAvailableLoader.name)
        return type(resolve_loader("a_share"))

    monkeypatch.setattr(registry, "_registered", False)
    monkeypatch.setattr(registry, "LOADER_REGISTRY", {})
    monkeypatch.setitem(FALLBACK_CHAINS, "a_share", [_FakeAvailableLoader.name])
    monkeypatch.setattr(importlib, "import_module", controlled_import)

    # Keep initialization inside its first import while a public reader enters.
    # Always release the importer before joining threads or restoring patches.
    with ThreadPoolExecutor(max_workers=2) as pool:
        initializer = pool.submit(_ensure_registered)
        try:
            assert importing.wait(5)
            reader = pool.submit(read_loader)
            assert reader_started.wait(5)
            with pytest.raises(TimeoutError):
                reader.result(timeout=0.1)
        finally:
            release.set()
        initializer.result(timeout=5)
        assert reader.result(timeout=5) is _FakeAvailableLoader

    assert registry._registered is True
    assert len(imports) == len(set(imports)), "initialization ran more than once"
    completed_imports = imports[:]
    assert read_loader() is _FakeAvailableLoader
    assert imports == completed_imports, "warm readers must not repeat imports"


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
        expected = {
            "a_share",
            "us_equity",
            "hk_equity",
            "india_equity",
            "kr_equity",
            "ca_equity",
            "ar_equity",
            "uk_equity",
            "vietnam_equity",
            "crypto",
            "futures",
            "fund",
            "macro",
            "forex",
            "index",
        }
        assert expected == set(FALLBACK_CHAINS.keys())

    def test_canada_chain_uses_only_compatible_sources(self) -> None:
        assert FALLBACK_CHAINS["ca_equity"] == ["yahoo", "yfinance", "local"]

    def test_argentina_chain_uses_only_compatible_sources(self) -> None:
        assert FALLBACK_CHAINS["ar_equity"] == ["yahoo", "yfinance", "local"]

    def test_vietnam_chain_uses_only_compatible_sources(self) -> None:
        assert FALLBACK_CHAINS["vietnam_equity"] == ["yahoo", "yfinance", "local"]

    def test_uk_chain_uses_only_compatible_sources(self) -> None:
        assert FALLBACK_CHAINS["uk_equity"] == ["yahoo", "yfinance", "local"]

    def test_chains_are_non_empty(self) -> None:
        for market, chain in FALLBACK_CHAINS.items():
            assert len(chain) > 0, f"Fallback chain for {market} is empty"

    def test_crypto_chain_includes_yfinance_fallback(self) -> None:
        """yfinance is a fallback for crypto when OKX, Binance and CCXT fail."""
        assert "yfinance" in FALLBACK_CHAINS["crypto"]
        # OKX, Binance and CCXT should be preferred in that order
        assert FALLBACK_CHAINS["crypto"][:3] == ["okx", "binance", "ccxt"]

    def test_chains_ordered_by_ip_ban_risk(self) -> None:
        """Equity chains lead with throttle-tolerant public sources and trail
        with key-gated REST fallbacks, in the exact reviewed order."""
        assert FALLBACK_CHAINS["a_share"] == [
            "tencent",
            "mootdx",
            "eastmoney",
            "baostock",
            "akshare",
            "tushare",
            "gildata",
            "local",
        ]
        assert FALLBACK_CHAINS["us_equity"] == [
            "yahoo",
            "stooq",
            "sina",
            "eastmoney",
            "yfinance",
            "tiingo",
            "fmp",
            "finnhub",
            "alphavantage",
            "longbridge",
            "akshare",
            "local",
        ]
        assert FALLBACK_CHAINS["hk_equity"] == [
            "tencent",
            "eastmoney",
            "yahoo",
            "futu",
            "akshare",
            "yfinance",
            "tushare",
            "longbridge",
            "local",
        ]

    def test_us_equity_includes_sina_fallback(self) -> None:
        """'sina' must be reachable for US equities (after yahoo/stooq) so it is
        not a dead config source that no chain can ever select."""
        chain = FALLBACK_CHAINS["us_equity"]
        assert "sina" in chain
        assert chain.index("sina") > chain.index("yahoo")
        assert chain.index("sina") > chain.index("stooq")

    def test_a_share_includes_baostock(self) -> None:
        """'baostock' must remain a reachable A-share fallback."""
        assert "baostock" in FALLBACK_CHAINS["a_share"]

    def test_unchanged_chains_preserved(self) -> None:
        """crypto/fund/macro/forex chains must be left untouched."""
        assert FALLBACK_CHAINS["crypto"] == [
            "okx",
            "binance",
            "ccxt",
            "yfinance",
            "local",
        ]
        assert FALLBACK_CHAINS["fund"] == ["tushare", "akshare", "local"]
        assert FALLBACK_CHAINS["macro"] == ["akshare", "tushare", "local"]
        # mt5 heads the forex chain (terminal feed when attached), degrading to
        # the previous chain unchanged.
        assert FALLBACK_CHAINS["forex"] == ["mt5", "akshare", "yfinance", "local"]

    def test_futures_chain_leads_with_a_source_that_implements_futures(self) -> None:
        """#1395 — tushare led this chain while implementing no futures path.

        ``resolve_loader`` walks FALLBACK_CHAINS and never consults a loader's
        ``markets`` set, so a loader listed here is asked for the market
        whether or not it declares it. tushare would have been constructed,
        found available on any TUSHARE_TOKEN, and returned an empty frame from
        the A-share ``daily()`` endpoint before akshare was ever reached.
        """
        assert FALLBACK_CHAINS["futures"] == ["akshare", "local"]
        assert "tushare" not in FALLBACK_CHAINS["futures"]

    def test_every_futures_chain_member_declares_the_market(self) -> None:
        """The invariant #1395 broke, stated directly.

        Written as a closure over the chain rather than a literal, so adding a
        source that does not serve futures fails here instead of at runtime.
        """
        _ensure_registered()
        for name in FALLBACK_CHAINS["futures"]:
            loader_cls = LOADER_REGISTRY.get(name)
            assert loader_cls is not None, f"{name} is in the chain but not registered"
            assert (
                "futures" in loader_cls.markets
            ), f"{name} leads the futures chain without declaring the market"

    def test_tickerall_is_explicit_only_never_a_fallback(self) -> None:
        """TickerAll is a valid explicit source but must NEVER join an automatic
        fallback chain. It reads a user's own broker account over a hosted API, so
        it runs only on a deliberate ``source="tickerall"`` request - never silently
        as a degradation target for another source. This guards that contract."""
        assert "tickerall" in VALID_SOURCES
        for market, chain in FALLBACK_CHAINS.items():
            assert (
                "tickerall" not in chain
            ), f"tickerall must not be in the {market} fallback chain"


# ---------------------------------------------------------------------------
# VALID_SOURCES
# ---------------------------------------------------------------------------


class TestValidSources:
    def test_includes_new_loaders(self) -> None:
        """Newly registered loaders must be accepted config sources."""
        new_sources = {
            "eastmoney",
            "sina",
            "stooq",
            "yahoo",
            "finnhub",
            "alphavantage",
            "tiingo",
            "fmp",
        }
        assert new_sources <= VALID_SOURCES

    def test_includes_binance(self) -> None:
        """Binance was added as a dedicated crypto source alongside OKX so the
        market_data fallback chain can fall through without aliasing CCXT. A
        config with ``source: binance`` must validate against VALID_SOURCES."""
        assert "binance" in VALID_SOURCES

    def test_covers_all_registered_loaders(self) -> None:
        """Every registered loader name must be an accepted config source so a
        new loader can never be silently rejected by config validation."""
        from backtest.loaders.registry import _ensure_registered

        _ensure_registered()
        missing = set(LOADER_REGISTRY) - VALID_SOURCES
        assert not missing, f"loaders missing from VALID_SOURCES: {missing}"


# ---------------------------------------------------------------------------
# resolve_loader
# ---------------------------------------------------------------------------


class TestResolveLoader:
    def test_returns_first_available(self) -> None:
        with patch.dict(
            LOADER_REGISTRY,
            {
                "fake_unavailable": _FakeUnavailableLoader,
                "fake_available": _FakeAvailableLoader,
            },
            clear=True,
        ):
            with patch.dict(
                FALLBACK_CHAINS,
                {
                    "a_share": ["fake_unavailable", "fake_available"],
                },
            ):
                loader = resolve_loader("a_share")
                assert loader.name == "fake_available"

    def test_raises_when_none_available(self) -> None:
        with patch.dict(
            LOADER_REGISTRY,
            {
                "fake_unavailable": _FakeUnavailableLoader,
            },
            clear=True,
        ):
            with patch.dict(
                FALLBACK_CHAINS,
                {
                    "a_share": ["fake_unavailable"],
                },
            ):
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
        with patch.dict(
            LOADER_REGISTRY,
            {
                "fake_available": _FakeAvailableLoader,
            },
            clear=True,
        ):
            cls = get_loader_cls_with_fallback("fake_available")
            assert cls is _FakeAvailableLoader

    def test_falls_back_when_unavailable(self) -> None:
        with patch.dict(
            LOADER_REGISTRY,
            {
                "fake_unavailable": _FakeUnavailableLoader,
                "fake_available": _FakeAvailableLoader,
            },
            clear=True,
        ):
            with patch.dict(
                FALLBACK_CHAINS,
                {
                    "a_share": ["fake_unavailable", "fake_available"],
                },
            ):
                cls = get_loader_cls_with_fallback("fake_unavailable")
                assert cls is _FakeAvailableLoader

    def test_unknown_source_raises(self) -> None:
        with patch.dict(LOADER_REGISTRY, {}, clear=True):
            with pytest.raises(NoAvailableSourceError):
                get_loader_cls_with_fallback("nonexistent")

    def test_no_fallback_raises(self) -> None:
        with patch.dict(
            LOADER_REGISTRY,
            {
                "fake_unavailable": _FakeUnavailableLoader,
            },
            clear=True,
        ):
            with patch.dict(FALLBACK_CHAINS, {"a_share": ["fake_unavailable"]}):
                with pytest.raises(NoAvailableSourceError):
                    get_loader_cls_with_fallback("fake_unavailable")

    def test_explicit_local_does_not_fall_through_to_network(self) -> None:
        """An explicit unavailable 'local' request must raise a clear error, never
        silently degrade to an unrelated network loader via its broad markets."""
        with patch.dict(
            LOADER_REGISTRY,
            {
                "local": _FakeLocalLoader,
                "fake_available": _FakeAvailableLoader,  # available a_share network src
            },
            clear=True,
        ):
            # Even though a network loader is available for one of local's markets,
            # the explicit 'local' request must not borrow it.
            with patch.dict(FALLBACK_CHAINS, {"a_share": ["fake_available"]}):
                with pytest.raises(NoAvailableSourceError) as excinfo:
                    get_loader_cls_with_fallback("local")
        msg = str(excinfo.value)
        assert "local" in msg
        # The error must point the user at the Data Bridge config, not a network hop.
        assert "data-bridge" in msg.lower() or "config" in msg.lower()

    def test_explicit_tickerall_does_not_fall_through_to_network(self) -> None:
        """An explicit unavailable 'tickerall' must raise, never silently degrade to a
        public forex source (akshare/yfinance) via its markets — it reads the user's own
        broker account, so a missing key is a config error to surface, not paper over.
        """

        class _FakeTickerall:
            name = "tickerall"
            markets = {"forex"}
            requires_auth = True

            def is_available(self) -> bool:
                return False

            def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
                return {}

        with patch.dict(
            LOADER_REGISTRY,
            {
                "tickerall": _FakeTickerall,
                "fake_available": _FakeAvailableLoader,  # an available loader listed in the forex chain
            },
            clear=True,
        ):
            with patch.dict(FALLBACK_CHAINS, {"forex": ["fake_available"]}):
                with pytest.raises(NoAvailableSourceError) as excinfo:
                    get_loader_cls_with_fallback("tickerall")
        msg = str(excinfo.value)
        assert "tickerall" in msg
        assert "TICKERALL_API_KEY" in msg


# ---------------------------------------------------------------------------
# Issue #50 — loaders that explode in __init__ (e.g. Tushare with no token)
# must not poison the fallback chain.
# ---------------------------------------------------------------------------


class TestInitErrorFallback:
    def test_resolve_loader_skips_init_error(self) -> None:
        with patch.dict(
            LOADER_REGISTRY,
            {
                "fake_init_error": _FakeInitErrorLoader,
                "fake_available": _FakeAvailableLoader,
            },
            clear=True,
        ):
            with patch.dict(
                FALLBACK_CHAINS,
                {
                    "a_share": ["fake_init_error", "fake_available"],
                },
            ):
                loader = resolve_loader("a_share")
                assert loader.name == "fake_available"

    def test_get_loader_cls_falls_back_when_requested_init_errors(self) -> None:
        with patch.dict(
            LOADER_REGISTRY,
            {
                "fake_init_error": _FakeInitErrorLoader,
                "fake_available": _FakeAvailableLoader,
            },
            clear=True,
        ):
            with patch.dict(
                FALLBACK_CHAINS,
                {
                    "a_share": ["fake_init_error", "fake_available"],
                },
            ):
                cls = get_loader_cls_with_fallback("fake_init_error")
                assert cls is _FakeAvailableLoader
