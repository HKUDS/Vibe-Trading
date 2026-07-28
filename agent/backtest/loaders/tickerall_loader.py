"""TickerAll hosted MetaTrader 5 data loader - forex/metals/CFD OHLCV over HTTP.

TickerAll (https://tickerall.com) is a hosted MetaTrader 5 API: it serves a
broker account's own candle history over REST, so backtests can pull forex,
metals, and index/CFD bars with the broker's exact symbols and session times
WITHOUT a local MetaTrader 5 terminal - no Windows, no Wine, no VM. It
complements the ``mt5`` loader (which needs a running, logged-in local terminal)
by covering the same forex market from any operating system.

Auth (opt-in): set ``TICKERALL_API_KEY`` and ``TICKERALL_ACCOUNT_ID`` in the
environment - an account id is required because history is served per connected
account. When either is unset, :meth:`DataLoader.is_available` is ``False`` and
the forex fallback chain degrades to ``mt5``/``akshare``/``yfinance``/``local``.
``TICKERALL_BASE_URL`` overrides the endpoint (defaults to the public API).

API format (Bearer-authenticated):
  ``GET {base}/v1/accounts/{account_id}/candles?symbol=SYM&hours=N&timeframe=TF``
returns ``[{timestamp, open, high, low, close, tickVolume}, ...]`` with
``timestamp`` in epoch seconds. The endpoint takes a relative ``hours`` lookback,
so the requested ``[start_date, end_date]`` window is converted to an hours span
and the response is trimmed back to the window. History depth is bounded by the
endpoint's per-request bar cap; for a deep multi-year window this returns the
most recent bars within that cap.

Broker account-type suffixes (e.g. Exness ``EURUSDm``) are resolved from the
account's own symbol list (fetched once and memoized), so callers pass plain
codes (``EURUSD``, ``EUR/USD``) and results are keyed by the ORIGINAL input code.

Every request routes through :mod:`backtest.loaders._http` so calls share one
process-wide minimum-spacing gate and a reused session.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest.loaders._http import resolve_min_interval, throttled_get_json
from backtest.loaders.base import cached_loader_fetch, validate_date_range
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_API_KEY_ENV = "TICKERALL_API_KEY"
_ACCOUNT_ENV = "TICKERALL_ACCOUNT_ID"
_DEFAULT_BASE_URL = "https://api.tickerall.com"

# Shared throttle/session bucket for every TickerAll request in this process.
_HOST_KEY = "tickerall"
_MIN_INTERVAL_ENV = "VIBE_TRADING_TICKERALL_MIN_INTERVAL"
_DEFAULT_MIN_INTERVAL_S = 0.25

#: Project interval token → TickerAll timeframe token. Lowercase ``1h``/``4h``/
#: ``1d``/``1w`` alias the project-style tokens; ``1m`` (minute) and ``1M``
#: (month) differ by case, matching the ``mt5`` loader.
_INTERVAL_MAP = {
    "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
    "1H": "H1", "1h": "H1", "4H": "H4", "4h": "H4",
    "1D": "D1", "1d": "D1", "1W": "W1", "1w": "W1", "1M": "MN1",
}

#: Nominal seconds per timeframe, used only to pick a sensible minimum lookback
#: when the requested start is in the future.
_TF_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800, "MN1": 2592000,
}

#: Relative-lookback ceiling accepted by the endpoint (~5 years in hours).
_MAX_HOURS = 43800

# TickerAll candles carry these numeric fields; emitted in this column order.
_OHLCV_FIELDS = ("open", "high", "low", "close", "volume")

#: account_id → broker symbol names memo (mt5 ``symbols_get`` parity).
_symbol_cache: Dict[str, List[str]] = {}


def _api_key() -> str:
    """Return the TickerAll API key from config, stripped (``""`` if unset)."""
    from src.config.accessor import get_env_config

    return get_env_config().data.tickerall_api_key.strip()


def _account_id() -> str:
    """Return the configured TickerAll account id, stripped (``""`` if unset)."""
    from src.config.accessor import get_env_config

    return get_env_config().data.tickerall_account_id.strip()


def _base_url() -> str:
    """Return the API base URL (config override or the public default), no trailing slash."""
    from src.config.accessor import get_env_config

    raw = (get_env_config().data.tickerall_base_url or "").strip()
    return (raw or _DEFAULT_BASE_URL).rstrip("/")


def _min_interval() -> float:
    """Resolve the per-call minimum spacing, honoring the env override."""
    return resolve_min_interval(_MIN_INTERVAL_ENV, _DEFAULT_MIN_INTERVAL_S)


def _auth_headers(api_key: str) -> Dict[str, str]:
    """Bearer auth headers for the hosted API."""
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _to_query_base(code: str) -> str:
    """``EUR/USD`` / ``EURUSD.FX`` → ``EURUSD`` (upper, separators stripped)."""
    token = code.strip().upper()
    if token.endswith(".FX"):
        token = token[: -len(".FX")]
    for separator in ("/", "-", "_", " "):
        token = token.replace(separator, "")
    return token


def _resolve_symbol(base: str, account_id: str, api_key: str) -> str:
    """Map a base symbol to the account's exact broker symbol (Exness ``EURUSDm``).

    Mirrors mt5's ``symbols_get(f"{base}*")`` resolution against the account's
    memoized symbol list: an exact normalized match first, else a normalized
    prefix match, shortest broker name winning (so ``EURUSDm`` beats ``EURUSDz``).
    Falls back to ``base`` when the list is unavailable or has no match.
    """
    names = _account_symbols(account_id, api_key)
    if not names:
        return base
    exact = [n for n in names if _to_query_base(n) == base]
    if exact:
        return min(exact, key=lambda n: (len(n), n))
    prefixed = [n for n in names if _to_query_base(n).startswith(base)]
    if prefixed:
        return min(prefixed, key=lambda n: (len(n), n))
    return base


def _account_symbols(account_id: str, api_key: str) -> List[str]:
    """Broker symbol names for one account, fetched once and memoized ([] on failure)."""
    cached = _symbol_cache.get(account_id)
    if cached is not None:
        return cached
    try:
        payload = throttled_get_json(
            f"{_base_url()}/v1/accounts/{account_id}/symbols",
            host_key=_HOST_KEY,
            min_interval=_min_interval(),
            headers=_auth_headers(api_key),
        )
        names = _symbol_names(payload)
    except Exception as exc:  # noqa: BLE001 - symbol resolution is best-effort
        logger.debug("tickerall: symbol list unavailable: %s", exc)
        names = []
    _symbol_cache[account_id] = names
    return names


def _symbol_names(payload: Any) -> List[str]:
    """Extract symbol name strings from a /symbols body (array or {symbols|data})."""
    items = payload
    if isinstance(payload, dict):
        items = payload.get("symbols") or payload.get("data") or []
    names: List[str] = []
    for item in items or []:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            name = item.get("symbol") or item.get("name")
            if isinstance(name, str):
                names.append(name)
    return names


@register
class DataLoader:
    """TickerAll hosted-MT5 forex/metals OHLCV loader (key-gated, HTTP, no terminal)."""

    name = "tickerall"
    markets = {"forex"}
    #: The hosted API key + account id are the auth surface (fmp/mt5 precedent).
    requires_auth = True

    def __init__(self) -> None:  # never raises - registry availability contract
        pass

    def is_available(self) -> bool:
        """Available when both ``TICKERALL_API_KEY`` and ``TICKERALL_ACCOUNT_ID`` are set."""
        return bool(_api_key() and _account_id())

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch OHLCV frames keyed by the original input codes.

        Per-symbol failures log and skip (never raise) so the runner's runtime
        fallback can engage for the missing symbols.

        Args:
            codes: Project symbols (e.g. ``["EURUSD", "XAUUSD"]``).
            start_date: Inclusive start date, ``YYYY-MM-DD``.
            end_date: Inclusive end date, ``YYYY-MM-DD``.
            interval: Bar size token (``1m``/``5m``/``15m``/``30m``/``1H``/``4H``/
                ``1D``/``1W``/``1M``); unknown tokens are rejected.
            fields: Ignored - the API returns a fixed OHLCV schema.

        Returns:
            Mapping ``{symbol: DataFrame(trade_date, open, high, low, close,
            volume)}`` for every symbol that returned non-empty data.

        Raises:
            ValueError: If ``start_date`` > ``end_date`` (via
                :func:`validate_date_range`).
        """
        validate_date_range(start_date, end_date)
        timeframe = _INTERVAL_MAP.get(str(interval).strip())
        if timeframe is None:
            # Reject unknown tokens; do not silently fetch D1 under the caller's key.
            logger.warning("tickerall unsupported interval %r; rejecting", interval)
            return {}
        if not self.is_available():
            logger.warning("tickerall fetch skipped: %s / %s not set", _API_KEY_ENV, _ACCOUNT_ENV)
            return {}

        result: Dict[str, pd.DataFrame] = {}
        for code in codes:
            clean = code.strip()
            if not clean:
                continue
            try:
                frame = cached_loader_fetch(
                    source=self.name,
                    symbol=_to_query_base(clean),
                    timeframe=interval,
                    start_date=start_date,
                    end_date=end_date,
                    fields=None,
                    fetch=lambda c=clean: self._fetch_one(c, start_date, end_date, timeframe),
                )
            except Exception as exc:  # noqa: BLE001 - one symbol never poisons the batch
                logger.warning("tickerall failed for %s: %s", clean, exc)
                continue
            if frame is not None and not frame.empty:
                result[code] = frame
        return result

    def _fetch_one(
        self, code: str, start_date: str, end_date: str, timeframe: str
    ) -> Optional[pd.DataFrame]:
        """Fetch and parse one symbol's bars over HTTP; ``None`` on no data."""
        api_key = _api_key()
        account_id = _account_id()
        if not (api_key and account_id):
            return None
        symbol = _resolve_symbol(_to_query_base(code), account_id, api_key)
        if not symbol:
            return None
        payload = throttled_get_json(
            f"{_base_url()}/v1/accounts/{account_id}/candles",
            host_key=_HOST_KEY,
            min_interval=_min_interval(),
            headers=_auth_headers(api_key),
            params={
                "symbol": symbol,
                "hours": _window_to_hours(start_date, end_date, timeframe),
                "timeframe": timeframe,
            },
        )
        return _parse_candles(payload, start_date, end_date)


