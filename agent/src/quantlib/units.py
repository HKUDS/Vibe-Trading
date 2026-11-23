"""Explicit rate units for reproducible comparisons, without prose inference."""

from __future__ import annotations

from decimal import Decimal
import math

__all__ = ["compare_rates"]

_TO_DECIMAL = {"decimal": Decimal(1), "percent": Decimal("0.01"), "bp": Decimal("0.0001")}


def compare_rates(
    left: float,
    right: float,
    input_unit: str = "decimal",
    left_label: str = "left",
    right_label: str = "right",
) -> dict:
    """Compare named rates and return their direction and signed difference.

    Args:
        left: Signed first rate, in input_unit.
        right: Signed comparison rate, in the same input_unit.
        input_unit: Explicit unit: decimal (0.01), percent (1), or bp (100)
            represent the same rate. Units and signs are never inferred.
        left_label: Name of the first operand, e.g. B in a B-minus-A comparison.
        right_label: Name of the subtracted operand, e.g. A.

    Returns:
        Named operands, relation (left is higher/lower/equal to right), and
        the signed difference in decimals, percentage points and bps.
        Relation describes numeric ordering, not which investment is better.
        This is an absolute rate difference, not a relative percentage change.

    Raises:
        ValueError: If an operand is nonnumeric/nonfinite or the unit is unknown.
    """
    if not isinstance(left_label, str) or not isinstance(right_label, str):
        raise ValueError("left_label and right_label must be strings")
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
        "left_label": left_label,
        "right_label": right_label,
        "relation": "higher" if difference > 0 else "lower" if difference < 0 else "equal",
        "left_decimal": float(lhs),
        "right_decimal": float(rhs),
        "difference_decimal": float(difference),
        "difference_percentage_points": float(difference * 100),
        "difference_bps": float(difference * 10000),
    }
