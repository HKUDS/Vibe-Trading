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
    # UK: London Stock Exchange (VOD.L, SHEL.L). Yahoo serves the suffix
    # verbatim; without this they fell through to the tushare default and were
    # routed to China-market loaders that cannot resolve them.
    (re.compile(r"^[A-Z0-9&.\-]+\.L$", re.I), "yahoo"),
    # Yahoo futures (GC=F, CL=F) and forex (EURUSD=X) suffix conventions —
    # served verbatim by Yahoo's public chart endpoint (#718). Without these,
    # such symbols fell through to the ``tushare`` default and were routed to
    # China-market loaders that cannot resolve them.
    (re.compile(r"^[A-Z0-9]+=F$", re.I), "yahoo"),
    (re.compile(r"^[A-Z]+=X$", re.I), "yahoo"),
    # Yahoo index symbols (^SPX, ^GSPC, ^FTSE, ^VIX, ...) — served verbatim,
    # same convention as =F/=X. Without this they fell to the tushare default.
    (re.compile(r"^\^[A-Za-z0-9.\-]+$", re.I), "yahoo"),
    # Korea: KOSPI (005930.KS) / KOSDAQ (247540.KQ), 6-digit codes. Served by
    # pykrx (KRX public data, no auth); registry falls back to Yahoo/yfinance.
    (re.compile(r"^\d{6}\.(KS|KQ)$", re.I), "pykrx"),
    (re.compile(r"^[A-Z]+-USDT$", re.I), "okx"),
    (re.compile(r"^[A-Z]+/USDT$", re.I), "ccxt"),
    # Iran: Nobitex IRT-quoted crypto pairs (BTCIRT / BTC-IRT). Toman-
    # denominated public UDF endpoint, no auth; explicit-source only (not in
    # the crypto fallback chain — non-IRT pairs would never resolve there).
    (re.compile(r"^[A-Z]+[-/]?IRT$", re.I), "nobitex"),
    # Iran: Wallex TMN-quoted crypto pairs (USDTTMN / USDT-TMN). Public UDF
    # endpoint, no auth; explicit-source only like nobitex.
    (re.compile(r"^[A-Z]+[-/]?TMN$", re.I), "wallex"),
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


#: ISO-4217-style fiat codes. A pair whose BOTH legs are fiat is an FX pair,
#: never a crypto instrument — ``GBP/USD`` used to be classified as the crypto
#: pair "GBP-USD" (its quote leg USD is a crypto-connector quote asset) by the
#: symbol-search tool's pair classifier and by the grounding ledger's symbol
#: scanner, which then disagreed with the search result ("GBPUSD=X") and made
#: the identity gate flag a conflict. One canonicalization is shared here so
#: search, fetch and grounding all agree.
FIAT_CODES = frozenset(
    {
        "USD", "EUR", "GBP", "JPY", "CHF", "CNY", "CNH", "HKD", "AUD", "NZD",
        "CAD", "KRW", "INR", "SGD", "SEK", "NOK", "DKK", "MXN", "BRL", "ZAR",
        "TRY", "RUB", "PLN", "THB", "MYR", "IDR", "PHP", "VND", "ILS", "AED",
        "SAR", "EGP", "CZK", "HUF", "RON", "CLP", "COP", "PEN", "TWD", "CUP",
    }
)

#: Yahoo-served FX pair symbol forms, canonicalized to ``XXXYYY=X``.
_FX_PAIR_RE = re.compile(r"^(?P<base>[A-Z]{3})(?:/)?(?P<quote>[A-Z]{3})$", re.IGNORECASE)


