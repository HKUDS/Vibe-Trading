"""Stooq loader: free, no-auth US-equity EOD OHLCV via CSV download.

Stooq publishes free end-of-day bars from a plain CSV endpoint
(``https://stooq.com/q/d/l/``) with no API key. Like other free quote
providers it rate-limits by source IP and must be throttled, so every request
routes through :mod:`backtest.loaders._http` (shared per-host spacing + session
reuse) under the ``"stooq"`` host bucket.

API format:
  https://stooq.com/q/d/l/?s=aapl.us&d1=20240101&d2=20240131&i=d

Symbol convention (Vibe-Trading -> Stooq):
  * ``AAPL.US`` -> ``aapl.us`` (Stooq tickers are lowercase; the ``.US`` market
    suffix is kept, just lower-cased).

Response body is CSV ``Date,Open,High,Low,Close,Volume``. An unknown symbol or
empty window yields the literal ``"N/D"`` or an empty body, both treated as
"no data" for that symbol (skipped, never fatal to the batch).

A refusal is not CSV: the endpoint answers a blocked client with a proof-of-work
challenge page, a plain-text quota message, or a bare 403/429. Those latch the
source off for a cooldown instead of parsing as "no data" (see ``_denial_reason``).
"""

from __future__ import annotations

import io
import logging
import time
from threading import Lock
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest.loaders._http import resolve_min_interval, throttled_get
from backtest.loaders.base import cached_loader_fetch, validate_date_range
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_BASE_URL = "https://stooq.com/q/d/l/"
HOST_KEY = "stooq"

_MIN_INTERVAL_ENV = "VIBE_TRADING_STOOQ_MIN_INTERVAL"
_DEFAULT_MIN_INTERVAL_S = 0.6

# Stooq refuses non-browser clients in more than one way: a JavaScript
# proof-of-work challenge page (HTTP 200, HTML body), the plain-text quota
# refusal its free CSV endpoint serves once the per-IP limit trips, or a bare
# 403/429. Without detection the loader parses the body as "no data" and the
# fallback chain slides past a source that never serves, with nothing in the run
# log to show for it. This deadline is the process-wide latch behind that
# warning: while it lies in the future no further symbol is probed, because a
# second request can only be answered the same way. It expires rather than
# latching for the process lifetime, so one transient block does not downgrade
# stooq for as long as ``vibe-trading serve`` happens to run.
_challenge_until = 0.0
# How long a latched process waits before it probes Stooq again.
_LATCH_COOLDOWN_S = 300.0
# Serialize each process-local probe with the latch check. Otherwise callers
# already waiting in the shared HTTP throttle can send after another caller
# discovers that Stooq is refusing requests.
_probe_lock = Lock()

# Refusals that arrive without an error status. Matched against the head of the
# body only, so a CSV row can never trip them.
_DENIAL_STATUS_CODES = frozenset({403, 429})
_DENIAL_TEXT_MARKERS = (
    "exceeded the daily hits limit",
    "daily hits limit",
    "too many requests",
)


def _looks_like_challenge_page(body: str) -> bool:
    text = (body or "").lstrip().lower()
    return text.startswith("<") or "challenge" in text[:2000] or "proof of work" in text[:2000]


def _denial_reason(response: Any) -> Optional[str]:
    """Return a short reason when the response is a refusal, else ``None``.

    Args:
        response: The HTTP response from Stooq's CSV endpoint.

    Returns:
        A human-readable cause when the source is refusing this client -- a
        403/429 status, the proof-of-work challenge page, or the plain-text
        quota message -- otherwise ``None`` for a response worth parsing. An
        ordinary "no data" body (``N/D``, empty) is not a refusal.
    """
    if response.status_code in _DENIAL_STATUS_CODES:
        return f"HTTP {response.status_code}"
    body = response.text or ""
    if _looks_like_challenge_page(body):
        return "anti-bot challenge page"
    head = body.lstrip().lower()[:2000]
    for marker in _DENIAL_TEXT_MARKERS:
        if marker in head:
            return f"refusal text {marker!r}"
    return None


def _latch(reason: str) -> None:
    """Stop probing for the cooldown and tell the operator why."""
    global _challenge_until
    _challenge_until = time.monotonic() + _LATCH_COOLDOWN_S
    logger.warning(
        "stooq is unavailable to this process (%s); skipping it for %g seconds. "
        "Move stooq to the end of the chain via MARKET_DATA_ORDER_* (e.g. "
        "MARKET_DATA_ORDER_US_EQUITY); the override must be a permutation of the "
        "default chain, so a source can be reordered but not removed.",
        reason,
        _LATCH_COOLDOWN_S,
    )

# Stooq's CSV header columns mapped to our output field names.
_COLUMN_MAP = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume",
}
_OUTPUT_COLUMNS = ["open", "high", "low", "close", "volume"]


def _min_interval() -> float:
    """Resolve the per-call minimum spacing, honoring the env override."""
    return resolve_min_interval(_MIN_INTERVAL_ENV, _DEFAULT_MIN_INTERVAL_S)


