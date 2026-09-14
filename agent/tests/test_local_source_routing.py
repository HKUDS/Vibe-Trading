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
from backtest.engines.china_a import ChinaAEngine
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

    def test_local_canadian_equity_routes_to_canadian_global_rules(self) -> None:
        engine = _create_market_engine("local", {"initial_cash": 100_000}, ["TD.TO"])
        assert isinstance(engine, GlobalEquityEngine)
        assert engine.market == "ca"

    def test_local_crypto_still_routes_to_crypto_engine(self) -> None:
        engine = _create_market_engine("local", {"initial_cash": 100_000}, ["BTC-USDT"])
        assert isinstance(engine, CryptoEngine)

    def test_local_a_share_routes_to_china_a_engine(self) -> None:
        engine = _create_market_engine("local", {"initial_cash": 100_000}, ["000001.SZ"])
        assert isinstance(engine, ChinaAEngine)

    # Sources with no Wave-1 branch in ``_create_market_engine``. Each is a
    # registered A-share source that a caller can name explicitly -- the
    # data-routing skill lists baostock/tencent/mootdx/eastmoney as A-share
    # sources, and ``skills/mootdx/SKILL.md`` documents
    # ``run(strategy=..., source="mootdx")``. Naming any of them used to route
    # A-shares to CryptoEngine: no stamp tax, no T+1, no price limits, no
    # 100-share lots, and an 8-hourly perpetual funding fee charged against
    # the position. ``"auto"`` is branchless here too -- the runner resolves it
    # through ``_detect_primary_source`` before calling, but this function must
    # not depend on that.
    @pytest.mark.parametrize(
        "source",
        ["local", "tencent", "eastmoney", "baostock", "mootdx", "sina", "stooq",
         "yahoo", "auto"],
    )
    def test_branchless_sources_route_a_share_to_china_a_engine(
        self, source: str,
    ) -> None:
        engine = _create_market_engine(source, {"initial_cash": 100_000}, ["600519.SH"])
        assert isinstance(engine, ChinaAEngine)

    @pytest.mark.parametrize("source", ["tushare", "akshare"])
    def test_branching_sources_keep_routing_a_share_to_china_a_engine(
        self, source: str,
    ) -> None:
        """The sources that already worked must keep working."""
        engine = _create_market_engine(source, {"initial_cash": 100_000}, ["600519.SH"])
        assert isinstance(engine, ChinaAEngine)


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
    def test_canadian_equity_uses_canadian_benchmark(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fallback = _FakeLoader([100.0, 103.0])
        monkeypatch.setattr("backtest.benchmark.YfinanceLoader", lambda: fallback)

        result = resolve_benchmark(
            strategy_codes=["BBD-B.TO"],
            source="yahoo",
            start_date="2023-01-03",
            end_date="2023-01-04",
        )

        assert result is not None
        assert result.ticker == "XIC.TO"
        assert fallback.fetched == ["XIC.TO"]

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


class TestNoNetworkFallbackIsPerSymbolToo:
    """``_NO_NETWORK_FALLBACK_SOURCES`` 的文档说显式点名的源不可用时是用户必须
    看到的配置问题，不该用 Yahoo/Tencent 的取数糊过去。但那个集合此前只在
    loader *整体* 不可用时被查；按标的的回落循环对所有源一视同仁。"""

    @staticmethod
    def _config(**over):
        cfg = {"codes": ["AAPL.US", "MSFT.US"], "start_date": "2023-01-03",
               "end_date": "2023-01-04", "source": "local"}
        cfg.update(over)
        return cfg

    def test_missing_symbol_raises_instead_of_reaching_the_network(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from backtest.loaders.base import NoAvailableSourceError
        from backtest.runner import fetch_data_map

        served = _FakeLoader([100.0, 101.0])

        def _only_first(codes, *a, **k):
            return {"AAPL.US": served.fetch(["AAPL.US"], *a, **k)["AAPL.US"]}

        monkeypatch.setattr(
            "backtest.runner._get_loader",
            lambda source: lambda: type("L", (), {"name": "local", "fetch": staticmethod(_only_first)})(),
        )
        monkeypatch.setattr(
            "backtest.runner.LOADER_REGISTRY",
            {"yahoo": lambda: (_ for _ in ()).throw(AssertionError("must not fall back"))},
        )

        with pytest.raises(NoAvailableSourceError, match="MSFT.US"):
            fetch_data_map(self._config())

    def test_a_fallback_source_still_reaches_the_chain(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """不在名单里的源行为不变：缺票仍走回落链。

        用一个可控的假 loader 顶替链上的 yahoo，绝不触网——断言的是「回落被
        尝试了」，不是「网络能通」。
        """
        from backtest.runner import fetch_data_map

        index = pd.date_range("2023-01-03", periods=2, freq="D")
        bars = pd.DataFrame({"open": [1.0, 1.0], "high": [1.0, 1.0],
                             "low": [1.0, 1.0], "close": [1.0, 1.0],
                             "volume": [1.0, 1.0]}, index=index)
        bars.index.name = "trade_date"

        class _Primary:
            name = "tencent"

            def fetch(self, codes, *a, **k):
                return {"AAPL.US": bars.copy()}

        reached: list[str] = []

        class _Fallback:
            name = "yahoo"

            def is_available(self):
                return True

            def fetch(self, codes, *a, **k):
                reached.extend(codes)
                return {c: bars.copy() for c in codes}

        monkeypatch.setattr("backtest.runner._get_loader", lambda source: _Primary)
        monkeypatch.setattr("backtest.runner.LOADER_REGISTRY", {"yahoo": _Fallback})
        monkeypatch.setattr("backtest.runner.FALLBACK_CHAINS", {"us_equity": ["yahoo"]})

        result = fetch_data_map(self._config(source="tencent"))

        assert reached == ["MSFT.US"]
        assert sorted(result.data_map) == ["AAPL.US", "MSFT.US"]
