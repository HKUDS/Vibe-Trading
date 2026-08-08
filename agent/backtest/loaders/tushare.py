"""Tushare loader for A-share daily and intraday bars plus optional fundamentals.

Supports ``interval``: 1D (default) / 1m / 5m / 15m / 30m / 1H.
Minute data uses ``pro.stk_mins()`` (Tushare points >= 2000).
"""

import logging
import time
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from backtest.loaders._symbol_utils import _is_etf_listed
from backtest.loaders.base import cached_loader_fetch, validate_date_range
from backtest.loaders.cn_adjust import apply_qfq
from backtest.loaders.registry import register

#: Substrings that identify a Tushare per-minute quota rejection rather than a
#: real failure. Tushare returns these as an ordinary exception message, so the
#: only way to tell "you are going too fast" from "this symbol does not exist"
#: is to read the text.
_RATE_LIMIT_MARKERS: tuple[str, ...] = (
    "每分钟",
    "每天",
    "抽取",
    "访问该接口",
    "频率",
    "rate limit",
    "too many requests",
)

#: Backoff schedule in seconds. The quota window is a minute, so the last wait
#: has to cross one; three attempts totalling ~65s clear it without turning a
#: genuinely broken call into a two-minute hang.
_RATE_LIMIT_BACKOFF_SECONDS: tuple[float, ...] = (5.0, 20.0, 40.0)


def _is_rate_limited(exc: Exception) -> bool:
    """Return whether an exception is a quota rejection rather than a failure.

    Args:
        exc: The exception raised by a Tushare endpoint call.

    Returns:
        True when the message carries any marker in :data:`_RATE_LIMIT_MARKERS`.
    """
    message = str(exc).lower()
    return any(marker.lower() in message for marker in _RATE_LIMIT_MARKERS)


def _call_with_backoff(fn: Callable[..., Any], /, **kwargs: Any) -> Any:
    """Call a Tushare endpoint, waiting out a per-minute quota rejection.

    Only quota rejections are retried. Retrying an ordinary failure would turn
    a broken symbol or a bad date range into a silent multi-second stall and
    then the same error anyway, so those propagate on the first attempt.

    Args:
        fn: The endpoint callable, e.g. ``api.daily``.
        **kwargs: Passed straight through.

    Returns:
        Whatever the endpoint returns.

    Raises:
        Exception: The endpoint's own exception, either immediately (not a
            quota issue) or after the backoff schedule is exhausted.
    """
    for delay in _RATE_LIMIT_BACKOFF_SECONDS:
        try:
            return fn(**kwargs)
        except Exception as exc:  # noqa: BLE001 - classified immediately below
            if not _is_rate_limited(exc):
                raise
            logger.warning(
                "tushare quota hit (%s); waiting %.0fs before retrying", exc, delay
            )
            time.sleep(delay)
    return fn(**kwargs)


logger = logging.getLogger(__name__)


TUSHARE_TOKEN_PLACEHOLDERS = {"", "your-tushare-token"}


def _is_index(code: str) -> bool:
    """Detect A-share index symbols (000xxx.SH, 000300.SH, 399xxx.SZ)."""
    upper = code.upper()
    if upper.endswith(".SH"):
        digits = upper.split(".")[0]
        return len(digits) == 6 and digits.isdigit() and digits.startswith("000")
    if upper.endswith(".SZ"):
        digits = upper.split(".")[0]
        return len(digits) == 6 and digits.isdigit() and digits.startswith("399")
    return False


def _is_hk_equity(code: str) -> bool:
    """Detect Hong Kong equity symbols (e.g. 00700.HK)."""
    return code.upper().endswith(".HK")


def _is_us_equity(code: str) -> bool:
    """Detect US equity symbols (e.g. AAPL.US)."""
    return code.upper().endswith(".US")


def _is_crypto(code: str) -> bool:
    """Detect crypto symbols (e.g. BTC-USDT, ETH/USDT)."""
    upper = code.upper()
    return upper.endswith("-USDT") or upper.endswith("/USDT")


