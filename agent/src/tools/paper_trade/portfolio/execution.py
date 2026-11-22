"""Decimal reconstruct-and-check execution adapter for pt-v2.0 portfolios.

The legacy single-day ``all_or_none`` matcher is used only as an ordered
producer of fill/reject/cancel terminal rows. Portfolio accounting never reads
its float ``Fill`` values as money, its ``end_state`` or its ``NavPoint`` rows:
every fill quantity comes from the source integer plan order, every execution
price from the prepared target-day close snapshot, and every fee from the same
:class:`~..rules.MarketRules` used by the plan. The legacy float fill is a
consistency guard only; any disagreement, nonfinite value, duplicate/missing
terminal outcome, nonpositive sale proceeds, negative fee or negative cash
aborts before an :class:`~.orchestrator.ExecutionOutcome` can be returned.

Only cash and position movements leave this module. FX conversions settle
before matching (task 11), volume-share/5m and strategy execution are out of
scope, and each planned order gets exactly one terminal outcome.

The implementation lives in focused sibling modules (``execution_common``,
``execution_validation``, ``execution_legacy_match``, ``execution_rows``,
``execution_outcome``, ``execution_adapter``); this facade keeps every historic
``execution.<symbol>`` binding path importable and patchable unchanged.
"""

from __future__ import annotations

from types import FunctionType

from .. import engine as engine
from . import execution_adapter, execution_legacy_match, execution_outcome
from .execution_adapter import DecimalExecutionAdapter
from .execution_common import (
    _EXACT_PRECISION as _EXACT_PRECISION,
    ExecutionAdapterError,
    _PreparedDayCalendar as _PreparedDayCalendar,
    _abort as _abort,
    _bucket_map as _bucket_map,
    _effective_models as _effective_models,
    _exact_product as _exact_product,
    _fee_for as _fee_for,
    _finite_decimal as _finite_decimal,
    _legacy_decimal as _legacy_decimal,
    _market_rules as _market_rules,
    _price_decimal as _price_decimal,
)
from .execution_legacy_match import (
    _bucket_day_calendar as _bucket_day_calendar,
    _legacy_account as _legacy_account,
    _legacy_orders as _legacy_orders,
    _run_legacy_match as _run_legacy_match,
)
from .execution_outcome import (
    _bucket_outcome as _bucket_outcome,
    _validate_replayed_ledger as _validate_replayed_ledger,
)
from .execution_rows import (
    _check_fee as _check_fee,
    _fill_row as _fill_row,
    _nonfill_row as _nonfill_row,
    _post_buy_avg_cost as _post_buy_avg_cost,
    _terminal_rows as _terminal_rows,
)
from .execution_validation import (
    _preflight_for_bucket as _preflight_for_bucket,
    _target_closes as _target_closes,
    _validate_plan as _validate_plan,
)

__all__ = ["DecimalExecutionAdapter", "ExecutionAdapterError"]


def _facade_bound(fn):
    """Rebind one moved function to this facade's live globals.

    Historic seams patch ``execution._fee_for`` (fee gates) and
    ``execution.engine`` (the legacy engine reference). The moved callers
    ``_bucket_outcome`` and ``_run_legacy_match`` must keep resolving those
    names through this module's dict at call time, exactly as they did
    before the split, while their source bodies stay verbatim in their
    focused modules.
    """
    rebound = FunctionType(
        fn.__code__, globals(), fn.__name__, fn.__defaults__, fn.__closure__
    )
    rebound.__kwdefaults__ = fn.__kwdefaults__
    rebound.__doc__ = fn.__doc__
    rebound.__qualname__ = fn.__qualname__
    rebound.__annotations__ = fn.__annotations__
    return rebound


_run_legacy_match = _facade_bound(_run_legacy_match)
execution_legacy_match._run_legacy_match = _run_legacy_match
execution_outcome._run_legacy_match = _run_legacy_match
_bucket_outcome = _facade_bound(_bucket_outcome)
execution_outcome._bucket_outcome = _bucket_outcome
execution_adapter._bucket_outcome = _bucket_outcome
