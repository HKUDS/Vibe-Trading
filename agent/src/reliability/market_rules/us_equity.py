"""US equity market-rule audit placeholder for Phase 2."""

from __future__ import annotations

from typing import Any, Mapping

from src.reliability.data.contracts import StructuredWarning


def audit_us_equity_assumptions(_config: Mapping[str, Any]) -> list[StructuredWarning]:
    """Return US equity market-rule warnings.

    Phase 2 keeps this intentionally empty; later scorecard phases can extend it.
    """
    return []
