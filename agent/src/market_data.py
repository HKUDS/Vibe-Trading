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

# Symbol -> preferred source. The matched source is a member of its market's
# fallback chain (registry.FALLBACK_CHAINS), so an unavailable preferred source
# still degrades gracefully to the rest of the chain. US equities route to the
# throttle-tolerant Yahoo public endpoint first (lower IP-ban risk than the
# yfinance SDK), A-shares and HK equities to the never-banned Tencent endpoint.
_SOURCE_PATTERNS = [
    (re.compile(r"^local:", re.I), "local"),
    (re.compile(r"^\d{6}\.(SZ|SH|BJ)$", re.I), "tencent"),
    (re.compile(r"^[A-Z]+\.US$", re.I), "yahoo"),
    (re.compile(r"^\d{3,5}\.HK$", re.I), "tencent"),
    # India: NSE (RELIANCE.NS) / BSE (500325.BO). Tickers may carry '&' and '-'
    # (e.g. M&M.NS, BAJAJ-AUTO.NS). Served by Yahoo's public chart endpoint.
    (re.compile(r"^[A-Z0-9&.\-]+\.(NS|BO)$", re.I), "yahoo"),
    # Canada: Toronto Stock Exchange (TD.TO) / TSX Venture (PNG.V).
    (re.compile(r"^[A-Z0-9&.\-]+\.(TO|V)$", re.I), "yahoo"),
    # UK: London Stock Exchange (VOD.L, SHEL.L). Served by Yahoo's public
    # chart endpoint verbatim (parity with Canada .TO/.V handling).
    (re.compile(r"^[A-Z0-9&.\-]+\.L$", re.I), "yahoo"),
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


# Canadian venue-alias helper: TSX (.TO) <-> TSX Venture (.V).
#
# A Canadian issuer lists on exactly one of the two venues. When a listing
# moves (graduation TSX-V -> TSX, or the rarer reverse), Yahoo keeps only the
# current venue's symbol; the old one 404s (HIVE.V -> HIVE.TO after HIVE
# Digital Technologies graduated to the main board). ``fetch_market_data``
# uses this to retry the sibling suffix before recording a symbol as
# ``_unresolved``, so moved listings resolve without a manual yfinance detour.
_CA_SUFFIX_RE = re.compile(r"^(?P<base>[A-Z0-9&.\-]+)\.(?P<suffix>TO|V)$", re.I)


def _ca_venue_sibling(code: str) -> str | None:
    """Return the other Canadian venue's symbol for a ``.TO``/``.V`` code.

    ``HIVE.V`` -> ``HIVE.TO``, ``TD.TO`` -> ``TD.V``, ``BBD-B.TO`` ->
    ``BBD-B.V`` (hyphenated class base preserved). Returns ``None`` for any
    symbol that is not a Canadian ``.TO``/``.V`` ticker, so non-Canadian
    lookups are never touched by the venue fallback.
    """
    match = _CA_SUFFIX_RE.match(code.strip())
    if not match:
        return None
    sibling = "V" if match.group("suffix").upper() == "TO" else "TO"
    return f"{match.group('base')}.{sibling}"


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
    max_fallback_attempts: int = 5,
    include_provenance: bool = False,
) -> dict[str, Any]:
    """Fetch normalized OHLCV data through the repository loader layer.

    When ``source="auto"`` (or any resolved source), if the chosen loader
    raises during :meth:`fetch` the call falls through to the next source in
    the market's :data:`backtest.loaders.registry.FALLBACK_CHAINS` (e.g. crypto
    OKX → Binance → CCXT → Yahoo). At most ``max_fallback_attempts`` retries
    are attempted before the symbol is recorded as ``_unresolved``.

    With ``include_provenance=True`` each symbol carries ``_provenance``
    metadata including ``volume_unit`` — the unit of the ``volume`` column as
    declared by the serving loader for that market (``"lots"`` = board lots of
    100 shares, ``"shares"`` = single shares, ``None`` = undeclared). Volume
    units are source- and market-dependent (HKUDS/Vibe-Trading#1062), so
    consumers must read this field instead of assuming a unit.
    """
    from backtest.engines._market_hooks import _detect_market
    from backtest.loaders.base import NoAvailableSourceError
    from backtest.loaders.registry import (
        FALLBACK_CHAINS,
        _NO_NETWORK_FALLBACK_SOURCES,
        get_source_order_override,
        refresh_source_order_overrides,
    )

    # Pick up MARKET_DATA_ORDER_* overrides that appeared after this module's
    # import (e.g. ~/.vibe-trading/.env loaded lazily, or a Settings PUT in
    # another code path). Snapshot-gated: no-op when nothing changed.
    refresh_source_order_overrides()

    results: dict[str, Any] = {}
    provenance: dict[str, dict[str, Any]] = {}
    result_aliases = {
        code: code.split(":", 1)[1]
        if code.lower().startswith("local:")
        else code
        for code in codes
    }

    groups: dict[tuple[str, str], list[str]] = {}
    for code in codes:
        src = detect_source(code) if source == "auto" else source
        groups.setdefault((src, _detect_market(code)), []).append(code)

    def _chain_for(src: str, market: str) -> list[str]:
        """Return the ordered fallback chain for ``src``.

        Prefers the chain of the symbol's own market when ``src`` is a member
        of it. Matching by source name alone is ambiguous — ``yahoo`` appears
        in the US, HK, India and Korea chains, and a first-match lookup would
        send HK symbols down the US chain, exhausting the attempt budget on
        US-only sources.

        Falls back to ``[src]`` so an explicit source outside any chain still
        gets at least one attempt.
        """
        if fallback_chain_provider is not None:
            return fallback_chain_provider(src)
        market_chain = FALLBACK_CHAINS.get(market, [])
        if src in market_chain:
            return market_chain
        for chain in FALLBACK_CHAINS.values():
            if src in chain:
                return chain
        return [src]

    def _fetch_via_chain(
        src: str, market: str, src_codes: list[str]
    ) -> tuple[dict[str, Any], str | None, type | None]:
        """Run the ordered source chain for one group.

        Returns ``(data_map, used_source, provider_cls)`` — ``data_map`` keyed
        by requested symbol -> OHLCV frame (possibly empty), the source name
        that actually served it, and the serving loader class (both ``None``
        when every attempt failed).
        """
        chain = _chain_for(src, market)
        # An env-configured order override (MARKET_DATA_ORDER_<MARKET>, set
        # via the Settings page) rewrites the attempt order for auto-detected
        # sources: the override list IS the attempt order, so a user who put
        # tushare first actually starts there. Guards: explicit source
        # requests stay src-first; the fallback_chain_provider test hook wins;
        # local:/qveris/tickerall keep their no-network entry point.
        override = (
            get_source_order_override(market)
            if source == "auto"
            and fallback_chain_provider is None
            and src not in _NO_NETWORK_FALLBACK_SOURCES
            else None
        )
        candidates = (
            list(override)
            if override is not None and src in override
            else [src, *chain]
        )
        # Deduplicate (preserving order), then cap the attempt budget.
        attempts: list[str] = []
        for candidate in candidates:
            if candidate not in attempts:
                attempts.append(candidate)
        attempts = attempts[: max(1, max_fallback_attempts)]

        data_map: dict[str, Any] = {}
        used_source: str | None = None
        provider_cls: type | None = None
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
                provider_cls = loader_cls
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
        return data_map, used_source, provider_cls

    def _emit(
        symbol: str,
        df: Any,
        *,
        src: str,
        used_source: str | None,
        provider_cls: type | None,
        market: str,
        extra_provenance: dict[str, Any] | None = None,
    ) -> None:
        """Normalize one symbol's frame into ``results`` (+ provenance)."""
        records = df.reset_index().to_dict(orient="records")
        for row in records:
            for key, value in row.items():
                row[key] = _json_safe(value)
        results[symbol] = cap_rows(records, max_rows)
        if include_provenance:
            volume_units = getattr(provider_cls, "volume_units", None) or {}
            entry: dict[str, Any] = {
                "source": used_source or src,
                "requested_source": source,
                "detected_source": src,
                "fallback_used": bool(used_source and used_source != src),
                "currency_conversion": "none",
                "volume_unit": volume_units.get(market),
            }
            if extra_provenance:
                entry.update(extra_provenance)
            provenance[symbol] = entry

    for (src, market), src_codes in groups.items():
        data_map, used_source, provider_cls = _fetch_via_chain(src, market, src_codes)
        for symbol, df in data_map.items():
            _emit(
                symbol, df,
                src=src, used_source=used_source, provider_cls=provider_cls, market=market,
            )

    unresolved = [
        code
        for code in codes
        if code not in results and result_aliases[code] not in results
    ]

    # Canadian venue-alias fallback: TSX (.TO) <-> TSX Venture (.V).
    #
    # A company lists on TSX or TSX-V, never both, so when one venue's symbol
    # fails to resolve (e.g. Yahoo 404s HIVE.V after the issuer graduated to
    # the main board), the sibling suffix is the only plausible re-listing.
    # Retry the sibling through the same market chain before giving up, and
    # key the result under the ORIGINAL requested symbol so the grounding/
    # identity gate and callers still see evidence for exactly what was asked.
    if unresolved:
        for code in list(unresolved):
            sibling = _ca_venue_sibling(code)
            if sibling is None:
                continue
            src = detect_source(code) if source == "auto" else source
            if src in _NO_NETWORK_FALLBACK_SOURCES:
                # Explicit local/tickerall/qveris requests must not silently
                # fall through to a network loader (registry contract).
                continue
            market = _detect_market(code)
            if sibling in results:
                # The sibling was already requested and resolved in this run —
                # alias its bars under the requested code (no extra fetch).
                results[code] = results[sibling]
                if include_provenance:
                    base = provenance.get(sibling, {})
                    provenance[code] = {
                        "source": base.get("source", src),
                        "requested_source": source,
                        "detected_source": src,
                        "fallback_used": True,
                        "currency_conversion": "none",
                        "volume_unit": base.get("volume_unit"),
                        "venue_fallback": True,
                        "resolved_symbol": sibling,
                    }
                logger.info(
                    "market-data venue alias %s -> %s (source=%s)", code, sibling, src,
                )
                unresolved.remove(code)
                continue
            # Sibling not already resolved — targeted re-fetch of just that
            # symbol through the same market's source chain.
            sibling_data, used_source, provider_cls = _fetch_via_chain(
                src, market, [sibling]
            )
            if sibling_data:
                df = next(iter(sibling_data.values()))
                if df is not None and not df.empty:
                    _emit(
                        code, df,
                        src=src, used_source=used_source, provider_cls=provider_cls,
                        market=market,
                        extra_provenance={
                            "venue_fallback": True,
                            "resolved_symbol": sibling,
                        },
                    )
                    logger.info(
                        "market-data venue fallback %s -> %s (source=%s)",
                        code, sibling, src,
                    )
                    unresolved.remove(code)

    if unresolved:
        results["_unresolved"] = unresolved
    if include_provenance and provenance:
        results["_provenance"] = provenance

    return results


def fetch_market_data_json(**kwargs: Any) -> str:
    """Fetch market data and return strict JSON."""
    return json.dumps(fetch_market_data(**kwargs), ensure_ascii=False, indent=2, allow_nan=False)
