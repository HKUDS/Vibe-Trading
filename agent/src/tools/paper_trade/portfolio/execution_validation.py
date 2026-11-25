"""Plan/ledger/prepared-data identity validation and preflight gates.

``_validate_plan`` asserts the request/ledger/plan/prepared bundle is one
coherent post-conversion snapshot; ``_preflight_for_bucket`` and
``_target_closes`` gate each bucket's raw preflight journal and read the
target-day close prices as exact Decimals.
"""

from __future__ import annotations

from decimal import Decimal

from .data import BucketPreflight, PreparedBucketData, PreparedPortfolioData
from .execution_common import _abort, _bucket_map, _price_decimal
from .ledger import BucketLedger, PortfolioLedger
from .models import PortfolioRequest
from .order_plan import OrderPlan, PlannedOrder


def _validate_plan(
    request: PortfolioRequest,
    ledger: PortfolioLedger,
    plan: OrderPlan,
    prepared: PreparedPortfolioData,
) -> None:
    if not isinstance(request, PortfolioRequest):
        _abort("invalid_request", "$")
    if not isinstance(ledger, PortfolioLedger):
        _abort("invalid_ledger", "portfolio_ledger")
    if not isinstance(plan, OrderPlan):
        _abort("invalid_order_plan", "order_plan")
    if not isinstance(prepared, PreparedPortfolioData):
        _abort("invalid_prepared_data", "prepared_data")
    if request.interval != "1d" or request.fill_model != "all_or_none":
        _abort("unsupported_execution_mode", "request", detail="only single-day all_or_none")
    expected_mode = "explicit_orders" if request.orders is not None else "target_weights"
    if plan.mode != expected_mode:
        _abort("plan_mode_mismatch", "order_plan.mode")
    if (
        plan.trade_date != request.trade_date
        or plan.planning_at != request.planning_at
        or plan.base_currency != request.base_currency
    ):
        _abort("plan_identity_mismatch", "order_plan")

    ledger_by_id = _bucket_map(ledger)
    plan_ids = [bucket.bucket_id for bucket in plan.buckets]
    if len(plan_ids) != len(set(plan_ids)) or set(plan_ids) != set(ledger_by_id):
        _abort("plan_ledger_bucket_mismatch", "order_plan.buckets")
    for bucket_plan in plan.buckets:
        bucket = ledger_by_id[bucket_plan.bucket_id]
        if (
            bucket_plan.market != bucket.market
            or bucket_plan.currency != bucket.currency
        ):
            _abort(
                "plan_ledger_identity_mismatch",
                f"order_plan.buckets.{bucket_plan.bucket_id}",
                bucket_id=bucket_plan.bucket_id,
            )
        if bucket_plan.opening_cash != bucket.cash:
            _abort(
                "plan_ledger_cash_mismatch",
                f"order_plan.buckets.{bucket_plan.bucket_id}.opening_cash",
                bucket_id=bucket_plan.bucket_id,
                detail="the plan must be built from this post-conversion ledger",
            )

    prepared_ids = [bucket.bucket_id for bucket in prepared.buckets]
    if len(prepared_ids) != len(set(prepared_ids)) or set(prepared_ids) != set(ledger_by_id):
        _abort("prepared_bucket_mismatch", "prepared_data.buckets")
    for bucket in prepared.buckets:
        ledger_bucket = ledger_by_id[bucket.bucket_id]
        if (
            bucket.session.bucket_id != bucket.bucket_id
            or bucket.session.market != ledger_bucket.market
            or bucket.session.price_date != request.trade_date
        ):
            _abort(
                "prepared_session_mismatch",
                f"prepared_data.buckets.{bucket.bucket_id}.session",
                bucket_id=bucket.bucket_id,
            )

    if not prepared.preflight:
        _abort(
            "missing_preflight_journal",
            "prepared_data.preflight",
            detail="the Decimal adapter needs the raw preflight market-data journal",
        )
    journal_ids = [entry.bucket_id for entry in prepared.preflight]
    if len(journal_ids) != len(set(journal_ids)) or set(journal_ids) != set(ledger_by_id):
        _abort("incomplete_preflight_journal", "prepared_data.preflight")

    seen_orders: set[str] = set()
    seen_instruments: set[tuple[str, str]] = set()
    for order in plan.orders:
        if not isinstance(order, PlannedOrder):
            _abort("invalid_planned_order", "order_plan.orders")
        if order.plan_order_id in seen_orders:
            _abort(
                "duplicate_plan_order_id",
                f"order_plan.orders.{order.plan_order_id}",
                bucket_id=order.bucket_id,
            )
        seen_orders.add(order.plan_order_id)
        bucket = ledger_by_id.get(order.bucket_id)
        if bucket is None:
            _abort("unknown_plan_bucket", f"order_plan.orders.{order.plan_order_id}.bucket_id")
        if (
            order.market != bucket.market
            or order.currency != bucket.currency
            or order.side not in ("buy", "sell")
            or type(order.qty) is not int
            or order.qty <= 0
            or not isinstance(order.symbol, str)
            or not order.symbol
        ):
            _abort(
                "invalid_planned_order",
                f"order_plan.orders.{order.plan_order_id}",
                bucket_id=order.bucket_id,
            )
        key = (order.bucket_id, order.symbol)
        if key in seen_instruments:
            _abort(
                "duplicate_plan_instrument",
                f"order_plan.orders.{order.plan_order_id}.symbol",
                bucket_id=order.bucket_id,
            )
        seen_instruments.add(key)