def canonical_fx_pair(value: str) -> str | None:
    """Return a Yahoo FX pair in canonical ``XXXYYY=X`` form, or ``None``.

    Recognizes ``GBP/USD``, ``GBPUSD`` and ``GBPUSD=X`` (both legs must be
    fiat codes — ``ETH/USD`` and ``XAU/USD`` are not FX pairs) and returns
    the canonical spelling the market-data fetch layer serves directly.
    """
    clean = str(value or "").strip().upper()
    if clean.endswith("=X"):
        clean = clean[:-2]
    matched = _FX_PAIR_RE.fullmatch(clean)
    if not matched:
        return None
    base, quote = matched.group("base"), matched.group("quote")
    if base not in FIAT_CODES or quote not in FIAT_CODES:
        return None
    return f"{base}{quote}=X"


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
        price_caliber,
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
    ) -> tuple[dict[str, Any], str | None, type | None, dict[str, tuple[str, type]]]:
        """Run the ordered source chain for one group, per symbol.

        Returns ``(data_map, used_source, provider_cls, symbol_sources)`` —
        ``data_map`` keyed by requested symbol -> OHLCV frame (possibly
        empty), ``used_source``/``provider_cls`` the first source that served
        anything (``None`` when every attempt failed), and ``symbol_sources``
        mapping each served symbol to the source that actually served it. A
        partially successful attempt no longer stops the walk: symbols the
        loader omitted are retried down the chain and merged in.
        """
        chain = _chain_for(src, market)
        # An env-configured order override (MARKET_DATA_ORDER_<MARKET>, set
        # via the Settings page) rewrites the attempt order for auto-detected
        # sources: the override list IS the attempt order, so a user who put
        # tushare first actually starts there. Guards: explicit source
        # requests stay src-first; the fallback_chain_provider test hook wins;
        # local:/qveris/tickerall/fmp keep their no-network entry point
        # (explicit fmp must not silently return yahoo on Stable 403 — issue #1270).
        # Sources in _NO_NETWORK_FALLBACK_SOURCES never walk the chain.
        if src in _NO_NETWORK_FALLBACK_SOURCES:
            candidates = [src]
            override = None
        else:
            override = (
                get_source_order_override(market)
                if source == "auto"
                and fallback_chain_provider is None
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
        symbol_sources: dict[str, tuple[str, type]] = {}
        used_source: str | None = None
        provider_cls: type | None = None
        remaining = list(dict.fromkeys(src_codes))
        for attempt_src in attempts:
            if not remaining:
                break
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
                partial = loader.fetch(remaining, start_date, end_date, interval=interval)
            except Exception as exc:  # noqa: BLE001 — contained per-symbol fallback
                logger.error(
                    "market-data loader %r failed for %s; trying next source in chain: %s",
                    attempt_src, remaining, exc,
                )
                continue
            if not partial:
                continue
            if used_source is None:
                used_source = attempt_src
                provider_cls = loader_cls
            for symbol, df in partial.items():
                data_map[symbol] = df
                symbol_sources[symbol] = (attempt_src, loader_cls)
            remaining = [symbol for symbol in remaining if symbol not in partial]

        if used_source and used_source != src:
            logger.info(
                "market-data source %r unavailable for %s; fell back to %r",
                src, src_codes, used_source,
            )
        served_elsewhere = sorted(
            {serve_src for serve_src, _ in symbol_sources.values()} - {used_source}
        )
        if served_elsewhere:
            logger.info(
                "market-data per-symbol fallback: %s served the remaining symbols %r could not",
                served_elsewhere, src,
            )
        return data_map, used_source, provider_cls, symbol_sources

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
            frame_attrs = getattr(df, "attrs", None)
            frame_attrs = frame_attrs if isinstance(frame_attrs, dict) else {}
            currency_conversion = frame_attrs.get("currency_conversion")
            if not isinstance(currency_conversion, str) or not currency_conversion:
                currency_conversion = "none"
            entry: dict[str, Any] = {
                "source": used_source or src,
                "requested_source": source,
                "detected_source": src,
                "fallback_used": bool(used_source and used_source != src),
                "currency_conversion": currency_conversion,
                "volume_unit": volume_units.get(market),
                "adjustment": price_caliber(used_source or src, market),
            }
            quote_currency = frame_attrs.get("quote_currency")
            if isinstance(quote_currency, str) and quote_currency:
                entry["quote_currency"] = quote_currency
            if extra_provenance:
                entry.update(extra_provenance)
            provenance[symbol] = entry

    for (src, market), src_codes in groups.items():
        data_map, used_source, provider_cls, symbol_sources = _fetch_via_chain(
            src, market, src_codes
        )
        for symbol, df in data_map.items():
            symbol_source, symbol_provider_cls = symbol_sources.get(
                symbol, (used_source, provider_cls)
            )
            _emit(
                symbol, df,
                src=src, used_source=symbol_source, provider_cls=symbol_provider_cls,
                market=market,
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
                        "adjustment": base.get("adjustment", price_caliber(src, market)),
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
            sibling_data, used_source, provider_cls, _ = _fetch_via_chain(
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
