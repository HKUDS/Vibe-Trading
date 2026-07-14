"""OKX spot candle loader (crypto).

Uses OKX V5 public REST API (no auth).

Endpoints
---------
- ``/market/candles`` — recent bars only (limited depth; not enough for multi-year
  backtests).
- ``/market/history-candles`` — multi-year history; used whenever the requested
  range is older than a few months or recent endpoint returns empty.

Hardening (2026-07 local audit)
--------------------------------
- Explicit proxy support (same env vars as CCXT loader); required on networks
  that time out direct HTTPS to www.okx.com.
- Raise / retry on HTTP 429/5xx and OKX business ``code != "0"``.
- Prefer ``history-candles`` for deep ranges so 2020-era backtests no longer
  return empty frames.
- ``is_available()`` does a short probe instead of always returning True.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Dict, List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

from backtest.loaders.base import (
    cached_loader_fetch,
    check_budget,
    positive_env_float,
    positive_env_int,
    retry_with_budget,
    validate_date_range,
)
from backtest.loaders.registry import register

BASE_URL = "https://www.okx.com/api/v5"
CANDLES_PATH = f"{BASE_URL}/market/candles"
HISTORY_CANDLES_PATH = f"{BASE_URL}/market/history-candles"
_MAX_PER_PAGE = 300
# Recent endpoint typically only covers ~months of 1D bars; beyond this age
# always hit history-candles first.
_RECENT_ONLY_DAYS = 400

_OKX_TIMEOUT = positive_env_int("OKX_TIMEOUT_S", 20)
_OKX_FETCH_BUDGET_S = positive_env_float("OKX_FETCH_BUDGET_S", 90.0)
_OKX_PROBE_TIMEOUT = positive_env_int("OKX_PROBE_TIMEOUT_S", 8)


def _first_proxy_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()  # noqa: env-gate — system proxy vars
        if value:
            return value
    return ""


def _okx_proxy_config() -> dict[str, str]:
    """Build requests proxies from conventional env vars (parity with CCXT)."""
    all_proxy = _first_proxy_env("ALL_PROXY", "all_proxy")
    http_proxy = _first_proxy_env("HTTP_PROXY", "http_proxy") or all_proxy
    https_proxy = _first_proxy_env("HTTPS_PROXY", "https_proxy") or all_proxy or http_proxy
    proxies: dict[str, str] = {}
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    return proxies


def _okx_session() -> requests.Session:
    session = requests.Session()
    proxies = _okx_proxy_config()
    if proxies:
        session.proxies.update(proxies)
    return session


@register
class DataLoader:
    """OKX crypto OHLCV loader."""

    name = "okx"
    markets = {"crypto"}
    requires_auth = False

    def is_available(self) -> bool:
        """Probe public candles with a short timeout (honours proxy env)."""
        try:
            session = _okx_session()
            resp = session.get(
                CANDLES_PATH,
                params={"instId": "BTC-USDT", "bar": "1D", "limit": "1"},
                timeout=_OKX_PROBE_TIMEOUT,
            )
            if resp.status_code != 200:
                logger.warning("OKX probe HTTP %s", resp.status_code)
                return False
            data = resp.json()
            return data.get("code") == "0" and bool(data.get("data"))
        except Exception as exc:  # noqa: BLE001 — availability probe
            logger.warning("OKX probe failed: %s", exc)
            return False

    def __init__(self) -> None:
        """No credentials required for public candles."""
        pass

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch crypto OHLCV via OKX public API.

        Args:
            codes: Symbols like ``["BTC-USDT", "ETH-USDT"]``.
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).
            fields: Ignored (OKX has no extra fields).
            interval: Bar size (1m/5m/15m/30m/1H/4H/1D), default ``1D``.

        Returns:
            Mapping symbol -> DataFrame.
        """
        validate_date_range(start_date, end_date)

        if fields:
            logger.warning("OKX ignores extra fields: %s", fields)

        valid_intervals = {"1m", "5m", "15m", "30m", "1H", "4H", "1D"}
        if interval not in valid_intervals:
            logger.warning("unsupported OKX interval %s, using 1D", interval)
            interval = "1D"

        codes = [c.replace("/", "-").upper() for c in codes]

        start_ts = int(pd.Timestamp(start_date).timestamp() * 1000)
        end_ts = int((pd.Timestamp(end_date) + pd.Timedelta(days=1)).timestamp() * 1000)

        # More pages for minute bars; history endpoint still needs walk-back.
        if interval in ("1m", "5m"):
            max_pages = 200
        elif interval in ("15m", "30m"):
            max_pages = 80
        else:
            max_pages = 40

        use_history = self._should_use_history(start_date)
        session = _okx_session()

        result: Dict[str, pd.DataFrame] = {}
        for symbol in codes:
            try:
                df = cached_loader_fetch(
                    source=self.name,
                    symbol=symbol,
                    timeframe=interval,
                    start_date=start_date,
                    end_date=end_date,
                    fields=None,
                    fetch=lambda symbol=symbol, use_history=use_history: self._fetch_candles(
                        session,
                        symbol,
                        start_ts,
                        end_ts,
                        interval,
                        max_pages,
                        prefer_history=use_history,
                    ),
                )
                if df is not None and not df.empty:
                    result[symbol] = df
            except Exception as exc:
                logger.warning("failed to fetch %s: %s", symbol, exc)
        return result

    @staticmethod
    def _should_use_history(start_date: str) -> bool:
        """True when the range starts older than recent-only window."""
        try:
            start = pd.Timestamp(start_date)
            age_days = (pd.Timestamp.utcnow().tz_localize(None) - start).days
            return age_days > _RECENT_ONLY_DAYS
        except Exception:
            return True

    def _fetch_candles(
        self,
        session: requests.Session,
        inst_id: str,
        start_ts: int,
        end_ts: int,
        bar: str = "1D",
        max_pages: int = 20,
        *,
        prefer_history: bool = True,
    ) -> Optional[pd.DataFrame]:
        """Paginated candle download (history endpoint for deep ranges)."""
        endpoints: list[str] = []
        if prefer_history:
            endpoints = [HISTORY_CANDLES_PATH, CANDLES_PATH]
        else:
            endpoints = [CANDLES_PATH, HISTORY_CANDLES_PATH]

        last_error: Exception | None = None
        for endpoint in endpoints:
            try:
                df = self._paginate(
                    session,
                    endpoint,
                    inst_id,
                    start_ts,
                    end_ts,
                    bar,
                    max_pages,
                )
                if df is not None and not df.empty:
                    return df
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "OKX %s failed for %s: %s — trying next endpoint",
                    endpoint.rsplit("/", 1)[-1],
                    inst_id,
                    exc,
                )

        if last_error is not None:
            logger.warning("OKX empty/failed for %s: %s", inst_id, last_error)
        else:
            logger.warning("OKX empty response: %s", inst_id)
        return None

    def _paginate(
        self,
        session: requests.Session,
        endpoint: str,
        inst_id: str,
        start_ts: int,
        end_ts: int,
        bar: str,
        max_pages: int,
    ) -> Optional[pd.DataFrame]:
        all_rows: list = []
        after = str(end_ts)
        deadline = time.monotonic() + _OKX_FETCH_BUDGET_S
        label = f"OKX fetch for {inst_id} via {endpoint.rsplit('/', 1)[-1]}"

        for _ in range(max_pages):
            check_budget(deadline, label, budget_s=_OKX_FETCH_BUDGET_S)
            params = {
                "instId": inst_id,
                "bar": bar,
                "limit": str(_MAX_PER_PAGE),
                "after": after,
            }

            def _do_request(params=params) -> dict:
                resp = session.get(
                    endpoint,
                    params=params,
                    timeout=_OKX_TIMEOUT,
                )
                # Transient gateway / rate-limit → raise for retry_with_budget
                if resp.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(
                        f"OKX HTTP {resp.status_code}",
                        response=resp,
                    )
                resp.raise_for_status()
                try:
                    data = resp.json()
                except ValueError as exc:
                    raise requests.RequestException(
                        f"OKX non-JSON response HTTP {resp.status_code}"
                    ) from exc
                code = str(data.get("code", ""))
                if code != "0":
                    # Business errors are not always transient; still surface.
                    msg = data.get("msg") or data.get("error_message") or code
                    raise requests.RequestException(f"OKX API code={code} msg={msg}")
                return data

            data = retry_with_budget(
                _do_request,
                transient=(requests.RequestException, TimeoutError),
                deadline=deadline,
                label=label,
            )
            raw_rows = data.get("data") or []
            if not raw_rows:
                break

            # Keep confirmed bars (confirm=="1"); also keep unconfirmed when
            # it is the only data returned so live partial days are not empty.
            confirmed = [r for r in raw_rows if len(r) > 8 and str(r[8]) == "1"]
            rows = confirmed if confirmed else list(raw_rows)
            all_rows.extend(rows)

            oldest_ts = int(raw_rows[-1][0])
            if oldest_ts <= start_ts or len(raw_rows) < _MAX_PER_PAGE:
                break
            after = str(oldest_ts)

        if not all_rows:
            return None

        columns = [
            "ts", "open", "high", "low", "close",
            "vol", "volCcy", "volCcyQuote", "confirm",
        ]
        # Rows may be shorter if API schema changes — pad safely
        normalized = []
        for r in all_rows:
            row = list(r) + [""] * (len(columns) - len(r))
            normalized.append(row[: len(columns)])

        df = pd.DataFrame(normalized, columns=columns)
        # OKX daily open is UTC+8 midnight (= 16:00 UTC). Keep absolute UTC
        # timestamps so multi-source merges stay consistent; floor to second.
        df["trade_date"] = pd.to_datetime(
            pd.to_numeric(df["ts"], errors="coerce"),
            unit="ms",
            utc=True,
        ).dt.tz_convert(None)
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df["vol"], errors="coerce").fillna(0)
        df = df.dropna(subset=["trade_date"]).set_index("trade_date").sort_index()
        df = df[~df.index.duplicated(keep="last")]

        start_dt = pd.Timestamp(start_ts, unit="ms")
        end_dt = pd.Timestamp(end_ts, unit="ms")
        df = df[(df.index >= start_dt) & (df.index < end_dt)]

        df = df[["open", "high", "low", "close", "volume"]].dropna(
            subset=["open", "high", "low", "close"]
        )
        return df if not df.empty else None
