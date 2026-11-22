"""Shared Decimal primitives and issue rows for the portfolio replay.

Every reconcile cluster renders money/weights through these helpers and reports
disagreements as ``{code, path, expected, actual}`` issue rows. The precision
constant and exact product come from the canonical ``numeric`` module; the
reconcile-specific ratio and rendering helpers stay local.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any

from .numeric import _EXACT_PRECISION, _exact_product


_exact = _exact_product
_CENT = Decimal("0.01")
_WEIGHT_QUANTUM = Decimal("0.000000000001")
_ZERO = Decimal(0)
_GENERATED_ORDER_ID = re.compile(r"^pt2-(\d{8})-(.+)-(buy|sell)-(.+)$")


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = _EXACT_PRECISION
        return numerator / denominator


def _money_even(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_EVEN)


def _weight(value: Decimal) -> Decimal:
    if value == 0:
        return Decimal(0)
    return value.quantize(_WEIGHT_QUANTUM, rounding=ROUND_HALF_EVEN)


def _text(value: Decimal) -> str:
    """Render an exact Decimal without exponent notation or negative zero."""
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _money_text(value: Decimal) -> str:
    return format(_money_even(value), ".2f")


def _issue(
    issues: list[dict[str, Any]],
    code: str,
    path: str,
    expected: Any,
    actual: Any,
) -> None:
    issues.append(
        {"code": code, "path": path, "expected": expected, "actual": actual}
    )
