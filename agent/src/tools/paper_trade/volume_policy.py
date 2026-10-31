"""Per-order volume-share caps for 5m matching (pt-v1.3, T8).

JoinQuant semantics: ``order_volume_ratio`` limits each ORDER independently —
a market order against a share of the full continuous-session volume, a limit
order against a share of the matched bar's volume (official PDF, 订单处理 /
``set_option('order_volume_ratio')``).  There is deliberately no shared
per-bar budget: two orders on one bar each receive the same cap, so their
combined fill may exceed that bar's volume (the documented divergence).

Arithmetic discipline (VD-9):

* every input converts through ``Decimal(str(value))`` — never float math
  (``100 * 0.29`` is ``28.999999999999996`` in binary floating point);
* every cap floors to a whole board lot (cn_a 100): a 250-share bar at 0.25
  is 62.5 shares, i.e. zero whole lots, and is never rounded up to 100;
* the ratio normalizes to 6 decimal places.

Pure module: no engine/session import, no clock, no state; every call is a
function of its arguments.
"""

from __future__ import annotations

from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation

from .schema import DEFAULT_ORDER_VOLUME_RATIO

__all__ = [
    "DEFAULT_ORDER_VOLUME_RATIO",
    "executable_qty",
    "limit_bar_cap",
    "lot_floor",
    "market_cap",
    "normalize_ratio",
]

_ZERO = Decimal("0")
_ONE = Decimal("1")
_RATIO_QUANTUM = Decimal("0.000001")


def _as_decimal(value: object, name: str) -> Decimal:
    """``Decimal(str(value))`` conversion (VD-9) with an explicit error."""
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number, got bool")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a number, got {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite, got {value!r}")
    return result


def normalize_ratio(ratio: object) -> Decimal:
    """Validate ``order_volume_ratio`` and normalize it to a 6dp Decimal.

    The request parser (schema T7) already gates the wire field; this is the
    policy-layer defense-in-depth: finite, non-bool, ``0 < ratio <= 1``.
    """
    value = _as_decimal(ratio, "order_volume_ratio")
    if value <= _ZERO or value > _ONE:
        raise ValueError(f"order_volume_ratio must be > 0 and <= 1, got {ratio!r}")
    return value.quantize(_RATIO_QUANTUM, rounding=ROUND_HALF_UP)


def lot_floor(qty: object, lot: int) -> int:
    """Floor a share quantity down to a whole board lot (never rounds up)."""
    if isinstance(lot, bool) or not isinstance(lot, int) or lot <= 0:
        raise ValueError(f"lot must be a positive integer, got {lot!r}")
    value = _as_decimal(qty, "qty")
    whole_lots = (value / Decimal(lot)).to_integral_value(rounding=ROUND_FLOOR)
    return int(whole_lots) * lot


def _volume_cap(volume: object, ratio: object, lot: int, name: str) -> int:
    shares = _as_decimal(volume, name)
    if shares < _ZERO:
        raise ValueError(f"{name} must be >= 0, got {volume!r}")
    return lot_floor(shares * normalize_ratio(ratio), lot)


def market_cap(day_volume_shares: object, ratio: object, lot: int) -> int:
    """Cap for a MARKET order: its share of the full continuous-session volume.

    ``day_volume_shares`` is ``SessionBar.volume`` — provider shares, with the
    09:30 opening auction already excluded by the continuous-session assembly
    (T4).  The cap is computed once per order, never shared between orders.
    """
    return _volume_cap(day_volume_shares, ratio, lot, "day_volume_shares")


def limit_bar_cap(bar_volume_shares: object, ratio: object, lot: int) -> int:
    """Cap for a LIMIT order on one bar: its share of that bar's volume."""
    return _volume_cap(bar_volume_shares, ratio, lot, "bar_volume_shares")


def executable_qty(remaining: object, cap: object) -> int:
    """Whole shares executable now: ``min(remaining, cap)`` floored at zero."""
    rem = _as_decimal(remaining, "remaining")
    ceiling = _as_decimal(cap, "cap")
    return int(max(_ZERO, min(rem, ceiling)))
