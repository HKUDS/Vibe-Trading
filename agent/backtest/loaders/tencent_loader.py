"""Tencent Finance loader: free, no-auth A-share / HK data via HTTP API.

Uses Tencent's ifzq.gtimg.cn API which is not blocked by eastmoney's CDN.
Covers: A-shares (SH/SZ) and HK equities.  No API token required.

API format:
  https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh601595,day,2026-06-01,2026-06-13,500,qfq
  https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=hk00700,day,2026-06-01,2026-06-13,500,qfq
"""

from __future__ import annotations

import json
import logging
import time
from typing import Dict, List, Optional
import ssl
import urllib.request

import certifi
import pandas as pd

from backtest.loaders._symbol_utils import _is_etf_listed
from backtest.loaders.additive_conversion import convert_additive_to_multiplicative
from backtest.loaders.base import cached_loader_fetch, validate_date_range
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_BASE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
# The raw companion lives on the non-fq endpoint: fqkline without the qfq
# suffix serves no bars at all, while kline/kline returns the unadjusted
# "day" series (verified live 2026-09-23).
_RAW_BASE_URL = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"

# Tencent fqkline caps a single response at `_PAGE_SIZE` bars and serves the
# LAST bars of the requested window (ending at the `end` parameter), not the
# first — verified empirically 2026-09-11: a 2018-01-01..2026-06-30 request
# returned 500 bars spanning 2024-06-06..2026-06-30, while a window holding
# fewer than 500 trading days was served in full from its start (the start
# clamp is honoured).  Multi-year windows therefore paginate BACKWARD: see
# `_fetch_one`.
_PAGE_SIZE = 500
# 12 pages * 500 bars = 6000 bars ≈ 24 trading years; a hard cap also guards
# against pathological loop behavior if the API ever stops advancing.
_MAX_PAGES = 12
_PAGE_RETRIES = 3
_PAGE_BACKOFF = 0.6

_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

def _is_a_share(code: str) -> bool:
    return code.upper().endswith((".SZ", ".SH"))


def _is_hk_equity(code: str) -> bool:
    return code.upper().endswith(".HK")


