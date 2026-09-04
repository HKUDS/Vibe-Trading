"""Wallex spot candle loader (crypto, TMN/Toman-quoted pairs).

Uses the Wallex public TradingView-UDF REST endpoint (no auth):

    GET https://api.wallex.ir/v1/udf/history
        ?symbol=USDTTMN&resolution=60&from=<epoch_s>&to=<epoch_s>

Source facts (verified against api.wallex.ir live probes, 2026-08-26):

- ``*TMN`` symbols are quoted in Toman; ``*USDT`` pairs are also available.
- Docs list resolutions 1/15/60/240/480/720/1D/2D/3D, but the backend only
  produces three real buckets: ``1`` (1m), ``60`` (1h), ``1D`` (daily).
  ``15`` silently degrades to 1m and ``240/480/720`` to 1h — returning that
  data under a finer label would be silently wrong, so this loader accepts
  ONLY 1m/1h/1d and rejects everything else with an empty result.
- No pagination. Ranges are hard-capped (~25d of 1m, ~3y of 1h per request;
  over-cap returns HTTP 500, not a truncation) — windows are chunked
  client-side well under the caps.
- Response OHLCV values are decimal STRINGS; timestamps are bar-open unix
  seconds. Volume is base-asset volume.
- Rate limit headers show ``x-ratelimit-limit: 600``.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

import pandas as pd
import requests

from backtest.loaders.base import (
    cached_loader_fetch,
    check_budget,
    positive_env_float,
    positive_env_int,
    retry_with_budget,
    validate_date_range,
    validate_ohlc,
)
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

# Project interval tokens -> Wallex UDF ``resolution`` values. Only the three
# buckets the backend truly serves are mapped; anything else (including the
# silently-degrading 15m/4h documented values) rejects with {} so the fallback
# chain continues instead of receiving mislabeled bars.
_INTERVAL_MAP = {
    "1m": "1",
    "1h": "60",
    "1H": "60",
    "1d": "1D",
    "1D": "1D",
}

# Client-side chunk spans per resolution (unix seconds), kept well under the
# observed per-request caps (~25d of 1m, ~3y of 1h, full history of 1D).
_CHUNK_SPAN_S = {
    "1": 20 * 86400,
    "60": 2 * 365 * 86400,
    "1D": 40 * 365 * 86400,
}

HISTORY_URL = "https://api.wallex.ir/v1/udf/history"
_PAGE_SLEEP_S = 0.3

_WALLEX_TIMEOUT_S = positive_env_int("WALLEX_TIMEOUT_S", 20)
_WALLEX_FETCH_BUDGET_S = positive_env_float("WALLEX_FETCH_BUDGET_S", 90.0)
_WALLEX_PROBE_TIMEOUT_S = positive_env_int("WALLEX_PROBE_TIMEOUT_S", 8)

_OUTPUT_COLUMNS = ["open", "high", "low", "close", "volume"]

_HEADERS = {"User-Agent": "TraderBot/vibe-trading-loader"}


def map_symbol(symbol: str) -> str:
    """``USDT-TMN`` / ``USDTTMN`` / ``usdttmn`` -> ``USDTTMN``."""
    return symbol.strip().upper().replace("-", "").replace("/", "")


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(_HEADERS)
    return session


@register
class DataLoader:
    """Wallex crypto OHLCV loader (public UDF endpoint, no auth)."""

    name = "wallex"
    markets = {"crypto"}
    requires_auth = False

    def __init__(self) -> None:
        """No credentials required for public candles."""
        pass

    def is_available(self) -> bool:
        """Probe the public endpoint with a short 1D request."""
        try:
            now = int(time.time())
            resp = _session().get(
                HISTORY_URL,
                params={
                    "symbol": "USDTTMN",
                    "resolution": "1D",
                    "from": now - 2 * 86400,
                    "to": now,
                },
                timeout=_WALLEX_PROBE_TIMEOUT_S,
            )
            if resp.status_code != 200:
                logger.warning("Wallex probe HTTP %s", resp.status_code)
                return False
            return resp.json().get("s") == "ok"
        except Exception as exc:  # noqa: BLE001 — availability probe
            logger.warning("Wallex probe failed: %s", exc)
            return False

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch TMN-quoted crypto OHLCV (e.g. ``["USDT-TMN", "BTC-TMN"]``).

        Args:
            codes: Symbols like ``USDT-TMN`` / ``USDTTMN`` (Toman-quoted).
            start_date: Start date (YYYY-MM-DD, inclusive).
            end_date: End date (YYYY-MM-DD, exclusive).
            fields: Ignored (Wallex has no extra fields).
            interval: Bar size — only 1m/1h/1d are truly served by Wallex;
                anything else rejects with an empty result, default ``1D``.

        Returns:
            Mapping symbol -> DataFrame(trade_date, open, high, low, close, volume).
        """
        validate_date_range(start_date, end_date)

        if fields:
            logger.warning("Wallex ignores extra fields: %s", fields)

        resolution = _INTERVAL_MAP.get(interval.strip())
        if resolution is None:
            logger.warning(
                "unsupported Wallex interval %r; rejecting (Wallex truly serves "
                "only 1m/1h/1d — other documented values silently degrade)",
                interval,
            )
            return {}

        start_ts = int(pd.Timestamp(start_date).timestamp())
        end_ts = int((pd.Timestamp(end_date) + pd.Timedelta(days=1)).timestamp())
        session = _session()

        result: Dict[str, pd.DataFrame] = {}
        for code in codes:
            symbol = map_symbol(code)
            try:
                df = cached_loader_fetch(
                    source=self.name,
                    symbol=symbol,
                    timeframe=interval,
                    start_date=start_date,
                    end_date=end_date,
                    fields=None,
                    fetch=lambda symbol=symbol: self._fetch_one(
                        session, symbol, resolution, start_ts, end_ts
                    ),
                )
                if df is not None and not df.empty:
                    result[code] = df
            except Exception as exc:  # noqa: BLE001 — one bad symbol must not abort the batch
                logger.warning("Wallex failed for %s: %s", symbol, exc)
        return result

    def _fetch_one(
        self,
        session: requests.Session,
        symbol: str,
        resolution: str,
        start_ts: int,
        end_ts: int,
    ) -> Optional[pd.DataFrame]:
        """Forward time-window chunking (Wallex has no pagination)."""
        deadline = time.monotonic() + _WALLEX_FETCH_BUDGET_S
        label = f"Wallex fetch for {symbol}"
        span = _CHUNK_SPAN_S.get(resolution, 2 * 365 * 86400)
        frames: list[pd.DataFrame] = []
        window_start = start_ts

        while window_start < end_ts:
            check_budget(deadline, label, budget_s=_WALLEX_FETCH_BUDGET_S)
            window_end = min(window_start + span, end_ts)

            def _do_request(
                window_start: int = window_start, window_end: int = window_end
            ) -> dict:
                resp = session.get(
                    HISTORY_URL,
                    params={
                        "symbol": symbol,
                        "resolution": resolution,
                        "from": window_start,
                        "to": window_end,
                    },
                    timeout=_WALLEX_TIMEOUT_S,
                )
                if resp.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(
                        f"Wallex HTTP {resp.status_code}", response=resp
                    )
                resp.raise_for_status()
                return resp.json()

            data = retry_with_budget(
                _do_request,
                transient=(requests.RequestException, TimeoutError),
                deadline=deadline,
                label=label,
            )
            if data.get("s") == "error":
                raise requests.RequestException(
                    f"Wallex UDF error: {data.get('errmsg') or 'error'}"
                )
            times = data.get("t") or []
            if times:
                frames.append(
                    pd.DataFrame(
                        {
                            "trade_date": pd.to_datetime(times, unit="s"),
                            "open": pd.to_numeric(data["o"], errors="coerce"),
                            "high": pd.to_numeric(data["h"], errors="coerce"),
                            "low": pd.to_numeric(data["l"], errors="coerce"),
                            "close": pd.to_numeric(data["c"], errors="coerce"),
                            "volume": pd.to_numeric(
                                data.get("v") or [0.0] * len(times), errors="coerce"
                            ),
                        }
                    )
                )
            window_start = window_end
            if window_start < end_ts:
                time.sleep(_PAGE_SLEEP_S)

        if not frames:
            return None

        df = pd.concat(frames).set_index("trade_date").sort_index()
        df = df[~df.index.duplicated(keep="last")]
        start_dt = pd.Timestamp(start_ts, unit="s")
        end_dt = pd.Timestamp(end_ts, unit="s")
        df = df[(df.index >= start_dt) & (df.index < end_dt)]
        df = df[_OUTPUT_COLUMNS].dropna(subset=["open", "high", "low", "close"])
        if df.empty:
            return None
        df = validate_ohlc(df)
        return df.astype("float64") if not df.empty else None
