"""AKShare loader: free, no-auth data for A-shares, US, HK, futures, forex, macro.

AKShare (https://github.com/akfamily/akshare) is a completely free financial
data aggregator covering Chinese and global markets.  No API token required.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

import pandas as pd

from backtest.engines._market_hooks import _detect_market, _is_china_futures
from backtest.loaders._symbol_utils import _is_etf_listed
from backtest.loaders.additive_conversion import convert_additive_to_multiplicative
from backtest.loaders.base import cached_loader_fetch, validate_date_range
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_INTERVAL_MAP_DAILY = {
    "1D": "daily",
    "1d": "daily",
    "1W": "weekly",
    "1w": "weekly",
    "1M": "monthly",
}

# US/HK/ETF/forex serve daily bars only.
_DAILY_ONLY_ALIASES = frozenset({"1d", "d", "day", "daily"})


def _require_daily_interval(interval: str, market: str) -> None:
    if str(interval).strip().lower() not in _DAILY_ONLY_ALIASES:
        raise ValueError(
            f"Unsupported interval {interval!r}; akshare {market} supports daily bars only"
        )


def _is_a_share(code: str) -> bool:
    return code.upper().endswith((".SZ", ".SH", ".BJ"))


def _is_hk(code: str) -> bool:
    return code.upper().endswith(".HK")


def _is_us(code: str) -> bool:
    return code.upper().endswith(".US")


def _is_crypto(code: str) -> bool:
    return "-USDT" in code.upper() or "/USDT" in code.upper()


#: Sina takes the bare contract code. Passing the exchange suffix through does
#: not return an empty frame — ``futures_zh_daily_sina("RB2601.SHFE")`` raises
#: ``ValueError: Length mismatch`` from inside akshare, so the suffix has to be
#: stripped here rather than discovered as a fetch failure.
def _sina_contract(code: str) -> str:
    """Return the bare uppercase contract code Sina's endpoints expect."""
    return code.split(".")[0].upper()


_CN_FUTURES_MAIN_RE = re.compile(r"^[A-Z]{1,2}0$")





def _is_forex(code: str) -> bool:
    """Detect forex pairs by matching against AKShare's symbol_market_map.

    Issue #54 — forex symbols (EURUSD, GBPUSD, etc.) have no exchange suffix
    and previously fell through to the A-share endpoint.
    """
    # Accept the canonical slash form (EUR/USD) too, so the forex fallback
    # chain (mt5 → akshare) actually engages for project-style codes.
    upper = code.upper().removesuffix(".FX").replace("/", "")
    try:
        from akshare.forex.cons import symbol_market_map
    except Exception:
        return False
    return upper in symbol_market_map


