"""Reuse bar loaders and normalization with bounded, network-adaptive attempts."""

import json
import math
import time
from datetime import datetime, timedelta, timezone
from .service import GatewayError, GatewayBusy
from .scheduling import deadline as request_deadline


def _available(loader):
    """Check configuration without letting a broken alternative poison a route."""
    try:
        return loader is not None and loader().is_available()
    except Exception:
        # Some optional SDKs initialize in their constructor and raise when
        # credentials are absent. This is not the active source's failure.
        return False


def fetch_bars(gateway, *, exact_source=False, **params):
    """Overlap independent markets using existing source slots and one deadline."""
    from .fanout import acquire_groups
    from .scheduling import background

    from src.market_data import data_market

    groups = {}
    for code in params["codes"]:
        try:
            market = data_market(code)
        except ValueError:
            market = "unsupported"
        groups.setdefault(market, []).append(code)
    # Background scans/history retain their one-source admission and serialized
    # execution. No additional executor, coordinator, cache or retry is created.
    batches = [params["codes"]] if background.get() else list(groups.values())
    walkers = [_walk_bars(gateway, exact_source=exact_source, **{**params, "codes": codes}) for codes in batches]
    until = request_deadline.get() or time.monotonic() + gateway.config.request_timeout
    values = acquire_groups(gateway, walkers, until, parallel=len(walkers) > 1)
    # Other groups may have demonstrated recovery after an all-cooled group
    # finished. Complete only those never-attempted symbols, once, inside the
    # original deadline; keep every healthy group and its fetched data intact.
    if len(values) > 1 and params.get("source", "auto") == "auto" and not exact_source:
        from backtest.loaders.base import source_interval

        repairs, owners = [], []
        for index, value in enumerate(values):
            eligible = []
            for code in value["data"]["_unresolved"]:
                attempts = value["data"]["_diagnostics"].get(code, [])
                if not attempts or any(a["reason"] != "network_cooldown" for a in attempts):
                    continue
                scope = f"bars:{data_market(code)}:{source_interval(params.get('interval', '1D'))}"
                if gateway.router.retry_after(scope, [a["source"] for a in attempts]) <= 0:
                    eligible.append(code)
            if eligible and time.monotonic() < until:
                owners.append((index, eligible))
                repairs.append(_walk_bars(gateway, **{**params, "codes": eligible}))
        if repairs:
            recovered = acquire_groups(gateway, repairs, until, parallel=True)
            for (index, codes), repair in zip(owners, recovered):
                original = values[index]
                old_attempts = original["data"]["_diagnostics"]
                for code in codes:
                    repair["data"]["_diagnostics"][code] = old_attempts.get(code, []) + repair["data"][
                        "_diagnostics"
                    ].get(code, [])
                    if code not in repair["data"]["_unresolved"]:
                        repair["data"].setdefault("_recovery", {})[code] = {
                            "state": "recovered_in_request",
                            "source": repair["data"]["_provenance"][code]["source"],
                        }
                for code in codes:
                    original["data"].get("_recovery", {}).pop(code, None)
                for key, part in repair["data"].items():
                    if key.startswith("_") and isinstance(part, dict):
                        original["data"].setdefault(key, {}).update(part)
                    elif key != "_unresolved":
                        original["data"][key] = part
                original["data"]["_unresolved"] = [
                    c for c in batches[index] if c not in original["data"]["_provenance"]
                ]
                original["ok"] = bool(original["data"]["_provenance"])
                original["complete"] = not original["data"]["_unresolved"] and not any(
                    row["status"] == "partial" for row in original["data"]["_coverage"].values()
                )
                original.pop("retry_after_seconds", None)
                if not original["complete"] and repair.get("retry_after_seconds"):
                    original["retry_after_seconds"] = repair["retry_after_seconds"]
    if len(values) == 1:
        return values[0]
    data = {}
    for value in values:
        for key, part in value["data"].items():
            if key.startswith("_") and isinstance(part, dict):
                data.setdefault(key, {}).update(part)
            elif key == "_unresolved":
                data.setdefault(key, []).extend(part)
            else:
                data[key] = part
    return {
        "ok": any(value["ok"] for value in values),
        "complete": all(value["complete"] for value in values),
        "complete_scope": values[0]["complete_scope"],
        "source": "existing_routes",
        "data": data,
        **(
            {
                "retry_after_seconds": min(
                    value["retry_after_seconds"] for value in values if value.get("retry_after_seconds")
                )
            }
            if any(value.get("retry_after_seconds") for value in values)
            else {}
        ),
        **({"error": "No compatible source returned data"} if not data.get("_provenance") else {}),
    }


