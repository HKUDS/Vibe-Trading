"""AKShare a-share fetch must not silently remap unknown intervals to daily."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backtest.loaders.akshare_loader import DataLoader, _INTERVAL_MAP_DAILY


def test_akshare_a_share_rejects_minute_interval() -> None:
    ak = MagicMock()
    loader = DataLoader()
    with pytest.raises(ValueError, match="Unsupported interval"):
        loader._fetch_a_share(ak, "600519.SH", "2026-01-01", "2026-01-31", "1m")
    ak.stock_zh_a_hist.assert_not_called()


def test_akshare_a_share_keeps_supported_monthly(monkeypatch) -> None:
    import pandas as pd

    ak = MagicMock()
    ak.stock_zh_a_hist.return_value = pd.DataFrame(
        {
            "日期": ["2026-01-31"],
            "开盘": [1.0],
            "最高": [1.0],
            "最低": [1.0],
            "收盘": [1.0],
            "成交量": [1.0],
        }
    )
    loader = DataLoader()
    monkeypatch.setattr(loader, "_normalize", lambda df, date_col="日期": df)
    loader._fetch_a_share(ak, "600519.SH", "2026-01-01", "2026-01-31", "1M")
    assert ak.stock_zh_a_hist.call_args.kwargs["period"] == _INTERVAL_MAP_DAILY["1M"]