@register
class DataLoader:
    """AKShare universal OHLCV loader (free, no auth)."""

    name = "akshare"
    markets = {"a_share", "us_equity", "hk_equity", "futures", "fund", "macro", "forex"}
    # stock_zh_a_hist empirically returns board lots (HKUDS/Vibe-Trading#1062;
    # 600519.SH 2026-07-31 ratio 1.00 vs tencent/eastmoney). Note: akshare's
    # own documentation states shares for this interface — the docs disagree
    # with the actual behavior. Other markets stay undeclared.
    volume_units = {"a_share": "lots"}
    requires_auth = False

    def is_available(self) -> bool:
        """Available if akshare is installed."""
        try:
            import akshare  # noqa: F401
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
        """Fetch OHLCV data via AKShare.

        Args:
            codes: Symbol list.
            start_date: YYYY-MM-DD.
            end_date: YYYY-MM-DD.
            interval: Bar size (only 1D supported currently).
            fields: Ignored.

        Returns:
            Mapping symbol -> OHLCV DataFrame.
        """
        validate_date_range(start_date, end_date)

        result: Dict[str, pd.DataFrame] = {}
        for code in codes:
            try:
                df = cached_loader_fetch(
                    source=self.name,
                    symbol=code,
                    timeframe=interval,
                    start_date=start_date,
                    end_date=end_date,
                    fields=None,
                    fetch=lambda code=code: self._fetch_one(code, start_date, end_date, interval),
                )
                if df is not None and not df.empty and _is_a_share(code) and not _is_etf_listed(code):
                    # #1541: adjust="qfq" is dividend-additive and cannot serve
                    # returns; convert to the multiplicative convention when
                    # the adjust="" companion supports it.
                    raw_df = None
                    try:
                        raw_df = cached_loader_fetch(
                            source=self.name,
                            symbol=code,
                            timeframe=interval,
                            start_date=start_date,
                            end_date=end_date,
                            fields=["raw"],
                            fetch=lambda code=code: self._fetch_a_share_raw(code, start_date, end_date, interval),
                        )
                    except Exception as exc:  # noqa: BLE001 - degrade to additive
                        logger.warning(
                            "akshare raw companion fetch failed for %s, serving additive: %s",
                            code, exc,
                        )
                    converted = convert_additive_to_multiplicative(raw_df, df)
                    if converted is not None:
                        converted.attrs = {
                            **getattr(df, "attrs", {}),
                            "adjustment": "split_dividend",
                        }
                        result[code] = converted
                        continue
                if df is not None and not df.empty:
                    result[code] = df
            except Exception as exc:
                logger.warning("akshare failed for %s: %s", code, exc)
        return result

    def _fetch_one(
        self, code: str, start_date: str, end_date: str, interval: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch a single symbol."""
        import akshare as ak

        # ETF check must precede A-share — 518880.SH ends with .SH but is an ETF.
        if _is_etf_listed(code):
            _require_daily_interval(interval, "etf")
            return self._fetch_etf(ak, code, start_date, end_date)
        if _is_a_share(code):
            return self._fetch_a_share(ak, code, start_date, end_date, interval)
        if _is_us(code):
            _require_daily_interval(interval, "us")
            return self._fetch_us(ak, code, start_date, end_date)
        if _is_hk(code):
            _require_daily_interval(interval, "hk")
            return self._fetch_hk(ak, code, start_date, end_date)
        if _is_forex(code):
            _require_daily_interval(interval, "forex")
            return self._fetch_forex(ak, code, start_date, end_date)
        if _is_china_futures(code):
            _require_daily_interval(interval, "futures")
            return self._fetch_china_futures(ak, code, start_date, end_date)
        if _detect_market(code) == "futures":
            # A futures contract Sina does not carry (CL2412.NYMEX, ESZ4).
            # Returning None hands the symbol to the next link in the chain;
            # letting it reach the A-share default below priced a USD-quoted
            # global contract off ``stock_zh_a_hist`` without erroring (#1395).
            logger.warning(
                "akshare serves Chinese futures only; %s has no akshare source", code
            )
            return None
        # Default: try A-share
        return self._fetch_a_share(ak, code, start_date, end_date, interval)

    def _fetch_a_share(
        self, ak, code: str, start_date: str, end_date: str, interval: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch A-share via stock_zh_a_hist."""
        symbol = code.split(".")[0]
        period = _INTERVAL_MAP_DAILY.get(interval)
        if period is None:
            raise ValueError(
                f"Unsupported interval {interval!r}; akshare a-share supports "
                f"{sorted(_INTERVAL_MAP_DAILY)}"
            )
        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period=period,
            start_date=sd,
            end_date=ed,
            adjust="qfq",
        )
        if df is None or df.empty:
            return None
        return self._normalize(df, date_col="日期")

    def _fetch_a_share_raw(
        self, code: str, start_date: str, end_date: str, interval: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch the raw (unadjusted) companion of ``_fetch_a_share`` (#1541)."""
        import akshare as ak

        symbol = code.split(".")[0]
        period = _INTERVAL_MAP_DAILY.get(interval)
        if period is None:
            raise ValueError(
                f"Unsupported interval {interval!r}; akshare a-share supports "
                f"{sorted(_INTERVAL_MAP_DAILY)}"
            )
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period=period,
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            adjust="",
        )
        if df is None or df.empty:
            return None
        return self._normalize(df, date_col="日期")

    def _fetch_us(self, ak, code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """Fetch US stock via stock_us_hist."""
        symbol = code.replace(".US", "")
        # akshare uses the format like "105.AAPL" for NASDAQ
        # Try common prefixes
        for prefix in ["105.", "106.", ""]:
            try:
                df = ak.stock_us_hist(
                    symbol=f"{prefix}{symbol}",
                    period="daily",
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", ""),
                    adjust="qfq",
                )
                if df is not None and not df.empty:
                    return self._normalize(df, date_col="日期")
            except Exception:
                continue
        return None

    def _fetch_etf(self, ak, code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """Fetch exchange-listed ETF / LOF via fund_etf_hist_sina.

        Sina symbol format is ``sh518880`` / ``sz159915``. The endpoint returns
        the full history; we filter to the requested window after fetching.
        """
        digits, _, suffix = code.upper().partition(".")
        symbol = f"{suffix.lower()}{digits}"
        df = ak.fund_etf_hist_sina(symbol=symbol)
        if df is None or df.empty:
            return None
        df = self._normalize(df, date_col="date")
        # fund_etf_hist_sina returns full history — clip to window.
        return df.loc[start_date:end_date]

    def _fetch_forex(self, ak, code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """Fetch forex pair via forex_hist_em.

        Columns returned are 日期 / 代码 / 名称 / 今开 / 最新价 / 最高 / 最低 / 振幅
        — note ``最新价`` (latest) plays the role of close. Volume isn't reported,
        so we synthesize a zero column to satisfy the OHLCV contract.
        """
        symbol = code.upper().removesuffix(".FX").replace("/", "")
        df = ak.forex_hist_em(symbol=symbol)
        if df is None or df.empty:
            return None
        df = df.rename(columns={
            "日期": "trade_date",
            "今开": "open",
            "最新价": "close",
            "最高": "high",
            "最低": "low",
        })
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date").sort_index()
        df["volume"] = 0.0
        for col in ("open", "high", "low", "close"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df[["open", "high", "low", "close", "volume"]].dropna(
            subset=["open", "high", "low", "close"]
        )
        return df.loc[start_date:end_date]

    def _fetch_hk(self, ak, code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """Fetch HK stock via stock_hk_hist."""
        symbol = code.replace(".HK", "").zfill(5)
        df = ak.stock_hk_hist(
            symbol=symbol,
            period="daily",
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            adjust="qfq",
        )
        if df is None or df.empty:
            return None
        return self._normalize(df, date_col="日期")

    def _fetch_china_futures(
        self, ak, code: str, start_date: str, end_date: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch a Chinese futures contract from Sina's token-free endpoints.

        Two contract forms arrive here, and they use different endpoints with
        different payload shapes:

        * Dated (``RB2601``, ``IF2512.CFFEX``) -> ``futures_zh_daily_sina``,
          which takes *no* date range and serves the contract's whole life, so
          the requested window is applied here. Columns are already English.
        * Main continuous (``RB0``) -> ``futures_main_sina``, which does take a
          range and answers in Chinese column names carrying a ``价`` suffix
          (``开盘价``), distinct from the ``开盘`` spelling ``_normalize``
          knows from the equity endpoints.

        Args:
            ak: The imported ``akshare`` module.
            code: Contract code, with or without an exchange suffix.
            start_date: YYYY-MM-DD, inclusive.
            end_date: YYYY-MM-DD, inclusive.

        Returns:
            OHLCV frame indexed by trade date, or None when Sina carries no
            series for the contract.
        """
        symbol = _sina_contract(code)
        try:
            if _CN_FUTURES_MAIN_RE.match(symbol):
                raw = ak.futures_main_sina(
                    symbol=symbol,
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", ""),
                )
                if raw is None or raw.empty:
                    return None
                raw = raw.rename(columns={
                    "开盘价": "开盘", "最高价": "最高",
                    "最低价": "最低", "收盘价": "收盘",
                })
                return self._normalize(raw, date_col="日期")

            raw = ak.futures_zh_daily_sina(symbol=symbol)
        except Exception as exc:  # noqa: BLE001 - one bad contract must not raise
            # akshare raises rather than returning empty for a code Sina does
            # not list (a ZCE three-digit delivery month such as ``MA605``, or
            # a stray exchange suffix), so this is the not-found path too.
            logger.warning("akshare futures fetch failed for %s: %s", code, exc)
            return None

        if raw is None or raw.empty:
            return None
        df = self._normalize(raw, date_col="date")
        # The dated endpoint ignores the window, so slice it here; without this
        # a one-month request came back with the contract's entire history.
        return df.loc[str(start_date):str(end_date)]

    @staticmethod
    def _normalize(df: pd.DataFrame, date_col: str = "日期") -> pd.DataFrame:
        """Normalize AKShare DataFrame to standard OHLCV schema.

        AKShare Chinese column names: 日期, 开盘, 最高, 最低, 收盘, 成交量
        AKShare English column names: date, open, high, low, close, volume
        """
        col_map_cn = {"开盘": "open", "最高": "high", "最低": "low", "收盘": "close", "成交量": "volume"}
        col_map_en = {"date": "trade_date", "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"}

        if date_col in df.columns:
            df = df.rename(columns={date_col: "trade_date"})
        elif "date" in df.columns:
            df = df.rename(columns={"date": "trade_date"})

        # Try Chinese column names first, then English
        if "开盘" in df.columns:
            df = df.rename(columns=col_map_cn)
        else:
            df = df.rename(columns=col_map_en)

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