def _window_to_hours(start_date: str, end_date: str, timeframe: str) -> int:
    """Convert a ``[start, end]`` window into the endpoint's relative ``hours`` lookback.

    The endpoint counts back from *now*, so we request from ``start_date`` to now
    (capped at :data:`_MAX_HOURS`) and trim the response to the window in
    :func:`_parse_candles`.
    """
    try:
        start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    except ValueError:
        return _MAX_HOURS
    span_seconds = (datetime.now(timezone.utc) - start).total_seconds()
    if span_seconds <= 0:
        # start is in the future: request a minimal but useful lookback.
        span_seconds = _TF_SECONDS.get(timeframe, 86400) * 2
    hours = int(span_seconds // 3600) + 1
    return max(1, min(hours, _MAX_HOURS))


def _parse_candles(
    payload: Any, start_date: str, end_date: str
) -> Optional[pd.DataFrame]:
    """Convert a TickerAll candles body into an ascending OHLCV frame, trimmed to the window.

    Args:
        payload: Decoded JSON body (a list, or ``{candles|data: [...]}``) where
            each bar has ``timestamp`` (epoch seconds) plus ``open/high/low/close``
            and ``volume`` or ``tickVolume``.
        start_date: Inclusive window start, ``YYYY-MM-DD``.
        end_date: Inclusive window end, ``YYYY-MM-DD``.

    Returns:
        DataFrame indexed by ``trade_date`` with float ``open/high/low/close/
        volume`` columns, or ``None`` when no usable in-window rows are present.
    """
    items = payload
    if isinstance(payload, dict):
        items = payload.get("candles") or payload.get("data") or []
    if not items:
        return None

    rows = []
    for bar in items:
        if not isinstance(bar, dict) or "timestamp" not in bar:
            continue
        volume = bar.get("volume")
        if volume is None:
            volume = bar.get("tickVolume")
        rows.append(
            {
                "trade_date": bar["timestamp"],
                "open": bar.get("open"),
                "high": bar.get("high"),
                "low": bar.get("low"),
                "close": bar.get("close"),
                "volume": volume,
            }
        )
    if not rows:
        return None

    df = pd.DataFrame(rows)
    # timestamp is epoch seconds; index is tz-naive UTC to match the other loaders.
    df["trade_date"] = pd.to_datetime(df["trade_date"], unit="s", utc=True).dt.tz_localize(None)
    for field in _OHLCV_FIELDS:
        # Cast to float (not just to_numeric) so integer tick volume does not
        # leave the column int64 and break the float-OHLCV contract.
        df[field] = pd.to_numeric(df[field], errors="coerce").astype(float)

    df = df.set_index("trade_date").sort_index()
    df = df[list(_OHLCV_FIELDS)].dropna(subset=["open", "high", "low", "close"])

    # Trim the relative-lookback response to the requested inclusive window
    # (end inclusive of its whole day).
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1)
    df = df[(df.index >= start_ts) & (df.index < end_ts)]
    if df.empty:
        return None
    return df