@register
class DataLoader:
    """Tushare-backed OHLCV loader."""

    name = "tushare"
    markets = {"a_share", "hk_equity", "futures", "fund"}
    requires_auth = True

    def is_available(self) -> bool:
        """Available when TUSHARE_TOKEN is set."""
        from src.config.accessor import get_env_config

        return get_env_config().data.tushare_token.strip() not in TUSHARE_TOKEN_PLACEHOLDERS

    def __init__(self) -> None:
        """Initialize Tushare pro API."""
        import tushare as ts

        from src.config.accessor import get_env_config

        token = get_env_config().data.tushare_token
        self.api = ts.pro_api(token)

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch A-share / HK equity bars via Tushare API.

        Args:
            codes: Stock codes (e.g. ``000001.SZ``, ``00700.HK``).
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).
            fields: Extra fundamental columns (daily only).
            interval: Bar size (1D/1m/5m/15m/30m/1H), default ``1D``.

        Returns:
            Mapping code -> OHLCV DataFrame.
        """
        validate_date_range(start_date, end_date)

        # Tencent/sina-style daily aliases; bare ``1d`` must not take the minute path.
        if str(interval).strip().lower() in {"1d", "d", "day", "daily"}:
            interval = "1D"
        elif interval != "1D":
            return self._fetch_minutes(codes, start_date, end_date, interval)

        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")
        cache_fields = list(fields or [])
        result: Dict[str, pd.DataFrame] = {}

        # Every code goes through the opt-in cache helper, which is a direct
        # passthrough when the cache is disabled. Fundamentals are merged inside
        # the cached unit so a cached entry already carries its extra columns.
        for code in codes:
            def _fetch_one(code: str = code) -> Optional[pd.DataFrame]:
                try:
                    df = self._fetch_daily_frame(code, sd, ed)
                    if df is None:
                        return None
                    merged = self._merge_basic_fields(
                        {code: df}, [code], start_date, end_date, cache_fields
                    )
                    return merged.get(code)
                except Exception as exc:
                    logger.warning("failed to fetch %s: %s", code, exc)
                    return None

            df = cached_loader_fetch(
                source=self.name,
                symbol=code,
                timeframe="1D",
                start_date=start_date,
                end_date=end_date,
                fields=cache_fields,
                fetch=_fetch_one,
            )
            if df is not None and not df.empty:
                result[code] = df

        return result

    def _fetch_daily_frame(
        self,
        code: str,
        start_date: str,
        end_date: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch and normalize one daily OHLCV frame, routing by symbol type."""
        if _is_us_equity(code) or _is_crypto(code):
            logger.warning("tushare does not support %s (US/crypto); skipping", code)
            return None

        if _is_etf_listed(code):
            endpoint_name = "fund_daily"
            df = self.api.fund_daily(ts_code=code, start_date=start_date, end_date=end_date)
            adjust = getattr(self.api, "fund_adj", None)
        elif _is_index(code):
            endpoint_name = "index_daily"
            df = self.api.index_daily(ts_code=code, start_date=start_date, end_date=end_date)
            # An index level is already continuous across its members' ex-dates.
            adjust = None
        elif _is_hk_equity(code):
            endpoint_name = "hk_daily"
            df = _call_with_backoff(self.api.hk_daily, ts_code=code, start_date=start_date, end_date=end_date)
            # Tushare publishes no HK adjustment-factor series.
            adjust = None
        else:
            endpoint_name = "daily"
            df = _call_with_backoff(self.api.daily, ts_code=code, start_date=start_date, end_date=end_date)
            adjust = getattr(self.api, "adj_factor", None)

        if df is None or df.empty:
            logger.warning("tushare returned empty for %s via %s", code, endpoint_name)
            return None
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
        if adjust is None:
            return ohlcv

        try:
            factor = _call_with_backoff(adjust, ts_code=code, start_date=start_date, end_date=end_date)
        except Exception as exc:  # noqa: BLE001 - one bad fetch must not raise
            logger.warning("tushare adjustment-factor fetch failed for %s: %s", code, exc)
            factor = None
        adjusted = apply_qfq(ohlcv, factor)
        if adjusted is None:
            # Returning the raw frame here is what produced the defect: a
            # close-to-close return across an ex-date spans the mechanical gap,
            # measured at -47.2%% on 300750.SZ 2023-04-26 against a true +5.4%%.
            logger.warning(
                "tushare: no usable adjustment factors for %s — dropping the "
                "symbol rather than backtesting it on unadjusted prices",
                code,
            )
        return adjusted

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
            if (
                _is_etf_listed(code)
                or _is_index(code)
                or _is_hk_equity(code)
                or _is_us_equity(code)
                or _is_crypto(code)
            ):
                # daily_basic is stock-only; skip fundamental enrichment for non-stock symbols
                continue
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
                logger.warning("daily_basic for %s failed: %s", code, exc)

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
            logger.error("unsupported Tushare interval: %s", interval)
            return {}

        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")
        result: Dict[str, pd.DataFrame] = {}

        for code in codes:
            if _is_etf_listed(code):
                # tushare has no fund_mins endpoint; ETF intraday is unavailable
                logger.warning("tushare does not support intraday data for %s (ETF); skipping", code)
                continue
            if _is_index(code) or _is_hk_equity(code) or _is_us_equity(code) or _is_crypto(code):
                sym_type = (
                    "index" if _is_index(code)
                    else "HK" if _is_hk_equity(code)
                    else "US" if _is_us_equity(code)
                    else "crypto"
                )
                logger.warning("tushare does not support intraday data for %s (%s); skipping", code, sym_type)
                continue
            try:
                df = self.api.stk_mins(ts_code=code, freq=freq, start_date=sd, end_date=ed)
                if df is None or df.empty:
                    logger.warning("empty Tushare minute data: %s (points >= 2000 required)", code)
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
                logger.warning("failed to fetch minute data %s: %s", code, exc)
        return result
