"""Options order risk and the options mandate check (#1435).

Options are not sized like shares: a contract controls ``trade_value_multiplier``
units of the underlying (100 for a standard US equity option), and its exposure
is the worst-case loss of the whole order, not its premium. This module turns a
normalized :class:`OptionOrderIntent` into two USD figures, both with the
multiplier applied, and checks them against the user's
:class:`~src.live.mandate.model.OptionLimits`:

* ``premium_usd``: the net debit the order pays (0 for a net credit).
* ``max_loss_usd``: the worst expiry payoff of all legs together, net of the
  premium. A short call not covered by a long call has no bound and is
  refused outright.

:func:`check_option_order` is pure, like
:func:`~src.live.enforcement.check_mandate`, and returns a
:class:`~src.live.enforcement.BreachEvent` with the same structural/quantitative
routing, so the gate that calls it keeps one DENY / PAUSE_FOR_REAUTH path.

No broker order path calls it yet: Robinhood advertises ``place_option_order``
and ``review_option_order`` but their argument schemas have not been observed,
so there is no extractor that could build an intent from a real request
(see :data:`src.trading.connectors.robinhood.mcp.OPTIONS_ORDERS_SUPPORTED`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone

from src.live.enforcement import (
    BREACH_KIND_INSTRUMENT,
    BREACH_KIND_QUANTITATIVE,
    BREACH_KIND_UNIVERSE,
    BreachEvent,
    OrderIntent,
)
from src.live.mandate.model import InstrumentType, Mandate


@dataclass(frozen=True)
class OptionLeg:
    """One leg of an options order, one contract per order unit.

    Attributes:
        option_type: ``"call"`` or ``"put"``.
        side: ``"buy"`` or ``"sell"``.
        strike: Strike price per underlying unit, USD.
        expiration: ISO date, ``YYYY-MM-DD``.
    """

    option_type: str
    side: str
    strike: float
    expiration: str


@dataclass(frozen=True)
class OptionOrderIntent:
    """A normalized options order: explicit contracts, explicit limit premium.

    Attributes:
        underlying: Upper-case underlying symbol.
        legs: One leg for a single-leg order, several for a spread.
        quantity: Contracts (spread units for a multi-leg order).
        limit_price: Net limit premium per underlying unit, positive.
        price_effect: ``"debit"`` (the order pays) or ``"credit"`` (it receives).
        multiplier: The contract's ``trade_value_multiplier``.
        atomic: Whether the broker executes every leg in one call. A spread
            placed leg by leg can fill one leg alone, so it is refused.
    """

    underlying: str
    legs: tuple[OptionLeg, ...]
    quantity: int
    limit_price: float
    price_effect: str
    multiplier: float
    atomic: bool = True


@dataclass(frozen=True)
class OptionRisk:
    """USD figures for one order, multiplier applied.

    Attributes:
        premium_usd: Net debit paid; 0 for a credit.
        max_loss_usd: Worst-case loss at expiry, or ``None`` when unbounded.
        naked_short: Whether a short leg is not covered by a long leg of the
            same type in this order.
    """

    premium_usd: float
    max_loss_usd: float | None
    naked_short: bool


def option_order_risk(intent: OptionOrderIntent) -> OptionRisk:
    """Price an options order's premium and worst-case loss.

    Every leg must share one expiration (checked by :func:`check_option_order`),
    so the payoff at expiry is piecewise linear in the underlying price with
    kinks only at the strikes: its minimum is at ``0``, at a strike, or at
    infinity, which is unbounded exactly when short calls outnumber long calls.

    Args:
        intent: A validated options order.

    Returns:
        The order's :class:`OptionRisk`.
    """
    units = intent.multiplier * intent.quantity
    cash = intent.limit_price * units
    net_cash = -cash if intent.price_effect == "debit" else cash

    def signed(leg: OptionLeg) -> int:
        return 1 if leg.side == "buy" else -1

    def payoff(price: float) -> float:
        total = net_cash
        for leg in intent.legs:
            intrinsic = (
                max(0.0, price - leg.strike) if leg.option_type == "call" else max(0.0, leg.strike - price)
            )
            total += signed(leg) * intrinsic * units
        return total

    net_calls = sum(signed(leg) for leg in intent.legs if leg.option_type == "call")
    net_puts = sum(signed(leg) for leg in intent.legs if leg.option_type == "put")
    worst = min(payoff(price) for price in [0.0, *(leg.strike for leg in intent.legs)])
    return OptionRisk(
        premium_usd=cash if intent.price_effect == "debit" else 0.0,
        max_loss_usd=None if net_calls < 0 else max(0.0, -worst),
        naked_short=net_calls < 0 or net_puts < 0,
    )


def _invalid_reason(intent: OptionOrderIntent, today: date) -> str | None:
    """Return why ``intent`` is malformed, or ``None`` when it is well-formed."""
    if not intent.underlying or not intent.legs:
        return "options order needs an underlying and at least one leg"
    if isinstance(intent.quantity, bool) or not isinstance(intent.quantity, int) or intent.quantity <= 0:
        return "contract quantity must be a positive whole number"
    for value in (intent.limit_price, intent.multiplier):
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            return "limit premium and contract multiplier must be positive numbers"
    if intent.price_effect not in ("debit", "credit"):
        return "price effect must be debit or credit"
    expirations = set()
    for leg in intent.legs:
        if leg.option_type not in ("call", "put") or leg.side not in ("buy", "sell"):
            return "each leg needs call/put and buy/sell"
        if not isinstance(leg.strike, (int, float)) or not math.isfinite(leg.strike) or leg.strike <= 0:
            return "each leg needs a positive strike"
        try:
            expirations.add(date.fromisoformat(leg.expiration))
        except (TypeError, ValueError):
            return "each leg needs an ISO expiration date"
    if len(expirations) != 1:
        return "every leg must share one expiration"
    if expirations.pop() < today:
        return "the contract has expired"
    return None


def check_option_order(
    mandate: Mandate,
    intent: OptionOrderIntent,
    *,
    broker: str,
    remote_tool: str,
    daily_count: int,
    premium_used_today_usd: float,
    max_loss_used_today_usd: float,
    today: date | None = None,
) -> BreachEvent | None:
    """Evaluate one options order against the mandate (fail-closed).

    Order: options enabled → instrument allowed → exclude list → well-formed →
    atomic → bounded loss → naked short → per-order premium → per-order loss →
    per-day premium → per-day loss → daily count → funding.

    Args:
        mandate: The active, schema-valid, unexpired mandate.
        intent: The normalized options order.
        broker: Broker key, stamped onto any breach.
        remote_tool: Broker tool the agent invoked.
        daily_count: Orders already placed today.
        premium_used_today_usd: Premium already paid today, USD.
        max_loss_used_today_usd: Worst-case loss already opened today, USD.
        today: UTC date to judge expiry against; defaults to now.

    Returns:
        ``None`` when the order is within the mandate, else the first breach.
    """
    caps = mandate.hard_caps
    limits = mandate.option_limits
    underlying = (intent.underlying or "").strip().upper()
    summary = OrderIntent(
        symbol=underlying,
        side="buy" if intent.price_effect == "debit" else "sell",
        notional_usd=None,
        quantity=float(intent.quantity) if isinstance(intent.quantity, (int, float)) else None,
        instrument_type=InstrumentType.OPTION,
        limit_price=intent.limit_price if isinstance(intent.limit_price, (int, float)) else None,
    )

    def breach(kind: str, limit: str, limit_value: float = 0.0, attempted: float = 0.0, detail: str = "") -> BreachEvent:
        return BreachEvent(
            broker=broker,
            limit=limit,
            limit_value=limit_value,
            attempted_value=attempted,
            overage=attempted - limit_value,
            proposed_action=summary,
            remote_tool=remote_tool,
            created_at=datetime.now(timezone.utc).isoformat(),
            kind=kind,
            detail=detail,
        )

    if limits is None:
        return breach(BREACH_KIND_INSTRUMENT, "option_limits", detail="options are not enabled on this mandate")
    if InstrumentType.OPTION not in caps.allowed_instruments:
        return breach(BREACH_KIND_INSTRUMENT, "allowed_instruments", detail="option not in allowed_instruments")
    if underlying in {s.strip().upper() for s in mandate.universe.exclude_symbols}:
        return breach(BREACH_KIND_UNIVERSE, "exclude_symbols", detail=f"{underlying} is on the mandate exclude list")
    reason = _invalid_reason(intent, today or datetime.now(timezone.utc).date())
    if reason is not None:
        return breach(BREACH_KIND_INSTRUMENT, "order_intent", detail=reason)
    if len(intent.legs) > 1 and not intent.atomic:
        return breach(BREACH_KIND_INSTRUMENT, "order_intent", detail="a multi-leg order must execute atomically")

    risk = option_order_risk(intent)
    if risk.max_loss_usd is None:
        return breach(BREACH_KIND_INSTRUMENT, "option_max_loss", detail="an uncovered short call has unbounded loss")
    if risk.naked_short and not limits.allow_naked_short:
        return breach(BREACH_KIND_INSTRUMENT, "allow_naked_short", detail="naked short options are not allowed")

    summary = replace(summary, notional_usd=risk.max_loss_usd)
    for limit, value, attempted in (
        ("max_premium_per_order_usd", limits.max_premium_per_order_usd, risk.premium_usd),
        ("max_loss_per_order_usd", limits.max_loss_per_order_usd, risk.max_loss_usd),
        ("max_premium_per_day_usd", limits.max_premium_per_day_usd, premium_used_today_usd + risk.premium_usd),
        ("max_loss_per_day_usd", limits.max_loss_per_day_usd, max_loss_used_today_usd + risk.max_loss_usd),
        ("max_trades_per_day", float(caps.max_trades_per_day), float(daily_count + 1)),
        ("account_funding_usd", caps.account_funding_usd, risk.max_loss_usd),
    ):
        if attempted > value:
            return breach(BREACH_KIND_QUANTITATIVE, limit, value, attempted)
    return None
