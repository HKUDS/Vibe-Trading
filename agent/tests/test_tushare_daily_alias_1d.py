"""Tushare daily fetch must accept lowercase 1d instead of falling into minutes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from backtest.loaders.tushare import DataLoader


def _daily_frame() -> pd.DataFrame:
    idx = pd.to_datetime(["2024-01-02"])
    return pd.DataFrame(
        {
            "open": [1.0],
            "high": [2.0],
            "low": [0.5],
            "close": [1.5],
            "volume": [100.0],
        },
        index=idx,
    )


def test_lowercase_1d_uses_daily_path_not_minutes() -> None:
    """``1d`` used to miss ``!= "1D"`` and return empty from minute freq_map."""
    loader = DataLoader.__new__(DataLoader)
    loader.api = MagicMock()
    daily = _daily_frame()
    with patch.object(loader, "_fetch_daily_frame", return_value=daily) as mock_daily:
        with patch.object(loader, "_fetch_minutes") as mock_mins:
            with patch(
                "backtest.loaders.tushare.cached_loader_fetch",
                side_effect=lambda **kw: kw["fetch"](),
            ):
                out = loader.fetch(
                    ["000001.SZ"], "2024-01-01", "2024-01-31", interval="1d"
                )
    assert set(out) == {"000001.SZ"}
    mock_daily.assert_called()
    mock_mins.assert_not_called()


def test_hour_interval_still_uses_minutes() -> None:
    loader = DataLoader.__new__(DataLoader)
    loader.api = MagicMock()
    with patch.object(loader, "_fetch_minutes", return_value={}) as mock_mins:
        with patch.object(loader, "_fetch_daily_frame") as mock_daily:
            out = loader.fetch(
                ["000001.SZ"], "2024-01-01", "2024-01-31", interval="1H"
            )
    assert out == {}
    mock_mins.assert_called_once()
    mock_daily.assert_not_called()
