"""TickerAll hosted MetaTrader 5 data loader - forex/metals/CFD OHLCV over HTTP.

TickerAll (https://tickerall.com) is a hosted MetaTrader 5 API: it serves a
broker account's own candle history over REST, so backtests can pull forex,
metals, and index/CFD bars with the broker's exact symbols and session times
WITHOUT a local MetaTrader 5 terminal - no Windows, no Wine, no VM. It
complements the ``mt5`` loader (which needs a running, logged-in local terminal)
by covering the same forex market from any operating system.

Selection (opt-in, EXPLICIT-only): this loader is NOT part of any automatic
fallback chain. It runs only when a backtest names ``source="tickerall"``
explicitly, and only when ``TICKERALL_API_KEY`` and ``TICKERALL_ACCOUNT_ID`` are
configured (an account id is required because history is served per connected
account). When either is unset, :meth:`DataLoader.is_available` is ``False``.
``TICKERALL_BASE_URL`` overrides the endpoint (defaults to the public API). Never
joining the automatic chain keeps a user's own broker credential off the default
path: it is used only when the operator deliberately asks for it.

Read-only + scoped: every request this module issues is an HTTP **GET** to a
read endpoint (``/candles``, ``/symbols``) for the single configured account.
There is no trade, order, or account-mutation code path here - the credential is
used read-only and scoped to one account. Provision a dedicated, least-privilege
TickerAll key for backtesting.

API format (Bearer-authenticated), date-range mode:
  ``GET {base}/v1/accounts/{account_id}/candles?symbol=SYM&from=ISO&to=ISO&timeframe=TF``
returns ``{candles: [{timestamp, open, high, low, close, tickVolume}, ...],
truncated: bool, coverage: "complete"|..., stopReason: str, ...}`` with
``timestamp`` in epoch seconds. The endpoint answers the exact ``[from, to]``
window and reports whether it could serve the whole of it. **A partial answer is
an error, not a silently short series** - and the endpoint signals incompleteness
two ways, BOTH of which raise :class:`IncompleteHistoryError` (so the caller narrows
the range rather than backtesting on a quietly-clipped series):
  (a) a served (200) response flagged ``truncated`` (the history walk stopped early);
  (b) a 400 ``{"error": "range_too_large", "maxWindowDays", "maxBars"}`` when the
      requested window is wider than one request may carry (e.g. > ~5 years of daily
      bars). Without (b) this 400 would be swallowed as a skipped symbol - the exact
      silent-truncation this loader must avoid.

Broker account-type suffixes (e.g. Exness ``EURUSDm``) are resolved from the
account's own symbol list (fetched once and memoized per ``(base_url, account)``),
so callers pass plain codes (``EURUSD``, ``EUR/USD``) and results are keyed by
the ORIGINAL input code.

Every request routes through :mod:`backtest.loaders._http` so calls share one
process-wide minimum-spacing gate and a reused session.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

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

#: The candles endpoint runs a deep-history walk for a multi-year window, which can
#: take well over the shared 15s default. Give it room: a too-short read timeout would
#: otherwise surface as a swallowed per-symbol skip (a silent gap) on a large window -
#: exactly the quiet-failure this loader is meant to avoid.
_CANDLES_TIMEOUT_S = 90.0

#: Project interval token → TickerAll timeframe token. Lowercase ``1h``/``4h``/
#: ``1d``/``1w`` alias the project-style tokens; ``1m`` (minute) and ``1M``
#: (month) differ by case, matching the ``mt5`` loader.
_INTERVAL_MAP = {
    "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
    "1H": "H1", "1h": "H1", "4H": "H4", "4h": "H4",
    "1D": "D1", "1d": "D1", "1W": "W1", "1w": "W1", "1M": "MN1",
}

# TickerAll candles carry these numeric fields; emitted in this column order.
_OHLCV_FIELDS = ("open", "high", "low", "close", "volume")

#: (base_url, account_id) → broker symbol names memo (mt5 ``symbols_get`` parity).
#: Keyed by BOTH base URL and account so two accounts - or the same account id on
#: a different endpoint (staging vs prod) - never share a resolution.
_symbol_cache: Dict[Tuple[str, str], List[str]] = {}


class IncompleteHistoryError(RuntimeError):
    """The API could not serve the whole requested window (a partial/truncated walk).

    Raised instead of returning a silently-short series, so a backtest fails
    loudly and the caller can narrow the date range or lower the timeframe.
    """


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


def _base_host(base_url: str) -> str:
    """Host[:port] of a base URL - the stable part of the cache identity."""
    netloc = urlsplit(base_url).netloc
    return netloc or base_url


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
    """Broker symbol names for one account, fetched once and memoized ([] on failure).

    Memoized per ``(base_url, account_id)`` so the same account id on two
    endpoints - or two accounts - never share a resolution.
    """
    base = _base_url()
    cache_key = (base, account_id)
    cached = _symbol_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        payload = throttled_get_json(
            f"{base}/v1/accounts/{account_id}/symbols",
            host_key=_HOST_KEY,
            min_interval=_min_interval(),
            headers=_auth_headers(api_key),
        )
        names = _symbol_names(payload)
    except Exception as exc:  # noqa: BLE001 - symbol resolution is best-effort
        logger.debug("tickerall: symbol list unavailable: %s", exc)
        names = []
    _symbol_cache[cache_key] = names
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

        A transient per-symbol failure (network blip, one bad symbol) logs and
        skips so it never poisons the batch. An :class:`IncompleteHistoryError`
        (the API served only part of the requested window) is NOT swallowed - it
        propagates so the backtest fails loudly instead of running on a quietly
        clipped series.

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
            IncompleteHistoryError: If the API could not serve the whole
                requested window for a symbol (truncated / partial coverage).
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

        # Cache identity includes the account id + base host, so two accounts - or
        # the same account on a different endpoint - never collide in the local
        # loader cache (the on-disk key is a hash of these fields).
        account_id = _account_id()
        cache_scope = f"{account_id}@{_base_host(_base_url())}"

        result: Dict[str, pd.DataFrame] = {}
        for code in codes:
            clean = code.strip()
            if not clean:
                continue
            try:
                frame = cached_loader_fetch(
                    source=self.name,
                    symbol=f"{cache_scope}:{_to_query_base(clean)}",
                    timeframe=interval,
                    start_date=start_date,
                    end_date=end_date,
                    fields=None,
                    fetch=lambda c=clean: self._fetch_one(c, start_date, end_date, timeframe),
                )
            except IncompleteHistoryError:
                # A partial window is a hard error - fail loud, never a short series.
                raise
            except Exception as exc:  # noqa: BLE001 - one symbol never poisons the batch
                logger.warning("tickerall failed for %s: %s", clean, exc)
                continue
            if frame is not None and not frame.empty:
                result[code] = frame
        return result

    def _fetch_one(
        self, code: str, start_date: str, end_date: str, timeframe: str
    ) -> Optional[pd.DataFrame]:
        """Fetch and parse one symbol's bars over HTTP; ``None`` on no data.

        Uses the endpoint's exact date-range mode (``from``/``to``) and honors its
        completeness signal: a truncated/partial answer raises
        :class:`IncompleteHistoryError` rather than returning a short frame.
        """
        api_key = _api_key()
        account_id = _account_id()
        if not (api_key and account_id):
            return None
        symbol = _resolve_symbol(_to_query_base(code), account_id, api_key)
        if not symbol:
            return None
        try:
            payload = throttled_get_json(
                f"{_base_url()}/v1/accounts/{account_id}/candles",
                host_key=_HOST_KEY,
                min_interval=_min_interval(),
                headers=_auth_headers(api_key),
                params={
                    "symbol": symbol,
                    "from": f"{start_date}T00:00:00Z",
                    "to": f"{end_date}T23:59:59Z",
                    "timeframe": timeframe,
                },
                timeout=_CANDLES_TIMEOUT_S,
            )
        except Exception as exc:  # noqa: BLE001 - inspected, then re-raised
            # A 'range_too_large' 400 = the window is wider than one request may carry;
            # that is INCOMPLETE history, so surface it loudly instead of letting the
            # batch loop swallow it as a skipped symbol. Anything else propagates.
            _reraise_if_range_too_large(exc, symbol, start_date, end_date)
            raise
        _raise_if_incomplete(payload, symbol, start_date, end_date)
        return _parse_candles(payload, start_date, end_date)


def _reraise_if_range_too_large(exc: Exception, symbol: str, start_date: str, end_date: str) -> None:
    """Convert the endpoint's ``range_too_large`` 400 into :class:`IncompleteHistoryError`.

    A window wider than the endpoint's per-request limit is rejected up front with
    HTTP 400 ``{"error": "range_too_large", "maxWindowDays": N, "maxBars": M}`` (NOT a
    200 with ``truncated``). That is the caller asking for more history than one
    request can carry - an incomplete answer - so it must fail loudly rather than be
    swallowed as a transient per-symbol skip. Any other error is left to propagate
    unchanged (the batch loop then skips just that symbol). Duck-typed on ``.response``
    so the loader needs no ``requests`` import.
    """
    resp = getattr(exc, "response", None)
    if resp is None or getattr(resp, "status_code", None) != 400:
        return
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001 - a non-JSON 400 is not our signal
        return
    if not isinstance(body, dict) or body.get("error") != "range_too_large":
        return
    raise IncompleteHistoryError(
        f"tickerall: the requested window for {symbol} [{start_date}, {end_date}] exceeds the "
        f"API's per-request limit (max {body.get('maxWindowDays')} days / {body.get('maxBars')} bars); "
        f"narrow the date range or use a coarser timeframe"
    ) from exc


def _raise_if_incomplete(payload: Any, symbol: str, start_date: str, end_date: str) -> None:
    """Raise :class:`IncompleteHistoryError` when a 200 response served only part of the window.

    On a served (200) response the endpoint reports ``truncated`` (the authoritative
    signal: the history walk could not cover the whole requested range) plus a
    ``coverage`` string (``"complete"`` when whole; a non-complete value otherwise).
    Either means the answer is short of what was asked. ``stopReason`` says why. (The
    other incompleteness path - a window wider than one request may carry - is a 400
    handled by :func:`_reraise_if_range_too_large`.)
    """
    if not isinstance(payload, dict):
        return
    truncated = bool(payload.get("truncated"))
    coverage = payload.get("coverage")
    incomplete_coverage = isinstance(coverage, str) and coverage not in ("complete", "full")
    if not (truncated or incomplete_coverage):
        return
    reason = payload.get("stopReason") or ("partial" if incomplete_coverage else "truncated")
    raise IncompleteHistoryError(
        f"tickerall: incomplete history for {symbol} over [{start_date}, {end_date}] "
        f"(stopReason={reason}); narrow the date range or use a coarser timeframe"
    )


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

    # The endpoint answers the exact [from, to] window; trim defensively to the
    # inclusive window (end inclusive of its whole day) in case an edge bar slips in.
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1)
    df = df[(df.index >= start_ts) & (df.index < end_ts)]
    if df.empty:
        return None
    return df
