"""Neutral home of the pt-v2.0 portfolio boundary rejection type.

Kept separate from ``schema`` and ``numeric`` so both can re-export the single
class object without an import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PortfolioRequestError(ValueError):
    """One stable, structured pt-v2.0 boundary rejection."""

    reason: str
    path: str
    bucket_id: str | None = None
    detail: str = ""

    @property
    def code(self) -> str:
        return "INVALID_REQUEST"

    def __str__(self) -> str:
        return f"{self.code}:{self.reason}:{self.path}"
