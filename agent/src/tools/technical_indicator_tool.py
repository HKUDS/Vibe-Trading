"""Read-only technical indicator tool.

Computes RSI, MACD, Bollinger Bands, SMA, EMA, and volume statistics for a given
symbol using the existing market-data pipeline. RSI and Bollinger Bands come from
``fin_primitives.ta`` (TA-Lib conventions); the rest is numpy/pandas.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from fin_primitives import ta

from src.agent.tools import BaseTool
from src.market_data import fetch_market_data
from src.tools.market_data_tool import _canonicalize_interval

logger = logging.getLogger(__name__)

# ── Indicator defaults ────────────────────────────────────────────────────────
_RSI_PERIOD = 14
_MACD_FAST = 12
_MACD_SLOW = 26
_MACD_SIGNAL = 9
_BB_PERIOD = 20
_BB_STD = 2.0
_SMA_PERIODS = (20, 50, 200)
_EMA_PERIOD = 20
_DEFAULT_LOOKBACK = 200
_MAX_LOOKBACK = 500
#: Calendar days fetched per requested bar. Two covers weekends and holidays
#: for daily bars; a weekly or monthly bar needs its whole period, or 200
#: weekly bars would be asked for over 400 days and come back as 57 (#1479).
_CALENDAR_DAYS_PER_BAR = {"1W": 7, "1M": 31}


_CLOSE_KEYS = ("close", "Close", "CLOSE", "adj_close")
_VOLUME_KEYS = ("volume", "Volume", "VOLUME")
_DATE_KEYS = ("trade_date", "date", "datetime", "timestamp", "time")


def _extract_series(
    payload: Any, keys: tuple[str, ...], *, keep_missing: bool = False
) -> pd.Series | None:
    """Extract one numeric column from a loader payload, on its dates.

    Loader results can be a ``DataFrame``, a plain column mapping, or the
    ``list[dict]`` shape returned by :func:`fetch_market_data`. Preserve a real
    date index when one is available; a payload without dates intentionally
    keeps a ``RangeIndex`` so callers do not report a row number as a date.

    Args:
        payload: The loader result for one symbol.
        keys: Column spellings to look for, first match wins.
        keep_missing: Keep a dated bar whose value is missing as NaN instead
            of dropping it, so a gap cannot slide an older value into "latest".

    Returns:
        A float series, or ``None`` when the payload has no such column.
    """
    if isinstance(payload, list):
        if not payload or not isinstance(payload[0], dict):
            return None
        frame = pd.DataFrame(payload)
    elif isinstance(payload, dict):
        inner = payload.get("data")
        if isinstance(inner, list):
            return _extract_series(inner, keys, keep_missing=keep_missing)
        try:
            frame = pd.DataFrame(payload)
        except ValueError:
            return None
    elif isinstance(payload, pd.DataFrame):
        frame = payload.copy()
    else:
        return None

    key = next((key for key in keys if key in frame.columns), None)
    if key is None:
        return None

    values = pd.to_numeric(frame[key], errors="coerce")
    date_key = next((key for key in _DATE_KEYS if key in frame.columns), None)
    if date_key is not None:
        dates = pd.to_datetime(frame[date_key], errors="coerce")
    elif isinstance(frame.index, pd.DatetimeIndex):
        dates = pd.Series(frame.index, index=frame.index)
    elif not isinstance(
        frame.index, pd.RangeIndex
    ) and not pd.api.types.is_integer_dtype(frame.index.dtype):
        dates = pd.Series(
            pd.to_datetime(frame.index, errors="coerce"), index=frame.index
        )
    else:
        kept = values if keep_missing else values.dropna()
        return kept.reset_index(drop=True).astype(float)

    valid = dates.notna() if keep_missing else values.notna() & dates.notna()
    normalized = pd.Series(
        values.loc[valid].to_numpy(dtype=float),
        index=pd.DatetimeIndex(dates.loc[valid]),
        dtype=float,
    )
    return normalized.sort_index(kind="stable")


def _extract_close_series(payload: Any) -> pd.Series | None:
    """Extract the close-price series from a loader payload."""
    return _extract_series(payload, _CLOSE_KEYS)


def _extract_volume_series(payload: Any) -> pd.Series | None:
    """Extract the volume series, keeping a dated bar with no volume as NaN."""
    return _extract_series(payload, _VOLUME_KEYS, keep_missing=True)


def _compute_volume_stats(
    volume: pd.Series, period: int = 20
) -> dict[str, float | None]:
    """Return latest volume, its trailing mean, and latest/mean ratio.

    The trailing mean is reported only when the latest period bars all carry
    finite volume values, so a missing bar cannot silently change the window.
    """
    if volume.empty:
        return {"latest": None, "sma_20": None, "ratio_20": None}

    latest_raw = volume.iloc[-1]
    latest = float(latest_raw) if pd.notna(latest_raw) else None
    window = volume.iloc[-period:]
    sma = None
    ratio = None
    if len(window) == period and window.notna().all():
        sma = float(window.mean())
        if latest is not None and sma != 0:
            ratio = float(latest / sma)

    return {"latest": latest, "sma_20": sma, "ratio_20": ratio}


def _dataset_fingerprint(
    close: pd.Series, volume: pd.Series | None, interval: str
) -> str:
    """SHA-256 of the exact bars (date, close, volume) the indicators use."""
    volumes = volume.tolist() if volume is not None else []
    volumes += [None] * (len(close) - len(volumes))
    bars = [
        [str(label), float(price), None if pd.isna(vol) else float(vol)]
        for label, price, vol in zip(close.index, close, volumes)
    ]
    canonical = json.dumps([interval, bars], separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _compute_sma(close: pd.Series, period: int) -> float | None:
    """Simple moving average over the last *period* bars."""
    if len(close) < period:
        return None
    return float(close.iloc[-period:].mean())


def _compute_ema(close: pd.Series, period: int) -> float | None:
    """Exponential moving average over the full series."""
    if len(close) < period:
        return None
    return float(close.ewm(span=period, adjust=False).mean().iloc[-1])


def _compute_rsi(close: pd.Series, period: int = _RSI_PERIOD) -> float | None:
    """Relative Strength Index (Wilder smoothing) over *period* bars.

    Wilder's averages start from the simple mean of the first *period*
    gains/losses and then recurse, as in TA-Lib and in
    ``shadow_account/indicators.py``. An exponential mean started from the
    first delta reads differently over the short windows this tool accepts.
    A series with no down bar reads 100 (no downward pressure).
    """
    if len(close) < period + 1:
        return None
    if not (close.diff() < 0).any():
        return 100.0
    value = ta.rsi(close, length=period).iloc[-1]
    return float(value) if pd.notna(value) else None


def _round_keeping_precision(value: float, min_decimals: int, reference: float | None = None) -> float:
    """Round to ``min_decimals`` places, widening for tiny magnitudes.

    A fixed 2- or 4-decimal round collapses the output of a sub-penny asset
    (e.g. a 1.2e-5 crypto price) to 0.0. Keep at least four significant digits
    of each nonzero value, using ``reference`` only if it requires more
    precision; ordinary prices keep ``min_decimals``. Python's decimal-place
    count can exceed 15 for tiny floats without claiming more significant
    digits than the input carries.

    Args:
        value: Indicator value to round.
        min_decimals: Minimum number of decimal places.
        reference: Optional scale of the related indicator.

    Returns:
        Rounded value with at least four significant digits when nonzero.
    """
    if not math.isfinite(value) or value == 0:
        return round(value, min_decimals)
    ref = abs(value)
    if reference is not None and math.isfinite(reference) and reference != 0:
        ref = min(ref, abs(reference))
    decimals = max(min_decimals, 3 - math.floor(math.log10(ref)))
    return round(value, decimals)


def _compute_macd(
    close: pd.Series,
    fast: int = _MACD_FAST,
    slow: int = _MACD_SLOW,
    signal: int = _MACD_SIGNAL,
) -> dict[str, float | None] | None:
    """MACD line, signal line, and histogram."""
    if len(close) < slow + signal:
        return None
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    macd_last = float(macd_line.iloc[-1])
    signal_last = float(signal_line.iloc[-1])
    return {
        "macd_line": _round_keeping_precision(macd_last, 4, reference=macd_last),
        "signal_line": _round_keeping_precision(signal_last, 4, reference=macd_last),
        "histogram": _round_keeping_precision(float(histogram.iloc[-1]), 4, reference=macd_last),
    }


def _compute_bollinger(
    close: pd.Series,
    period: int = _BB_PERIOD,
    num_std: float = _BB_STD,
) -> dict[str, float | None] | None:
    """Bollinger Bands: upper, middle (SMA), lower.

    The band width uses the population standard deviation of the window, as
    Bollinger defined it and as TA-Lib, pandas-ta and TradingView compute it.
    """
    if len(close) < period:
        return None
    bands = ta.bbands(close, length=period, std=num_std)
    lower, middle, upper = (float(value) for value in bands.iloc[-1, :3])
    return {
        "upper": _round_keeping_precision(upper, 2, reference=middle),
        "middle": _round_keeping_precision(middle, 2, reference=middle),
        "lower": _round_keeping_precision(lower, 2, reference=middle),
    }


class TechnicalIndicatorTool(BaseTool):
    """Compute common technical indicators for a symbol.

    Fetches OHLCV data through the existing loader pipeline, then computes
    RSI, MACD, Bollinger Bands, SMA, EMA, and volume statistics locally, with
    no network calls beyond what the loaders already do.
    """

    name = "technical_indicators"
    description = (
        "Compute common technical indicators (RSI, MACD, Bollinger Bands, "
        "SMA, EMA) plus latest/20-bar volume statistics for a trading symbol "
        "(volume.unit is the serving source's declared unit -- lots or shares -- "
        "or null when undeclared). Returns read_identity with the acquisition "
        "boundary, serving provenance and a fingerprint of the exact bars used. "
        "Uses the project's data loaders to fetch price history, then computes "
        "indicators locally."
    )
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": (
                    "Trading symbol, e.g. AAPL for US stocks, "
                    "600519.SH for A-shares, BTC-USDT for crypto."
                ),
            },
            "interval": {
                "type": "string",
                "description": "Bar interval: 1d (default), 1wk, or 1mo.",
                "default": "1d",
            },
            "lookback": {
                "type": "integer",
                "description": (
                    "Number of bars to fetch. Default 200, max 500. "
                    "More bars = more accurate long-term indicators (SMA 200)."
                ),
                "default": _DEFAULT_LOOKBACK,
            },
            "end_date": {
                "type": "string",
                "description": (
                    "Optional YYYY-MM-DD acquisition boundary. Omit it for the "
                    "current local date. The boundary pins the requested period; "
                    "read_identity.dataset_fingerprint identifies the exact bars used."
                ),
            },
        },
        "required": ["symbol"],
    }
    repeatable = True
    is_readonly = True
    replay_after_compaction = True

    def execute(self, **kwargs: Any) -> str:
        symbol = str(kwargs.get("symbol", "")).strip()
        requested_interval = str(kwargs.get("interval", "1d")).strip()
        lookback_raw = kwargs.get("lookback", _DEFAULT_LOOKBACK)

        if not symbol:
            return json.dumps({"ok": False, "error": "symbol is required"})
        # The documented 1d / 1wk / 1mo spellings used to reach the loaders
        # verbatim, and most of them know neither weekly spelling.
        interval = _canonicalize_interval(requested_interval)
        if interval is None:
            return json.dumps(
                {
                    "ok": False,
                    "error": f"unsupported interval {requested_interval!r}; use 1d, 1wk or 1mo",
                }
            )

        try:
            lookback = int(lookback_raw)
        except (TypeError, ValueError):
            lookback = _DEFAULT_LOOKBACK
        lookback = max(10, min(lookback, _MAX_LOOKBACK))

        # One clock read per call, or an explicit zero-padded YYYY-MM-DD boundary.
        end_date_raw = str(kwargs.get("end_date") or "").strip()
        if end_date_raw:
            try:
                reference_date = date.fromisoformat(end_date_raw)
            except ValueError:
                reference_date = None
            if reference_date is None or reference_date.isoformat() != end_date_raw:
                return json.dumps(
                    {"ok": False, "error": "end_date must use YYYY-MM-DD"}
                )
        else:
            reference_date = datetime.now().date()
        end_date = reference_date.isoformat()
        days = lookback * _CALENDAR_DAYS_PER_BAR.get(interval, 2)
        start_date = (reference_date - timedelta(days=days)).isoformat()

        try:
            data = fetch_market_data(
                codes=[symbol],
                start_date=start_date,
                end_date=end_date,
                interval=interval,
                # Indicators require consecutive bars. ``max_rows=lookback``
                # would make the shared helper even-stride sample long windows.
                max_rows=0,
                # For volume_unit: lots on the A-share sources, shares on the
                # Yahoo family (#1062) -- 100x apart, and nothing to infer from.
                include_provenance=True,
            )
        except Exception as exc:
            logger.debug("fetch_market_data failed for %s: %s", symbol, exc)
            return json.dumps({"ok": False, "error": f"Failed to fetch data: {exc}"})

        df = data.get(symbol)
        if df is None:
            return json.dumps({"ok": False, "error": f"No data returned for {symbol}"})
        if isinstance(df, pd.DataFrame) and df.empty:
            return json.dumps({"ok": False, "error": f"No data returned for {symbol}"})
        if isinstance(df, list) and not df:
            return json.dumps({"ok": False, "error": f"No data returned for {symbol}"})
        if isinstance(df, dict) and not df:
            return json.dumps({"ok": False, "error": f"No data returned for {symbol}"})
        if isinstance(df, dict) and df.get("truncated") is True:
            return json.dumps(
                {
                    "ok": False,
                    "error": "Indicator calculation requires consecutive, untruncated bars",
                }
            )

        close = _extract_close_series(df)
        if close is None or close.empty:
            return json.dumps({"ok": False, "error": "No close price column in data"})
        close = close.sort_index(kind="stable").tail(lookback)

        volume = _extract_volume_series(df)
        if volume is not None:
            volume = volume.sort_index(kind="stable")
            if isinstance(close.index, pd.DatetimeIndex) and isinstance(
                volume.index, pd.DatetimeIndex
            ):
                volume = volume.reindex(close.index)
            else:
                volume = volume.tail(len(close)).reset_index(drop=True)
        volume_stats = (
            _compute_volume_stats(volume)
            if volume is not None
            else {"latest": None, "sma_20": None, "ratio_20": None}
        )
        provenance = (data.get("_provenance") or {}).get(symbol)
        volume_stats["unit"] = (
            provenance.get("volume_unit") if isinstance(provenance, dict) else None
        )

        # ── Compute indicators ────────────────────────────────────────────
        indicators: dict[str, Any] = {
            "rsi_14": _compute_rsi(close),
            "macd": _compute_macd(close),
            "bollinger": _compute_bollinger(close),
            "volume": volume_stats,
        }
        for period in _SMA_PERIODS:
            indicators[f"sma_{period}"] = _compute_sma(close, period)
        indicators[f"ema_{_EMA_PERIOD}"] = _compute_ema(close, _EMA_PERIOD)

        latest_close = float(close.iloc[-1]) if len(close) > 0 else None
        latest_date = (
            str(close.index[-1])[:10]
            if isinstance(close.index, pd.DatetimeIndex) and len(close) > 0
            else None
        )

        return json.dumps(
            {
                "ok": True,
                "symbol": symbol,
                "interval": interval,
                "latest_close": latest_close,
                "latest_date": latest_date,
                "read_identity": {
                    "mode": "pinned_boundary" if end_date_raw else "latest_boundary",
                    "requested_end_date": end_date,
                    "bar_count": len(close),
                    "dataset_fingerprint": _dataset_fingerprint(
                        close, volume, interval
                    ),
                    "provenance": provenance if isinstance(provenance, dict) else None,
                },
                "indicators": indicators,
            },
            ensure_ascii=False,
            default=str,
        )
