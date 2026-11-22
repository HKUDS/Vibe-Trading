"""Deterministic, auditable pt-v2.0 order plans.

This module is the boundary between the pure target-weight planner and the
matching/execution adapter. It consumes typed :class:`TargetWeightAllocation`
lines or caller-declared explicit orders and emits canonical whole-lot orders:
buckets are ordered canonically, sells precede buys inside every bucket, every
line has a stable ``plan_order_id``, and every bucket keeps its own planned cash
and lot residue. It never matches, fills, fetches data or promises exact
post-trade weights: ``planned_weight`` is only an estimate at planning marks and
``realized_weight`` stays ``None`` until a later execution layer reconciles it.

The implementation lives in focused sibling modules (``order_plan_models``,
``order_plan_primitives``, ``order_plan_target``, ``order_plan_explicit``,
``order_plan_builders``, ``order_plan_json``); this facade keeps every historic
``order_plan.<symbol>`` binding path importable and patchable unchanged.
"""

from __future__ import annotations

from .order_plan_builders import (
    build_explicit_order_plan,
    build_target_weight_order_plan,
)
from .order_plan_explicit import (
    _explicit_rows as _explicit_rows,
    _explicit_weights as _explicit_weights,
    _validate_explicit_header as _validate_explicit_header,
    _validate_marks as _validate_marks,
)
from .order_plan_json import (
    _base_price_text as _base_price_text,
    _fx_text as _fx_text,
    _gap_text as _gap_text,
    _money_text as _money_text,
    _price_text as _price_text,
    _weight_text as _weight_text,
    order_plan_to_json,
)
from .order_plan_models import (
    ORDER_PLAN_VERSION,
    REALIZED_WEIGHT_STATUS as REALIZED_WEIGHT_STATUS,
    WEIGHT_BASIS as WEIGHT_BASIS,
    BucketCashPlan,
    OrderPlan,
    PlanMode as PlanMode,
    PlannedOrder,
    Side as Side,
    SkippedPlanLine,
    WeightReconciliation,
    _BucketSpec as _BucketSpec,
    _Decision as _Decision,
    _ExplicitRow as _ExplicitRow,
)
from .order_plan_primitives import (
    _BASE_PRICE_SPEC as _BASE_PRICE_SPEC,
    _CANONICAL_CURRENCIES as _CANONICAL_CURRENCIES,
    _EXACT_PRECISION as _EXACT_PRECISION,
    _GAP_SPEC as _GAP_SPEC,
    _MARKET_BY_CURRENCY as _MARKET_BY_CURRENCY,
    _MARKET_ORDER as _MARKET_ORDER,
    _WEIGHT_QUANTUM as _WEIGHT_QUANTUM,
    _bucket_key as _bucket_key,
    _exact_product as _exact_product,
    _fee_models as _fee_models,
    _finite_decimal as _finite_decimal,
    _generated_id as _generated_id,
    _ledger_buckets as _ledger_buckets,
    _lot_size as _lot_size,
    _lot_table as _lot_table,
    _mark_price as _mark_price,
    _market_rules as _market_rules,
    _money as _money,
    _nonnegative_decimal as _nonnegative_decimal,
    _nonnegative_quantity as _nonnegative_quantity,
    _order_key as _order_key,
    _positive_decimal as _positive_decimal,
    _rate as _rate,
    _ratio as _ratio,
    _reject as _reject,
    _side as _side,
    _target_buckets as _target_buckets,
    _validate_allocation as _validate_allocation,
    _validate_identity as _validate_identity,
    _weight as _weight,
)
from .order_plan_target import (
    _cash_plans as _cash_plans,
    _lot_warnings as _lot_warnings,
    _make_order as _make_order,
    _target_decisions as _target_decisions,
    _target_weights as _target_weights,
    _validate_target_lines as _validate_target_lines,
)

__all__ = [
    "ORDER_PLAN_VERSION",
    "BucketCashPlan",
    "OrderPlan",
    "PlannedOrder",
    "SkippedPlanLine",
    "WeightReconciliation",
    "build_explicit_order_plan",
    "build_target_weight_order_plan",
    "order_plan_to_json",
]
