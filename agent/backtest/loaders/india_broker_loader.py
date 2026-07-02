"""India broker data bridge: feed Shoonya / Dhan history into the backtest layer.

The Shoonya (Finvasia) and Dhan connectors already expose live-account market
data via ``get_historical_bars`` (read path). This loader adapts that envelope
into the standard OHLCV frame so a user's *broker* history can back the same
backtests as the public Yahoo feed — useful when matching a live account exactly
or pulling symbols Yahoo lacks.

It is an OPT-IN source (``requires_auth``): ``is_available`` is True only when a
broker SDK is importable AND a broker is configured, so it trails Yahoo/yfinance
in the ``india_equity`` fallback chain and never fires in CI / unconfigured runs.

Symbol convention: project ``RELIANCE.NS`` / ``500325.BO`` → broker ``RELIANCE``
on exchange ``NSE`` / ``BSE`` (the suffix selects the exchange; the base symbol
is passed bare).

Limitation: broker endpoints return a bounded window of *recent* bars (period +
limit), not an arbitrary historical start. This loader requests enough bars to
cover the window and clips to ``[start_date, end_date]``; very old ranges may
come back short. For deep history prefer Yahoo.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest.loaders.base import validate_date_range
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_OUTPUT_COLUMNS = ["open", "high", "low", "close", "volume"]
# Project interval -> broker ``period`` token (both connectors share this set).
_PERIOD_MAP = {"1D": "1d", "1H": "1h", "5m": "5m", "15m": "15m", "30m": "30m", "1m": "1m"}


def _resolve_broker():
    """Return ``(broker_key, sdk_module)`` for the first available India broker.

    Prefers Shoonya, then Dhan. Returns ``(None, None)`` when neither the SDK
    nor a config is present. Import is deferred and defensive so a missing
    ``src.trading`` package or broker SDK simply means "unavailable", never a
    crash in the loader registry.
    """
    try:
        from src.trading.connectors.shoonya import sdk as shoonya_sdk

        if shoonya_sdk.shoonya_available():
            return "shoonya", shoonya_sdk
    except Exception as exc:  # noqa: BLE001 — optional dependency / config
        logger.debug("shoonya bridge unavailable: %s", exc)
    try:
        from src.trading.connectors.dhan import sdk as dhan_sdk

        if dhan_sdk.dhan_available():
            return "dhan", dhan_sdk
    except Exception as exc:  # noqa: BLE001
        logger.debug("dhan bridge unavailable: %s", exc)
    return None, None


def _exchange_for(code: str) -> str:
    """Map the project suffix to the broker exchange code (NSE / BSE)."""
    return "BSE" if code.strip().upper().endswith(".BO") else "NSE"


def _base_symbol(code: str) -> str:
    """Strip the ``.NS`` / ``.BO`` suffix, leaving the broker's bare symbol."""
    cleaned = code.strip()
    upper = cleaned.upper()
    if upper.endswith((".NS", ".BO")):
        return cleaned[:-3]
    return cleaned


def _bars_to_frame(bars: list[dict], start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """Convert the broker ``bars`` list into a clipped OHLCV frame, or ``None``."""
    if not bars:
        return None
    frame = pd.DataFrame(bars)
    if "time" not in frame.columns:
        return None
    # ``time`` is epoch seconds (Shoonya ssboe / Dhan candle[0]) or an ISO string.
    ts = pd.to_numeric(frame["time"], errors="coerce")
    if ts.notna().any():
        index = pd.to_datetime(ts, unit="s", errors="coerce")
    else:
        index = pd.to_datetime(frame["time"], errors="coerce")
    frame = frame.drop(columns=["time"])
    frame.index = pd.DatetimeIndex(index).tz_localize(None)
    frame.index.name = "trade_date"

    for col in _OUTPUT_COLUMNS:
        if col not in frame.columns:
            frame[col] = 0.0 if col == "volume" else pd.NA
    frame = frame[_OUTPUT_COLUMNS].apply(pd.to_numeric, errors="coerce")
    frame = frame.dropna(subset=["open", "high", "low", "close"]).sort_index()

    lower = pd.Timestamp(start_date).normalize()
    upper = pd.Timestamp(end_date).normalize() + pd.Timedelta(days=1)
    frame = frame[(frame.index >= lower) & (frame.index < upper)]
    return frame.astype(float) if not frame.empty else None


@register
class DataLoader:
    """Shoonya / Dhan history adapter for the ``india_equity`` market."""

    name = "india_broker"
    markets = {"india_equity"}
    requires_auth = True

    def __init__(self) -> None:
        pass

    def is_available(self) -> bool:
        """True only when an India broker SDK is importable and configured."""
        broker, _ = _resolve_broker()
        return broker is not None

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch OHLCV history for ``codes`` from the configured India broker."""
        del fields
        if not codes:
            return {}
        validate_date_range(start_date, end_date)

        broker, sdk = _resolve_broker()
        if sdk is None:
            return {}

        period = _PERIOD_MAP.get(str(interval).strip(), "1d")
        # Request enough bars to cover the window (business days + headroom).
        span_days = max((pd.Timestamp(end_date) - pd.Timestamp(start_date)).days, 1)
        limit = min(max(span_days, 30), 2000)

        result: Dict[str, pd.DataFrame] = {}
        for code in codes:
            try:
                envelope = sdk.get_historical_bars(
                    _base_symbol(code),
                    exchange=_exchange_for(code),
                    period=period,
                    limit=limit,
                )
            except TypeError:
                # Dhan uses ``exchange_segment``; retry without the ``exchange`` kw.
                try:
                    envelope = sdk.get_historical_bars(
                        _base_symbol(code), period=period, limit=limit
                    )
                except Exception as exc:  # noqa: BLE001 — one bad symbol never aborts
                    logger.warning("%s bridge failed for %s: %s", broker, code, exc)
                    continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s bridge failed for %s: %s", broker, code, exc)
                continue

            if not isinstance(envelope, dict) or str(envelope.get("status", "")).lower() != "ok":
                continue
            frame = _bars_to_frame(envelope.get("bars", []), start_date, end_date)
            if frame is not None and not frame.empty:
                result[code] = frame
        return result
