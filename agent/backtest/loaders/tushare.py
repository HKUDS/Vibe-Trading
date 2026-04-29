"""Tushare loader for A-share daily and intraday bars plus optional fundamentals.

Supports ``interval``: 1D (default) / 1m / 5m / 15m / 30m / 1H.
Minute data uses ``pro.stk_mins()`` (Tushare points >= 2000).
"""

import os
from typing import Dict, List, Optional

import pandas as pd

from backtest.loaders.base import validate_date_range
from backtest.loaders.registry import register


TUSHARE_TOKEN_PLACEHOLDERS = {"", "your-tushare-token"}


@register
class DataLoader:
    """Tushare-backed OHLCV loader."""

    name = "tushare"
    markets = {"a_share", "futures", "fund"}
    requires_auth = True

    def is_available(self) -> bool:
        """Available when TUSHARE_TOKEN is set."""
        return os.getenv("TUSHARE_TOKEN", "").strip() not in TUSHARE_TOKEN_PLACEHOLDERS

    def __init__(self) -> None:
        """Initialize Tushare pro API."""
        import tushare as ts

        token = os.getenv("TUSHARE_TOKEN", "")
        self.api = ts.pro_api(token)

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        fields: Optional[List[str]] = None,
        interval: str = "1D",
    ) -> Dict[str, pd.DataFrame]:
        """Fetch A-share bars via Tushare API.

        Args:
            codes: Stock codes (e.g. ``000001.SZ``).
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).
            fields: Extra fundamental columns (daily only).
            interval: Bar size (1D/1m/5m/15m/30m/1H), default ``1D``.

        Returns:
            Mapping code -> OHLCV DataFrame.
        """
        validate_date_range(start_date, end_date)

        if interval != "1D":
            return self._fetch_minutes(codes, start_date, end_date, interval)

        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")
        result: Dict[str, pd.DataFrame] = {}

        for code in codes:
            try:
                df = self.api.daily(ts_code=code, start_date=sd, end_date=ed)
                if df is None or df.empty:
                    continue
                df = df.sort_values("trade_date")
                df["trade_date"] = pd.to_datetime(df["trade_date"])
                df = df.set_index("trade_date")
                df = df.rename(columns={"vol": "volume"})
                for col in ["open", "high", "low", "close", "volume"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                ohlcv = df[["open", "high", "low", "close", "volume"]].dropna(
                    subset=["open", "high", "low", "close"]
                )
                result[code] = ohlcv
            except Exception as exc:
                print(f"[WARN] failed to fetch {code}: {exc}")

        return self._merge_basic_fields(result, codes, start_date, end_date, fields)

    def _merge_basic_fields(
        self,
        result: Dict[str, pd.DataFrame],
        codes: List[str],
        start_date: str,
        end_date: str,
        fields: Optional[List[str]],
    ) -> Dict[str, pd.DataFrame]:
        """Merge fundamental columns from daily_basic API.

        Args:
            result: Existing OHLCV frames.
            codes: All requested codes.
            start_date: Start date.
            end_date: End date.
            fields: Extra column names from daily_basic.

        Returns:
            Updated result map.
        """
        if not fields:
            return result

        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")
        active_codes = [c for c in codes if c in result]

        for code in active_codes:
            try:
                basic = self.api.daily_basic(
                    ts_code=code,
                    start_date=sd,
                    end_date=ed,
                    fields="ts_code,trade_date," + ",".join(fields),
                )
                if basic is not None and not basic.empty:
                    basic["trade_date"] = pd.to_datetime(basic["trade_date"])
                    basic = basic.set_index("trade_date").sort_index()
                    for f in fields:
                        if f in basic.columns:
                            result[code][f] = basic[f]
            except Exception as exc:
                print(f"[WARN] daily_basic for {code} failed: {exc}")

        return result

    def _fetch_minutes(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        interval: str,
    ) -> Dict[str, pd.DataFrame]:
        """Intraday bars via stk_mins.

        Args:
            codes: Stock codes.
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).
            interval: Minute bar (1m/5m/15m/30m/1H).

        Returns:
            Mapping code -> DataFrame.
        """
        freq_map = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1H": "60min"}
        freq = freq_map.get(interval)
        if not freq:
            print(f"[ERROR] unsupported Tushare interval: {interval}")
            return {}

        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")
        result: Dict[str, pd.DataFrame] = {}

        for code in codes:
            try:
                df = self.api.stk_mins(ts_code=code, freq=freq, start_date=sd, end_date=ed)
                if df is None or df.empty:
                    print(f"[WARN] empty Tushare minute data: {code} (points >= 2000 required)")
                    continue
                df = df.sort_values("trade_time")
                df["trade_date"] = pd.to_datetime(df["trade_time"])
                df = df.set_index("trade_date")
                df = df.rename(columns={"vol": "volume"})
                for col in ["open", "high", "low", "close", "volume"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                ohlcv = df[["open", "high", "low", "close", "volume"]].dropna(
                    subset=["open", "high", "low", "close"]
                )
                result[code] = ohlcv
            except Exception as exc:
                print(f"[WARN] failed to fetch minute data {code}: {exc}")
        return result
