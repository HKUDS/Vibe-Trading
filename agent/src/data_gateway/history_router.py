"""Capability-aware historical acquisition through the existing market routes."""

from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone
import importlib
import math
import re
import time

from .scheduling import background

history_context = ContextVar("history_context", default=None)
INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1H": 60, "4H": 240, "1D": 1440}
INTERVALS = (*INTERVAL_MINUTES, "1W", "1M")
_VERIFIED_MINUTES = {"5m", "15m", "30m", "1H"}
_DAILY_ONLY = {"tencent", "stooq", "pykrx", "b3_cotahist"}


class HistoryPaused(Exception):
    """Stop source failover promptly when the dataset was paused or shut down."""


class HistoryRouteError(ConnectionError):
    """No route supplied a compatible chunk; retain bounded per-source evidence."""

    def __init__(self, attempts):
        self.attempts = attempts[:32]
        self.retryable = any(row.get("status") in {"transient", "cooldown"} for row in self.attempts)
        detail = "; ".join(f"{row['source']}: {row['reason']}" for row in self.attempts)
        super().__init__("No source supplied a compatible chunk: " + detail[:800])


def inventory():
    """Derive all registered routes without probing networks or importing SDKs."""
    from backtest.loaders import registry

    registry._ensure_registered()
    result = []
    for name, cls in sorted(registry.LOADER_REGISTRY.items()):
        if name == "local":
            continue
        module = importlib.import_module(cls.__module__)
        mapping = getattr(module, "_INTERVAL_MAP", {})
        known = sorted(set(mapping) & set(INTERVALS)) if isinstance(mapping, dict) else []
        if name == "yahoo":
            known = list(dict.fromkeys([*known, "1m", "5m", "15m", "30m"]))
        if name in {"yahoo", "yfinance"}:
            # Both legacy loaders map 4H to 1H, which is not a 4H dataset.
            known = [item for item in known if item != "4H"]
        if name in _DAILY_ONLY:
            known = ["1D", "1W", "1M"]
        if name == "baostock":
            known = ["5m", "15m", "30m", "1H", "1D", "1W", "1M"]
        if "1D" in known:
            known = list(dict.fromkeys([*known, "1W", "1M"]))
        markets = [market for market, chain in registry.FALLBACK_CHAINS.items() if name in chain]
        result.append(
            {
                "source": name,
                "markets": markets or sorted(getattr(cls, "markets", [])),
                "intervals": known or None,
                "requires_auth": bool(getattr(cls, "requires_auth", False)),
                "availability": "checked_on_request",
                "coverage": "verified_per_chunk_or_explicitly_unverified",
            }
        )
    return result


def market_for(symbol):
    """Require a public identity understood by the existing market-data layer."""
    from src.market_data import data_market

    if not isinstance(symbol, str) or len(symbol) > 64 or symbol.lower().startswith("local:"):
        raise ValueError("Expected a public market symbol")
    return data_market(symbol)


def candidates(symbol, interval, source="auto"):
    """Reuse compatible configured ordering; explicit no-fallback sources stay strict."""
    from backtest.loaders import registry
    from src.market_data import detect_source

    registry._ensure_registered()
    if source not in registry.VALID_SOURCES or source == "local":
        raise ValueError("Expected auto or a registered public/configured source")
    if interval not in INTERVALS:
        raise ValueError("Unsupported historical interval")
    market = market_for(symbol)
    first = detect_source(symbol) if source == "auto" else source
    if source != "auto":
        # Selecting a source for a persisted dataset means exactly that source.
        order = [source]
    elif registry.is_no_network_fallback_source(first):
        order = [first]
    else:
        override = registry.get_source_order_override(market)
        order = list(dict.fromkeys([first, *registry.FALLBACK_CHAINS.get(market, [])]))
        if override is not None and first in override:
            order = list(override)
        if override is None and re.fullmatch(r"\d{6}\.(SH|SZ)", symbol) and interval in _VERIFIED_MINUTES:
            order = ["baostock", *[item for item in order if item != "baostock"]]
    profiles = {row["source"]: row for row in inventory()}
    return [
        item
        for item in order
        if item != "local"
        and item in profiles
        and (profiles[item]["intervals"] is None or interval in profiles[item]["intervals"])
    ]


