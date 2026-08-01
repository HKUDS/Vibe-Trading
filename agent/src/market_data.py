"""Shared market data helpers for MCP and local agent tools."""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MAX_ROWS = 250

# Symbol -> preferred source. The matched source is the head of its market's
# fallback chain (registry.FALLBACK_CHAINS), so an unavailable preferred source
# still degrades gracefully to the rest of the chain. US/HK equities route to
# the throttle-tolerant Yahoo public endpoint first (lower IP-ban risk than the
# yfinance SDK), A-shares to the Tencent quote endpoint.
_SOURCE_PATTERNS = [
    (re.compile(r"^local:", re.I), "local"),
    (re.compile(r"^\d{6}\.(SZ|SH|BJ)$", re.I), "tencent"),
    (re.compile(r"^[A-Z]+\.US$", re.I), "yahoo"),
    (re.compile(r"^\d{3,5}\.HK$", re.I), "yahoo"),
    # India: NSE (RELIANCE.NS) / BSE (500325.BO). Tickers may carry '&' and '-'
    # (e.g. M&M.NS, BAJAJ-AUTO.NS). Served by Yahoo's public chart endpoint.
    (re.compile(r"^[A-Z0-9&.\-]+\.(NS|BO)$", re.I), "yahoo"),
    # Yahoo futures (GC=F, CL=F) and forex (EURUSD=X) suffix conventions —
    # served verbatim by Yahoo's public chart endpoint (#718). Without these,
    # such symbols fell through to the ``tushare`` default and were routed to
    # China-market loaders that cannot resolve them.
    (re.compile(r"^[A-Z0-9]+=F$", re.I), "yahoo"),
    (re.compile(r"^[A-Z]+=X$", re.I), "yahoo"),
    # Korea: KOSPI (005930.KS) / KOSDAQ (247540.KQ), 6-digit codes. Served by
    # pykrx (KRX public data, no auth); registry falls back to Yahoo/yfinance.
    (re.compile(r"^\d{6}\.(KS|KQ)$", re.I), "pykrx"),
    (re.compile(r"^[A-Z]+-USDT$", re.I), "okx"),
    (re.compile(r"^[A-Z]+/USDT$", re.I), "ccxt"),
    # Forex pairs and metals (EUR/USD, XAU/USD, EURUSD.FX). mt5 is the head of
    # the forex chain and degrades to akshare/yfinance via the registry when no
    # local MT5 terminal is attached. The 3-letter quote cannot collide with
    # the 4-letter /USDT crypto rule above.
    (re.compile(r"^[A-Z]{3}/[A-Z]{3}$", re.I), "mt5"),
    (re.compile(r"^[A-Z]{6}\.FX$", re.I), "mt5"),
]


def detect_source(code: str) -> str:
    """Infer the best loader source for a normalized symbol."""
    for pattern, source in _SOURCE_PATTERNS:
        if pattern.match(code):
            return source
    return "tushare"


def get_loader(source: str):
    """Get loader class via registry with fallback support."""
    from backtest.loaders.registry import get_loader_cls_with_fallback

    return get_loader_cls_with_fallback(source)


def cap_rows(records: list, max_rows: int) -> list | dict[str, object]:
    """Bound a per-symbol row list to keep tool payloads within budget."""
    n = len(records)
    if max_rows < 0:
        max_rows = DEFAULT_MAX_ROWS
    if max_rows == 0 or n <= max_rows:
        return records
    step = math.ceil(n / max_rows)
    sampled = records[::step]
    if sampled[-1] is not records[-1]:
        sampled = sampled + [records[-1]]
    return {
        "rows": n,
        "returned": len(sampled),
        "truncated": True,
        "policy": f"every-{step}th-row (even stride; last bar pinned)",
        "hint": "narrow the date range, coarsen interval, or set max_rows=0 for all rows",
        "data": sampled,
    }


