"""Alpaca-backed loader for US-equity OHLCV data.

Fills the free *intraday* US-equity gap (1m/5m/15m/30m/1H) that yfinance (1H
floor) and akshare (daily only) cannot serve. Credentials and SDK plumbing are
shared with the broker connector (``src.trading.connectors.alpaca.sdk``) so a
single ``~/.vibe-trading/alpaca.json`` powers both order placement and data;
``ALPACA_API_KEY`` / ``ALPACA_SECRET_KEY`` env vars override it for parity with
the other loaders.

Alpaca bars are timezone-aware UTC. Intraday bars are converted to
``America/New_York`` and made tz-naive so they read as ET wall-clock
(09:30, 09:35, …); daily bars collapse to the calendar date.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest.loaders.base import (
    loader_cache_get,
    loader_cache_put,
    retry_with_budget,
    validate_date_range,
)
from backtest.loaders.registry import register

_OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]

# Intraday intervals get UTC -> ET conversion; 1D collapses to a date.
_INTRADAY_INTERVALS = {"1m", "5m", "15m", "30m", "1H", "4H"}
_MARKET_TZ = "America/New_York"

# Wall-clock budget for the (auto-paginated) batch bars request.
_ALPACA_FETCH_BUDGET_S = 30.0


def _to_alpaca_symbol(code: str) -> str:
    """Convert a project symbol into an Alpaca symbol.

    Args:
        code: Project symbol such as ``AAPL.US``.

    Returns:
        Alpaca symbol such as ``AAPL``.
    """
    upper = code.strip().upper()
    if upper.endswith(".US"):
        return upper[:-3]
    return upper


def _to_alpaca_timeframe(interval: str) -> Any:
    """Map a project interval to an Alpaca ``TimeFrame``.

    Args:
        interval: Backtest interval such as ``5m`` or ``1D``.

    Returns:
        An Alpaca ``TimeFrame`` instance. Unknown intervals fall back to daily.
    """
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit  # type: ignore

    token = str(interval or "1D").strip()
    minute_amounts = {"1m": 1, "5m": 5, "15m": 15, "30m": 30}
    if token in minute_amounts:
        return TimeFrame(minute_amounts[token], TimeFrameUnit.Minute)
    if token in ("1H", "4H"):
        return TimeFrame(1 if token == "1H" else 4, TimeFrameUnit.Hour)
    return TimeFrame(1, TimeFrameUnit.Day)


def _normalize_bars(bars: List[Any], interval: str) -> pd.DataFrame:
    """Normalize a symbol's Alpaca bars into the backtest OHLCV schema.

    Args:
        bars: Iterable of Alpaca ``Bar`` objects (or mapping-like rows).
        interval: Original backtest interval; drives the timezone handling.

    Returns:
        OHLCV dataframe indexed by ``trade_date``, sorted ascending. Empty when
        no usable rows are present.
    """
    rows = []
    index = []
    for bar in bars or []:
        timestamp = getattr(bar, "timestamp", None)
        if timestamp is None and isinstance(bar, dict):
            timestamp = bar.get("timestamp")
        if timestamp is None:
            continue
        index.append(timestamp)
        rows.append(
            {
                "open": getattr(bar, "open", None) if not isinstance(bar, dict) else bar.get("open"),
                "high": getattr(bar, "high", None) if not isinstance(bar, dict) else bar.get("high"),
                "low": getattr(bar, "low", None) if not isinstance(bar, dict) else bar.get("low"),
                "close": getattr(bar, "close", None) if not isinstance(bar, dict) else bar.get("close"),
                "volume": getattr(bar, "volume", None) if not isinstance(bar, dict) else bar.get("volume"),
            }
        )

    if not rows:
        return pd.DataFrame(columns=_OHLCV_COLUMNS)

    frame = pd.DataFrame(rows, index=pd.DatetimeIndex(pd.to_datetime(index)))
    frame = frame.loc[:, _OHLCV_COLUMNS].apply(pd.to_numeric, errors="coerce")

    idx = frame.index
    if getattr(idx, "tz", None) is None:
        idx = idx.tz_localize("UTC")
    if str(interval).strip() in _INTRADAY_INTERVALS:
        idx = idx.tz_convert(_MARKET_TZ).tz_localize(None)
    else:
        idx = idx.tz_convert(_MARKET_TZ).tz_localize(None).normalize()
    frame.index = idx
    frame.index.name = "trade_date"

    frame = frame.sort_index()
    frame["volume"] = frame["volume"].fillna(0.0)
    frame = frame.dropna(subset=["open", "high", "low", "close"])
    return frame


@register
class DataLoader:
    """Fetch US-equity bars from Alpaca via ``StockHistoricalDataClient``."""

    name = "alpaca"
    markets = {"us_equity"}
    requires_auth = True

    def __init__(self) -> None:
        """Resolve Alpaca config once (saved file ← env-var override).

        Never raises: an unreadable config or missing SDK simply yields an
        unavailable loader so the registry falls through to yfinance.
        """
        self._cfg = None
        try:
            from src.trading.connectors.alpaca.sdk import build_config

            overrides = {}
            env_key = os.getenv("ALPACA_API_KEY", "").strip()
            env_secret = os.getenv("ALPACA_SECRET_KEY", "").strip()
            if env_key:
                overrides["api_key"] = env_key
            if env_secret:
                overrides["secret_key"] = env_secret
            self._cfg = build_config(overrides=overrides or None)
        except Exception:
            self._cfg = None

    def is_available(self) -> bool:
        """Return True only when the SDK is installed and creds are present."""
        if self._cfg is None:
            return False
        try:
            from src.trading.connectors.alpaca.sdk import alpaca_available
        except Exception:
            return False
        return bool(alpaca_available() and self._cfg.api_key and self._cfg.secret_key)

    def _client(self) -> Any:
        """Build a ``StockHistoricalDataClient`` from the resolved config."""
        from alpaca.data.historical import StockHistoricalDataClient  # type: ignore

        return StockHistoricalDataClient(self._cfg.api_key, self._cfg.secret_key)

    def _feed(self) -> Any:
        """Map the configured feed string to the Alpaca ``DataFeed`` enum."""
        from alpaca.data.enums import DataFeed  # type: ignore

        return DataFeed.SIP if getattr(self._cfg, "feed", "iex") == "sip" else DataFeed.IEX

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        fields: Optional[List[str]] = None,
        interval: str = "1D",
    ) -> Dict[str, pd.DataFrame]:
        """Fetch OHLCV history keyed by the original project symbols.

        Args:
            codes: Project symbols such as ``AAPL.US``.
            start_date: Start date in ``YYYY-MM-DD`` format.
            end_date: End date in ``YYYY-MM-DD`` format.
            fields: Ignored; included for interface compatibility.
            interval: Backtest interval such as ``5m`` or ``1D``.

        Returns:
            Mapping of input symbol to normalized OHLCV dataframe.
        """
        del fields
        if not codes:
            return {}
        validate_date_range(start_date, end_date)

        requested_interval = str(interval or "1D").strip()

        symbol_groups: Dict[str, List[str]] = defaultdict(list)
        for code in codes:
            symbol_groups[_to_alpaca_symbol(code)].append(code)

        results: Dict[str, pd.DataFrame] = {}
        pending: List[str] = []
        for symbol in symbol_groups:
            cached = loader_cache_get(
                source=self.name,
                symbol=symbol,
                timeframe=requested_interval,
                start_date=start_date,
                end_date=end_date,
                fields=None,
            )
            if cached is not None:
                for original_code in symbol_groups[symbol]:
                    results[original_code] = cached.copy()
            else:
                pending.append(symbol)

        if not pending:
            return results

        try:
            data = self._fetch_bars(pending, start_date, end_date, requested_interval)
        except Exception as exc:  # noqa: BLE001 - a batch failure degrades to no data
            print(f"[WARN] alpaca bars request failed for {pending}: {exc}")
            data = {}

        for symbol in pending:
            try:
                normalized = _normalize_bars(data.get(symbol, []), requested_interval)
                if normalized.empty:
                    print(f"[WARN] alpaca returned no usable data for {symbol}")
                    continue
                loader_cache_put(
                    source=self.name,
                    symbol=symbol,
                    timeframe=requested_interval,
                    start_date=start_date,
                    end_date=end_date,
                    fields=None,
                    frame=normalized,
                )
                for original_code in symbol_groups[symbol]:
                    results[original_code] = normalized.copy()
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not sink the batch
                print(f"[WARN] Failed to normalize alpaca data for {symbol}: {exc}")
                continue

        return results

    def _fetch_bars(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        interval: str,
    ) -> Dict[str, List[Any]]:
        """Batch-fetch bars for ``symbols`` with a bounded retry budget.

        Returns:
            Mapping of Alpaca symbol to its list of bar objects (empty when the
            symbol returned nothing).
        """
        from alpaca.data.requests import StockBarsRequest  # type: ignore

        try:
            from alpaca.common.exceptions import APIError  # type: ignore

            transient: tuple = (APIError, ConnectionError, TimeoutError)
        except Exception:
            transient = (ConnectionError, TimeoutError)

        client = self._client()
        # End is inclusive of the whole final day (intraday bars run intraday).
        start = pd.Timestamp(start_date).to_pydatetime()
        end = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).to_pydatetime()
        req = StockBarsRequest(
            symbol_or_symbols=list(symbols),
            timeframe=_to_alpaca_timeframe(interval),
            start=start,
            end=end,
            feed=self._feed(),
        )

        def _call() -> Any:
            return client.get_stock_bars(req)

        bars = retry_with_budget(
            _call,
            transient=transient,
            deadline=time.monotonic() + _ALPACA_FETCH_BUDGET_S,
            label=f"alpaca bars for {symbols}",
        )
        data = getattr(bars, "data", None)
        if isinstance(data, dict):
            return {sym: list(data.get(sym, []) or []) for sym in symbols}
        return {sym: [] for sym in symbols}
