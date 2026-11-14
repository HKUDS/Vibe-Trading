"""Reuse bar loaders and normalization with bounded, network-adaptive attempts."""

import json
import time
from datetime import datetime, timedelta, timezone
from .service import GatewayError, GatewayBusy
from .scheduling import deadline as request_deadline


def fetch_bars(gateway, *, exact_source=False, **params):
    """Fetch only compatible existing routes; preserve per-symbol provenance.

    Args:
        gateway: Owner of the bounded source executor and local health table.
        **params: Existing market-data parameters, including explicit source.

    Returns:
        Historical data with missing symbols and an explicit completeness flag.
    """
    from backtest.engines._market_hooks import _detect_market
    from backtest.loaders import registry
    from backtest.loaders.base import source_interval
    from src.market_data import detect_source, fetch_market_data_json

    registry._ensure_registered()
    requested = params.get("source", "auto")
    combined, provenance, unresolved, diagnostics = {}, {}, [], {}
    coverage = {}
    attempted_batches = {}
    deadline = request_deadline.get() or (time.monotonic() + gateway.config.request_timeout)
    for code in params["codes"]:
        market = _detect_market(code)
        if code in provenance:
            coverage[code] = describe_coverage(combined[code], params, market)
            diagnostics[code] = []
            continue
        scope = f"bars:{market}:{source_interval(params.get('interval', '1D'))}"
        first = detect_source(code) if requested == "auto" else requested
        strict = exact_source or registry.is_no_network_fallback_source(first)
        baseline = [first] if strict else list(dict.fromkeys([first, *registry.FALLBACK_CHAINS.get(market, [])]))
        override = registry.get_source_order_override(market)
        if requested == "auto" and not strict and override is not None and first in override:
            baseline = list(override)
        candidates = gateway.router.order(scope, baseline) if requested == "auto" and not strict else baseline
        found = False
        diagnostics[code] = []

        # A single bounded half-open probe runs only after all ordinary routes.
        def route_attempts():
            yield from ((source, False) for source in candidates)
            if requested == "auto":
                probe = gateway.router.recovery_probe(scope, candidates)
                if probe:
                    yield probe, True

        for source, recovery in route_attempts():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                diagnostics[code].append({"source": source, "reason": "request_deadline"})
                break
            if not recovery and requested == "auto" and gateway.router.cooling(scope, source):
                diagnostics[code].append({"source": source, "reason": "network_cooldown"})
                continue
            started = time.monotonic()

            # HTTP adapters loop symbols serially inside one timed invocation.
            # Smaller batches fit the same deadline; BaoStock shares one login.
            batch_size = 8 if source == "baostock" else gateway.config.http_batch_symbols
            batch_codes = sorted(
                [
                    code,
                    *[
                        symbol
                        for symbol in params["codes"]
                        if symbol != code
                        and symbol not in provenance
                        and _detect_market(symbol) == market
                        and (requested != "auto" or detect_source(symbol) == first)
                    ],
                ][:batch_size]
            )
            batch_key = (source, tuple(batch_codes))
            cached_batch = attempted_batches.get(batch_key)

            def acquire(source=source, code=code, params=dict(params), batch_codes=batch_codes):
                def exact_loader(name):
                    cls = registry.LOADER_REGISTRY.get(name)
                    if cls is None or not cls().is_available():
                        raise GatewayError("Source is not configured or installed")
                    return cls

                from .isolated import fetch, requires_isolation

                if requires_isolation(registry.LOADER_REGISTRY.get(source)):
                    return fetch(
                        {
                            **params,
                            "codes": batch_codes,
                            "source": source,
                            "max_fallback_attempts": 1,
                            "include_provenance": True,
                        },
                        min(deadline - time.monotonic(), gateway.config.source_timeout),
                        gateway.config.entry_bytes,
                    )
                return json.loads(
                    fetch_market_data_json(
                        **{
                            **params,
                            "codes": batch_codes,
                            "source": source,
                            "max_fallback_attempts": 1,
                            "loader_resolver": exact_loader,
                            "include_provenance": True,
                        }
                    )
                )

            try:
                if cached_batch is not None:
                    result = cached_batch
                else:
                    if not gateway.pacer.acquire(source, deadline, cost=len(batch_codes)):
                        raise GatewayError("Source admission deadline reached")
                    result = gateway.invoke(
                        acquire, {}, min(deadline - time.monotonic(), gateway.config.source_timeout)
                    )
                    attempted_batches[batch_key] = result
                combined.update({k: v for k, v in result.items() if not k.startswith("_")})
                for symbol, stamp in result.get("_provenance", {}).items():
                    provenance[symbol] = {
                        **stamp,
                        "requested_source": requested,
                        "detected_source": first,
                        "fallback_used": stamp.get("fallback_used", False) or source != first,
                    }
                alias = code.split(":", 1)[1] if code.startswith("local:") else code
                if alias not in result:
                    attempts = result.get("_diagnostics", {}).get(code, {}).get("attempts", [])
                    if any(attempt.get("reason") in {"fetch_failed", "network_failure"} for attempt in attempts):
                        gateway.router.record(scope, source, False, time.monotonic() - started)
                    reason = (
                        "source_busy"
                        if any(a.get("reason") == "source_busy" for a in attempts)
                        else "no_data_or_source_unavailable"
                    )
                    diagnostics[code].append({"source": source, "reason": reason})
                    continue
                coverage[code] = describe_coverage(result[alias], params, market)
                gateway.router.record(scope, source, True, time.monotonic() - started)
                # Preserve normalization/caliber warnings from the existing layer.
                for key, value in result.items():
                    if key.startswith("_") and key not in {"_provenance", "_unresolved", "_diagnostics"}:
                        combined.setdefault(key, {})[code] = value
                found = True
                break
            except GatewayBusy:
                diagnostics[code].append({"source": source, "reason": "source_busy"})
            except GatewayError:
                diagnostics[code].append({"source": source, "reason": "source_unavailable"})
            except Exception as exc:
                gateway.router.record(scope, source, False, time.monotonic() - started)
                diagnostics[code].append(
                    {
                        "source": source,
                        "reason": "timeout" if isinstance(exc, TimeoutError) else "network_failure",
                        "error_type": type(exc).__name__,
                        "recovery_probe": recovery,
                    }
                )
        if not found:
            unresolved.append(code)
    combined["_provenance"] = provenance
    unresolved = [code for code in params["codes"] if code not in provenance]
    combined["_unresolved"] = unresolved
    combined["_diagnostics"] = diagnostics
    combined["_coverage"] = coverage
    return {
        "ok": bool(provenance),
        **(
            {"retry_after_seconds": 1}
            if any(a["reason"] == "source_busy" for rows in diagnostics.values() for a in rows)
            else {}
        ),
        "source": "existing_routes",
        "data": combined,
        "complete": not unresolved and not any(row["status"] == "partial" for row in coverage.values()),
        "complete_scope": "symbols_and_detected_boundary_gaps; internal gaps and exchange calendars are not verified",
        **({"error": "No compatible source returned data"} if not provenance else {}),
    }


