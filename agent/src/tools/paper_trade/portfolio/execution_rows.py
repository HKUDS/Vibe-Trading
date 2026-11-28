"""Terminal-row mapping: fills, rejections and cancellations.

``_terminal_rows`` asserts exactly one terminal outcome per planned
order; ``_fill_row``/``_nonfill_row`` reconstruct each row from the
source integer order, the target-day close and the shared fee primitive,
using the legacy float row only as a consistency guard.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal, localcontext

from .. import engine
from ..rules import quantize_money
from .execution_common import (
    _EXACT_PRECISION,
    _abort,
    _exact_product,
    _finite_decimal,
    _legacy_decimal,
)
from .ledger import BucketLedger, CashMovement, LedgerEvent, PositionMovement
from .numeric import MONEY_SPEC, canonical_decimal
from .orchestrator import ExecutionCancellation, ExecutionFill, ExecutionRejection
from .order_plan import PlannedOrder


def _terminal_rows(
    outcome: engine.MatchOutcome,
    bucket: BucketLedger,
    orders: Sequence[PlannedOrder],
    day: str,
) -> dict[tuple[str, str], tuple[str, object]]:
    rows: dict[tuple[str, str], tuple[str, object]] = {}
    expected = {(order.symbol, order.side) for order in orders}
    sources = (
        ("fill", outcome.fills),
        ("rejected", outcome.rejected_orders),
        ("canceled", outcome.canceled_orders),
    )
    for kind, values in sources:
        for row in values:
            key = (row.symbol, row.side)
            if key in rows:
                _abort(
                    "duplicate_order_outcome",
                    f"execution.{bucket.bucket_id}.{kind}.{row.symbol}",
                    bucket_id=bucket.bucket_id,
                    detail="every planned order has exactly one terminal outcome",
                )
            if key not in expected:
                _abort(
                    "unexpected_order_outcome",
                    f"execution.{bucket.bucket_id}.{kind}.{row.symbol}",
                    bucket_id=bucket.bucket_id,
                )
            if str(row.trade_date) != day:
                _abort(
                    "outcome_date_mismatch",
                    f"execution.{bucket.bucket_id}.{kind}.{row.symbol}",
                    bucket_id=bucket.bucket_id,
                )
            rows[key] = (kind, row)
    missing = expected - set(rows)
    if missing:
        symbol, side = sorted(missing)[0]
        _abort(
            "missing_order_outcome",
            f"execution.{bucket.bucket_id}.{symbol}.{side}",
            bucket_id=bucket.bucket_id,
        )
    if len(rows) != len(orders):
        _abort(
            "inconsistent_order_outcome_count",
            f"execution.{bucket.bucket_id}",
            bucket_id=bucket.bucket_id,
        )
    return rows


def _post_buy_avg_cost(
    bucket: BucketLedger,
    order: PlannedOrder,
    price: Decimal,
) -> Decimal:
    current = next(
        (position for position in bucket.positions if position.symbol == order.symbol),
        None,
    )
    if current is None:
        basis = price
    else:
        with localcontext() as context:
            context.prec = _EXACT_PRECISION
            total_qty = current.qty + order.qty
            basis = (
                Decimal(current.qty) * current.avg_cost + Decimal(order.qty) * price
            ) / Decimal(total_qty)
    # The Decimal ledger stores fee-exclusive average cost at the money scale;
    # canonical_decimal applies the ledger's ROUND_HALF_EVEN canonicalisation.
    return Decimal(
        canonical_decimal(
            basis,
            MONEY_SPEC,
            f"execution.{bucket.bucket_id}.{order.symbol}.avg_cost",
        )
    )


def _check_fee(fee: Decimal, bucket_id: str, order: PlannedOrder) -> None:
    _finite_decimal(fee, f"execution.{bucket_id}.{order.plan_order_id}.fee", bucket_id)
    if fee < 0:
        _abort(
            "negative_execution_fee",
            f"execution.{bucket_id}.{order.plan_order_id}.fee",
            bucket_id=bucket_id,
            detail="fees may not reduce a fill's cash effect",
        )


def _fill_row(
    *,
    bucket: BucketLedger,
    order: PlannedOrder,
    row: engine.Fill,
    price: Decimal,
    fee: Decimal,
    trade_date: date,
    running_cash: dict[str, Decimal],
) -> tuple[ExecutionFill, tuple[LedgerEvent, ...]]:
    day_path = f"execution.{bucket.bucket_id}.{order.plan_order_id}"
    legacy_qty = _legacy_decimal(row.qty, f"{day_path}.qty", bucket.bucket_id)
    if legacy_qty != Decimal(order.qty):
        _abort(
            "legacy_execution_mismatch",
            f"{day_path}.qty",
            bucket_id=bucket.bucket_id,
            detail=f"legacy qty {legacy_qty} != planned {order.qty}",
        )
    if order.side == "sell":
        try:
            notional = quantize_money(_exact_product(Decimal(order.qty), price))
        except ArithmeticError:
            _abort("nonfinite_execution_value", f"{day_path}.notional", bucket_id=bucket.bucket_id)
        proceeds = notional - fee
        if not proceeds.is_finite() or proceeds <= 0:
            _abort(
                "nonpositive_sale_proceeds",
                f"{day_path}.proceeds",
                bucket_id=bucket.bucket_id,
                detail=f"net proceeds {proceeds} must be positive",
            )
        cash_amount = proceeds
    else:
        try:
            notional = quantize_money(_exact_product(Decimal(order.qty), price))
        except ArithmeticError:
            _abort("nonfinite_execution_value", f"{day_path}.notional", bucket_id=bucket.bucket_id)
        cash_amount = -(notional + fee)

    legacy_price = _legacy_decimal(row.price, f"{day_path}.price", bucket.bucket_id)
    if legacy_price != price:
        _abort(
            "legacy_execution_mismatch",
            f"{day_path}.price",
            bucket_id=bucket.bucket_id,
            detail=f"legacy price {legacy_price} != target close {price}",
        )
    legacy_fee = _legacy_decimal(row.fee, f"{day_path}.fee", bucket.bucket_id)
    if legacy_fee != fee:
        _abort(
            "legacy_execution_mismatch",
            f"{day_path}.fee",
            bucket_id=bucket.bucket_id,
            detail=f"legacy fee {legacy_fee} != reconstructed {fee}",
        )

    if not cash_amount.is_finite():
        _abort("nonfinite_execution_value", f"{day_path}.cash", bucket_id=bucket.bucket_id)
    next_cash = running_cash[bucket.bucket_id] + cash_amount
    if not next_cash.is_finite():
        _abort("nonfinite_execution_value", f"{day_path}.cash", bucket_id=bucket.bucket_id)
    if next_cash < 0:
        _abort(
            "negative_execution_cash",
            f"{day_path}.cash",
            bucket_id=bucket.bucket_id,
            detail=f"cash {next_cash} would go negative",
        )
    running_cash[bucket.bucket_id] = next_cash

    events: list[LedgerEvent] = [
        CashMovement(bucket_id=bucket.bucket_id, amount=cash_amount)
    ]
    if order.side == "buy":
        events.append(
            PositionMovement(
                bucket_id=bucket.bucket_id,
                symbol=order.symbol,
                qty_delta=order.qty,
                avg_cost=_post_buy_avg_cost(bucket, order, price),
            )
        )
    else:
        events.append(
            PositionMovement(
                bucket_id=bucket.bucket_id,
                symbol=order.symbol,
                qty_delta=-order.qty,
            )
        )
    fill = ExecutionFill(
        plan_order_id=order.plan_order_id,
        bucket_id=bucket.bucket_id,
        symbol=order.symbol,
        currency=order.currency,
        side=order.side,
        qty=order.qty,
        price=price,
        fee=fee,
        trade_date=trade_date,
    )
    return fill, tuple(events)


def _nonfill_row(
    *,
    bucket: BucketLedger,
    order: PlannedOrder,
    kind: str,
    row: engine.RejectedOrder | engine.CanceledOrder,
    trade_date: date,
) -> ExecutionRejection | ExecutionCancellation:
    reason_code = getattr(row, "reason_code", "")
    if not isinstance(reason_code, str) or not reason_code:
        _abort(
            "missing_outcome_reason",
            f"execution.{bucket.bucket_id}.{order.plan_order_id}.reason_code",
            bucket_id=bucket.bucket_id,
        )
    legacy_qty = _legacy_decimal(
        row.qty,
        f"execution.{bucket.bucket_id}.{order.plan_order_id}.qty",
        bucket.bucket_id,
    )
    if legacy_qty != Decimal(order.qty):
        _abort(
            "outcome_quantity_mismatch",
            f"execution.{bucket.bucket_id}.{order.plan_order_id}.qty",
            bucket_id=bucket.bucket_id,
            detail="all_or_none terminal outcomes must match the planned quantity",
        )
    kwargs = {
        "plan_order_id": order.plan_order_id,
        "bucket_id": bucket.bucket_id,
        "symbol": order.symbol,
        "currency": order.currency,
        "side": order.side,
        "qty": order.qty,
        "trade_date": trade_date,
        "reason_code": reason_code,
        "detail": getattr(row, "detail", ""),
    }
    if kind == "canceled":
        return ExecutionCancellation(**kwargs)
    return ExecutionRejection(**kwargs)
