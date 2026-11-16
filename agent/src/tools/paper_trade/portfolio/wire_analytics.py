"""Exact analytics recomputation for the public pt-v2.0 wire.

The optional ``analytics`` object is checked against the public ledger by
``wire_success._assert_analytics``; this module owns the exact-arithmetic
helpers and the per-section validators (benchmark observations, one-day
attribution) that recompute every published ratio and reconciliation before
the document can be published. Each refusal raises
:class:`~.wire_errors.PortfolioWireError` (INTERNAL transport), never an
in-band error envelope.
"""

from __future__ import annotations

from decimal import Decimal

from .models import JsonValue
from .wire_contract import _DECIMAL_PATTERN
from .wire_errors import _reject


def _decimal_value(value: JsonValue, path: str) -> Decimal:
    """Read a canonical public decimal after the shape/decimal checks."""
    if not isinstance(value, str) or _DECIMAL_PATTERN.fullmatch(value) is None:
        _reject("invalid_decimal", path, detail="expected a canonical fixed-point string")
    return Decimal(value)


def _analytics_sum(rows: list[JsonValue], path: str) -> Decimal:
    total = Decimal(0)
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            _reject("invalid_analytics", f"{path}[{index}]")
        total += _decimal_value(row.get("value_base"), f"{path}[{index}].value_base")
    return total