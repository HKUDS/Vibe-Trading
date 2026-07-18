"""CCXT loader: unified crypto exchange data (100+ exchanges).

Uses the CCXT library to fetch OHLCV candles from any supported exchange.
Defaults to Binance; configurable via CCXT_EXCHANGE env var.
No API key required for public market data.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Dict, List, Optional

import pandas as pd

from backtest.loaders.base import (
    cached_loader_fetch,
    check_budget,
    positive_env_float,
    positive_env_int,
    retry_with_budget,
    validate_date_range,
)
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1H": "1h", "4H": "4h", "1D": "1d",
}

_TIMEFRAME_DELTA = {
    "1m": pd.Timedelta(minutes=1),
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "30m": pd.Timedelta(minutes=30),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
}

# P12-b: ccxt had no request timeout and an unbounded paginated fetch with
# no retry budget, so a transient disconnect hung get_market_data for 10+
# minutes. Cap each HTTP call, bound transient retries, and enforce a hard
# wall-clock budget so the fetch fails fast instead of hanging. Retry
# scheduling is delegated to :mod:`backtest.loaders.base`.
_CCXT_TIMEOUT_MS = positive_env_int("CCXT_TIMEOUT_MS", 15_000)
_CCXT_FETCH_BUDGET_S = positive_env_float("CCXT_FETCH_BUDGET_S", 60.0)


def _parse_ccxt_symbol(code: str) -> tuple[str, str]:
    """Return the canonical CCXT symbol and instrument type for ``code``."""
    normalized = code.strip().upper()
    if normalized.endswith("-PERP"):
        match = re.fullmatch(r"([A-Z0-9]+)-USDT-PERP", normalized)
        if match is None:
            raise ValueError(
                "USD-M perpetual symbol must use BASE-USDT-PERP, e.g. BTC-USDT-PERP"
            )
        return f"{match.group(1)}/USDT:USDT", "swap"
    return normalized.replace("-", "/"), "spot"


def _first_proxy_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()  # noqa: env-gate — system proxy vars
        if value:
            return value
    return ""


def _ccxt_proxy_config() -> dict[str, str]:
    """Build CCXT proxy settings from conventional proxy environment variables."""
    all_proxy = _first_proxy_env("ALL_PROXY", "all_proxy")
    http_proxy = _first_proxy_env("HTTP_PROXY", "http_proxy") or all_proxy
    https_proxy = _first_proxy_env("HTTPS_PROXY", "https_proxy") or all_proxy or http_proxy

    proxies: dict[str, str] = {}
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    return proxies


@register
class DataLoader:
    """CCXT-backed crypto OHLCV loader (100+ exchanges)."""

    name = "ccxt"
    markets = {"crypto"}
    requires_auth = False

    def is_available(self) -> bool:
        """Available if ccxt is installed."""
        try:
            import ccxt  # noqa: F401
            return True
        except ImportError:
            return False

    def __init__(self) -> None:
        pass

    def _get_exchange(self, instrument_type: str = "spot"):
        """Create an exchange instance for spot or Binance USD-M swaps."""
        import ccxt
        from src.config.accessor import get_env_config

        exchange_id = get_env_config().data.ccxt_exchange.lower()
        if instrument_type == "swap":
            if exchange_id not in {"binance", "binanceusdm"}:
                raise ValueError(
                    "BASE-USDT-PERP currently requires CCXT_EXCHANGE=binance"
                )
            exchange_id = "binanceusdm"
        exchange_cls = getattr(ccxt, exchange_id, None)
        if exchange_cls is None:
            logger.warning("Unknown CCXT exchange %s, falling back to binance", exchange_id)
            exchange_cls = ccxt.binance

        config = {"enableRateLimit": True, "timeout": _CCXT_TIMEOUT_MS}
        proxies = _ccxt_proxy_config()
        if proxies:
            config["proxies"] = proxies
        return exchange_cls(config)

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch crypto OHLCV via CCXT.

        Args:
            codes: Symbols like ``["BTC-USDT", "ETH-USDT"]``.
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).
            interval: Bar size.
            fields: Ignored.

        Returns:
            Mapping symbol -> OHLCV DataFrame.
        """
        validate_date_range(start_date, end_date)

        timeframe = _INTERVAL_MAP.get(interval, "1d")
        since_ms = int(pd.Timestamp(start_date).timestamp() * 1000)
        end_ms = int((pd.Timestamp(end_date) + pd.Timedelta(days=1)).timestamp() * 1000)

        # Build the exchange lazily so a full cache hit never imports ccxt or
        # opens an exchange object.
        exchange_holder: Dict[str, object] = {}

        def get_exchange(instrument_type: str):
            if instrument_type not in exchange_holder:
                exchange_holder[instrument_type] = self._get_exchange(instrument_type)
            return exchange_holder[instrument_type]

        result: Dict[str, pd.DataFrame] = {}
        for code in codes:
            instrument_type = "spot"
            try:
                ccxt_symbol, instrument_type = _parse_ccxt_symbol(code)
                exchange = get_exchange(instrument_type)

                def fetch_frame():
                    if instrument_type == "swap":
                        return self._fetch_perpetual(
                            exchange, ccxt_symbol, timeframe, since_ms, end_ms
                        )
                    return self._fetch_one(
                        exchange, ccxt_symbol, timeframe, since_ms, end_ms
                    )

                df = cached_loader_fetch(
                    source=self.name,
                    symbol=code,
                    timeframe=interval,
                    start_date=start_date,
                    end_date=end_date,
                    fields=None,
                    fetch=fetch_frame,
                )
                if df is not None and not df.empty:
                    result[code] = df
            except Exception as exc:
                if instrument_type == "swap" or code.strip().upper().endswith("-PERP"):
                    raise
                logger.warning("CCXT failed for %s: %s", code, exc)
        return result

    @classmethod
    def _fetch_perpetual(
        cls, exchange, symbol: str, timeframe: str, since_ms: int, end_ms: int,
    ) -> pd.DataFrame:
        """Fetch aligned trade-price and mark-price candles for one USD-M swap."""
        trade = cls._fetch_one(exchange, symbol, timeframe, since_ms, end_ms)
        mark = cls._fetch_one(
            exchange,
            symbol,
            timeframe,
            since_ms,
            end_ms,
            params={"price": "mark"},
        )
        if trade is None or mark is None or not trade.index.equals(mark.index):
            raise ValueError(f"mark-price timestamps are incomplete or unsynchronized for {symbol}")

        result = trade.copy()
        result["execution_open"] = trade["open"]
        for column in ("open", "high", "low", "close"):
            result[f"mark_{column}"] = mark[column]
        return result

    @staticmethod
    def _fetch_one(
        exchange,
        symbol: str,
        timeframe: str,
        since_ms: int,
        end_ms: int,
        *,
        params: dict[str, str] | None = None,
    ) -> Optional[pd.DataFrame]:
        """Paginated OHLCV fetch for one symbol."""
        import ccxt

        all_rows: list = []
        cursor = since_ms
        limit = 1000
        deadline = time.monotonic() + _CCXT_FETCH_BUDGET_S
        label = f"ccxt fetch for {symbol}"
        hit_page_cap = True

        for _ in range(200):
            check_budget(deadline, label, budget_s=_CCXT_FETCH_BUDGET_S)
            # ``ccxt.NetworkError`` covers RequestTimeout / DDoSProtection /
            # ExchangeNotAvailable — the transient family. Anything else
            # (e.g. ``ExchangeError`` for a bad symbol) is not retried.
            def fetch_page():
                kwargs = {"since": cursor, "limit": limit}
                if params is not None:
                    kwargs["params"] = params
                return exchange.fetch_ohlcv(symbol, timeframe, **kwargs)

            ohlcv = retry_with_budget(
                fetch_page,
                transient=ccxt.NetworkError,
                deadline=deadline,
                label=label,
            )
            if not ohlcv:
                hit_page_cap = False
                break
            all_rows.extend(ohlcv)
            last_ts = ohlcv[-1][0]
            if last_ts >= end_ms or len(ohlcv) < limit:
                hit_page_cap = False
                break
            cursor = last_ts + 1

        if not all_rows:
            return None

        df = pd.DataFrame(all_rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["trade_date"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.set_index("trade_date").sort_index()

        start_dt = pd.Timestamp(since_ms, unit="ms")
        end_dt = pd.Timestamp(end_ms, unit="ms")
        df = df[(df.index >= start_dt) & (df.index < end_dt)]

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df[["open", "high", "low", "close", "volume"]].dropna(
            subset=["open", "high", "low", "close"]
        )
        if df.empty:
            return None

        tolerance = _TIMEFRAME_DELTA.get(timeframe)
        if tolerance is None:
            raise ValueError(f"unsupported CCXT timeframe: {timeframe}")
        if hit_page_cap and df.index[-1] < end_dt - tolerance:
            raise ValueError(
                f"incomplete CCXT history for {symbol}: requested "
                f"[{start_dt}, {end_dt}), received [{df.index[0]}, {df.index[-1]}]"
            )
        return df
