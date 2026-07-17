"""Tests for pykrx_loader: symbol mapping and frame normalization.

Unit-level only — no network access and no ``pykrx`` dependency: the
normalization path is exercised through ``_normalize`` with synthetic
pykrx-shaped frames (Korean column names, date index).
"""

from __future__ import annotations

import pandas as pd

from backtest.loaders.pykrx_loader import _normalize, map_symbol


class TestMapSymbol:
    """``005930.KS`` / ``247540.KQ`` -> bare 6-digit pykrx ticker."""

    def test_kospi_suffix_stripped(self) -> None:
        assert map_symbol("005930.KS") == "005930"

    def test_kosdaq_suffix_stripped(self) -> None:
        assert map_symbol("247540.KQ") == "247540"

    def test_case_and_whitespace(self) -> None:
        assert map_symbol(" 005930.ks ") == "005930"


def _pykrx_frame() -> pd.DataFrame:
    """Synthetic frame in pykrx's native shape (Korean columns, date index)."""
    idx = pd.to_datetime(["2024-04-02", "2024-04-01"])  # deliberately unsorted
    return pd.DataFrame(
        {
            "시가": [102.0, 100.0],
            "고가": [103.0, 101.0],
            "저가": [101.0, 99.0],
            "종가": [102.5, 100.5],
            "거래량": [20_000, 10_000],
            "등락률": [1.99, 0.5],  # extra pykrx column: must be dropped
        },
        index=idx,
    )


class TestNormalize:
    def test_renames_sorts_and_selects_ohlcv(self) -> None:
        out = _normalize(_pykrx_frame())
        assert out is not None
        assert list(out.columns) == ["open", "high", "low", "close", "volume"]
        assert out.index.name == "trade_date"
        assert out.index.is_monotonic_increasing
        assert out["close"].iloc[-1] == 102.5
        assert all(dtype.kind == "f" for dtype in out.dtypes)

    def test_none_and_empty_input(self) -> None:
        assert _normalize(None) is None
        assert _normalize(pd.DataFrame()) is None

    def test_missing_columns_rejected(self) -> None:
        frame = _pykrx_frame().drop(columns=["종가"])
        assert _normalize(frame) is None

    def test_all_nan_price_rows_dropped(self) -> None:
        frame = _pykrx_frame()
        frame.loc[:, ["시가", "고가", "저가", "종가"]] = float("nan")
        assert _normalize(frame) is None
