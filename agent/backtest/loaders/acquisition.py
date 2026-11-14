"""Lightweight acquisition context; importing it must not load a market SDK."""

from contextvars import ContextVar

source_background = ContextVar("source_background", default=False)
source_deadline = ContextVar("source_deadline", default=None)


class SourceAdmissionTimeout(TimeoutError):
    """Local pacing consumed the request budget before any network call."""