def _json_safe(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def fetch_market_data(
    *,
    codes: list[str],
    start_date: str,
    end_date: str,
    source: str = "auto",
    interval: str = "1D",
    max_rows: int = DEFAULT_MAX_ROWS,
    loader_resolver: Callable[[str], type] = get_loader,
    fallback_chain_provider: Callable[[str], list[str]] | None = None,
    max_fallback_attempts: int = 3,
    include_provenance: bool = False,
) -> dict[str, Any]:
    """Fetch normalized OHLCV data through the repository loader layer.

    When ``source="auto"`` (or any resolved source), if the chosen loader
    raises during :meth:`fetch` the call falls through to the next source in
    the market's :data:`backtest.loaders.registry.FALLBACK_CHAINS` (e.g. crypto
    OKX → Binance → CCXT → Yahoo). At most ``max_fallback_attempts`` retries
    are attempted before the symbol is recorded as ``_unresolved``.
    """
    from backtest.loaders.base import NoAvailableSourceError
    from backtest.loaders.registry import FALLBACK_CHAINS

    results: dict[str, Any] = {}
    provenance: dict[str, dict[str, Any]] = {}
    result_aliases = {
        code: code.split(":", 1)[1]
        if code.lower().startswith("local:")
        else code
        for code in codes
    }

    if source == "auto":
        groups: dict[str, list[str]] = {}
        for code in codes:
            src = detect_source(code)
            groups.setdefault(src, []).append(code)
    else:
        groups = {source: list(codes)}

    def _chain_for(src: str) -> list[str]:
        """Return the ordered fallback chain for the market containing ``src``.

        Falls back to ``[src]`` so an explicit source outside any chain still
        gets at least one attempt.
        """
        if fallback_chain_provider is not None:
            return fallback_chain_provider(src)
        for market, chain in FALLBACK_CHAINS.items():
            if src in chain:
                return chain
        return [src]

    for src, src_codes in groups.items():
        chain = _chain_for(src)
        # Start the attempt list with the requested source, then the rest of
        # the chain (preserving order, no duplicates).
        attempts: list[str] = []
        for candidate in [src, *chain]:
            if candidate not in attempts:
                attempts.append(candidate)
        attempts = attempts[: max(1, max_fallback_attempts)]

        data_map: dict[str, Any] = {}
        used_source: str | None = None
        for attempt_src in attempts:
            try:
                loader_cls = loader_resolver(attempt_src)
            except NoAvailableSourceError as exc:
                logger.debug("loader %r unavailable: %s", attempt_src, exc)
                continue
            except Exception as exc:  # noqa: BLE001 — resolver may raise for non-network reasons
                logger.debug("loader %r resolver failed: %s", attempt_src, exc)
                continue
            try:
                loader = loader_cls()
                data_map = loader.fetch(src_codes, start_date, end_date, interval=interval)
                used_source = attempt_src
                if data_map:
                    break
            except Exception as exc:  # noqa: BLE001 — contained per-symbol fallback
                logger.error(
                    "market-data loader %r failed for %s; trying next source in chain: %s",
                    attempt_src, src_codes, exc,
                )
                continue

        if used_source and used_source != src:
            logger.info(
                "market-data source %r unavailable for %s; fell back to %r",
                src, src_codes, used_source,
            )

        for symbol, df in data_map.items():
            records = df.reset_index().to_dict(orient="records")
            for row in records:
                for key, value in row.items():
                    row[key] = _json_safe(value)
            results[symbol] = cap_rows(records, max_rows)
            if include_provenance:
                provenance[symbol] = {
                    "source": used_source or src,
                    "requested_source": source,
                    "detected_source": src,
                    "fallback_used": bool(used_source and used_source != src),
                    "currency_conversion": "none",
                }

    unresolved = [
        code
        for code in codes
        if code not in results and result_aliases[code] not in results
    ]
    if unresolved:
        results["_unresolved"] = unresolved
    if include_provenance and provenance:
        results["_provenance"] = provenance

    return results


def fetch_market_data_json(**kwargs: Any) -> str:
    """Fetch market data and return strict JSON."""
    return json.dumps(fetch_market_data(**kwargs), ensure_ascii=False, indent=2, allow_nan=False)
