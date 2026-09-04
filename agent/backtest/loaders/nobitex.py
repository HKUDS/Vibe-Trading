"""Nobitex spot candle loader (crypto, IRT/Toman-quoted pairs).

Uses the Nobitex public TradingView-UDF REST endpoint (no auth):

    GET https://apiv2.nobitex.ir/market/udf/history
        ?symbol=BTCIRT&resolution=D&from=<epoch_s>&to=<epoch_s>&page=1

Source facts (verified against apidocs.nobitex.ir + live probes, 2026-08-26):

- ``*IRT`` symbols are quoted in Toman; ``dstCurrency=rls`` stats are in Rial
  (1 Toman = 10 Rials). This loader only serves ``*IRT`` markets.
- Max 500 candles per request; ``page`` walks OLDER batches (page 1 = newest
  in range; a short page or ``{"s": "no_data"}`` ends the walk).
- Rate limit 60 req/min on this endpoint — a small sleep between pages.
- Candle timestamps align to Tehran local time (UTC+03:30): daily bars open
  at Tehran midnight, hourly bars at :30 past the UTC hour.
- Resolutions: 1/5/15/30 min, 60/180/240/360/720 min, D/2D/3D. There is no
  weekly resolution — ``1W`` requests reject with an empty result so the
  fallback chain continues.
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
    positive_env_int,
    retry_with_budget,
    validate_date_range,
    validate_ohlc,
)
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

# Project interval tokens -> Nobitex UDF ``resolution`` values. Case aliases
# accepted; anything else (including weekly) rejects with {} so the fallback
# chain continues instead of silently substituting daily bars.
_INTERVAL_MAP = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "1H": "60",
    "3h": "180",
    "3H": "180",
    "4h": "240",
    "4H": "240",
    "6h": "360",
    "6H": "360",
    "12h": "720",
    "12H": "720",
    "1d": "D",
    "1D": "D",
}

HISTORY_URL = "https://apiv2.nobitex.ir/market/udf/history"
_MAX_PER_PAGE = 500
_MAX_PAGES = 40
_PAGE_SLEEP_S = 0.5  # endpoint allows 60 req/min

_NOBITEX_TIMEOUT_S = positive_env_int("NOBITEX_TIMEOUT_S", 20)
_NOBITEX_FETCH_BUDGET_S = positive_env_int("NOBITEX_FETCH_BUDGET_S", 90)
_NOBITEX_PROBE_TIMEOUT_S = positive_env_int("NOBITEX_PROBE_TIMEOUT_S", 8)

_OUTPUT_COLUMNS = ["open", "high", "low", "close", "volume"]

_HEADERS = {"User-Agent": "TraderBot/vibe-trading-loader"}


def map_symbol(symbol: str) -> str:
    """``BTC-IRT`` / ``BTC/IRT`` / ``btcirt`` -> ``BTCIRT``."""
    return symbol.strip().upper().replace("-", "").replace("/", "")


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(_HEADERS)
    return session


@register
class DataLoader:
    """Nobitex crypto OHLCV loader (public UDF endpoint, no auth)."""

    name = "nobitex"
    markets = {"crypto"}
    requires_auth = False

    def __init__(self) -> None:
        """No credentials required for public candles."""
        pass

    def is_available(self) -> bool:
        """Probe the public endpoint with a 1-candle request."""
        try:
            resp = _session().get(
                HISTORY_URL,
                params={
                    "symbol": "BTCIRT",
                    "resolution": "D",
                    "countback": 1,
                    "to": int(time.time()),
                },
                timeout=_NOBITEX_PROBE_TIMEOUT_S,
            )
            if resp.status_code != 200:
                logger.warning("Nobitex probe HTTP %s", resp.status_code)
                return False
            return resp.json().get("s") == "ok"
        except Exception as exc:  # noqa: BLE001 — availability probe
            logger.warning("Nobitex probe failed: %s", exc)
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
        """Fetch IRT-quoted crypto OHLCV (e.g. ``["BTC-IRT", "USDT-IRT"]``).

        Args:
            codes: Symbols like ``BTC-IRT`` / ``BTCIRT`` (Toman-quoted).
            start_date: Start date (YYYY-MM-DD, inclusive).
            end_date: End date (YYYY-MM-DD, exclusive).
            fields: Ignored (Nobitex has no extra fields).
            interval: Bar size (1m/5m/15m/30m/1h/3h/4h/6h/12h/1d, case
                aliases accepted), default ``1D``.

        Returns:
            Mapping symbol -> DataFrame(trade_date, open, high, low, close, volume).
        """
        validate_date_range(start_date, end_date)

        if fields:
            logger.warning("Nobitex ignores extra fields: %s", fields)

        resolution = _INTERVAL_MAP.get(interval.strip())
        if resolution is None:
            logger.warning(
                "unsupported Nobitex interval %r; rejecting (supported: %s)",
                interval,
                sorted(_INTERVAL_MAP),
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
                logger.warning("Nobitex failed for %s: %s", symbol, exc)
        return result

    def _fetch_one(
        self,
        session: requests.Session,
        symbol: str,
        resolution: str,
        start_ts: int,
        end_ts: int,
    ) -> Optional[pd.DataFrame]:
        """Paginated UDF download; pages walk older batches of <=500 bars."""
        deadline = time.monotonic() + _NOBITEX_FETCH_BUDGET_S
        label = f"Nobitex fetch for {symbol}"
        frames: list[pd.DataFrame] = []
        page = 1

        for _ in range(_MAX_PAGES):
            check_budget(deadline, label, budget_s=_NOBITEX_FETCH_BUDGET_S)

            def _do_request(page: int = page) -> dict:
                resp = session.get(
                    HISTORY_URL,
                    params={
                        "symbol": symbol,
                        "resolution": resolution,
                        "from": start_ts,
                        "to": end_ts,
                        "page": page,
                    },
                    timeout=_NOBITEX_TIMEOUT_S,
                )
                if resp.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(
                        f"Nobitex HTTP {resp.status_code}", response=resp
                    )
                resp.raise_for_status()
                return resp.json()

            data = retry_with_budget(
                _do_request,
                transient=(requests.RequestException, TimeoutError),
                deadline=deadline,
                label=label,
            )
            status = data.get("s")
            if status == "no_data":
                break
            if status != "ok":
                raise requests.RequestException(
                    f"Nobitex UDF error: {data.get('errmsg') or status}"
                )
            times = data.get("t") or []
            if not times:
                break
            frame = pd.DataFrame(
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
            frame["volume"] = frame["volume"].fillna(0)
            frames.append(frame)
            if len(times) < _MAX_PER_PAGE or int(times[0]) <= start_ts:
                break
            page += 1
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