def describe_coverage(value, params, market):
    """Expose observed bounds without claiming that a nonempty frame is complete.

    Continuous crypto bars can prove a leading boundary gap. Other markets need
    an exchange calendar; their full interval coverage remains unverified.
    """
    rows = value if isinstance(value, list) else value.get("data", [])
    stamps = [row.get("trade_date") for row in rows if isinstance(row, dict) and row.get("trade_date")]
    interval = params.get("interval", "1D")
    result = {
        "requested_start": params["start_date"],
        "requested_end": params["end_date"],
        "observed_start": min(stamps) if stamps else None,
        "observed_end": max(stamps) if stamps else None,
        "status": "unverified",
        "sampled": isinstance(value, dict) and bool(value.get("truncated")),
        "reason": "Exchange calendar and internal gaps have not been verified",
    }
    minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1H": 60, "4H": 240, "1D": 1440}.get(interval)
    if stamps and market == "crypto" and minutes:
        try:
            first = datetime.fromisoformat(min(stamps)).replace(tzinfo=timezone.utc)
            requested = datetime.fromisoformat(params["start_date"]).replace(tzinfo=timezone.utc)
            if first >= requested + timedelta(minutes=minutes):
                result.update(status="partial", reason="Source starts after the requested continuous-market interval")
        except (ValueError, TypeError):
            pass
    return result
