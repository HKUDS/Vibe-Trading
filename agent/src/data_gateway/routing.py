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
        self.probe_tried = OrderedDict()

    def record(self, scope, source, success, elapsed):
        with self.lock:
            key = (scope, source)
            old = self.health.pop(key, {})
            failures = 0 if success else min(4, old.get("failures", 0) + 1)
            self.health[key] = {
                "checked": self.clock(),
                "success": success,
                "last_success_at": self.clock() if success else old.get("last_success_at"),
                "failures": failures,
                "latency_ms": round(elapsed * 1000, 2),
                "retry_at": 0 if success else self.clock() + min(self.lifetime, self.cooldown * 2 ** (failures - 1)),
            }
            if success:
                self.probe_tried.pop(scope, None)
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
            if first is not None and not first["success"] and now - first["checked"] > self.lifetime:
                return baseline
            return sorted(baseline, key=score)

    def _recovery_ready_at(self, scope, source, row):
        """Use later success as probe evidence, never as another market's data.

        Called with the router lock held. A success for the same adapter in a
        different scope permits one early half-open attempt; it does not clear
        this scope's backoff or bypass its existing probe-frequency budget.
        """
        newer_success = any(
            other_scope != scope
            and other_source == source
            and other["success"]
            and other["checked"] > row["checked"]
            and self.clock() - other["checked"] <= self.lifetime
            for (other_scope, other_source), other in self.health.items()
        )
        ready = row["checked"] if newer_success else row["checked"] + self.cooldown
        return max(ready, self.probes.get(scope, 0))

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
                if self.cooling(scope, source)
                and self._recovery_ready_at(scope, source, self.health[(scope, source)]) <= now
            ]
            if not candidates:
                return None
            tried = self.probe_tried.get(scope, set()) & set(candidates)
            remaining = [source for source in candidates if source not in tried]
            if not remaining:
                tried, remaining = set(), candidates

            def priority(name):
                row = self.health[(scope, name)]
                success_at = row.get("last_success_at")
                recent = max(
                    (
                        other["checked"]
                        for (other_scope, other_source), other in self.health.items()
                        if other_scope != scope
                        and other_source == name
                        and other["success"]
                        and other["checked"] > row["checked"]
                    ),
                    default=0,
                )
                return (not bool(recent), -recent, success_at is None, -(success_at or 0), row["retry_at"])

            source = min(remaining, key=priority)
            self.probe_tried[scope] = tried | {source}
            self.probe_tried.move_to_end(scope)
            while len(self.probe_tried) > 512:
                self.probe_tried.popitem(last=False)
            self.probes[scope] = now + self.cooldown
            self.probes.move_to_end(scope)
            while len(self.probes) > 512:
                self.probes.popitem(last=False)
            return source

    def retry_after(self, scope, sources):
        """Return time to the earliest normal or permitted half-open attempt.

        Merely observing an existing cooldown must not start a new cooldown
        for each request identity. This does not claim a recovery probe.
        """
        with self.lock:
            now = self.clock()
            delays = []
            for source in sources:
                row = self.health.get((scope, source))
                if row is None or row["retry_at"] <= now:
                    return 0
                probe_at = self._recovery_ready_at(scope, source, row)
                delays.append(max(0, min(row["retry_at"], probe_at) - now))
            return min(delays, default=self.cooldown)

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
            active_scopes = {key[0] for key in self.health}
            for scope in list(self.probe_tried):
                if scope not in active_scopes:
                    self.probe_tried.pop(scope, None)

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
