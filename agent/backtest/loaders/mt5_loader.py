"""MetaTrader 5 data loader — forex/metals history from a local MT5 terminal.

Feeds backtests and ``get_market_data`` from the user's own broker feed
(e.g. Exness), with the broker's exact symbols and session times. Requires
Windows, the optional ``MetaTrader5`` package (``pip install
"vibe-trading-ai[mt5]"``), and a running, logged-in MT5 terminal — when any of
those are missing :meth:`DataLoader.is_available` is ``False`` and the forex
fallback chain degrades to akshare/yfinance/local.

Config is shared with the MT5 trading connector via ``~/.vibe-trading/mt5.json``
(read directly — this module deliberately does not import the connector).
With no config file, ``mt5.initialize()`` attaches to the last-used, already
logged-in terminal, which is the primary read-only path.

History depth is bounded by the terminal's "Max bars in chart" setting.
Broker account-type suffixes (Exness ``EURUSDm``) are discovered via
``symbols_get`` and memoized; results are keyed by the caller's ORIGINAL
code so the runner's coverage check (``set(codes) - set(data_map)``) holds.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd

from backtest.loaders.base import cached_loader_fetch, validate_date_range, validate_ohlc
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

#: Shared file contract with the MT5 trading connector (extra keys tolerated).
_MT5_CONFIG_PATH = Path.home() / ".vibe-trading" / "mt5.json"

#: Canonical interval token → MetaTrader5 timeframe constant name.
#: Lowercase ``1h``/``4h``/``1d``/``1w`` alias project-style tokens (connector parity).
#: ``1m`` (minute) and ``1M`` (month) differ by case.
_INTERVAL_MAP = {
    "1m": "TIMEFRAME_M1", "5m": "TIMEFRAME_M5", "15m": "TIMEFRAME_M15",
    "30m": "TIMEFRAME_M30",
    "1H": "TIMEFRAME_H1", "1h": "TIMEFRAME_H1",
    "4H": "TIMEFRAME_H4", "4h": "TIMEFRAME_H4",
    "1D": "TIMEFRAME_D1", "1d": "TIMEFRAME_D1",
    "1W": "TIMEFRAME_W1", "1w": "TIMEFRAME_W1",
    "1M": "TIMEFRAME_MN1",
}

#: Process-lifetime attach cache: ``initialize`` can take seconds (it may even
#: launch the terminal), and chain resolution probes ``is_available`` often.
_init_state: bool | None = None

#: base symbol → resolved broker symbol memo.
_symbol_cache: dict[str, str] = {}


def _import_mt5() -> ModuleType | None:
    """Lazy-import the Windows-only SDK; ``None`` when absent."""
    try:
        import MetaTrader5  # type: ignore[import-not-found]
    except ImportError:
        return None
    return MetaTrader5


def _read_mt5_config() -> dict[str, Any]:
    """Best-effort read of the shared mt5.json ({} on missing/corrupt)."""
    try:
        raw = json.loads(_MT5_CONFIG_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def _ensure_initialized() -> bool:
    """Attach to the terminal once per process (result cached, even negative)."""
    global _init_state
    if _init_state is not None:
        return _init_state
    mt5 = _import_mt5()
    if mt5 is None:
        _init_state = False
        return False
    config = _read_mt5_config()
    kwargs: dict[str, Any] = {}
    if config.get("login"):
        kwargs["login"] = int(config["login"])
        kwargs["password"] = str(config.get("password") or "")
        kwargs["server"] = str(config.get("server") or "")
    if config.get("timeout"):
        kwargs["timeout"] = int(float(config["timeout"]) * 1000)
    args = (str(config["terminal_path"]),) if config.get("terminal_path") else ()
    try:
        ok = bool(mt5.initialize(*args, **kwargs))
    except Exception as exc:  # noqa: BLE001 - availability probe must not raise
        logger.warning("mt5: initialize raised: %s", exc)
        ok = False
    if not ok:
        try:
            logger.warning("mt5: terminal attach failed: %s", mt5.last_error())
        except Exception:  # noqa: BLE001
            pass
    _init_state = ok
    return ok


def _to_query_base(code: str) -> str:
    """``EUR/USD`` / ``EURUSD.FX`` → ``EURUSD`` (upper, separators stripped)."""
    token = code.strip().upper()
    if token.endswith(".FX"):
        token = token[: -len(".FX")]
    for separator in ("/", "-", "_", " "):
        token = token.replace(separator, "")
    return token


def _resolve_broker_symbol(mt5: ModuleType, code: str) -> str | None:
    """Resolve a project code to the broker's symbol name (memoized).

    Order: the raw token exactly (case-sensitive broker names pass through),
    the normalized base, then suffix discovery via ``symbols_get(f"{base}*")``
    — shortest name first, then alphabetical, which deterministically picks
    ``EURUSDm`` over ``EURUSDz`` on Exness-style brokers.
    """
    base = _to_query_base(code)
    cached = _symbol_cache.get(base)
    if cached is not None:
        return cached
    raw = code.strip()
    for candidate in dict.fromkeys((raw, base)):  # ordered, deduped
        if candidate and mt5.symbol_info(candidate) is not None:
            _symbol_cache[base] = candidate
            return candidate
    matches = sorted(
        (getattr(info, "name", "") for info in (mt5.symbols_get(group=f"{base}*") or ())),
        key=lambda name: (len(name), name),
    )
    matches = [m for m in matches if m]
    if not matches:
        logger.warning("mt5: symbol %r not offered by this broker (no match for %s*)", code, base)
        return None
    _symbol_cache[base] = matches[0]
    return matches[0]


def _rates_to_frame(rates: Any, start_date: str, end_date: str) -> pd.DataFrame | None:
    """Map a ``copy_rates_range`` structured array to the loader frame contract."""
    if rates is None or len(rates) == 0:
        return None
    frame = pd.DataFrame(rates)
    if "time" not in frame.columns or "close" not in frame.columns:
        return None
    frame["trade_date"] = pd.to_datetime(frame["time"], unit="s")
    frame = frame.set_index("trade_date").sort_index()
    # Forex real_volume is zero on most brokers; tick_volume is the standard proxy.
    frame["volume"] = frame.get("tick_volume", 0)
    # Bars carry intraday timestamps; the end date is inclusive of its whole day.
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date) + pd.Timedelta(days=1)
    frame = frame[(frame.index >= start) & (frame.index < end)]
    frame = frame[["open", "high", "low", "close", "volume"]].dropna()
    frame = validate_ohlc(frame)
    return frame if not frame.empty else None


@register
class DataLoader:
    """Forex/metals OHLCV from the local MT5 terminal (Windows, opt-in extra)."""

    name = "mt5"
    markets = {"forex"}
    #: A running, logged-in terminal is the auth surface (futu precedent).
    requires_auth = True

    def __init__(self) -> None:  # never raises — registry availability contract
        pass

    def is_available(self) -> bool:
        """SDK importable AND the terminal attach succeeded (cached)."""
        return _import_mt5() is not None and _ensure_initialized()

    def fetch(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: list[str] | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV frames keyed by the original input codes.

        Per-symbol failures log and skip (never raise) so the runner's
        runtime fallback can engage for the missing symbols.
        """
        validate_date_range(start_date, end_date)
        timeframe_name = _INTERVAL_MAP.get(str(interval).strip())
        if timeframe_name is None:
            # Reject unknown tokens; do not fetch TIMEFRAME_D1 under the caller's key.
            logger.warning("mt5 unsupported interval %r; rejecting", interval)
            return {}

        result: dict[str, pd.DataFrame] = {}
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
                    fetch=lambda c=clean: self._fetch_one(c, start_date, end_date, timeframe_name),
                )
            except Exception as exc:  # noqa: BLE001 - one symbol never poisons the batch
                logger.warning("mt5: fetch failed for %s: %s", clean, exc)
                continue
            if frame is not None and not frame.empty:
                result[code] = frame
        return result

    def _fetch_one(
        self, code: str, start_date: str, end_date: str, timeframe_name: str
    ) -> pd.DataFrame | None:
        """Fetch one symbol from the terminal (``None`` on any failure)."""
        mt5 = _import_mt5()
        if mt5 is None or not _ensure_initialized():
            return None
        name = _resolve_broker_symbol(mt5, code)
        if name is None:
            return None
        try:
            mt5.symbol_select(name, True)
            timeframe = getattr(mt5, timeframe_name)
            # tz-aware UTC is mandatory: the MT5 API shifts naive datetimes by
            # the local timezone, silently offsetting the requested range.
            date_from = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
            date_to = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc) + timedelta(days=1)
            rates = mt5.copy_rates_range(name, timeframe, date_from, date_to)
        except Exception as exc:  # noqa: BLE001 - terminal hiccups degrade, not raise
            logger.warning("mt5: rates fetch failed for %s (%s): %s", code, name, exc)
            return None
        return _rates_to_frame(rates, start_date, end_date)
