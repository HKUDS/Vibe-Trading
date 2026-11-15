"""Lightweight acquisition context; importing it must not load a market SDK."""

from contextvars import ContextVar
import time

source_background = ContextVar("source_background", default=False)
# A routed read can use another adapter instead of queueing for a busy SDK.
source_can_fallback = ContextVar("source_can_fallback", default=False)
# Set only when an SDK voluntarily yields before any login/query is sent.
source_admission_yielded = ContextVar("source_admission_yielded", default=False)
source_deadline = ContextVar("source_deadline", default=None)


class SourceAdmissionTimeout(TimeoutError):
    """Local pacing consumed the request budget before any network call."""


def remaining_timeout(default: float) -> float:
    """Cap socket/retry waits by the caller's aggregate acquisition deadline."""
    until = source_deadline.get()
    if until is None:
        return default
    remaining = until - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Acquisition deadline reached")
    return min(default, remaining)
