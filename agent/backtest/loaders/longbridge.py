"""LongPort (Longbridge) OpenAPI-backed loader for US and HK equity OHLCV data.

Wraps the ``longbridge`` SDK :class:`~longbridge.openapi.QuoteContext` to fetch
historical candlesticks for backtesting. Supports US and HK equities.

Auth requires the three LongPort credentials declared in
``src.config.env_schema.DataConfig``:
``LONGBRIDGE_APP_KEY``, ``LONGBRIDGE_APP_SECRET``, ``LONGBRIDGE_ACCESS_TOKEN``.

Paper-vs-live identity guard: this loader does **not** discriminate between
paper and live environments (LongPort exposes no API field for it). The loaded
Access Token implicitly selects the environment. For backtest purposes the
historical bars are identical regardless of source account.

The LongPort ``history_candlesticks_by_date`` endpoint caps responses at
~1000 bars per call. Date ranges longer than ~4 years of daily bars are
automatically split into sequential 180-day windows. Requests wider than the
bounded window budget fail explicitly instead of returning truncated history.

This module is for backtest data only; live trading uses the separate
``src.trading.connectors.longbridge.sdk`` module.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, List, Optional

import pandas as pd

from backtest.loaders.base import (
    NoAvailableSourceError,
    loader_cache_get,
    loader_cache_put,
    validate_date_range,
)
from backtest.loaders.registry import register
from src.trading.connectors.longbridge.credentials import (
    LongbridgeCredentialError,
    resolve_longbridge_credentials,
)

logger = logging.getLogger(__name__)

_OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]

_INTERVAL_MAP: dict[str, str] = {
    "1D": "Day",
    "1W": "Week",
    "1M": "Month",
    "1H": "Min_60",
    "1h": "Min_60",
    "1m": "Min_1",
    "5m": "Min_5",
    "15m": "Min_15",
    "30m": "Min_30",
}

# LongPort returns at most ~1000 bars per call. For wide ranges we split into
# sequential windows of this many days to avoid silent truncation.
_MAX_WINDOW_DAYS = 180
# Cap on the number of windows so a pathological request can't loop forever.
_MAX_WINDOWS = 20


class LongbridgeDependencyError(RuntimeError):
    """Raised when the ``longbridge`` SDK is not installed."""


def _require_longbridge():
    """Import and return the ``longbridge.openapi`` module.

    Raises:
        LongbridgeDependencyError: If the SDK is not installed.
    """
    try:
        from longbridge import openapi  # noqa: PLC0415
    except ImportError as exc:
        raise LongbridgeDependencyError(
            "The 'longbridge' SDK is not installed. "
            "Run: pip install 'vibe-trading-ai[longbridge]'"
        ) from exc
    return openapi


def _to_longport_symbol(code: str) -> str:
    """Convert a project symbol to LongPort format.

    LongPort accepts ``AAPL.US``, ``700.HK``, ``000001.SZ``, ``600519.SH``.
    Bare codes without a ``.`` suffix get ``.US`` appended so the resolver
    treats them as US equities (loader ``markets`` is us_equity + hk_equity;
    ambiguous codes lean US).

    Examples:
        AAPL      -> AAPL.US
        AAPL.US   -> AAPL.US
        700.HK    -> 700.HK
        0700.HK   -> 0700.HK
        000001.SZ -> 000001.SZ
        600519.SH -> 600519.SH
    """
    upper = code.strip().upper()
    if "." in upper:
        return upper
    return f"{upper}.US"


def _to_longport_period(interval: str):
    """Map a project interval string to a LongPort ``Period`` enum value.

    Lazy-imports the SDK so this module can be imported without it installed.
    Unsupported intervals fail explicitly so requested bar fidelity is never
    changed silently.
    """
    openapi = _require_longbridge()
    period_cls = getattr(openapi, "Period")
    token = interval.strip()
    attr = _INTERVAL_MAP.get(token)
    if attr is None:
        raise NoAvailableSourceError(
            f"unsupported Longbridge interval: {interval!r}; "
            f"supported intervals: {sorted(_INTERVAL_MAP)}"
        )
    try:
        return getattr(period_cls, attr)
    except AttributeError as exc:
        raise NoAvailableSourceError(
            f"installed Longbridge SDK does not expose Period.{attr}"
        ) from exc


def _date_windows(start: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    """Split a wide date range into sequential windows to respect the
    LongPort ~1000-bar per-call cap.

    Each window spans at most ``_MAX_WINDOW_DAYS`` days. Windows are capped
    at ``_MAX_WINDOWS`` so a pathological request cannot loop forever.
    """
    requested_days = (end - start).days + 1
    maximum_days = _MAX_WINDOW_DAYS * _MAX_WINDOWS
    if requested_days > maximum_days:
        raise NoAvailableSourceError(
            f"Longbridge date range spans {requested_days} days and exceeds "
            f"the {maximum_days}-day window limit"
        )

    windows: list[tuple[dt.date, dt.date]] = []
    cursor = start
    while cursor <= end and len(windows) < _MAX_WINDOWS:
        window_end = min(cursor + dt.timedelta(days=_MAX_WINDOW_DAYS - 1), end)
        windows.append((cursor, window_end))
        cursor = window_end + dt.timedelta(days=1)
    return windows


def _normalize_frame(bars: list[Any]) -> pd.DataFrame:
    """Normalise a list of LongPort Candlestick objects to OHLCV schema.

    Args:
        bars: List of candlestick objects returned by the SDK.

    Returns:
        DataFrame with columns [open, high, low, close, volume] indexed
        by ``trade_date`` (timezone-naive DatetimeIndex), sorted ascending.
    """
    if not bars:
        return pd.DataFrame(columns=_OHLCV_COLUMNS)

    rows = []
    for bar in bars:
        ts = getattr(bar, "timestamp", None)
        rows.append({
            "open": float(getattr(bar, "open", 0) or 0),
            "high": float(getattr(bar, "high", 0) or 0),
            "low": float(getattr(bar, "low", 0) or 0),
            "close": float(getattr(bar, "close", 0) or 0),
            "volume": float(getattr(bar, "volume", 0) or 0),
            "trade_date": pd.to_datetime(ts) if ts is not None else pd.NaT,
        })

    result = pd.DataFrame(rows)
    result.index = result["trade_date"]
    result.index.name = "trade_date"
    result = result[_OHLCV_COLUMNS].copy()

    # Standardise to timezone-naive UTC. Aware timestamps may be represented
    # in an exchange timezone by SDK versions even when the instant is UTC.
    if isinstance(result.index, pd.DatetimeIndex) and result.index.tz is not None:
        result.index = result.index.tz_convert("UTC").tz_localize(None)

    result = result.dropna(subset=["open", "high", "low", "close"])
    result["volume"] = result["volume"].fillna(0.0)
    return result.sort_index()


@register
class LongbridgeLoader:
    """Fetch US and HK equity bars from LongPort OpenAPI.

    Resolves one atomic credential set from the ``LONGBRIDGE_*`` environment
    variables or the backward-compatible runtime file.
    """

    name = "longbridge"
    markets = {"us_equity", "hk_equity"}
    requires_auth = True

    def __init__(self) -> None:
        try:
            resolution = resolve_longbridge_credentials()
        except LongbridgeCredentialError as exc:
            self._credential_source = None
            self._credential_error = exc
            self._app_key = self._app_secret = self._access_token = ""
            return
        self._credential_source = resolution.source
        self._credential_error: LongbridgeCredentialError | None = None
        if resolution.credentials is None:
            if resolution.conflict_fields:
                code = "credentials_conflict"
                fields = resolution.conflict_fields
            else:
                code = (
                    "credentials_missing"
                    if resolution.source is None
                    else "credentials_partial"
                )
                fields = resolution.missing_fields
            self._credential_error = LongbridgeCredentialError(code, fields)
            self._app_key = self._app_secret = self._access_token = ""
            return

        credentials = resolution.credentials
        self._app_key = credentials.app_key
        self._app_secret = credentials.app_secret
        self._access_token = credentials.access_token

    def is_available(self) -> bool:
        """Return True if the LongPort SDK is installed and credentials exist.

        Availability checks are side-effect free: they validate configured
        credentials and SDK importability without consuming quote API quota.
        """
        if not (self._app_key and self._app_secret and self._access_token):
            return False
        try:
            _require_longbridge()
            return True
        except Exception:
            return False

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV history from LongPort OpenAPI.

        Args:
            codes: Project symbols such as ``AAPL``, ``AAPL.US``, ``700.HK``,
                ``000001.SZ`` or ``600519.SH``.
            start_date: Start date in ``YYYY-MM-DD`` format.
            end_date: End date in ``YYYY-MM-DD`` format.
            interval: Backtest interval — ``1D``, ``1W``, ``1M``, ``1H``.
            fields: Ignored; included for interface compatibility.

        Returns:
            Mapping of input symbol to normalised OHLCV dataframe.

        Raises:
            NoAvailableSourceError: If the SDK connection fails or
                credentials are missing.
        """
        del fields
        if not codes:
            return {}
        validate_date_range(start_date, end_date)

        results: dict[str, pd.DataFrame] = {}

        # Serve cached symbols first; only open an SDK connection when at
        # least one symbol is uncached, so a fully-cached request needs no
        # network call.
        pending: List[str] = []
        for code in codes:
            cached = loader_cache_get(
                source=self.name,
                symbol=code,
                timeframe=interval,
                start_date=start_date,
                end_date=end_date,
                fields=None,
            )
            if cached is not None:
                results[code] = cached.copy()
            else:
                pending.append(code)

        if not pending:
            return results

        credential_error = getattr(self, "_credential_error", None)
        if credential_error is not None:
            if credential_error.code == "credentials_missing":
                message = (
                    "Longbridge credentials are not configured; missing fields: "
                    + ", ".join(credential_error.fields)
                )
            elif credential_error.code == "credentials_partial":
                message = (
                    "Longbridge credentials_partial; missing fields: "
                    + ", ".join(credential_error.fields)
                )
            else:
                message = (
                    "Longbridge credentials_conflict; differing fields: "
                    + ", ".join(credential_error.fields)
                )
            raise NoAvailableSourceError(message) from None
        if not (self._app_key and self._app_secret and self._access_token):
            raise NoAvailableSourceError(
                "Longbridge credentials are not configured; set "
                "LONGBRIDGE_APP_KEY, LONGBRIDGE_APP_SECRET, and "
                "LONGBRIDGE_ACCESS_TOKEN"
            )

        openapi = _require_longbridge()
        _init_error: str | None = None
        try:
            cfg = openapi.Config(
                self._app_key, self._app_secret, self._access_token,
            )
            ctx = openapi.QuoteContext(cfg)
        except LongbridgeDependencyError:
            raise
        except Exception:
            # Capture only stable text; do NOT raise inside the handler so
            # the original exception (which may contain secrets) cannot
            # leak into __context__.
            _init_error = "Longbridge SDK initialization failed."

        if _init_error is not None:
            raise NoAvailableSourceError(_init_error)

        period = _to_longport_period(interval)
        adjust_type = getattr(openapi, "AdjustType").NoAdjust
        try:
            start = dt.date.fromisoformat(start_date)
            end = dt.date.fromisoformat(end_date)
        except (TypeError, ValueError):
            raise NoAvailableSourceError(
                "Invalid Longbridge date range."
            ) from None

        windows = _date_windows(start, end)

        try:
            for code in pending:
                lp_symbol = _to_longport_symbol(code)
                all_bars: list[Any] = []
                _window_error: str | None = None
                for w_start, w_end in windows:
                    try:
                        bars = ctx.history_candlesticks_by_date(
                            lp_symbol, period, adjust_type,
                            start=w_start, end=w_end,
                        )
                        if isinstance(bars, (list, tuple)):
                            all_bars.extend(bars)
                        elif bars is not None:
                            all_bars.append(bars)
                    except Exception:
                        _window_error = "Longbridge history request failed."
                        break
                else:
                    _window_error = None

                if _window_error is not None:
                    raise NoAvailableSourceError(_window_error)

                if not all_bars:
                    logger.warning(
                        "LongPort returned no data for %s in [%s, %s]",
                        lp_symbol, start_date, end_date,
                    )
                    continue

                normalized = _normalize_frame(all_bars)
                loader_cache_put(
                    source=self.name,
                    symbol=code,
                    timeframe=interval,
                    start_date=start_date,
                    end_date=end_date,
                    fields=None,
                    frame=normalized,
                )
                results[code] = normalized
        finally:
            # LongPort QuoteContext has no explicit close(); the SDK manages
            # its own connection pool. No cleanup needed.
            pass

        return results
