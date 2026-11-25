"""Attribution state carrier and the opening bridge / event-row cluster.

Holds the shared attribution inputs plus the issue/check accumulators, then
builds the planning and valuation bridges, bucket FX references, cash FX rows,
conversion effects, fee effects, execution rounding rows and the execution
mark agreement checks. The computation body is byte-identical to the
pre-split ``_attribution`` bridge section.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from .analytics_common import (
    _Mark,
    _attribution_issue,
    _exact_difference,
    _exact_product,
    _exact_sum,
    _exact_text,
    _execution_notional,
    _fx_reference,
    _planning_mark_meta,
    _price_text,
    _rate_text,
)
from .data import PreparedPortfolioData, TargetBarValuation
from .fx import FxConversionEvent, FxRateBook
from .ledger import BucketLedger, PortfolioLedger, value_ledger
from .models import (
    AnalyticsCashFxEffect,
    AnalyticsCashRow,
    AnalyticsConversionEffect,
    AnalyticsExecutionRounding,
    AnalyticsFeeEffect,
    AnalyticsFxReference,
    AnalyticsPositionRow,
    AnalyticsReconciliationCheck,
    PortfolioIssue,
    PortfolioRequest,
)
from .numeric import MONEY_SPEC, canonical_decimal, parse_price
from .orchestrator import ExecutionCancellation, ExecutionFill, ExecutionRejection
from .order_plan import OrderPlan


@dataclass
class _AttributionState:
    """Declared attribution inputs plus the shared issue/check accumulators."""

    request: PortfolioRequest
    prepared: PreparedPortfolioData
    opening_ledger: PortfolioLedger
    post_conversion_ledger: PortfolioLedger
    end_ledger: PortfolioLedger
    conversion_events: Sequence[FxConversionEvent]
    fills: Sequence[ExecutionFill]
    rejected_orders: Sequence[ExecutionRejection]
    canceled_orders: Sequence[ExecutionCancellation]
    plan: OrderPlan
    cash_rows: Sequence[AnalyticsCashRow]
    position_rows: Sequence[AnalyticsPositionRow]
    valuation_rounding: Decimal
    nav_base: Decimal
    exact_nav_base: Decimal
    book: FxRateBook
    marks: dict[str, dict[str, _Mark]]
    issues: list[PortfolioIssue] = field(default_factory=list)
    checks: list[AnalyticsReconciliationCheck] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _BridgeResult:
    """Bridges, bucket maps, FX references and the cash/conversion/fee rows."""

    planning_marks: dict[str, _Mark]
    start_nav: Decimal
    start_exact: Decimal
    planning_nav: Decimal
    planning_exact: Decimal
    end_buckets: dict[str, BucketLedger]
    opening_buckets: dict[str, BucketLedger]
    post_buckets: dict[str, BucketLedger]
    planning_rates: dict[str, tuple[AnalyticsFxReference, Decimal]]
    valuation_rates: dict[str, tuple[AnalyticsFxReference, Decimal]]
    cash_fx_rows: list[AnalyticsCashFxEffect]
    cash_fx_total: Decimal
    conversion_effects: list[AnalyticsConversionEffect]
    conversion_total: Decimal
    fee_effects: list[AnalyticsFeeEffect]
    rounding_rows: list[AnalyticsExecutionRounding]
    fee_total: Decimal
    expected_rounding: Decimal
    trade_cash: dict[tuple[str, str], Decimal]
    fills_by_key: dict[tuple[str, str], list[ExecutionFill]]


def _attribution_bridge(state: _AttributionState) -> _BridgeResult:
    """Build the planning bridges and the declared cash/conversion/fee rows."""
    request = state.request
    prepared = state.prepared
    opening_ledger = state.opening_ledger
    post_conversion_ledger = state.post_conversion_ledger
    end_ledger = state.end_ledger
    conversion_events = state.conversion_events
    fills = state.fills
    book = state.book
    issues = state.issues
    base_currency = request.base_currency
    planning_marks = _planning_mark_meta(prepared)
    planning_prices = {symbol: mark.price for symbol, mark in planning_marks.items()}
    planning_book = FxRateBook.from_snapshots(
        request.fx_snapshots,
        at=request.planning_at,
    )
    start_bridge = value_ledger(
        opening_ledger,
        planning_prices,
        planning_book,
        base_currency=base_currency,
        path="attribution.planning_marks",
    )
    planning_bridge = value_ledger(
        post_conversion_ledger,
        planning_prices,
        planning_book,
        base_currency=base_currency,
        path="attribution.planning_marks",
    )
    start_nav = start_bridge.total.reported_base
    start_exact = start_bridge.total.exact_base
    planning_nav = planning_bridge.total.reported_base
    planning_exact = planning_bridge.total.exact_base

    end_buckets = {bucket.bucket_id: bucket for bucket in end_ledger.buckets}
    opening_buckets = {bucket.bucket_id: bucket for bucket in opening_ledger.buckets}
    post_buckets = {
        bucket.bucket_id: bucket for bucket in post_conversion_ledger.buckets
    }
    if set(opening_buckets) != set(end_buckets) or set(post_buckets) != set(end_buckets):
        issues.append(
            _attribution_issue(
                "attribution_bucket_set_mismatch",
                "attribution.buckets",
                "opening, post-conversion and ending ledgers must name the same buckets",
            )
        )

    planning_rates: dict[str, tuple[AnalyticsFxReference, Decimal]] = {}
    valuation_rates: dict[str, tuple[AnalyticsFxReference, Decimal]] = {}
    for bucket_id, bucket in end_buckets.items():
        planning_rates[bucket_id] = _fx_reference(
            bucket.currency,
            base_currency,
            planning_book,
            request.planning_at,
            path=f"attribution.cash_fx.{bucket_id}.opening_rate",
        )
        valuation_rates[bucket_id] = _fx_reference(
            bucket.currency,
            base_currency,
            book,
            request.valuation_at,
            path=f"attribution.cash_fx.{bucket_id}.ending_rate",
        )
    for bucket_id, bucket in opening_buckets.items():
        end_bucket = end_buckets.get(bucket_id)
        if end_bucket is not None and (
            end_bucket.currency != bucket.currency
            or end_bucket.market != bucket.market
        ):
            issues.append(
                _attribution_issue(
                    "attribution_bucket_identity_mismatch",
                    f"attribution.buckets.{bucket_id}",
                    "a bucket's market and currency must be stable across the day",
                    bucket_id=bucket_id,
                )
            )

    # Cash FX is valued on opening cash only; conversion and fill cash already
    # exist at the valuation instant and are valued there exactly once.
    cash_fx_rows: list[AnalyticsCashFxEffect] = []
    cash_fx_total = Decimal(0)
    for bucket_id in sorted(end_buckets):
        bucket = end_buckets[bucket_id]
        opening = opening_buckets.get(bucket_id)
        opening_cash = opening.cash if opening is not None else Decimal(0)
        opening_ref, opening_rate = planning_rates[bucket_id]
        ending_ref, ending_rate = valuation_rates[bucket_id]
        effect = _exact_product(
            opening_cash,
            _exact_difference(ending_rate, opening_rate),
        )
        cash_fx_total = _exact_sum((cash_fx_total, effect))
        cash_fx_rows.append(
            AnalyticsCashFxEffect(
                bucket_id=bucket_id,
                market=bucket.market,
                currency=bucket.currency,
                opening_cash=canonical_decimal(
                    opening_cash,
                    MONEY_SPEC,
                    f"attribution.cash_fx.{bucket_id}.opening_cash",
                ),
                ending_cash=canonical_decimal(
                    bucket.cash,
                    MONEY_SPEC,
                    f"attribution.cash_fx.{bucket_id}.ending_cash",
                ),
                opening_fx=opening_ref,
                ending_fx=ending_ref,
                cash_fx_effect_base=_exact_text(
                    effect,
                    f"attribution.cash_fx.{bucket_id}.effect",
                ),
            )
        )

    conversion_effects: list[AnalyticsConversionEffect] = []
    conversion_total = Decimal(0)
    for index, event in enumerate(conversion_events):
        path = f"attribution.conversions[{index}]"
        source_bucket = end_buckets.get(event.from_bucket_id)
        target_bucket = end_buckets.get(event.to_bucket_id)
        if source_bucket is None or target_bucket is None:
            issues.append(
                _attribution_issue(
                    "attribution_conversion_bucket_mismatch",
                    path,
                    "a conversion must name two declared buckets",
                )
            )
        else:
            if (
                source_bucket.currency != event.from_currency
                or target_bucket.currency != event.to_currency
            ):
                issues.append(
                    _attribution_issue(
                        "attribution_conversion_bucket_mismatch",
                        path,
                        "the event currency disagrees with its bucket currency",
                    )
                )
        source_ref, source_rate = _fx_reference(
            event.from_currency,
            base_currency,
            book,
            request.valuation_at,
            path=f"{path}.source_rate",
        )
        target_ref, target_rate = _fx_reference(
            event.to_currency,
            base_currency,
            book,
            request.valuation_at,
            path=f"{path}.target_rate",
        )
        expected_exact = _exact_product(event.source_amount, event.rate)
        expected_residual = _exact_difference(
            event.exact_converted,
            event.converted_amount,
        )
        if event.exact_converted != expected_exact:
            issues.append(
                _attribution_issue(
                    "attribution_conversion_math_mismatch",
                    f"{path}.exact_converted",
                    "exact_converted must equal source_amount * rate",
                )
            )
        if event.residual != expected_residual:
            issues.append(
                _attribution_issue(
                    "attribution_conversion_math_mismatch",
                    f"{path}.rounding_residual_local",
                    "the conversion residual must tie exact to converted",
                )
            )
        source_effect = _exact_product(
            -event.source_amount,
            source_rate,
        )
        target_effect = _exact_product(event.converted_amount, target_rate)
        effect = _exact_sum((source_effect, target_effect))
        conversion_total = _exact_sum((conversion_total, effect))
        conversion_effects.append(
            AnalyticsConversionEffect(
                rate_id=event.rate_id,
                from_bucket_id=event.from_bucket_id,
                to_bucket_id=event.to_bucket_id,
                from_currency=event.from_currency,
                to_currency=event.to_currency,
                source_amount=canonical_decimal(
                    event.source_amount,
                    MONEY_SPEC,
                    f"{path}.source_amount",
                ),
                rate=_rate_text(event.rate, f"{path}.rate"),
                exact_converted=_exact_text(
                    event.exact_converted,
                    f"{path}.exact_converted",
                ),
                converted_amount=canonical_decimal(
                    event.converted_amount,
                    MONEY_SPEC,
                    f"{path}.converted_amount",
                ),
                rounding_residual_local=_exact_text(
                    event.residual,
                    f"{path}.rounding_residual_local",
                ),
                source_fx=source_ref,
                target_fx=target_ref,
                source_effect_base=_exact_text(
                    source_effect,
                    f"{path}.source_effect_base",
                ),
                target_effect_base=_exact_text(
                    target_effect,
                    f"{path}.target_effect_base",
                ),
                conversion_effect_base=_exact_text(
                    effect,
                    f"{path}.conversion_effect_base",
                ),
                rounding_loss_base=_exact_text(
                    -_exact_product(expected_residual, target_rate),
                    f"{path}.rounding_loss_base",
                ),
            )
        )

    fee_effects: list[AnalyticsFeeEffect] = []
    rounding_rows: list[AnalyticsExecutionRounding] = []
    fee_total = Decimal(0)
    expected_rounding = Decimal(0)
    trade_cash: dict[tuple[str, str], Decimal] = {}
    fills_by_key: dict[tuple[str, str], list[ExecutionFill]] = {}
    for fill in fills:
        fills_by_key.setdefault((fill.bucket_id, fill.symbol), []).append(fill)

    for index, fill in enumerate(fills):
        path = f"attribution.fills[{index}]"
        rate_pair = valuation_rates.get(fill.bucket_id)
        bucket = end_buckets.get(fill.bucket_id)
        if rate_pair is None or bucket is None:
            issues.append(
                _attribution_issue(
                    "attribution_fill_bucket_mismatch",
                    path,
                    "a fill must name a declared ending bucket",
                    bucket_id=fill.bucket_id,
                )
            )
            ref, rate = _fx_reference(
                fill.currency,
                base_currency,
                book,
                request.valuation_at,
                path=f"{path}.fx",
            )
        else:
            ref, rate = rate_pair
            if bucket.currency != fill.currency:
                issues.append(
                    _attribution_issue(
                        "attribution_fill_currency_mismatch",
                        path,
                        "a fill's currency must equal its bucket currency",
                        bucket_id=fill.bucket_id,
                    )
                )
        exact_notional = _exact_product(Decimal(fill.qty), fill.price)
        notional = _execution_notional(exact_notional)
        rounding = _exact_difference(exact_notional, notional)
        signed_rounding = rounding if fill.side == "buy" else -rounding
        rounding_base = _exact_product(signed_rounding, rate)
        expected_rounding = _exact_sum((expected_rounding, rounding_base))
        fee_effect = _exact_product(-fill.fee, rate)
        fee_total = _exact_sum((fee_total, fee_effect))
        fee_effects.append(
            AnalyticsFeeEffect(
                plan_order_id=fill.plan_order_id,
                bucket_id=fill.bucket_id,
                symbol=fill.symbol,
                side=fill.side,
                qty=fill.qty,
                execution_price=_price_text(fill.price, f"{path}.price"),
                fee_local=canonical_decimal(
                    fill.fee,
                    MONEY_SPEC,
                    f"{path}.fee_local",
                ),
                fx=ref,
                fee_effect_base=_exact_text(fee_effect, f"{path}.fee_effect_base"),
            )
        )
        rounding_rows.append(
            AnalyticsExecutionRounding(
                plan_order_id=fill.plan_order_id,
                bucket_id=fill.bucket_id,
                symbol=fill.symbol,
                side=fill.side,
                qty=fill.qty,
                execution_price=_price_text(fill.price, f"{path}.price"),
                exact_notional_local=_exact_text(
                    exact_notional,
                    f"{path}.exact_notional",
                ),
                notional_local=canonical_decimal(
                    notional,
                    MONEY_SPEC,
                    f"{path}.notional_local",
                ),
                rounding_local=_exact_text(rounding, f"{path}.rounding_local"),
                fx=ref,
                rounding_effect_base=_exact_text(
                    rounding_base,
                    f"{path}.rounding_effect_base",
                ),
            )
        )
        key = (fill.bucket_id, fill.symbol)
        signed_notional = (
            -exact_notional if fill.side == "buy" else exact_notional
        )
        trade_cash[key] = _exact_sum(
            (trade_cash.get(key, Decimal(0)), _exact_product(signed_notional, rate))
        )

    # Execution prices and valuation marks must agree with the prepared
    # target-day snapshot. A changed mark or fill cannot pass unnoticed.
    execution_closes: dict[str, dict[str, Decimal]] = {}
    for bucket in prepared.buckets:
        if bucket.execution is None:
            continue
        execution_closes[bucket.bucket_id] = {
            bar.symbol: parse_price(
                bar.close,
                f"attribution.execution_marks.{bucket.bucket_id}.{bar.symbol}",
            )
            for bar in bucket.execution.bars
        }
        if isinstance(bucket.valuation, TargetBarValuation):
            execution_map = execution_closes[bucket.bucket_id]
            for bar in bucket.valuation.snapshot.bars:
                close = execution_map.get(bar.symbol)
                if close is None:
                    continue
                valuation_close = parse_price(
                    bar.close,
                    f"attribution.valuation_marks.{bucket.bucket_id}.{bar.symbol}",
                )
                if close != valuation_close:
                    issues.append(
                        _attribution_issue(
                            "attribution_valuation_execution_mark_mismatch",
                            f"attribution.valuation_marks.{bucket.bucket_id}.{bar.symbol}",
                            "the valuation close disagrees with the execution snapshot",
                            bucket_id=bucket.bucket_id,
                        )
                    )
    for index, fill in enumerate(fills):
        closes = execution_closes.get(fill.bucket_id)
        if closes is None:
            continue
        close = closes.get(fill.symbol)
        if close is None or close != fill.price:
            issues.append(
                _attribution_issue(
                    "attribution_fill_price_mark_mismatch",
                    f"attribution.fills[{index}].price",
                    "the fill price disagrees with the prepared execution close",
                    bucket_id=fill.bucket_id,
                )
            )
    return _BridgeResult(
        planning_marks=planning_marks,
        start_nav=start_nav,
        start_exact=start_exact,
        planning_nav=planning_nav,
        planning_exact=planning_exact,
        end_buckets=end_buckets,
        opening_buckets=opening_buckets,
        post_buckets=post_buckets,
        planning_rates=planning_rates,
        valuation_rates=valuation_rates,
        cash_fx_rows=cash_fx_rows,
        cash_fx_total=cash_fx_total,
        conversion_effects=conversion_effects,
        conversion_total=conversion_total,
        fee_effects=fee_effects,
        rounding_rows=rounding_rows,
        fee_total=fee_total,
        expected_rounding=expected_rounding,
        trade_cash=trade_cash,
        fills_by_key=fills_by_key,
    )
