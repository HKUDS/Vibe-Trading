"""Local loader resample rules must accept connector-style hour aliases."""

from __future__ import annotations

import pandas as pd

from backtest.loaders.local_loader import _RESAMPLE_RULES, _resample_to_interval


def _hourly_frame() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=8, freq="h")
    return pd.DataFrame(
        {
            "open": range(8),
            "high": range(8),
            "low": range(8),
            "close": range(8),
            "volume": range(8),
        },
        index=idx,
    )


def test_lowercase_1h_matches_project_token() -> None:
    assert _RESAMPLE_RULES["1h"] == _RESAMPLE_RULES["1H"] == "1h"


def test_lowercase_4h_resamples_like_4H() -> None:
    """``4h`` used to miss the map and return native hourly bars unchanged."""
    df = _hourly_frame()
    out_upper = _resample_to_interval(df, "4H", "X")
    out_lower = _resample_to_interval(df, "4h", "X")
    assert len(out_upper) == 2
    assert len(out_lower) == 2
    assert list(out_lower.index) == list(out_upper.index)
