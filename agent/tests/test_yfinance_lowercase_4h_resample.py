"""yfinance loader must resample to 4-hour bars for lowercase ``4h`` too.

``_to_yfinance_interval`` already treats ``4h``/``4H`` the same when picking
the Yahoo interval to download (see test_yfinance_lowercase_4h_1w.py), but
``_normalize_frame``'s resample trigger was a case-sensitive ``== "4H"``
check. A request for ``interval="4h"`` therefore fetched hourly bars from
Yahoo and then silently skipped the resample step, returning raw 1-hour
bars mislabeled as 4-hour data.
"""

from __future__ import annotations

import pandas as pd

from backtest.loaders.yfinance_loader import _normalize_frame


def _hourly_frame() -> pd.DataFrame:
    """Eight sequential 1-hour OHLCV bars starting at midnight."""
    index = pd.date_range("2024-01-01 00:00", periods=8, freq="1h")
    values = list(range(1, 9))
    return pd.DataFrame(
        {
            "open": values,
            "high": [v + 0.5 for v in values],
            "low": [v - 0.5 for v in values],
            "close": values,
            "volume": [100] * 8,
        },
        index=index,
    )


def test_uppercase_4H_resamples_hourly_bars_to_four_hour() -> None:
    normalized = _normalize_frame(_hourly_frame(), "4H")
    assert len(normalized) == 2


def test_lowercase_4h_also_resamples_hourly_bars_to_four_hour() -> None:
    """Regression for the case-sensitivity bug: lowercase ``4h`` must resample
    identically to ``4H`` instead of passing raw hourly bars through."""
    normalized = _normalize_frame(_hourly_frame(), "4h")
    assert len(normalized) == 2


def test_mixed_case_4h_also_resamples() -> None:
    normalized = _normalize_frame(_hourly_frame(), "4h ")
    assert len(normalized) == 2


def test_other_intervals_are_not_resampled() -> None:
    normalized = _normalize_frame(_hourly_frame(), "1H")
    assert len(normalized) == 8