def _preflight_for_bucket(
    bucket: BucketLedger,
    request: PortfolioRequest,
    prepared: PreparedPortfolioData,
) -> BucketPreflight:
    entry = next(
        (row for row in prepared.preflight if row.bucket_id == bucket.bucket_id),
        None,
    )
    if entry is None:
        _abort("missing_bucket_preflight", "prepared_data.preflight", bucket_id=bucket.bucket_id)
    if entry.market != bucket.market:
        _abort("prepared_market_mismatch", "prepared_data.preflight", bucket_id=bucket.bucket_id)
    bucket_data = entry.prepared
    if (
        bucket_data.session.bucket_id != bucket.bucket_id
        or bucket_data.session.market != bucket.market
        or bucket_data.session.price_date != request.trade_date
        or not bucket_data.session.matchable
    ):
        _abort("bucket_not_matchable", "prepared_data.buckets", bucket_id=bucket.bucket_id)
    if bucket_data.execution is None:
        _abort("missing_execution_snapshot", "prepared_data.buckets", bucket_id=bucket.bucket_id)
    if bucket_data.execution.price_date != request.trade_date:
        _abort(
            "execution_date_mismatch",
            f"prepared_data.buckets.{bucket.bucket_id}.execution",
            bucket_id=bucket.bucket_id,
        )
    if (
        entry.market_data.market != bucket.market
        or entry.market_data.interval != "1d"
        or entry.market_data.from_date != request.trade_date.isoformat()
        or entry.market_data.to_date != request.trade_date.isoformat()
    ):
        _abort(
            "prepared_market_data_mismatch",
            f"prepared_data.buckets.{bucket.bucket_id}.market_data",
            bucket_id=bucket.bucket_id,
        )
    if not entry.readiness.ready:
        _abort("target_bar_not_ready", "prepared_data.preflight", bucket_id=bucket.bucket_id)
    day = request.trade_date.isoformat()
    day_entries = tuple(row for row in entry.day_plan if row.date == day)
    if len(day_entries) != 1:
        _abort("missing_day_plan", f"prepared_data.buckets.{bucket.bucket_id}.day_plan", bucket_id=bucket.bucket_id)
    if day_entries[0].skip_reason is not None:
        _abort("closed_target_day", "prepared_data.buckets", bucket_id=bucket.bucket_id)
    if day in entry.corporate_actions.clean_by_day or day in entry.corporate_actions.unresolved_by_day:
        _abort(
            "corporate_action_at_execution",
            f"prepared_data.buckets.{bucket.bucket_id}.corporate_actions",
            bucket_id=bucket.bucket_id,
        )
    return entry


def _target_closes(
    bucket: BucketLedger,
    entry: BucketPreflight,
) -> dict[str, Decimal]:
    bucket_data: PreparedBucketData = entry.prepared
    execution = bucket_data.execution
    if execution is None:
        _abort("missing_execution_snapshot", "prepared_data.buckets", bucket_id=bucket.bucket_id)
    closes: dict[str, Decimal] = {}
    for bar in execution.bars:
        if bar.symbol in closes:
            _abort(
                "duplicate_execution_price",
                f"prepared_data.buckets.{bucket.bucket_id}.execution.{bar.symbol}",
                bucket_id=bucket.bucket_id,
            )
        closes[bar.symbol] = _price_decimal(
            bar.close,
            f"prepared_data.buckets.{bucket.bucket_id}.execution.{bar.symbol}.close",
            bucket.bucket_id,
        )
    if not closes:
        _abort("missing_execution_prices", "prepared_data.buckets", bucket_id=bucket.bucket_id)
    return closes
