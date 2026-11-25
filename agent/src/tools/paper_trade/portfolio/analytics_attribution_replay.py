"""Ledger replay and symbol-contribution cluster of the one-day attribution.

Replays conversions and fills against the actual ledgers without ever adjusting
the ending state, then builds the per-symbol market/currency contribution rows.
The computation body is byte-identical to the pre-split ``_attribution`` replay
section.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .analytics_attribution_bridge import _AttributionState, _BridgeResult
from .analytics_common import (
    _Mark,
    _attribution_issue,
    _exact_difference,
    _exact_product,
    _exact_sum,
    _exact_text,
    _execution_notional,
    _mark_reference,
    _position_quantities,
    _price_text,
    _reject,
)
from .models import AnalyticsReconciliationCheck, AnalyticsSymbolContribution


@dataclass(frozen=True, slots=True)
class _ReplayResult:
    """Ending quantities and the per-symbol contribution rows."""

    end_qty: dict[tuple[str, str], int]
    symbol_rows: list[AnalyticsSymbolContribution]
    symbol_by_key: dict[tuple[str, str], AnalyticsSymbolContribution]
    position_total: Decimal


def _attribution_replay(
    state: _AttributionState, bridge: _BridgeResult
) -> _ReplayResult:
    """Replay conversions/fills and build the symbol contribution rows."""
    request = state.request
    conversion_events = state.conversion_events
    fills = state.fills
    opening_ledger = state.opening_ledger
    post_conversion_ledger = state.post_conversion_ledger
    end_ledger = state.end_ledger
    plan = state.plan
    marks = state.marks
    issues = state.issues
    checks = state.checks
    opening_buckets = bridge.opening_buckets
    post_buckets = bridge.post_buckets
    end_buckets = bridge.end_buckets
    planning_marks = bridge.planning_marks
    planning_rates = bridge.planning_rates
    valuation_rates = bridge.valuation_rates
    trade_cash = bridge.trade_cash
    fills_by_key = bridge.fills_by_key
    # Replay conversions and fills against the actual ledgers without ever
    # adjusting the ending state to make the bridge balance.
    conversion_cash = {
        bucket_id: bucket.cash for bucket_id, bucket in opening_buckets.items()
    }
    conversion_ok = True
    for event in conversion_events:
        if (
            event.from_bucket_id not in conversion_cash
            or event.to_bucket_id not in conversion_cash
        ):
            conversion_ok = False
            continue
        conversion_cash[event.from_bucket_id] = _exact_sum(
            (
                conversion_cash[event.from_bucket_id],
                -event.source_amount,
            )
        )
        conversion_cash[event.to_bucket_id] = _exact_sum(
            (
                conversion_cash[event.to_bucket_id],
                event.converted_amount,
            )
        )
    for bucket_id, bucket in post_buckets.items():
        if conversion_cash.get(bucket_id) != bucket.cash:
            conversion_ok = False
            issues.append(
                _attribution_issue(
                    "attribution_conversion_replay_mismatch",
                    f"attribution.conversions.{bucket_id}",
                    "opening cash plus conversions does not equal post-conversion cash",
                    bucket_id=bucket_id,
                )
            )
    checks.append(
        AnalyticsReconciliationCheck(
            name="conversion_replay",
            passed=conversion_ok,
            detail="opening cash plus settled conversions equals the post-conversion ledger",
        )
    )

    fill_cash = {
        bucket_id: bucket.cash for bucket_id, bucket in post_buckets.items()
    }
    fill_qty = _position_quantities(post_conversion_ledger)
    fill_replay_ok = True
    for fill in fills:
        if fill.bucket_id not in fill_cash:
            fill_replay_ok = False
            continue
        exact_notional = _exact_product(Decimal(fill.qty), fill.price)
        notional = _execution_notional(exact_notional)
        delta = (
            _exact_difference(notional, fill.fee)
            if fill.side == "sell"
            else _exact_sum((notional, fill.fee))
        )
        if fill.side == "buy":
            delta = -delta
        fill_cash[fill.bucket_id] = _exact_sum((fill_cash[fill.bucket_id], delta))
        key = (fill.bucket_id, fill.symbol)
        qty_delta = fill.qty if fill.side == "buy" else -fill.qty
        fill_qty[key] = fill_qty.get(key, 0) + qty_delta
    for bucket_id, bucket in end_buckets.items():
        if fill_cash.get(bucket_id) != bucket.cash:
            fill_replay_ok = False
            issues.append(
                _attribution_issue(
                    "attribution_fill_replay_mismatch",
                    f"attribution.fills.{bucket_id}.cash",
                    "post-conversion cash plus fills does not equal ending cash",
                    bucket_id=bucket_id,
                )
            )
    end_qty = _position_quantities(end_ledger)
    for key in sorted(set(fill_qty) | set(end_qty)):
        if fill_qty.get(key, 0) != end_qty.get(key, 0):
            fill_replay_ok = False
            issues.append(
                _attribution_issue(
                    "attribution_fill_replay_mismatch",
                    f"attribution.fills.{key[0]}.{key[1]}.qty",
                    "post-conversion quantities plus fills do not equal ending quantities",
                    bucket_id=key[0],
                )
            )
    checks.append(
        AnalyticsReconciliationCheck(
            name="fill_replay",
            passed=fill_replay_ok,
            detail="post-conversion cash and quantities plus fills equal the ending ledger",
        )
    )

    opening_qty = _position_quantities(opening_ledger)
    bucket_rank = {
        bucket_id: index for index, bucket_id in enumerate(end_buckets)
    }
    keys = sorted(
        set(opening_qty)
        | set(end_qty)
        | {(row.bucket_id, row.symbol) for row in plan.weights},
        key=lambda key: (bucket_rank.get(key[0], len(bucket_rank)), key[0], key[1]),
    )
    symbol_rows: list[AnalyticsSymbolContribution] = []
    symbol_by_key: dict[tuple[str, str], AnalyticsSymbolContribution] = {}
    for bucket_id, symbol in keys:
        bucket = end_buckets.get(bucket_id) or opening_buckets.get(bucket_id)
        if bucket is None:
            issues.append(
                _attribution_issue(
                    "attribution_position_bucket_mismatch",
                    f"attribution.positions.{bucket_id}.{symbol}",
                    "a position bucket is absent from the ending ledger",
                    bucket_id=bucket_id,
                )
            )
            continue
        opening_mark = planning_marks.get(symbol)
        if opening_mark is None:
            _reject(
                "missing_planning_mark",
                f"attribution.planning_marks.{symbol}",
                bucket_id=bucket_id,
                detail="every attributed instrument needs a strict prior planning mark",
            )
        end_mark = marks.get(bucket_id, {}).get(symbol)
        key_fills = fills_by_key.get((bucket_id, symbol), [])
        if end_mark is None:
            if key_fills:
                last_fill = key_fills[-1]
                end_mark = _Mark(
                    price=last_fill.price,
                    price_date=last_fill.trade_date,
                    source="execution_fill",
                    as_of=request.valuation_at,
                )
            else:
                end_mark = opening_mark
        if end_qty.get((bucket_id, symbol), 0) > 0 and end_mark is None:
            _reject(
                "missing_valuation_mark",
                f"attribution.valuation_marks.{bucket_id}.{symbol}",
                bucket_id=bucket_id,
            )
        opening_ref, opening_rate = planning_rates[bucket_id]
        ending_ref, ending_rate = valuation_rates[bucket_id]
        opening_units = opening_qty.get((bucket_id, symbol), 0)
        ending_units = end_qty.get((bucket_id, symbol), 0)
        traded = sum(
            fill.qty if fill.side == "buy" else -fill.qty for fill in key_fills
        )
        opening_local = _exact_product(Decimal(opening_units), opening_mark.price)
        ending_local = _exact_product(Decimal(ending_units), end_mark.price)
        opening_value = _exact_product(opening_local, opening_rate)
        ending_value = _exact_product(ending_local, ending_rate)
        currency_effect = _exact_product(
            opening_local,
            _exact_difference(ending_rate, opening_rate),
        )
        trade_base = trade_cash.get((bucket_id, symbol), Decimal(0))
        market_effect = _exact_sum(
            (
                _exact_difference(ending_value, opening_value),
                -currency_effect,
                trade_base,
            )
        )
        total_effect = _exact_sum((market_effect, currency_effect))
        if ending_units == 0 and opening_units > 0:
            outcome = "closed"
        elif opening_units == 0 and ending_units > 0:
            outcome = "opened"
        elif ending_units > opening_units:
            outcome = "increased"
        elif ending_units < opening_units:
            outcome = "reduced"
        else:
            outcome = "unchanged"
        row = AnalyticsSymbolContribution(
            bucket_id=bucket_id,
            market=bucket.market,
            currency=bucket.currency,
            symbol=symbol,
            opening_qty=opening_units,
            ending_qty=ending_units,
            traded_qty=traded,
            opening_price=_price_text(
                opening_mark.price,
                f"attribution.positions.{bucket_id}.{symbol}.opening_price",
            ),
            ending_price=_price_text(
                end_mark.price,
                f"attribution.positions.{bucket_id}.{symbol}.ending_price",
            ),
            opening_mark=_mark_reference(opening_mark),
            ending_mark=_mark_reference(end_mark),
            opening_fx=opening_ref,
            ending_fx=ending_ref,
            opening_local_value=_exact_text(
                opening_local,
                f"attribution.positions.{bucket_id}.{symbol}.opening_local",
            ),
            ending_local_value=_exact_text(
                ending_local,
                f"attribution.positions.{bucket_id}.{symbol}.ending_local",
            ),
            opening_value_base=_exact_text(
                opening_value,
                f"attribution.positions.{bucket_id}.{symbol}.opening_value",
            ),
            ending_value_base=_exact_text(
                ending_value,
                f"attribution.positions.{bucket_id}.{symbol}.ending_value",
            ),
            trade_cash_base=_exact_text(
                trade_base,
                f"attribution.positions.{bucket_id}.{symbol}.trade_cash",
            ),
            market_contribution_base=_exact_text(
                market_effect,
                f"attribution.positions.{bucket_id}.{symbol}.market_contribution",
            ),
            currency_contribution_base=_exact_text(
                currency_effect,
                f"attribution.positions.{bucket_id}.{symbol}.currency_contribution",
            ),
            total_contribution_base=_exact_text(
                total_effect,
                f"attribution.positions.{bucket_id}.{symbol}.total_contribution",
            ),
            outcome=outcome,
        )
        symbol_rows.append(row)
        symbol_by_key[(bucket_id, symbol)] = row

    position_total = _exact_sum(
        Decimal(row.total_contribution_base) for row in symbol_rows
    )
    return _ReplayResult(
        end_qty=end_qty,
        symbol_rows=symbol_rows,
        symbol_by_key=symbol_by_key,
        position_total=position_total,
    )