def plan(codes, start_date, end_date, interval, source):
    """Plan bounded chunks without claiming unavailable historical depth exists."""
    if not isinstance(codes, list) or not 1 <= len(codes) <= 100 or not all(isinstance(c, str) for c in codes):
        raise ValueError("Supply 1..100 distinct public symbols")
    codes = [code.strip().upper() for code in codes]
    if len(set(codes)) != len(codes):
        raise ValueError("Supply distinct symbols")
    if not isinstance(start_date, str) or not isinstance(end_date, str):
        raise ValueError("start_date and end_date are required ISO dates")
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    if start > end or end >= datetime.now(timezone.utc).date():
        raise ValueError("Request settled dates in an ordered range")
    if interval not in INTERVALS:
        raise ValueError("Unsupported historical interval")
    parts, routes = [], {}
    upper_rows = 0
    for code in codes:
        market = market_for(code)
        sources = candidates(code, interval, source)
        if not sources:
            raise ValueError(f"No registered compatible route for {code} at {interval}")
        routes[code] = {"market": market, "candidates": sources, "availability": "checked_on_download"}
        verified_minute = (
            bool(re.fullmatch(r"\d{6}\.(SH|SZ)", code))
            and interval in _VERIFIED_MINUTES
            and source in {"auto", "baostock"}
        )
        frequency = INTERVAL_MINUTES.get(interval, 1440)
        if verified_minute:
            upper_rows += sum((start + timedelta(days=i)).weekday() < 5 for i in range((end - start).days + 1)) * (
                240 // frequency
            )
        elif interval == "1M":
            upper_rows += (end.year - start.year) * 12 + end.month - start.month + 1
        elif interval == "1W":
            upper_rows += ((end - start).days + start.weekday()) // 7 + 1
        else:
            upper_rows += ((end - start).days + 1) * max(1, 1440 // frequency)
        cursor = start
        while cursor <= end:
            next_month = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
            last = min(end, next_month - timedelta(days=1))
            if not verified_minute and frequency < 1440:
                # Keep ordinary loader requests short enough for the unchanged
                # source deadline; sub-day chunks aren't needed for <=1440 rows.
                days = max(1 if market == "crypto" else 7, min(31, 1000 * frequency // 1440))
                last = min(end, cursor + timedelta(days=days - 1))
                # Avoid turning an ordinary weekend at a chunk boundary into
                # a standalone acquisition. Empty responses still never prove coverage.
                if market != "crypto" and (end - last).days <= 2:
                    last = end
            if interval == "1D":
                last = min(end, date(cursor.year, 12, 31))
            if interval == "1M":
                # Five years through the final month of daily input (<1860 bars),
                # well below the unchanged 10000-row normalization bound.
                # End on a month boundary so no monthly bar is split/repeated.
                last = min(
                    end,
                    (date(cursor.year + 5, cursor.month, 28) + timedelta(days=4)).replace(day=1) - timedelta(days=1),
                )
            if interval == "1W":
                # Never cut one weekly aggregate across two persisted chunks.
                last = min(end, cursor + timedelta(days=(6 - cursor.weekday()) + 51 * 7))
            if len(parts) >= 4096:
                raise ValueError("Request exceeds 4096 chunks; split symbols or date ranges into separate jobs")
            parts.append((code, str(cursor), str(last)))
            cursor = last + timedelta(days=1)
    return {
        "spec": {
            "codes": codes,
            "start_date": start_date,
            "end_date": end_date,
            "interval": interval,
            "source": source,
        },
        "chunks": len(parts),
        "estimated_max_rows": upper_rows,
        "estimated_uncompressed_bytes": upper_rows * 256,
        "estimate_basis": "conservative bar-count estimate; source depth and calendar coverage are checked during acquisition",
        "routes": routes,
        "parts": parts,
        "coverage_note": "Downloaded chunks are not complete-market evidence unless coverage_verified is true. No recent-tail substitution.",
    }


def _compatible(meta, expected, market):
    if not expected:
        return True
    fields = ("adjustment", "quote_currency", "volume_unit")
    if any(meta.get(key) != expected.get(key) for key in fields):
        return False
    if market == "crypto":
        offset = expected.get("bar_offset_seconds")
        # Earlier routed chunks recorded observed_start but not the grid phase.
        # Recover that measured phase so a format upgrade doesn't block resume.
        if offset is None and expected.get("observed_start") and meta.get("interval") in INTERVAL_MINUTES:
            stamp = datetime.fromisoformat(expected["observed_start"].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            offset = int(stamp.timestamp() % (INTERVAL_MINUTES[meta["interval"]] * 60))
        if meta.get("bar_offset_seconds") != offset:
            return False
    if meta.get("source") != expected.get("source"):
        if market == "crypto" or any(meta.get(key) in {None, "unknown"} for key in fields):
            return False
    return True


def _normalize(rows, symbol, start, end, interval, provenance, market):
    if not isinstance(rows, list) or not rows or len(rows) > 10000:
        raise ValueError("Source returned missing, sampled or oversized bars")
    output, stamps = [], []
    lower = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    upper = datetime.fromisoformat(end).replace(tzinfo=timezone.utc) + timedelta(days=1)
    for row in rows:
        raw = row.get("trade_date")
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)  # Ordering only; source timezone remains explicitly unknown.
        stamp = stamp.astimezone(timezone.utc)
        if not lower <= stamp < upper:
            raise ValueError("Source returned a bar outside the requested chunk")
        prices = [row.get(key) for key in ("open", "high", "low", "close")]
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in prices):
            raise ValueError("Source returned missing or nonfinite OHLC")
        op, high, low, close = prices
        if low > min(op, close) or high < max(op, close) or low > high:
            raise ValueError("Source returned inconsistent OHLC")
        output.append({**{k: v for k, v in row.items() if k != "trade_date"}, "symbol": symbol, "time": str(raw)})
        stamps.append(stamp)
    if stamps != sorted(set(stamps)):
        raise ValueError("Source returned duplicated or unordered timestamps")
    step = INTERVAL_MINUTES.get(interval)
    differences = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:])]
    if step and step < 1440 and differences and (min(differences) < step * 60 or min(differences) > step * 60 * 1.5):
        raise ValueError("Source returned a different bar interval")
    verified = False
    coverage = "source_rows_only_calendar_unverified"
    if market == "crypto" and step:
        seconds = step * 60
        expected_count = int((upper - lower).total_seconds() // seconds)
        verified = (
            len(stamps) == expected_count
            and stamps[0] < lower + timedelta(seconds=seconds)
            and stamps[-1] >= upper - timedelta(seconds=seconds)
            and all(abs(delta - seconds) < 0.001 for delta in differences)
        )
        if not verified:
            raise ValueError(
                f"Incomplete continuous grid: {len(stamps)}/{expected_count} bars; "
                f"observed {stamps[0].isoformat()}..{stamps[-1].isoformat()}. "
                "The source may not have closed or published the requested final bar."
            )
        coverage = "continuous_market_grid"
    else:
        # A recent tail must not pass as an old requested window. This bound
        # catches truncation; it is deliberately NOT a calendar-completeness proof.
        tolerance = timedelta(days=7 if interval not in {"1W", "1M"} else 35)
        if stamps[0] - lower > tolerance or upper - stamps[-1] > tolerance:
            raise ValueError("Source returned a truncated boundary; requested history is missing")
    meta = {
        **provenance,
        "source": provenance.get("source"),
        "interval": interval,
        "coverage": coverage,
        "coverage_verified": verified,
        "observed_start": str(rows[0]["trade_date"]),
        "observed_end": str(rows[-1]["trade_date"]),
        "bar_offset_seconds": int((stamps[0] - lower).total_seconds() % (step * 60))
        if market == "crypto" and step
        else None,
        "timestamp_basis": "source_timestamp",
        "timezone": "UTC" if market == "crypto" else "source_timezone_unverified",
    }
    if market != "crypto":
        from .calendars import validate

        output, calendar_meta = validate(output, market, start, end, interval, provenance)
        meta.update(calendar_meta)
    return output, meta


def fetch_chunk(symbol, start, end, interval):
    """Acquire through compatible routes, preserving per-symbol series identity."""
    from . import get_gateway
    from .history_source import fetch_chunk as baostock_chunk

    context = history_context.get() or {"source": "auto"}
    requested, expected = context.get("source", "auto"), context.get("expected")
    market = market_for(symbol)
    if (date.fromisoformat(end) - date.fromisoformat(start)).days < 7:
        from .calendars import schedule

        found = schedule(market, start, end)
        if found is not None and found[2].empty:
            import exchange_calendars

            return [], {
                "source": None,
                "interval": interval,
                "coverage_verified": True,
                "coverage": "exchange_closed_interval",
                "calendar": found[0],
                "calendar_version": exchange_calendars.__version__,
                "sessions": 0,
                "timezone": found[1],
                "timestamp_basis": "session_date",
                "requested_source": requested,
            }
    gateway = get_gateway()
    errors = []
    token = background.set(True)
    from backtest.loaders.base import source_interval

    scope = f"bars:{market}:{source_interval(interval)}"
    order = candidates(symbol, interval, requested)
    if requested == "auto":
        order = gateway.router.order(scope, order)
    # A persisted series prefers its last compatible source before trying alternatives.
    if expected and expected.get("source") in order:
        previous = expected["source"]
        order = [previous, *[item for item in order if item != previous]]

    try:
        for source in order:
            if context.get("stop_requested", lambda: False)():
                raise HistoryPaused()
            started = time.monotonic()
            try:
                if source == "baostock" and interval in _VERIFIED_MINUTES:
                    if gateway.router.cooling(scope, source) and not gateway.router.recovery_probe(scope, [source]):
                        errors.append({"source": source, "status": "cooldown", "reason": "temporary network backoff"})
                        continue
                    rows, meta = baostock_chunk(symbol, start, end, interval)
                    meta = {**meta, "coverage_verified": True}
                else:
                    value = gateway.bars(
                        codes=[symbol],
                        start_date=start,
                        end_date=end,
                        interval=interval,
                        source=source,
                        max_rows=0,
                        exact_source=True,
                        respect_cooldown=True,
                    )
                    if not value.get("ok"):
                        failures = value.get("data", {}).get("_diagnostics", {}).get(symbol, [])
                        network = any(
                            row.get("reason")
                            in {"network_failure", "timeout", "network_cooldown", "source_busy", "request_deadline"}
                            for row in failures
                        ) or (not failures and bool(value.get("retry_after_seconds")))
                        error = ConnectionError if network else ValueError
                        raise error(value.get("error", "Source acquisition unavailable"))
                    data = value.get("data", {})
                    provenance = data.get("_provenance", {}).get(symbol)
                    if not provenance or provenance.get("source") != source:
                        raise ValueError("Exact source identity was not preserved")
                    rows, meta = _normalize(data.get(symbol), symbol, start, end, interval, provenance, market)
                if not _compatible(meta, expected, market):
                    raise ValueError("Fallback has incompatible currency, adjustment, volume or venue")
                if source == "baostock" and interval in _VERIFIED_MINUTES:
                    gateway.router.record(scope, source, True, time.monotonic() - started)
                return rows, {
                    **meta,
                    "requested_source": requested,
                    "route_attempts": errors + [{"source": source, "status": "ok"}],
                }
            except (ValueError, OSError, TimeoutError) as exc:
                if isinstance(exc, OSError) and source == "baostock" and interval in _VERIFIED_MINUTES:
                    gateway.router.record(scope, source, False, time.monotonic() - started)
                errors.append(
                    {
                        "source": source,
                        "status": "transient" if isinstance(exc, (ConnectionError, TimeoutError)) else "unavailable",
                        "reason": str(exc)[:160],
                    }
                )
        raise HistoryRouteError(errors)
    finally:
        background.reset(token)
