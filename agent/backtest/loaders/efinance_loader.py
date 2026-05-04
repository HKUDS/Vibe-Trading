"""EFinance loader: free, no-auth data from East Money (东方财富).

EFinance (https://github.com/Micro-sheep/efinance) provides free A-share,
US, HK and ETF data from East Money.  No API token required.

Usage:
    from backtest.loaders.efinance_loader import DataLoader
    loader = DataLoader()
    df_map = loader.fetch(["000001", "600519"], "2024-01-01", "2024-12-31")
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import pandas as pd

from backtest.loaders.base import validate_date_range
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

# A-share ETF/LOF prefix codes (same as akshare)
_ETF_PREFIXES = frozenset({"15", "16", "50", "51", "52", "56", "58"})

# Column names returned by efinance:
# "日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"
# Plus "股票名称", "股票代码" for identification.
_EFINANCE_COL_MAP = {
    "日期": "trade_date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
}


def _is_a_share(code: str) -> bool:
    return code.upper().endswith((".SZ", ".SH", ".BJ"))


def _is_hk(code: str) -> bool:
    return code.upper().endswith(".HK")


def _is_us(code: str) -> bool:
    return code.upper().endswith(".US")


def _is_etf_listed(code: str) -> bool:
    """Detect exchange-listed ETF / LOF symbols (e.g. 518880.SH)."""
    upper = code.upper()
    if not upper.endswith((".SH", ".SZ")):
        return False
    digits = upper.split(".")[0]
    if len(digits) != 6 or not digits.isdigit():
        return False
    return digits[:2] in _ETF_PREFIXES


def _resolve_market_type(code: str) -> str:
    """Return the efinance MarketType enum member name for a symbol."""
    if _is_etf_listed(code):
        return "A_stock"          # ETFs trade on A-share markets
    if _is_a_share(code):
        return "A_stock"
    if _is_hk(code):
        return "Hongkong"
    if _is_us(code):
        return "US_stock"
    # Fallback: pure digit codes → A-share
    if code.isdigit() and len(code) in (5, 6):
        return "A_stock"
    return "A_stock"


def _resolve_symbol(code: str) -> str:
    """Strip exchange suffix to get the raw symbol for efinance."""
    upper = code.upper()
    if _is_a_share(code):
        return upper.split(".")[0]
    if _is_hk(code):
        return upper.replace(".HK", "").zfill(5)
    if _is_us(code):
        return upper.replace(".US", "")
    # Fallback
    return code


@register
class DataLoader:
    """EFinance (东方财富) universal OHLCV loader (free, no auth)."""

    name = "efinance"
    markets = {"a_share", "us_equity", "hk_equity", "fund"}
    requires_auth = False

    def is_available(self) -> bool:
        """Available if efinance package is installed."""
        try:
            import efinance  # noqa: F401
            return True
        except ImportError:
            return False

    def __init__(self) -> None:
        pass

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch OHLCV data via EFinance.

        Args:
            codes: Symbol list (e.g. "000001", "600519.SH", "AAPL.US", "0700.HK").
            start_date: YYYY-MM-DD.
            end_date: YYYY-MM-DD.
            interval: Bar size (1D, 1W, 1M).
            fields: Ignored.

        Returns:
            Mapping symbol -> OHLCV DataFrame.
        """
        validate_date_range(start_date, end_date)

        result: Dict[str, pd.DataFrame] = {}
        for code in codes:
            try:
                df = self._fetch_one(code, start_date, end_date, interval)
                if df is not None and not df.empty:
                    result[code] = df
            except Exception as exc:
                logger.warning("efinance failed for %s: %s", code, exc)
        return result

    def _fetch_one(
        self, code: str, start_date: str, end_date: str, interval: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch a single symbol via efinance.stock.get_quote_history."""
        from efinance.common.config import MarketType
        from efinance.stock import getter as stock_getter

        market_type_name = _resolve_market_type(code)
        symbol = _resolve_symbol(code)
        klt = {"1D": 101, "1W": 102, "1M": 103}.get(interval, 101)
        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")

        market_type = MarketType[market_type_name]

        try:
            df = stock_getter.get_quote_history(
                stock_codes=symbol,
                beg=sd,
                end=ed,
                klt=klt,
                fqt=1,  # 前复权 (forward-adjusted)
                market_type=market_type,
            )
        except Exception as exc:
            logger.debug("efinance get_quote_history(%s, %s) failed: %s", symbol, market_type_name, exc)
            return None

        # get_quote_history may return DataFrame or Dict[str, DataFrame]
        if isinstance(df, dict):
            df = list(df.values())[0] if df else None
        if df is None or df.empty:
            return None

        return self._normalize(df)

    @staticmethod
    def _normalize(df: pd.DataFrame) -> pd.DataFrame:
        """Normalize EFinance DataFrame to standard OHLCV schema.

        EFinance column names: 日期, 开盘, 收盘, 最高, 最低, 成交量
        """
        # Rename columns
        rename_map = {}
        for src, dst in _EFINANCE_COL_MAP.items():
            if src in df.columns:
                rename_map[src] = dst

        df = df.rename(columns=rename_map)

        if "trade_date" not in df.columns:
            raise ValueError("efinance returned unexpected columns; cannot find date column")

        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date").sort_index()

        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        ohlcv_cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
        df = df[ohlcv_cols].dropna(subset=["open", "high", "low", "close"])
        if "volume" not in df.columns:
            df["volume"] = 0.0
        return df
