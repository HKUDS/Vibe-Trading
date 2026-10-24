"""OKX history-candles pages hold at most 100 rows, so paging must not stop
after the first full history page."""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd

import backtest.loaders.okx as okx
from backtest.loaders.okx import DataLoader

_DAY_MS = 86_400_000
_START = pd.Timestamp("2022-01-01")
_END = pd.Timestamp("2022-12-31")
_START_TS = int(_START.timestamp() * 1000)
_END_TS = int((_END + pd.Timedelta(days=1)).timestamp() * 1000)


class _HistoryVenue:
    """Daily candles served newest first, capped like OKX's history endpoint."""

    def __init__(self, cap: int) -> None:
        self.cap = cap
        self.limits: list[str] = []

    def __call__(self, url, params=None, timeout=None):
        self.limits.append(params["limit"])
        after = int(params["after"])
        size = min(int(params["limit"]), self.cap)
        rows = []
        ts = after - _DAY_MS
        while len(rows) < size and ts >= _START_TS - 30 * _DAY_MS:
            rows.append([str(ts), "1", "2", "0.5", "1.5", "10", "0", "0", "1"])
            ts -= _DAY_MS
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"code": "0", "data": rows}
        return resp


def test_history_endpoint_pages_past_its_100_row_cap():
    venue = _HistoryVenue(cap=100)
    session = MagicMock()
    session.get = venue

    df = DataLoader()._paginate(
        session, okx.HISTORY_CANDLES_PATH, "BTC-USDT", _START_TS, _END_TS, "1D", 40
    )

    assert df is not None
    assert len(df) == 365
    assert df.index.min() == _START
    assert df.index.max() == _END
    assert set(venue.limits) == {"100"}


def test_recent_endpoint_keeps_300_row_pages():
    venue = _HistoryVenue(cap=300)
    session = MagicMock()
    session.get = venue

    df = DataLoader()._paginate(
        session, okx.CANDLES_PATH, "BTC-USDT", _START_TS, _END_TS, "1D", 40
    )

    assert df is not None
    assert len(df) == 365
    assert set(venue.limits) == {"300"}
