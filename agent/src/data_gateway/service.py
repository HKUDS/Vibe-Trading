"""Capability gateway: bounded work, single-flight, cache and source recovery."""

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from datetime import datetime, timezone
import hashlib
import json
import threading
import time
from typing import Any, Callable

from .cache import Cache
from .config import Config
from .routing import NetworkRouter


class GatewayError(Exception):
    """A recoverable acquisition failure, safe to expose as a short message."""


class GatewayBusy(GatewayError):
    """All bounded source slots are currently occupied."""


class MarketDataGateway:
    """Serve capability requests without blocking an application's event loop.

    Sources run in a separate bounded pool. A timeout stops waiting, not an
    uncooperative Python thread; its capacity remains occupied until it exits.
    No worker is replaced and no unbounded retry queue is created.
    """

    def __init__(self, config: Config, providers: dict[str, dict[str, Callable]] | None = None):
        self.config = config
        self.cache = Cache(config)
        self.router = NetworkRouter(config.cooldown, config.health_ttl)
        if providers is None:
            from .sources import yahoo_options, cboe_options

            providers = {
                "options_chain": {"yahoo": yahoo_options, "cboe": cboe_options},
                "bars": {"existing_routes": self._historical_bars},
            }
        self.providers = providers
        self.lock = threading.RLock()
        self.flights: dict[str, Future] = {}
        self.failures: dict[tuple[str, str], float] = {}
        self.refresh_after: dict[str, float] = {}
        self.coordinators = ThreadPoolExecutor(max_workers=min(config.workers, 2), thread_name_prefix="gateway-request")
        self.sources = ThreadPoolExecutor(max_workers=config.workers, thread_name_prefix="gateway-source")
        self.source_slots = threading.BoundedSemaphore(config.workers)
        self.stop = threading.Event()
        self.cleaner = threading.Thread(target=self._clean, daemon=True, name="gateway-cache-cleanup")
        self.cleaner.start()

    def _clean(self):
        while not self.stop.wait(min(self.config.cleanup_interval, self.config.memory_idle, self.config.stale_ttl)):
            try:
                self.cache.prune()
            except OSError:
                pass  # An unavailable cache must not stop data acquisition.
            with self.lock:
                now = time.monotonic()
                self.refresh_after = {k: v for k, v in self.refresh_after.items() if v > now}
                self.failures = {k: v for k, v in self.failures.items() if v > now}
            self.router.prune()

    def close(self):
        """Stop housekeeping and cancel queued work without spawning replacements."""
        self.stop.set()
        self.cleaner.join(timeout=1)
        self.coordinators.shutdown(wait=False, cancel_futures=True)
        self.sources.shutdown(wait=False, cancel_futures=True)

    def _key(self, capability: str, params: dict) -> str:
        return hashlib.sha256(
            json.dumps(["v2", capability, params, self.config.sources], sort_keys=True, allow_nan=False).encode()
        ).hexdigest()

    def _decorate(self, entry: dict, state: str) -> dict:
        payload = json.loads(json.dumps(entry["payload"], allow_nan=False))
        payload["gateway"] = {
            **payload.get("gateway", {}),
            "cache": state,
            "age_seconds": round(max(0, time.time() - entry["stored_at"]), 3),
            "fetched_at": datetime.fromtimestamp(entry["stored_at"], timezone.utc).isoformat(),
        }
        return payload

    def request(
        self, capability: str, params: dict[str, Any], *, allow_stale: bool = True, cacheable: bool = True
    ) -> dict:
        """Fetch a capability, merging equal concurrent requests.

        Args:
            capability: A registered data capability such as options_chain.
            params: Validated, normalized provider arguments; included in identity.
            allow_stale: Return an explicitly stale snapshot while refreshing it.
            cacheable: Disable persistent reuse for mutable local-file requests.

        Returns:
            A JSON-compatible envelope with explicit source/cache metadata.
        """
        if capability not in self.providers:
            return {"ok": False, "error": "Unsupported data capability"}
        key = self._key(capability, params)
        cached = self.cache.get(key) if cacheable else None
        if cached and time.time() - cached["stored_at"] <= self.config.ttl:
            return self._decorate(cached, "fresh")
        with self.lock:
            flight = self.flights.get(key)
            if (
                flight is None
                and time.monotonic() >= self.refresh_after.get(key, 0)
                and len(self.flights) < self.config.pending
            ):
                flight = self.coordinators.submit(self._fetch, capability, params, key, cacheable)
                self.flights[key] = flight
                flight.add_done_callback(lambda f: self._done(key, f))
        if cached and allow_stale:
            result = self._decorate(cached, "stale")
            result["gateway"]["refreshing"] = flight is not None and not flight.done()
            return result
        if flight is None:
            return {
                "ok": False,
                "error": "Data gateway is cooling down or busy; retry shortly",
                "retry_after_seconds": self.config.cooldown,
            }
        try:
            return json.loads(json.dumps(flight.result(timeout=self.config.request_timeout), allow_nan=False))
        except TimeoutError:
            return {
                "ok": False,
                "error": "Data request timed out; retry shortly",
                "retry_after_seconds": self.config.cooldown,
            }
        except Exception:
            return {"ok": False, "error": "Data acquisition failed; retry or select another expiration"}

    def _done(self, key: str, future: Future):
        with self.lock:
            self.flights.pop(key, None)
            if future.cancelled() or future.exception() or not future.result().get("ok"):
                # Bounded by pending requests plus active cooldowns, cleaned below.
                self.refresh_after[key] = time.monotonic() + self.config.cooldown
                while len(self.refresh_after) > self.config.entries:
                    self.refresh_after.pop(next(iter(self.refresh_after)))

    def _fetch(self, capability: str, params: dict, key: str, cacheable: bool) -> dict:
        started = time.monotonic()
        routes = self.providers[capability]
        baseline = self.config.sources if capability == "options_chain" else tuple(routes)
        order = self.router.order(capability, baseline)
        attempts = []
        for source in order:
            if source not in routes:
                continue
            with self.lock:
                cooling = self.failures.get((capability, source), 0) > time.monotonic()
            if cooling or self.router.cooling(capability, source):
                attempts.append({"source": source, "status": "cooldown"})
                continue
            remaining = self.config.request_timeout - (time.monotonic() - started)
            if remaining <= 0:
                break
            attempt_started = time.monotonic()
            try:
                if routes[source] == self._historical_bars:
                    payload = self._historical_bars(**params)
                    if not payload.get("ok"):
                        return {
                            **payload,
                            "gateway": {"attempts": [{"source": source, "status": "unavailable"}]},
                            "retry_after_seconds": self.config.cooldown,
                        }
                else:
                    payload = self.invoke(routes[source], params, min(remaining, self.config.source_timeout))
                if not isinstance(payload, dict) or not payload.get("ok"):
                    raise GatewayError("Source returned no usable data")
                # Only JSON data, never DataFrames/NaN or model-generated estimates.
                encoded = json.dumps(payload, allow_nan=False)
                if len(encoded.encode()) > self.config.entry_bytes:
                    raise GatewayError("Response exceeds gateway entry limit")
                self.router.record(capability, source, True, time.monotonic() - attempt_started)
                attempts.append({"source": source, "status": "ok"})
                payload["gateway"] = {
                    **payload.get("gateway", {}),
                    "attempts": attempts,
                    "request_ms": round((time.monotonic() - started) * 1000, 2),
                }
                if cacheable:
                    try:
                        self.cache.put(key, payload)
                    except OSError:
                        pass
                return self._decorate({"stored_at": time.time(), "payload": payload}, "miss")
            except Exception as exc:
                attempts.append(
                    {
                        "source": source,
                        "status": "timeout"
                        if isinstance(exc, TimeoutError)
                        else "busy"
                        if isinstance(exc, GatewayBusy)
                        else "unavailable",
                    }
                )
                if not isinstance(exc, GatewayError):
                    self.router.record(capability, source, False, time.monotonic() - attempt_started)
                    with self.lock:
                        self.failures[(capability, source)] = time.monotonic() + self.config.cooldown
        return {
            "ok": False,
            "error": "No usable data from available sources; retry or select another expiration",
            "gateway": {"attempts": attempts},
            "retry_after_seconds": self.config.cooldown,
        }

    def invoke(self, function, params, timeout):
        """Bound actual source work, retaining timed-out threads in their slots."""
        if not self.source_slots.acquire(blocking=False):
            raise GatewayBusy("Data source capacity reached")
        try:
            future = self.sources.submit(function, **params)
        except Exception:
            self.source_slots.release()
            raise
        future.add_done_callback(lambda _: self.source_slots.release())
        return future.result(timeout=timeout)

    def _historical_bars(self, routing_policy=None, **params):
        from .historical import fetch_bars

        return fetch_bars(self, **params)

    def options_chain(
        self, ticker: str, expiration: int | None = None, *, allow_stale: bool = True, full: bool = False
    ) -> dict:
        """Acquire a US option snapshot; symbol normalization unifies cache keys."""
        import re

        symbol = ticker.strip().upper().removesuffix(".US")
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,15}", symbol):
            return {"ok": False, "error": "Invalid US option underlying"}
        if expiration is not None and (
            isinstance(expiration, bool) or not isinstance(expiration, int) or expiration <= 0
        ):
            return {"ok": False, "error": "expiration must be positive epoch seconds"}
        params = {"ticker": symbol, "expiration": expiration}
        if full:
            params["full"] = True
        return self.request("options_chain", params, allow_stale=allow_stale)

    def bars(self, **params) -> dict:
        """Reuse existing market-aware routes, preserving their provenance."""
        import os

        # Source ordering changes must invalidate cache identities.
        policy = {k: v for k, v in os.environ.items() if k.startswith("MARKET_DATA_ORDER_")}
        local = params.get("source") == "local" or any(c.startswith("local:") for c in params.get("codes", []))
        return self.request("bars", {**params, "routing_policy": policy}, allow_stale=False, cacheable=not local)

    def status(self) -> dict:
        """Return limits and occupancy, never cached market data or credentials."""
        with self.lock:
            active = len(self.flights)
        return {
            "ok": True,
            "active_requests": active,
            "cache": self.cache.stats(),
            "limits": {
                "disk_bytes": self.config.disk_bytes,
                "memory_bytes": self.config.memory_bytes,
                "workers": self.config.workers,
                "pending": self.config.pending,
            },
            "capabilities": {k: list(v) for k, v in self.providers.items()},
            "source_health": self.router.status(),
        }
