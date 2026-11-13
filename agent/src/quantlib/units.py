"""Explicit rate units for reproducible comparisons, without prose inference."""

from __future__ import annotations

from decimal import Decimal
import math

__all__ = ["compare_rates"]

_TO_DECIMAL = {"decimal": Decimal(1), "percent": Decimal("0.01"), "bp": Decimal("0.0001")}


def compare_rates(left: float, right: float, input_unit: str = "decimal") -> dict:
    """Compute left minus right in rate fractions, percentage points and bps.

    Args:
        left: Signed first rate, in input_unit.
        right: Signed comparison rate, in the same input_unit.
        input_unit: Explicit unit: decimal (0.01), percent (1), or bp (100)
            represent the same rate. Units and signs are never inferred.

    Returns:
        Operands in decimals and the signed difference in three units. This
        is an absolute rate difference, not a relative percentage change.

    Raises:
        ValueError: If an operand is nonnumeric/nonfinite or the unit is unknown.
    """
    if input_unit not in _TO_DECIMAL:
        raise ValueError("input_unit must be decimal, percent, or bp")
    for value in (left, right):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("left and right must be finite numbers")
    lhs, rhs = (Decimal(str(x)) * _TO_DECIMAL[input_unit] for x in (left, right))
    difference = lhs - rhs
    return {
        "operation": "left - right (absolute rate difference)",
        "input_unit": input_unit,
        "left_decimal": float(lhs),
        "right_decimal": float(rhs),
        "difference_decimal": float(difference),
        "difference_percentage_points": float(difference * 100),
        "difference_bps": float(difference * 10000),
    }
