"""OKX spot candle loader (crypto).

Uses OKX V5 public REST API (no auth).
Supports 1m/5m/15m/30m/1H/4H/1D.
Up to 300 bars per request; paginates with ``after`` for longer history.

Disk cache: when env var OKX_CACHE_DIR is set (or default
~/.cache/vibe-trading-okx exists) the fetch result is cached as parquet
keyed by (sorted codes, start_date, end_date, interval). Cross-combo
stage-4 sweeps reuse the same window — a single OKX round-trip turns
into ~ms parquet reads for every subsequent combo.
"""

import hashlib
import json as _json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests

from backtest.loaders.base import (
    check_budget,
    retry_with_budget,
    validate_date_range,
)
from backtest.loaders.registry import register

BASE_URL = "https://www.okx.com/api/v5"
_MAX_PER_PAGE = 300
# P12-b parity: OKX already sets a per-request timeout but had no retry
# budget, so a transient blip dropped the whole symbol and a slow tier
# could stall ~max_pages*timeout. Bound it like the ccxt loader; retry
# scheduling is delegated to :mod:`backtest.loaders.base`.
_OKX_TIMEOUT = int(os.getenv("OKX_TIMEOUT_S", "15"))
_OKX_FETCH_BUDGET_S = float(os.getenv("OKX_FETCH_BUDGET_S", "60"))


def _cache_dir() -> Optional[Path]:
    """Return the cache root, or None if disabled (OKX_CACHE_DIR=disable)."""
    val = os.getenv("OKX_CACHE_DIR")
    if val == "disable":
        return None
    if val:
        p = Path(val)
    else:
        p = Path.home() / ".cache" / "vibe-trading-okx"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _cache_key(codes: List[str], start_date: str, end_date: str, interval: str) -> str:
    payload = _json.dumps(
        {"codes": sorted(c.replace("/", "-").upper() for c in codes),
         "start": start_date, "end": end_date, "interval": interval},
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _cache_load(key: str) -> Optional[Dict[str, pd.DataFrame]]:
    root = _cache_dir()
    if root is None:
        return None
    meta_path = root / f"{key}.json"
    if not meta_path.exists():
        return None
    try:
        meta = _json.loads(meta_path.read_text(encoding="utf-8"))
        out: Dict[str, pd.DataFrame] = {}
        for code, fname in meta.items():
            fp = root / fname
            if not fp.exists():
                return None
            out[code] = pd.read_parquet(fp)
        return out
    except Exception:  # noqa: BLE001
        return None


def _cache_save(key: str, result: Dict[str, pd.DataFrame]) -> None:
    root = _cache_dir()
    if root is None:
        return
    meta: Dict[str, str] = {}
    for code, df in result.items():
        safe_code = code.replace("/", "_")
        fname = f"{key}_{safe_code}.parquet"
        try:
            df.to_parquet(root / fname)
            meta[code] = fname
        except Exception:  # noqa: BLE001
            return
    try:
        (root / f"{key}.json").write_text(_json.dumps(meta), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


@register
class DataLoader:
    """OKX crypto OHLCV loader."""

    name = "okx"
    markets = {"crypto"}
    requires_auth = False

    def is_available(self) -> bool:
        """Always available (public API, no auth)."""
        return True

    def __init__(self) -> None:
        """No credentials required for public candles."""
        pass

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        fields: Optional[List[str]] = None,
        interval: str = "1D",
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
            print(f"[WARN] OKX ignores extra fields: {fields}")

        valid_intervals = {"1m", "5m", "15m", "30m", "1H", "4H", "1D"}
        if interval not in valid_intervals:
            print(f"[WARN] unsupported OKX interval {interval}, using 1D")
            interval = "1D"

        codes = [c.replace("/", "-").upper() for c in codes]

        # Disk cache hit → skip OKX entirely.
        cache_key = _cache_key(codes, start_date, end_date, interval)
        cached = _cache_load(cache_key)
        if cached is not None and all(c in cached for c in codes):
            print(f"[okx-cache] hit {cache_key} ({len(cached)} codes, "
                  f"{sum(len(df) for df in cached.values())} total rows)")
            return {c: cached[c] for c in codes}

        start_ts = int(pd.Timestamp(start_date).timestamp() * 1000)
        end_ts = int((pd.Timestamp(end_date) + pd.Timedelta(days=1)).timestamp() * 1000)

        max_pages = 200 if interval in ("1m", "5m") else 50 if interval in ("15m", "30m") else 200

        result: Dict[str, pd.DataFrame] = {}
        for symbol in codes:
            try:
                df = self._fetch_candles(symbol, start_ts, end_ts, interval, max_pages)
                if df is not None and not df.empty:
                    result[symbol] = df
            except Exception as exc:
                print(f"[WARN] failed to fetch {symbol}: {exc}")

        if result:
            _cache_save(cache_key, result)
        return result

    def _fetch_candles(
        self, inst_id: str, start_ts: int, end_ts: int,
        bar: str = "1D", max_pages: int = 20,
    ) -> Optional[pd.DataFrame]:
        """Paginated candle download.

        Args:
            inst_id: OKX instrument id.
            start_ts: Start time (ms).
            end_ts: End time (ms).
            bar: Bar size.
            max_pages: Max pagination rounds.

        Returns:
            OHLCV DataFrame or None.
        """
        all_rows: list = []
        after = str(end_ts)
        deadline = time.monotonic() + _OKX_FETCH_BUDGET_S
        label = f"OKX fetch for {inst_id}"

        for _ in range(max_pages):
            check_budget(deadline, label, budget_s=_OKX_FETCH_BUDGET_S)
            params = {
                "instId": inst_id,
                "bar": bar,
                "limit": str(_MAX_PER_PAGE),
                "after": after,
            }

            def _do_request() -> dict:
                resp = requests.get(
                    f"{BASE_URL}/market/history-candles",
                    params=params,
                    timeout=_OKX_TIMEOUT,
                )
                return resp.json()

            data = retry_with_budget(
                _do_request,
                transient=requests.RequestException,
                deadline=deadline,
                label=label,
            )
            if data.get("code") != "0" or not data.get("data"):
                break

            rows = data["data"]
            rows = [r for r in rows if r[8] == "1"]
            all_rows.extend(rows)

            oldest_ts = int(rows[-1][0]) if rows else start_ts
            if oldest_ts <= start_ts or len(data["data"]) < _MAX_PER_PAGE:
                break
            after = str(oldest_ts)

        if not all_rows:
            print(f"[WARN] OKX empty response: {inst_id}")
            return None

        columns = ["ts", "open", "high", "low", "close", "vol", "volCcy", "volCcyQuote", "confirm"]
        df = pd.DataFrame(all_rows, columns=columns)
        df["trade_date"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms")
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df["vol"], errors="coerce").fillna(0)
        df = df.set_index("trade_date").sort_index()

        start_dt = pd.Timestamp(start_ts, unit="ms")
        end_dt = pd.Timestamp(end_ts, unit="ms")
        df = df[(df.index >= start_dt) & (df.index < end_dt)]

        df = df[["open", "high", "low", "close", "volume"]].dropna(subset=["open", "high", "low", "close"])
        return df if not df.empty else None