def map_symbol(symbol: str) -> str:
    """Translate a Vibe-Trading symbol into Stooq's ticker convention.

    Args:
        symbol: Project-side symbol, e.g. ``AAPL.US``.

    Returns:
        The lower-cased Stooq ticker, e.g. ``aapl.us``.
    """
    return symbol.strip().lower()


def _compact_date(value: str) -> str:
    """Render a date string as Stooq's ``YYYYMMDD`` form."""
    return pd.Timestamp(value).strftime("%Y%m%d")


@register
class DataLoader:
    """Stooq US-equity EOD OHLCV loader (free, HTTP CSV, no auth)."""

    name = "stooq"
    markets = {"us_equity"}
    # Stooq US EOD volume is single shares (universal US convention,
    # HKUDS/Vibe-Trading#1062).
    volume_units = {"us_equity": "shares"}
    requires_auth = False

    def __init__(self) -> None:
        pass

    def is_available(self) -> bool:
        """Always available — uses plain throttled HTTP, no credentials."""
        return True

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch daily OHLCV bars for ``codes`` over ``[start_date, end_date]``.

        Args:
            codes: Project-side symbols (e.g. ``["AAPL.US", "MSFT.US"]``).
            start_date: Inclusive start date (``YYYY-MM-DD``).
            end_date: Inclusive end date (``YYYY-MM-DD``).
            interval: Bar size; only daily (``"1D"``) is supported. Other
                intervals return an empty map so the fallback chain can continue.
            fields: Unused — the CSV always carries the full OHLCV set.

        Returns:
            Mapping ``{symbol: DataFrame}`` for symbols that returned data. Each
            frame has a ``DatetimeIndex`` named ``trade_date`` and float columns
            ``open/high/low/close/volume`` in ascending date order. A symbol that
            errors or has no data is omitted, never aborting the batch.

        Raises:
            ValueError: If ``start_date > end_date`` or a date is unparseable.
        """
        validate_date_range(start_date, end_date)

        # Daily-only CSV endpoint; do not silently return day bars for ``1H``.
        if str(interval).strip().lower() not in {"1d", "d", "day", "daily"}:
            logger.warning(
                "stooq supports daily bars only; rejecting interval=%r",
                interval,
            )
            return {}

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
                    fetch=lambda code=code: self._fetch_one(code, start_date, end_date),
                )
                if df is not None and not df.empty:
                    result[code] = df
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not abort the batch
                logger.warning("stooq failed for %s: %s", code, exc)
        return result

    def _fetch_one(
        self, code: str, start_date: str, end_date: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch and parse one symbol's CSV; ``None`` when Stooq has no data."""
        with _probe_lock:
            if _challenge_until > time.monotonic():
                # Latched by an earlier probe: the warning already told the
                # operator the source is unavailable, and a second request can
                # only be answered the same way. Probing resumes once the
                # cooldown expires.
                return None
            params = {
                "s": map_symbol(code),
                "d1": _compact_date(start_date),
                "d2": _compact_date(end_date),
                "i": "d",
            }
            response = throttled_get(
                _BASE_URL,
                host_key=HOST_KEY,
                min_interval=_min_interval(),
                params=params,
            )
            # Check for a refusal before ``raise_for_status()``: a 403/429 is the
            # source blocking this client, not one symbol failing, and letting it
            # raise would spend one throttled request on every remaining symbol.
            reason = _denial_reason(response)
            if reason is not None:
                _latch(reason)
                return None
            response.raise_for_status()
            body = response.text
        return _parse_csv(body)


def _parse_csv(body: str) -> Optional[pd.DataFrame]:
    """Convert a Stooq EOD CSV body into our OHLCV frame, ``None`` on no data.

    Args:
        body: Raw CSV text ``Date,Open,High,Low,Close,Volume``. An empty body or
            the sentinel ``"N/D"`` (unknown symbol / empty window) means no data.

    Returns:
        A frame indexed by ``trade_date`` with float OHLCV columns sorted
        ascending, or ``None`` when the body carries no usable rows.
    """
    text = (body or "").strip()
    if not text or text.upper().startswith("N/D"):
        return None

    frame = pd.read_csv(io.StringIO(text))
    if frame.empty or "Date" not in frame.columns:
        return None

    rename = {col: _COLUMN_MAP[col] for col in _COLUMN_MAP if col in frame.columns}
    frame = frame.rename(columns=rename)
    if not all(col in frame.columns for col in _OUTPUT_COLUMNS):
        return None

    frame["trade_date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame = frame.dropna(subset=["trade_date"]).set_index("trade_date").sort_index()
    frame.index.name = "trade_date"

    for col in _OUTPUT_COLUMNS:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame[_OUTPUT_COLUMNS].dropna(subset=["open", "high", "low", "close"])
    if frame.empty:
        return None
    return frame.astype(float)
