"""Reuse bar loaders and normalization with bounded, network-adaptive attempts."""

import json
import time
from .service import GatewayError


def fetch_bars(gateway, **params):
    """Fetch only compatible existing routes; preserve per-symbol provenance.

    Args:
        gateway: Owner of the bounded source executor and local health table.
        **params: Existing market-data parameters, including explicit source.

    Returns:
        Historical data with missing symbols and an explicit completeness flag.
    """
    from backtest.engines._market_hooks import _detect_market
    from backtest.loaders import registry
    from src.market_data import detect_source, fetch_market_data_json

    registry._ensure_registered()
    requested = params.get("source", "auto")
    combined, provenance, unresolved, diagnostics = {}, {}, [], {}
    deadline = time.monotonic() + gateway.config.request_timeout
    for code in params["codes"]:
        market = _detect_market(code)
        scope = f"bars:{market}:{params.get('interval', '1D')}"
        first = detect_source(code) if requested == "auto" else requested
        strict = registry.is_no_network_fallback_source(first)
        baseline = [first] if strict else list(dict.fromkeys([first, *registry.FALLBACK_CHAINS.get(market, [])]))
        override = registry.get_source_order_override(market)
        if requested == "auto" and not strict and override is not None and first in override:
            baseline = list(override)
        candidates = gateway.router.order(scope, baseline) if requested == "auto" and not strict else baseline
        found = False
        diagnostics[code] = []
        for source in candidates:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                diagnostics[code].append({"source": source, "reason": "request_deadline"})
                break
            if requested == "auto" and gateway.router.cooling(scope, source):
                diagnostics[code].append({"source": source, "reason": "network_cooldown"})
                continue
            started = time.monotonic()

            def acquire(source=source, code=code, params=dict(params)):
                def exact_loader(name):
                    cls = registry.LOADER_REGISTRY.get(name)
                    if cls is None or not cls().is_available():
                        raise GatewayError("Source is not configured or installed")
                    return cls

                return json.loads(
                    fetch_market_data_json(
                        **{
                            **params,
                            "codes": [code],
                            "source": source,
                            "max_fallback_attempts": 1,
                            "loader_resolver": exact_loader,
                            "include_provenance": True,
                        }
                    )
                )

            try:
                result = gateway.invoke(acquire, {}, min(remaining, gateway.config.source_timeout))
                alias = code.split(":", 1)[1] if code.startswith("local:") else code
                if alias not in result:
                    attempts = result.get("_diagnostics", {}).get(code, {}).get("attempts", [])
                    if any(attempt.get("reason") == "fetch_failed" for attempt in attempts):
                        gateway.router.record(scope, source, False, time.monotonic() - started)
                    diagnostics[code].append({"source": source, "reason": "no_data_or_source_unavailable"})
                    continue
                gateway.router.record(scope, source, True, time.monotonic() - started)
                combined.update({k: v for k, v in result.items() if not k.startswith("_")})
                for symbol, stamp in result.get("_provenance", {}).items():
                    provenance[symbol] = {
                        **stamp,
                        "requested_source": requested,
                        "detected_source": first,
                        "fallback_used": stamp.get("fallback_used", False) or source != first,
                    }
                # Preserve normalization/caliber warnings from the existing layer.
                for key, value in result.items():
                    if key.startswith("_") and key not in {"_provenance", "_unresolved", "_diagnostics"}:
                        combined.setdefault(key, {})[code] = value
                found = True
                break
            except GatewayError:
                diagnostics[code].append({"source": source, "reason": "source_busy_or_unavailable"})
            except Exception:
                gateway.router.record(scope, source, False, time.monotonic() - started)
                diagnostics[code].append({"source": source, "reason": "timeout_or_network_failure"})
        if not found:
            unresolved.append(code)
    combined["_provenance"] = provenance
    combined["_unresolved"] = unresolved
    combined["_diagnostics"] = diagnostics
    return {
        "ok": bool(provenance),
        "source": "existing_routes",
        "data": combined,
        "complete": not unresolved,
        **({"error": "No compatible source returned data"} if not provenance else {}),
    }
