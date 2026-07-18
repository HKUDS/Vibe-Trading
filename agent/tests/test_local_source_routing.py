"""Tests that an explicit local data source is honored end to end.

Covers the two halves of the bug:
1. Engine routing follows the instrument market, not the loader name
   (local AAPL.US -> GlobalEquityEngine, not CryptoEngine).
2. Benchmark fetch goes through the configured source's loader instead of
   unconditionally creating a yfinance loader.
"""

from __future__ import annotations

from typing import Dict, List

import pandas as pd
import pytest

from backtest.benchmark import resolve_benchmark
from backtest.engines.crypto import CryptoEngine
from backtest.engines.global_equity import GlobalEquityEngine
from backtest.runner import _create_market_engine


class TestLocalSourceEngineRouting:
    def test_local_us_equity_routes_to_global_equity_engine(self) -> None:
        engine = _create_market_engine("local", {"initial_cash": 100_000}, ["AAPL.US"])
        assert isinstance(engine, GlobalEquityEngine)

    def test_local_hk_equity_routes_to_global_equity_engine(self) -> None:
        engine = _create_market_engine("local", {"initial_cash": 100_000}, ["00700.HK"])
        assert isinstance(engine, GlobalEquityEngine)

    def test_local_crypto_still_routes_to_crypto_engine(self) -> None:
        engine = _create_market_engine("local", {"initial_cash": 100_000}, ["BTC-USDT"])
        assert isinstance(engine, CryptoEngine)


class _FakeLoader:
    """Loader stub returning a fixed close series for any requested code."""

    name = "local"

    def __init__(self, closes: List[float]) -> None:
        self._closes = closes
        self.fetched: List[str] = []

    def fetch(
        self, codes: List[str], start_date: str, end_date: str, **kwargs: object,
    ) -> Dict[str, pd.DataFrame]:
        self.fetched.extend(codes)
        index = pd.date_range("2023-01-03", periods=len(self._closes), freq="D")
        return {c: pd.DataFrame({"close": self._closes}, index=index) for c in codes}


class _EmptyLoader:
    name = "local"

    def fetch(self, *args: object, **kwargs: object) -> Dict[str, pd.DataFrame]:
        return {}


class _RaisingLoader:
    name = "local"

    def fetch(self, *args: object, **kwargs: object) -> Dict[str, pd.DataFrame]:
        raise RuntimeError("boom")


class _SwappedNetworkLoader:
    """Simulates fetch_data_map's runtime fallback swapping in a network
    loader while config['source'] still says local."""

    name = "yahoo"

    def fetch(self, *args: object, **kwargs: object) -> Dict[str, pd.DataFrame]:
        raise AssertionError("network loader must not be fetched for source=local")


class TestBenchmarkLoaderForwarding:
    def test_explicit_source_loader_is_used_instead_of_yfinance(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _no_network() -> None:
            raise AssertionError("yfinance loader must not be created")

        monkeypatch.setattr("backtest.benchmark.YfinanceLoader", _no_network)

        loader = _FakeLoader([100.0, 110.0])
        result = resolve_benchmark(
            strategy_codes=["AAPL.US"],
            source="local",
            start_date="2023-01-03",
            end_date="2023-01-04",
            explicit="AAPL.US",
            loader=loader,
        )

        assert result is not None
        assert result.ticker == "AAPL.US"
        assert loader.fetched == ["AAPL.US"]
        assert result.total_ret == pytest.approx(0.1)

    @pytest.mark.parametrize(
        "loader", [_EmptyLoader(), _RaisingLoader(), _SwappedNetworkLoader(), None],
    )
    def test_local_source_fails_closed_without_yfinance(
        self, monkeypatch: pytest.MonkeyPatch, loader: object,
    ) -> None:
        """source=local must never touch the network, even when the local
        loader yields no benchmark data, raises, or was silently swapped for
        a network loader by fetch_data_map's runtime fallback chain."""

        def _no_network() -> None:
            raise AssertionError("yfinance loader must not be created")

        monkeypatch.setattr("backtest.benchmark.YfinanceLoader", _no_network)

        result = resolve_benchmark(
            strategy_codes=["AAPL.US"],
            source="local",
            start_date="2023-01-03",
            end_date="2023-01-04",
            explicit="SPY",
            loader=loader,
        )

        assert result is None

    def test_non_local_source_falls_back_to_yfinance_when_no_data(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fallback = _FakeLoader([100.0, 105.0])
        monkeypatch.setattr("backtest.benchmark.YfinanceLoader", lambda: fallback)

        result = resolve_benchmark(
            strategy_codes=["600519.SH"],
            source="tushare",
            start_date="2023-01-03",
            end_date="2023-01-04",
            explicit="SPY",
            loader=_EmptyLoader(),
        )

        assert result is not None
        assert fallback.fetched == ["SPY"]
        assert result.total_ret == pytest.approx(0.05)

    def test_no_loader_keeps_yfinance_default(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fallback = _FakeLoader([100.0, 102.0])
        monkeypatch.setattr("backtest.benchmark.YfinanceLoader", lambda: fallback)

        result = resolve_benchmark(
            strategy_codes=["AAPL.US"],
            source="auto",
            start_date="2023-01-03",
            end_date="2023-01-04",
            explicit="SPY",
        )

        assert result is not None
        assert fallback.fetched == ["SPY"]
