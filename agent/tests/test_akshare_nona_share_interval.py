"""AKShare US/HK/ETF/forex must not return daily bars for intraday intervals."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backtest.loaders.akshare_loader import DataLoader


def _us_daily_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "日期": ["2024-01-02", "2024-01-03"],
            "开盘": [1.0, 2.0],
            "最高": [2.0, 3.0],
            "最低": [0.5, 1.0],
            "收盘": [1.5, 2.5],
            "成交量": [10.0, 20.0],
        }
    )


def test_us_intraday_interval_does_not_hit_daily_endpoint() -> None:
    """Runner ``1H`` used to fetch stock_us_hist daily bars under a 1H cache key."""
    ak = MagicMock()
    ak.stock_us_hist.return_value = _us_daily_frame()
    loader = DataLoader()
    with patch.dict("sys.modules", {"akshare": ak}):
        with pytest.raises(ValueError, match="Unsupported interval"):
            loader._fetch_one("AAPL.US", "2024-01-01", "2024-01-31", "1H")
    ak.stock_us_hist.assert_not_called()


def test_hk_four_hour_interval_rejected() -> None:
    ak = MagicMock()
    loader = DataLoader()
    with patch.dict("sys.modules", {"akshare": ak}):
        with pytest.raises(ValueError, match="Unsupported interval"):
            loader._fetch_one("0700.HK", "2024-01-01", "2024-01-31", "4H")
    ak.stock_hk_hist.assert_not_called()


def test_etf_intraday_interval_rejected() -> None:
    ak = MagicMock()
    loader = DataLoader()
    with patch.dict("sys.modules", {"akshare": ak}):
        with pytest.raises(ValueError, match="Unsupported interval"):
            loader._fetch_one("510050.SH", "2024-01-01", "2024-01-31", "1H")
    ak.fund_etf_hist_sina.assert_not_called()


def test_us_daily_interval_still_fetches() -> None:
    ak = MagicMock()
    ak.stock_us_hist.return_value = _us_daily_frame()
    loader = DataLoader()
    with patch.dict("sys.modules", {"akshare": ak}):
        frame = loader._fetch_one("AAPL.US", "2024-01-01", "2024-01-31", "1D")
    assert frame is not None
    assert len(frame) == 2
    ak.stock_us_hist.assert_called()