def _walk_bars(gateway, *, exact_source=False, respect_cooldown=False, **params):
    """Fetch only compatible existing routes; preserve per-symbol provenance.

    Args:
        gateway: Owner of the bounded source executor and local health table.
        **params: Existing market-data parameters, including explicit source.

    Returns:
        Historical data with missing symbols and an explicit completeness flag.
    """
    from backtest.loaders import registry
    from backtest.loaders.base import source_interval
    from src.market_data import data_market, detect_source, fetch_market_data_json

    registry._ensure_registered()
    requested = params.get("source", "auto")
    managed = requested == "auto" or respect_cooldown
    combined, provenance, unresolved, diagnostics = {}, {}, [], {}
    coverage = {}
    calendar_schedules = {}
    attempted_symbols = {}
    markets_by_code = {}
    for symbol in params["codes"]:
        try:
            markets_by_code[symbol] = data_market(symbol)
        except ValueError:
            pass
    deadline = request_deadline.get() or (time.monotonic() + gateway.config.request_timeout)
    for code in params["codes"]:
        try:
            market = data_market(code)
        except ValueError as exc:
            unresolved.append(code)
            diagnostics[code] = [{"source": "router", "reason": "unsupported_market", "detail": str(exc)}]
            continue
        if code in provenance:
            coverage[code] = describe_coverage(
                combined[code], params, market, provenance.get(code, {}), calendar_schedules
            )
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
        deferred_admissions = []

        # A single bounded half-open probe runs only after all ordinary routes.
        def route_attempts():
            yield from ((source, False, False) for source in candidates)
            # An SDK that yielded before login has not attempted acquisition.
            # If every alternative failed, admit that original read through its
            # fair queue within the same request/source deadlines, once.
            yield from ((source, False, True) for source in deferred_admissions)
            if managed:
                probe = gateway.router.recovery_probe(scope, candidates)
                if probe:
                    yield probe, True, False

        for source, recovery, wait_for_admission in route_attempts():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                diagnostics[code].append({"source": source, "reason": "request_deadline"})
                break
            if not recovery and managed and gateway.router.cooling(scope, source):
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
                        and (source, symbol) not in attempted_symbols
                        and markets_by_code.get(symbol) == market
                        and (requested != "auto" or detect_source(symbol) == first)
                    ],
                ][:batch_size]
            )
            cached_batch = attempted_symbols.get((source, code))
            admission = {"yielded": False}

            def acquire(source=source, code=code, params=dict(params), batch_codes=batch_codes, admission=admission):
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
                from backtest.loaders.acquisition import source_can_fallback, source_admission_yielded

                # A configured chain is not an available escape route. In
                # particular, do not abandon the only healthy SDK session for
                # cooled HTTP sources or an unconfigured token/file adapter.
                alternatives = any(
                    other != source
                    and not gateway.router.cooling(scope, other)
                    and (other, code) not in attempted_symbols
                    and _available(registry.LOADER_REGISTRY.get(other))
                    for other in candidates
                ) if requested == "auto" and not strict and not wait_for_admission else False
                token = source_can_fallback.set(alternatives)
                yield_token = source_admission_yielded.set(False)
                try:
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
                finally:
                    admission["yielded"] = source_admission_yielded.get()
                    source_admission_yielded.reset(yield_token)
                    source_can_fallback.reset(token)

            try:
                if cached_batch is not None:
                    result = cached_batch
                else:
                    from .fanout import SourceCall

                    result = yield SourceCall(source, acquire, len(batch_codes))
                    local_busy = not result.get("_provenance") and all(
                        (attempts := result.get("_diagnostics", {}).get(symbol, {}).get("attempts", []))
                        and all(a.get("reason") == "source_busy" for a in attempts)
                        for symbol in batch_codes
                    )
                    if local_busy and admission["yielded"] and not wait_for_admission:
                        deferred_admissions.append(source)
                    else:
                        for symbol in batch_codes:
                            attempted_symbols[source, symbol] = result
                    # A successful head symbol does not erase transport failures
                    # elsewhere in the same serial batch. Record the attempt once.
                    network_failed = any(
                        a.get("reason") in {"fetch_failed", "network_failure"}
                        for detail in result.get("_diagnostics", {}).values()
                        for a in detail.get("attempts", [])
                    )
                    if network_failed or result.get("_provenance"):
                        gateway.router.record(scope, source, not network_failed, time.monotonic() - started)
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
                    reason = (
                        "source_busy"
                        if any(a.get("reason") == "source_busy" for a in attempts)
                        else "network_failure"
                        if any(a.get("reason") in {"fetch_failed", "network_failure"} for a in attempts)
                        else "no_data_or_source_unavailable"
                    )
                    diagnostics[code].append({"source": source, "reason": reason})
                    continue
                coverage[code] = describe_coverage(
                    result[alias], params, market, provenance.get(code, {}), calendar_schedules
                )
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
    recovery = {}
    for code in unresolved:
        attempts = diagnostics.get(code, [])
        if attempts and all(a["reason"] == "network_cooldown" for a in attempts):
            scope = f"bars:{data_market(code)}:{source_interval(params.get('interval', '1D'))}"
            recovery[code] = {
                "state": "waiting_for_route",
                "retry_after_seconds": max(
                    1, math.ceil(gateway.router.retry_after(scope, [a["source"] for a in attempts]))
                ),
            }
    if recovery:
        combined["_recovery"] = recovery
    return {
        "ok": bool(provenance),
        **(
            {"retry_after_seconds": 1}
            if any(a["reason"] == "source_busy" for rows in diagnostics.values() for a in rows)
            else {}
        ),
        **({"retry_after_seconds": min(row["retry_after_seconds"] for row in recovery.values())} if recovery else {}),
        "source": "existing_routes",
        "data": combined,
        "complete": not unresolved and not any(row["status"] == "partial" for row in coverage.values()),
        "complete_scope": "requested_symbols_and_coverage_checks; see per-symbol calendar verification and sampling metadata",
        **({"error": "No compatible source returned data"} if not provenance else {}),
    }


