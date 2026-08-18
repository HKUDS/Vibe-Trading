"""Tests for Vietnam (HOSE) equity data routing via Yahoo.

All network access is mocked at the loader's ``yahoo_client.get_chart`` import
site; nothing here reaches Yahoo.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from backtest.engines._market_hooks import _detect_market
from backtest.loaders.registry import FALLBACK_CHAINS
from backtest.loaders.yahoo_client import map_symbol
from backtest.loaders.yahoo_loader import DataLoader, _is_supported
from backtest.loaders.yfinance_loader import _to_yfinance_symbol


class TestSymbolGating:
    """``.VN`` is accepted alongside the other equity suffixes."""

    def test_vn_suffix_supported(self) -> None:
        assert _is_supported("VIC.VN") is True
        assert _is_supported("vic.vn") is True

    def test_vn_does_not_collide_with_tsx_venture(self) -> None:
        # ``.V`` (TSXV) and ``.VN`` (HOSE) are distinct suffixes; neither may
        # swallow the other.
        assert _is_supported("PNG.V") is True
        assert _detect_market("PNG.V") == "ca_equity"
        assert _detect_market("VIC.VN") != "ca_equity"


class TestSymbolMapping:
    """Both Yahoo paths carry ``.VN`` verbatim — no conversion."""

    def test_yahoo_client_passes_vn_through(self) -> None:
        assert map_symbol("VIC.VN") == "VIC.VN"

    def test_yfinance_passes_vn_through(self) -> None:
        assert _to_yfinance_symbol("VIC.VN") == "VIC.VN"


class TestFallbackChain:
    def test_vietnam_chain(self) -> None:
        assert FALLBACK_CHAINS["vietnam_equity"] == ["yahoo", "yfinance", "local"]

    def test_yahoo_declares_vietnam_market(self) -> None:
        assert "vietnam_equity" in DataLoader.markets


class TestFetch:
    """The loader returns a normalized frame for a HOSE symbol."""

    def _chart_rows(self) -> list[dict]:
        # 2024-01-02 .. 2024-01-04 UTC midnights, VND prices.
        return [
            {"trade_date": 1704153600, "open": 42.0, "high": 43.0,
             "low": 41.5, "close": 42.5, "volume": 1_000_000},
            {"trade_date": 1704240000, "open": 42.5, "high": 44.0,
             "low": 42.0, "close": 43.8, "volume": 1_200_000},
            {"trade_date": 1704326400, "open": 43.8, "high": 44.5,
             "low": 43.0, "close": 44.2, "volume": 900_000},
        ]

    def test_fetch_returns_ohlcv_frame(self) -> None:
        with patch(
            "backtest.loaders.yahoo_loader.yahoo_client.get_chart",
            return_value=self._chart_rows(),
        ) as chart:
            result = DataLoader().fetch(
                ["VIC.VN"], "2024-01-01", "2024-01-31", interval="1D"
            )

        assert "VIC.VN" in result
        frame = result["VIC.VN"]
        assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
        assert len(frame) == 3
        assert isinstance(frame.index, pd.DatetimeIndex)
        assert frame["close"].iloc[-1] == 44.2
        # The symbol reaches the client unchanged.
        assert chart.call_args.args[0] == "VIC.VN"

    def test_unlisted_symbol_is_omitted_not_raised(self) -> None:
        # HNX/UPCOM are unsupported on Yahoo: no rows, no exception.
        with patch(
            "backtest.loaders.yahoo_loader.yahoo_client.get_chart",
            return_value=[],
        ):
            result = DataLoader().fetch(
                ["PVS.VN"], "2024-01-01", "2024-01-31", interval="1D"
            )

        assert result == {} or result.get("PVS.VN", pd.DataFrame()).empty
