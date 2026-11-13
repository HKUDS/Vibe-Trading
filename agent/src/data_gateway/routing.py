"""Local-network route learning, without geolocation or background probe traffic."""

from collections import OrderedDict
import threading
import time


class NetworkRouter:
    """Prefer recently successful compatible sources; retry originals after expiry.

    Health is scoped by capability and market, expires, and never persists user
    IP addresses or credentials. Empty-symbol results are not network failures.
    """

    def __init__(self, cooldown=30, lifetime=300, clock=time.monotonic):
        self.cooldown = cooldown
        self.lifetime = lifetime
        self.clock = clock
        self.health = OrderedDict()
        self.lock = threading.RLock()
        self.probes = OrderedDict()

    def record(self, scope, source, success, elapsed):
        with self.lock:
            key = (scope, source)
            old = self.health.pop(key, {})
            failures = 0 if success else min(4, old.get("failures", 0) + 1)
            self.health[key] = {
                "checked": self.clock(),
                "success": success,
                "failures": failures,
                "latency_ms": round(elapsed * 1000, 2),
                "retry_at": 0 if success else self.clock() + min(self.lifetime, self.cooldown * 2 ** (failures - 1)),
            }
            while len(self.health) > 512:
                self.health.popitem(last=False)

    def cooling(self, scope, source):
        with self.lock:
            row = self.health.get((scope, source))
            return bool(row and row["retry_at"] > self.clock())

    def order(self, scope, sources):
        """Reorder only the supplied compatible candidates, never add a venue."""
        with self.lock:
            now = self.clock()

            def score(source):
                row = self.health.get((scope, source))
                if row is None or now - row["checked"] > self.lifetime:
                    return (1, 0)
                if row["retry_at"] > now:
                    return (3, 0)
                return (0, row["latency_ms"]) if row["success"] else (2, 0)

            # Periodically re-evaluate baseline order when its first source's
            # failed observation expires. This adapts to a changed network.
            baseline = list(dict.fromkeys(sources))
            first = self.health.get((scope, baseline[0])) if baseline else None
            if first is None or (not first["success"] and now - first["checked"] > self.lifetime):
                return baseline
            return sorted(baseline, key=score)

    def recovery_probe(self, scope, sources):
        """Claim at most one half-open attempt per scope per cooldown period.

        Called only after normal routes failed. Exponential source backoff stays
        in place; this bounded probe lets recovered networks become usable
        without waiting for the longest accumulated source cooldown.
        """
        with self.lock:
            now = self.clock()
            if now < self.probes.get(scope, 0):
                return None
            candidates = [
                source
                for source in sources
                if self.cooling(scope, source) and now - self.health[(scope, source)]["checked"] >= self.cooldown
            ]
            if not candidates:
                return None
            source = min(candidates, key=lambda name: self.health[(scope, name)]["retry_at"])
            self.probes[scope] = now + self.cooldown
            self.probes.move_to_end(scope)
            while len(self.probes) > 512:
                self.probes.popitem(last=False)
            return source

    def prune(self):
        """Delete idle network observations instead of retaining historical probes."""
        with self.lock:
            now = self.clock()
            for scope, until in list(self.probes.items()):
                if until <= now:
                    self.probes.pop(scope, None)
            for key, row in list(self.health.items()):
                if now - row["checked"] > self.lifetime:
                    self.health.pop(key, None)

    def status(self):
        with self.lock:
            now = self.clock()
            return [
                {
                    "scope": scope,
                    "source": source,
                    "last_success": row["success"],
                    "latency_ms": row["latency_ms"],
                    "cooldown_seconds": round(max(0, row["retry_at"] - now), 1),
                }
                for (scope, source), row in self.health.items()
                if now - row["checked"] <= self.lifetime
            ]
