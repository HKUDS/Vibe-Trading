"""Legacy single-day engine seam: account/order/calendar adapters + run.

``_run_legacy_match`` calls ``engine.run_day_loop`` through the legacy
engine MODULE ATTRIBUTE so monkeypatching ``engine.run_day_loop`` keeps
intercepting, and aborts on any engine fault, in-band error, skipped day
or post-fill FX conversion. ``limits_client=None`` is preserved verbatim.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .. import engine
from ..rules import MarketRules
from ..schema import AccountState, Order, Position
from .data import BucketPreflight
from .execution_common import _PreparedDayCalendar, _abort
from .ledger import BucketLedger
from .models import PortfolioRequest
from .order_plan import PlannedOrder


def _legacy_account(bucket: BucketLedger) -> AccountState:
    # Decimal inputs cross the seam unchanged: MarketRules and the engine call
    # money()/Decimal(str(...)) themselves, so no float is introduced here.
    return AccountState(
        cash=bucket.cash,
        positions=tuple(
            Position(symbol=position.symbol, qty=position.qty, avg_cost=position.avg_cost)
            for position in bucket.positions
        ),
    )


def _legacy_orders(orders: Sequence[PlannedOrder]) -> tuple[Order, ...]:
    return tuple(
        Order(symbol=order.symbol, side=order.side, qty=order.qty, limit=order.limit)
        for order in orders
    )


def _bucket_day_calendar(entry: BucketPreflight) -> _PreparedDayCalendar:
    return _PreparedDayCalendar(
        open_days=frozenset(
            row.date for row in entry.day_plan if row.skip_reason is None
        )
    )


def _run_legacy_match(
    bucket: BucketLedger,
    request: PortfolioRequest,
    entry: BucketPreflight,
    rules: MarketRules,
    orders: Sequence[PlannedOrder],
    hk_lot_sizes: Mapping[str, int] | None,
) -> engine.MatchOutcome:
    day = request.trade_date.isoformat()
    try:
        outcome = engine.run_day_loop(
            market=bucket.market,
            account_state=_legacy_account(bucket),
            from_date=day,
            to_date=day,
            orders_by_day={day: _legacy_orders(orders)},
            market_data=entry.market_data,
            fee_model=dict(rules.effective_fee_model),
            calendar_client=_bucket_day_calendar(entry) if bucket.market == "cn_a" else None,
            limits_client=None,
            corporate_action_unresolved_by_day=entry.corporate_actions.unresolved_by_day,
            hk_lot_sizes=hk_lot_sizes,
        )
    except Exception as exc:  # noqa: BLE001 — an engine fault must abort the document
        _abort(
            "engine_execution_failed",
            f"execution.{bucket.bucket_id}",
            bucket_id=bucket.bucket_id,
            detail=f"{type(exc).__name__}: {exc}"[:200],
        )
    if outcome.error is not None:
        _abort(
            "legacy_engine_error",
            f"execution.{bucket.bucket_id}",
            bucket_id=bucket.bucket_id,
            detail=f"{outcome.error.code}: {outcome.error.message}"[:200],
        )
    if outcome.skipped_days:
        _abort(
            "unexpected_skipped_day",
            f"execution.{bucket.bucket_id}.skipped_days",
            bucket_id=bucket.bucket_id,
        )
    for attribute in ("conversions", "fx_conversions", "conversion_requests"):
        if getattr(outcome, attribute, ()):
            _abort(
                "post_fill_fx_conversion",
                f"execution.{bucket.bucket_id}.{attribute}",
                bucket_id=bucket.bucket_id,
            )
    return outcome
