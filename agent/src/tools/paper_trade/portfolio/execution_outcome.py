"""Per-bucket outcome assembly and replayed-ledger validation.

``_bucket_outcome`` drives the legacy match, reconstructs every terminal
row and collects the cash/position ledger events; ``_validate_replayed_ledger``
replays them and asserts the end ledger keeps its buckets and nonnegative
finite cash.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..rules import MarketRules
from .data import BucketPreflight
from .execution_common import _abort, _fee_for
from .execution_legacy_match import _run_legacy_match
from .execution_rows import _check_fee, _fill_row, _nonfill_row, _terminal_rows
from .execution_validation import _target_closes
from .ledger import BucketLedger, LedgerEvent, PortfolioLedger
from .models import PortfolioRequest
from .orchestrator import ExecutionCancellation, ExecutionFill, ExecutionRejection
from .order_plan import PlannedOrder
from .schema import PortfolioRequestError


def _bucket_outcome(
    *,
    bucket: BucketLedger,
    request: PortfolioRequest,
    orders: Sequence[PlannedOrder],
    entry: BucketPreflight,
    rules: MarketRules,
    hk_lot_sizes: Mapping[str, int] | None,
) -> tuple[
    tuple[ExecutionFill, ...],
    tuple[ExecutionRejection, ...],
    tuple[ExecutionCancellation, ...],
    tuple[LedgerEvent, ...],
]:
    legacy = _run_legacy_match(bucket, request, entry, rules, orders, hk_lot_sizes)
    closes = _target_closes(bucket, entry)
    rows = _terminal_rows(legacy, bucket, orders, request.trade_date.isoformat())
    running_cash = {bucket.bucket_id: bucket.cash}
    fills: list[ExecutionFill] = []
    rejected: list[ExecutionRejection] = []
    canceled: list[ExecutionCancellation] = []
    events: list[LedgerEvent] = []
    for order in orders:
        kind, row = rows[(order.symbol, order.side)]
        if kind == "fill":
            price = closes.get(order.symbol)
            if price is None:
                _abort(
                    "missing_execution_price",
                    f"execution.{bucket.bucket_id}.{order.plan_order_id}.price",
                    bucket_id=bucket.bucket_id,
                    detail="a fill needs its source target-day close",
                )
            fee = _fee_for(rules, order.side, order.qty, price)
            _check_fee(fee, bucket.bucket_id, order)
            fill, fill_events = _fill_row(
                bucket=bucket,
                order=order,
                row=row,
                price=price,
                fee=fee,
                trade_date=request.trade_date,
                running_cash=running_cash,
            )
            fills.append(fill)
            events.extend(fill_events)
            continue
        if kind == "canceled":
            canceled.append(
                _nonfill_row(
                    bucket=bucket,
                    order=order,
                    kind="canceled",
                    row=row,
                    trade_date=request.trade_date,
                )
            )
        else:
            rejected.append(
                _nonfill_row(
                    bucket=bucket,
                    order=order,
                    kind="rejected",
                    row=row,
                    trade_date=request.trade_date,
                )
            )
    return tuple(fills), tuple(rejected), tuple(canceled), tuple(events)


def _validate_replayed_ledger(
    ledger: PortfolioLedger,
    events: Sequence[LedgerEvent],
) -> None:
    try:
        end = ledger.apply(events)
    except PortfolioRequestError as exc:
        _abort(
            "ledger_replay_failed",
            exc.path,
            bucket_id=exc.bucket_id,
            detail=exc.reason,
        )
    before_ids = tuple(bucket.bucket_id for bucket in ledger.buckets)
    after_ids = tuple(bucket.bucket_id for bucket in end.buckets)
    if before_ids != after_ids:
        _abort("end_ledger_bucket_mismatch", "end_ledger.buckets")
    for bucket in end.buckets:
        if not bucket.cash.is_finite() or bucket.cash < 0:
            _abort(
                "negative_execution_cash",
                f"end_ledger.{bucket.bucket_id}.cash",
                bucket_id=bucket.bucket_id,
            )