@register
class DataLoader:
    """Tencent Finance A-share / HK OHLCV loader (free, HTTP, no auth)."""

    name = "tencent"
    markets = {"a_share", "hk_equity"}
    # Volume unit is market-dependent (HKUDS/Vibe-Trading#1062): the A-share
    # endpoint reports board lots (1 lot = 100 shares) while the HK endpoint
    # reports single shares. Empirically verified 2026-08-11 against
    # 600519.SH (55,128 lots) and 00700.HK (31,100,240 shares).
    volume_units = {"a_share": "lots", "hk_equity": "shares"}
    requires_auth = False

    def is_available(self) -> bool:
        """Always available — uses plain HTTP."""
        return True

    def __init__(self) -> None:
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
        validate_date_range(start_date, end_date)
        del fields

        if interval.strip().lower() not in {"1d", "d", "day", "daily"}:
            logger.warning(
                "tencent supports daily bars only; rejecting interval=%s",
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
                if df is not None and not df.empty and _is_a_share(code) and not _is_etf_listed(code):
                    # #1541: the additive qfq cannot serve returns; convert to
                    # the multiplicative convention when the raw companion
                    # supports it, keeping the additive series otherwise.
                    raw_df = None
                    try:
                        raw_df = cached_loader_fetch(
                            source=self.name,
                            symbol=code,
                            timeframe=interval,
                            start_date=start_date,
                            end_date=end_date,
                            fields=["raw"],
                            fetch=lambda code=code: self._fetch_one(
                                code, start_date, end_date, forward_adjusted=False
                            ),
                        )
                    except Exception as exc:  # noqa: BLE001 - degrade to additive
                        logger.warning(
                            "tencent raw companion fetch failed for %s, serving additive: %s",
                            code,
                            exc,
                        )
                    converted = convert_additive_to_multiplicative(raw_df, df)
                    if converted is not None:
                        converted.attrs = {
                            **getattr(df, "attrs", {}),
                            "adjustment": "split_dividend",
                        }
                        result[code] = converted
                        continue
                if df is not None and not df.empty:
                    result[code] = df
            except Exception as exc:
                logger.warning("tencent failed for %s: %s", code, exc)
        return result

    def _request_page(
        self, code: str, start_date: str, end_date: str, forward_adjusted: bool = True,
    ) -> Optional[pd.DataFrame]:
        """Fetch up to `_PAGE_SIZE` bars in [start_date, end_date]."""
        if not _is_a_share(code) and not _is_hk_equity(code):
            return None

        parts = code.upper().split(".")
        symbol = parts[0]
        suffix = parts[1] if len(parts) > 1 else ""

        if suffix == "SH":
            tencent_code = f"sh{symbol}"
        elif suffix == "SZ":
            tencent_code = f"sz{symbol}"
        elif suffix == "HK":
            # Tencent expects a zero-padded 5-digit HK code (hk00700).
            tencent_code = f"hk{symbol.zfill(5)}"
        else:
            return None

        url = (
            f"{_BASE_URL if forward_adjusted else _RAW_BASE_URL}?param={tencent_code},day,"
            f"{start_date},{end_date},{_PAGE_SIZE}"
            f"{',qfq' if forward_adjusted else ''}"
        )

        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://web.ifzq.gtimg.cn/",
        })
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CONTEXT) as resp:
            raw = resp.read().decode("utf-8")

        data = json.loads(raw)
        # Response: {"code":0,"data":{"sh601595":{"day":[["2026-06-01","21.32",...], ...]}}}
        if data.get("code") not in (0, None) and not data.get("data"):
            # An error-shaped reply is a failure, not an empty window: None
            # here would let a throttled reply end the walk mid-pagination
            # and serve (and cache) a truncated series as complete history.
            raise ValueError(f"tencent fqkline error reply: code={data.get('code')}")
        stock_data = data.get("data", {})
        if not stock_data:
            return None

        # Get the first (only) key
        stock_key = next(iter(stock_data), None)
        if not stock_key:
            return None

        # Try "day" first, then "qfqday" (forward-adjusted)
        if forward_adjusted:
            klines = stock_data[stock_key].get("qfqday") or stock_data[stock_key].get("day")
        else:
            klines = stock_data[stock_key].get("day")
        if not klines:
            return None

        # Each row: ["date", "open", "close", "high", "low", "volume"]
        rows = []
        for k in klines:
            if len(k) >= 6:
                rows.append({
                    "trade_date": k[0],
                    "open": float(k[1]),
                    "close": float(k[2]),
                    "high": float(k[3]),
                    "low": float(k[4]),
                    "volume": float(k[5]),
                })

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date").sort_index()
        df = df[["open", "high", "low", "close", "volume"]].dropna(
            subset=["open", "high", "low", "close"]
        )
        return df

    def _fetch_one(
        self, code: str, start_date: str, end_date: str, forward_adjusted: bool = True,
    ) -> Optional[pd.DataFrame]:
        """Paginate [start_date, end_date] in `_PAGE_SIZE`-bar windows.

        The Tencent API returns at most 500 bars per request regardless of the
        requested window, and those are the LAST bars ending at the requested
        end date (see the `_PAGE_SIZE` comment for the verified semantics).
        Pagination therefore walks BACKWARD: start_date stays fixed and the end
        cursor moves to the day before each page's oldest bar, until a short
        page (< `_PAGE_SIZE`) or an exhausted cursor signals the window is
        served in full. Walking forward instead — advancing the start cursor
        past each page's newest bar — silently degrades any window longer than
        one page to its most recent ~500 bars: the first response already ends
        at end_date, the advanced cursor steps past the window, the next page
        is empty, and the loop exits cleanly with a tail-only series.

        A window this loader cannot serve in full raises instead of returning a
        quietly short series, matching the other bounded-window loaders.
        """
        chunks: List[pd.DataFrame] = []
        cursor_end = end_date
        seen_ends: set[str] = set()

        for _ in range(_MAX_PAGES):
            if cursor_end in seen_ends:
                raise ValueError(
                    f"incomplete tencent history: {code} stopped advancing at "
                    f"{cursor_end} before reaching {start_date}"
                )
            seen_ends.add(cursor_end)

            page: Optional[pd.DataFrame] = None
            last_error: Optional[Exception] = None
            for attempt in range(_PAGE_RETRIES):
                try:
                    page = self._request_page(code, start_date, cursor_end, forward_adjusted)
                    last_error = None
                    break
                except Exception as exc:  # noqa: BLE001 - transient network jitter
                    last_error = exc
                    if attempt < _PAGE_RETRIES - 1:
                        time.sleep(_PAGE_BACKOFF * (2 ** attempt))
            if last_error is not None:
                # Partial pages already collected would read as a complete
                # history downstream; a failed page is an error, not a series.
                raise ValueError(
                    f"incomplete tencent history: {code} page ending at "
                    f"{cursor_end} failed after {_PAGE_RETRIES} attempts: "
                    f"{last_error}"
                ) from last_error

            if page is None or page.empty:
                if not chunks:
                    break
                # A mid-walk empty page is ambiguous: the genuine start of
                # history, or a throttled reply. One re-request decides — a
                # transient glitch returns data, a genuine boundary stays
                # empty and terminates the walk.
                time.sleep(_PAGE_BACKOFF)
                try:
                    page = self._request_page(code, start_date, cursor_end, forward_adjusted)
                except Exception as exc:  # noqa: BLE001 - transient network jitter
                    raise ValueError(
                        f"incomplete tencent history: {code} re-request at "
                        f"{cursor_end} failed: {exc}"
                    ) from exc
                if page is None or page.empty:
                    break
            chunks.append(page)

            # A short page means the walk reached start_date.
            if len(page) < _PAGE_SIZE:
                break
            first = page.index.min()
            next_end = (first - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            if next_end < start_date:
                break
            cursor_end = next_end
        else:
            raise ValueError(
                f"incomplete tencent history: {code} hit {_MAX_PAGES} pages "
                f"without reaching {start_date}"
            )

        if not chunks:
            return None
        df = pd.concat(chunks)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        return df
