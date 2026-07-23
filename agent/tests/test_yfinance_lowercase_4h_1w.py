"""yfinance interval map must not leave lowercase 4h/1w as invalid Yahoo tokens."""

from __future__ import annotations

from backtest.loaders.yfinance_loader import _to_yfinance_interval


def test_lowercase_4h_maps_like_4H() -> None:
    """``4h`` used to fall through to ``.lower()`` and become invalid ``4h``."""
    assert _to_yfinance_interval("4H") == "1h"
    assert _to_yfinance_interval("4h") == "1h"


def test_lowercase_1w_maps_like_1W() -> None:
    """``1w`` used to become ``1w``; yfinance expects ``1wk``."""
    assert _to_yfinance_interval("1W") == "1wk"
    assert _to_yfinance_interval("1w") == "1wk"


def test_month_vs_minute_case_preserved() -> None:
    assert _to_yfinance_interval("1M") == "1mo"
    assert _to_yfinance_interval("1m") == "1m"