def describe_coverage(value, params, market, provenance=None, schedules=None):
    """Expose observed bounds without claiming that a nonempty frame is complete.

    Settled unsampled exchange bars use the same calendar check as downloads.
    Unknown calendars, live ranges and sampled results stay explicitly unverified.
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
    if (
        market != "crypto"
        and not result["sampled"]
        and params["end_date"] < datetime.now(timezone.utc).date().isoformat()
    ):
        from .calendars import schedule, validate, CalendarCoverageError

        schedules = schedules if schedules is not None else {}
        key = (market, params["start_date"], params["end_date"])
        try:
            if key not in schedules:
                schedules[key] = schedule(*key)
            if schedules[key] is not None:
                kept, meta = validate(
                    rows,
                    market,
                    params["start_date"],
                    params["end_date"],
                    interval,
                    provenance or {},
                    prepared=schedules[key],
                )
                result.update(meta)
                if meta["coverage_verified"]:
                    result.update(status="verified", reason="Exact exchange session grid verified")
                    if len(kept) != len(rows):
                        result.update(
                            status="partial",
                            reason="Source contains non-bar close points; normalized history excludes and reports them",
                        )
        except CalendarCoverageError as exc:
            result.update(status="partial", coverage_verified=False, reason=str(exc))
    return result
