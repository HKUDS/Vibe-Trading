"""Independent replay of one pt-v2.0 portfolio step document.

The caller supplies the opening ``portfolio_state`` (the same object accepted by
the step request) and the returned success document. This module reconstructs
the ledger from the document's own opening buckets, caller conversions, order
plan and fills with Decimal arithmetic, then re-derives the NAV bridge,
exposure roll-ups and one-day attribution identities. It never refetches marks
or FX and never recomputes a hash whose raw layers are absent; those limits are
published in ``not_verified``.

Only the stable ``paper_trade_reconcile`` envelope leaves this module. A field
disagreement is an issue, not an exception; malformed input raises ``ValueError``
so the existing tool wrapper can emit its stable JSON error envelope.
"""

from __future__ import annotations

import re
from collections import Counter
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any

from pydantic import ValidationError

from ..rules import MarketRules, quantize_money
from .analytics import reconcile_attribution
from .ledger import PortfolioLedger
from .models import (
    ExplicitOrdersPlan,
    PortfolioResult,
    PortfolioState,
    TargetWeightsPlan,
)
from .numeric import parse_effective_fee_model
from .schema import PortfolioRequestError

__all__ = ["reconcile_portfolio_document"]

_CENT = Decimal("0.01")
_WEIGHT_QUANTUM = Decimal("0.000000000001")
_ZERO = Decimal(0)
_EXACT_PRECISION = 60
_GENERATED_ORDER_ID = re.compile(r"^pt2-(\d{8})-(.+)-(buy|sell)-(.+)$")


def _exact(value: Decimal, other: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = _EXACT_PRECISION
        return value * other


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = _EXACT_PRECISION
        return numerator / denominator


def _money_even(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_EVEN)


def _weight(value: Decimal) -> Decimal:
    if value == 0:
        return Decimal(0)
    return value.quantize(_WEIGHT_QUANTUM, rounding=ROUND_HALF_EVEN)


def _text(value: Decimal) -> str:
    """Render an exact Decimal without exponent notation or negative zero."""
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _money_text(value: Decimal) -> str:
    return format(_money_even(value), ".2f")


def _issue(
    issues: list[dict[str, Any]],
    code: str,
    path: str,
    expected: Any,
    actual: Any,
) -> None:
    issues.append(
        {"code": code, "path": path, "expected": expected, "actual": actual}
    )


def _parse_result(result: Any) -> PortfolioResult:
    try:
        return PortfolioResult.model_validate(result)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ())) or "$"
        message = str(first.get("msg", "invalid document"))
        raise ValueError(
            "result must be a successful pt-v2.0 portfolio document "
            f"({location}: {message})"
        ) from exc


def _parse_account_state(account_state: Any) -> PortfolioState:
    if not isinstance(account_state, dict) or "buckets" not in account_state:
        raise ValueError(
            "account_state must be a pt-v2.0 portfolio_state object with buckets"
        )
    try:
        return PortfolioState.model_validate(account_state)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ())) or "$"
        message = str(first.get("msg", "invalid state"))
        raise ValueError(
            "account_state must be a pt-v2.0 portfolio_state object "
            f"({location}: {message})"
        ) from exc


def _fee_rules(
    state: PortfolioState,
) -> tuple[dict[str, MarketRules], dict[str, Any]]:
    rules: dict[str, MarketRules] = {}
    buckets: dict[str, Any] = {}
    for bucket in state.buckets:
        if bucket.bucket_id in buckets:
            continue
        buckets[bucket.bucket_id] = bucket
        try:
            model = parse_effective_fee_model(bucket)
            rules[bucket.bucket_id] = MarketRules(
                model.market, dict(model.parameters)
            )
        except (ArithmeticError, TypeError, ValueError, PortfolioRequestError) as exc:
            raise ValueError(
                "result.opening_portfolio fee model is invalid for bucket "
                f"{bucket.bucket_id}: {exc}"
            ) from exc
    return rules, buckets


def _state_maps(state: PortfolioState) -> tuple[dict[str, Decimal], dict[tuple[str, str], dict[str, Any]]]:
    cash: dict[str, Decimal] = {}
    positions: dict[tuple[str, str], dict[str, Any]] = {}
    for bucket in state.buckets:
        cash[bucket.bucket_id] = Decimal(bucket.cash)
        for position in bucket.positions:
            positions[(bucket.bucket_id, position.symbol)] = {
                "qty": position.qty,
                "avg_cost": Decimal(position.avg_cost),
                "currency": position.currency,
            }
    return cash, positions


def _check_duplicate_buckets(
    issues: list[dict[str, Any]], state: PortfolioState, path: str
) -> None:
    seen: set[str] = set()
    for index, bucket in enumerate(state.buckets):
        if bucket.bucket_id in seen:
            _issue(
                issues,
                "duplicate_bucket",
                f"{path}[{index}].bucket_id",
                "one row per bucket",
                bucket.bucket_id,
            )
        seen.add(bucket.bucket_id)


def _compare_states(
    issues: list[dict[str, Any]],
    expected: PortfolioState,
    actual: PortfolioState,
    path: str,
) -> None:
    """Report every field where the caller ledger disagrees with the document."""
    expected_cash, expected_positions = _state_maps(expected)
    actual_cash, actual_positions = _state_maps(actual)
    expected_buckets = {bucket.bucket_id: bucket for bucket in expected.buckets}
    actual_buckets = {bucket.bucket_id: bucket for bucket in actual.buckets}
    for bucket_id in sorted(set(expected_cash) | set(actual_cash)):
        bucket_path = f"{path}.buckets.{bucket_id}"
        if bucket_id not in actual_cash:
            _issue(issues, "opening_portfolio_mismatch", bucket_path, "present", None)
            continue
        if bucket_id not in expected_cash:
            _issue(
                issues,
                "opening_portfolio_mismatch",
                bucket_path,
                None,
                "unexpected bucket",
            )
            continue
        expected_bucket = expected_buckets[bucket_id]
        actual_bucket = actual_buckets[bucket_id]
        if expected_bucket.market != actual_bucket.market:
            _issue(
                issues,
                "opening_portfolio_mismatch",
                f"{bucket_path}.market",
                expected_bucket.market,
                actual_bucket.market,
            )
        if expected_bucket.currency != actual_bucket.currency:
            _issue(
                issues,
                "opening_portfolio_mismatch",
                f"{bucket_path}.currency",
                expected_bucket.currency,
                actual_bucket.currency,
            )
        if expected_bucket.fee_model != actual_bucket.fee_model:
            _issue(
                issues,
                "opening_portfolio_mismatch",
                f"{bucket_path}.fee_model",
                "caller-declared fee model",
                "different fee model",
            )
        if expected_cash[bucket_id] != actual_cash[bucket_id]:
            _issue(
                issues,
                "opening_portfolio_mismatch",
                f"{bucket_path}.cash",
                _money_text(expected_cash[bucket_id]),
                _money_text(actual_cash[bucket_id]),
            )
    for key in sorted(set(expected_positions) | set(actual_positions)):
        bucket_id, symbol = key
        position_path = f"{path}.buckets.{bucket_id}.positions[{symbol}]"
        expected_position = expected_positions.get(key)
        actual_position = actual_positions.get(key)
        if expected_position is None:
            _issue(
                issues,
                "opening_portfolio_mismatch",
                position_path,
                None,
                "unexpected position",
            )
            continue
        if actual_position is None:
            _issue(
                issues,
                "opening_portfolio_mismatch",
                position_path,
                expected_position["qty"],
                None,
            )
            continue
        if expected_position["qty"] != actual_position["qty"]:
            _issue(
                issues,
                "opening_portfolio_mismatch",
                f"{position_path}.qty",
                expected_position["qty"],
                actual_position["qty"],
            )
        if expected_position["avg_cost"] != actual_position["avg_cost"]:
            _issue(
                issues,
                "opening_portfolio_mismatch",
                f"{position_path}.avg_cost",
                _money_text(expected_position["avg_cost"]),
                _money_text(actual_position["avg_cost"]),
            )
        if expected_position["currency"] != actual_position["currency"]:
            _issue(
                issues,
                "opening_portfolio_mismatch",
                f"{position_path}.currency",
                expected_position["currency"],
                actual_position["currency"],
            )


def _apply_conversions(
    issues: list[dict[str, Any]],
    document: PortfolioResult,
    buckets: dict[str, Any],
    cash: dict[str, Decimal],
    not_verified: list[str],
) -> tuple[bool, set[str]]:
    """Replay pre-fill conversions from the declared analytics rows.

    Returns whether the conversion arithmetic could be independently replayed
    and which buckets' cash stays unverified because their conversion could not
    be replayed. A conversion without a published rate or a conversion that
    fails its own replay leaves only its declared buckets unverified rather
    than silently assuming every converted bucket correct.
    """
    conversions = list(document.conversions)
    if not conversions:
        return True, set()
    conversion_buckets = {
        bucket_id
        for conversion in conversions
        for bucket_id in (conversion.from_bucket_id, conversion.to_bucket_id)
    }
    unverified_buckets: set[str] = set()
    analytics = document.analytics
    if analytics is None:
        not_verified.append(
            "fx conversion rates are absent without analytics; post-conversion "
            "cash and affected end-cash rows were not replayed."
        )
        return False, conversion_buckets
    rows = list(analytics.conversion_rows)
    if len(rows) != len(conversions):
        _issue(
            issues,
            "conversion_mismatch",
            "conversions",
            len(conversions),
            len(rows),
        )
    available = dict(cash)
    for index, conversion in enumerate(conversions):
        path = f"conversions[{index}]"
        if index >= len(rows):
            unverified_buckets.update(
                (conversion.from_bucket_id, conversion.to_bucket_id)
            )
            continue
        row = rows[index]
        if (
            conversion.rate_id != row.rate_id
            or conversion.from_bucket_id != row.from_bucket_id
            or conversion.to_bucket_id != row.to_bucket_id
            or Decimal(conversion.amount) != Decimal(row.source_amount)
        ):
            _issue(
                issues,
                "conversion_mismatch",
                path,
                {
                    "rate_id": conversion.rate_id,
                    "from_bucket_id": conversion.from_bucket_id,
                    "to_bucket_id": conversion.to_bucket_id,
                    "amount": conversion.amount,
                },
                {
                    "rate_id": row.rate_id,
                    "from_bucket_id": row.from_bucket_id,
                    "to_bucket_id": row.to_bucket_id,
                    "amount": row.source_amount,
                },
            )
        source_bucket = buckets.get(conversion.from_bucket_id)
        target_bucket = buckets.get(conversion.to_bucket_id)
        if source_bucket is None or target_bucket is None:
            _issue(
                issues,
                "conversion_bucket_mismatch",
                path,
                "declared buckets",
                {
                    "from": conversion.from_bucket_id,
                    "to": conversion.to_bucket_id,
                },
            )
            continue
        if (
            source_bucket.currency != row.from_currency
            or target_bucket.currency != row.to_currency
        ):
            _issue(
                issues,
                "conversion_currency_mismatch",
                path,
                {
                    "from": source_bucket.currency,
                    "to": target_bucket.currency,
                },
                {"from": row.from_currency, "to": row.to_currency},
            )
        source = Decimal(row.source_amount)
        rate = Decimal(row.rate)
        if rate <= 0:
            _issue(
                issues,
                "conversion_arithmetic_mismatch",
                f"{path}.rate",
                "> 0",
                row.rate,
            )
            continue
        exact = _exact(source, rate)
        expected_converted = _money_even(exact)
        expected_residual = exact - expected_converted
        declared_exact = Decimal(row.exact_converted)
        declared_converted = Decimal(row.converted_amount)
        declared_residual = Decimal(row.rounding_residual_local)
        if declared_exact != exact:
            _issue(
                issues,
                "conversion_arithmetic_mismatch",
                f"{path}.exact_converted",
                _text(exact),
                _text(declared_exact),
            )
        if declared_converted != expected_converted:
            _issue(
                issues,
                "conversion_arithmetic_mismatch",
                f"{path}.converted_amount",
                _money_text(expected_converted),
                _money_text(declared_converted),
            )
        if declared_residual != expected_residual:
            _issue(
                issues,
                "conversion_arithmetic_mismatch",
                f"{path}.rounding_residual_local",
                _text(expected_residual),
                _text(declared_residual),
            )
        expected_residual_base = _exact(
            expected_residual, Decimal(row.valuation_fx.rate)
        )
        if Decimal(row.rounding_residual_base) != expected_residual_base:
            _issue(
                issues,
                "conversion_arithmetic_mismatch",
                f"{path}.rounding_residual_base",
                _text(expected_residual_base),
                _text(Decimal(row.rounding_residual_base)),
            )
        if source <= 0:
            _issue(issues, "conversion_arithmetic_mismatch", f"{path}.amount", "> 0", conversion.amount)
            continue
        if available.get(conversion.from_bucket_id, _ZERO) < source:
            _issue(
                issues,
                "insufficient_conversion_cash",
                f"{path}.amount",
                _money_text(available.get(conversion.from_bucket_id, _ZERO)),
                _money_text(source),
            )
            continue
        available[conversion.from_bucket_id] -= source
        cash[conversion.from_bucket_id] -= source
        cash[conversion.to_bucket_id] += expected_converted
    return True, unverified_buckets


def _check_post_conversion(
    issues: list[dict[str, Any]],
    document: PortfolioResult,
    cash: dict[str, Decimal],
    positions: dict[tuple[str, str], dict[str, Any]],
    conversions_replayed: bool,
) -> None:
    post_cash, post_positions = _state_maps(document.post_conversion_portfolio)
    opening_buckets = {
        bucket.bucket_id: bucket for bucket in document.opening_portfolio.buckets
    }
    for bucket in document.post_conversion_portfolio.buckets:
        expected_bucket = opening_buckets.get(bucket.bucket_id)
        if expected_bucket is None:
            continue
        bucket_path = f"post_conversion_portfolio.buckets.{bucket.bucket_id}"
        if expected_bucket.market != bucket.market:
            _issue(
                issues,
                "conversion_bucket_mismatch",
                f"{bucket_path}.market",
                expected_bucket.market,
                bucket.market,
            )
        if expected_bucket.currency != bucket.currency:
            _issue(
                issues,
                "conversion_bucket_mismatch",
                f"{bucket_path}.currency",
                expected_bucket.currency,
                bucket.currency,
            )
    if not document.conversions or conversions_replayed:
        for bucket_id in sorted(set(cash) | set(post_cash)):
            path = f"post_conversion_portfolio.buckets.{bucket_id}.cash"
            if bucket_id not in post_cash:
                _issue(issues, "conversion_cash_mismatch", path, _money_text(cash[bucket_id]), None)
                continue
            if bucket_id not in cash:
                _issue(issues, "conversion_cash_mismatch", path, None, _money_text(post_cash[bucket_id]))
                continue
            if cash[bucket_id] != post_cash[bucket_id]:
                _issue(
                    issues,
                    "conversion_cash_mismatch",
                    path,
                    _money_text(cash[bucket_id]),
                    _money_text(post_cash[bucket_id]),
                )
        for key in sorted(set(positions) | set(post_positions)):
            bucket_id, symbol = key
            path = f"post_conversion_portfolio.buckets.{bucket_id}.positions[{symbol}]"
            if key not in positions:
                _issue(issues, "conversion_position_mismatch", path, None, post_positions[key]["qty"])
                continue
            if key not in post_positions:
                _issue(issues, "conversion_position_mismatch", path, positions[key]["qty"], None)
                continue
            if positions[key]["qty"] != post_positions[key]["qty"]:
                _issue(
                    issues,
                    "conversion_position_mismatch",
                    f"{path}.qty",
                    positions[key]["qty"],
                    post_positions[key]["qty"],
                )
            if positions[key]["currency"] != post_positions[key]["currency"]:
                _issue(
                    issues,
                    "conversion_position_mismatch",
                    f"{path}.currency",
                    positions[key]["currency"],
                    post_positions[key]["currency"],
                )


def _replay_fills(
    issues: list[dict[str, Any]],
    document: PortfolioResult,
    buckets: dict[str, Any],
    fee_rules: dict[str, MarketRules],
    cash: dict[str, Decimal],
    positions: dict[tuple[str, str], dict[str, Any]],
    *,
    unverified_cash_buckets: set[str],
) -> None:
    for index, fill in enumerate(document.fills):
        path = f"fills[{index}]"
        bucket = buckets.get(fill.bucket_id)
        if bucket is None:
            _issue(issues, "unknown_fill_bucket", f"{path}.bucket_id", "declared bucket", fill.bucket_id)
            continue
        if fill.currency != bucket.currency:
            _issue(
                issues,
                "fill_currency_mismatch",
                f"{path}.currency",
                bucket.currency,
                fill.currency,
            )
        if fill.trade_date != document.trade_date:
            _issue(
                issues,
                "fill_trade_date_mismatch",
                f"{path}.trade_date",
                document.trade_date.isoformat(),
                fill.trade_date.isoformat(),
            )
        price = Decimal(fill.price)
        fee = Decimal(fill.fee)
        if price <= 0:
            _issue(issues, "invalid_fill_price", f"{path}.price", "> 0", fill.price)
            continue
        rules = fee_rules[fill.bucket_id]
        try:
            expected_fee = rules.fee(fill.side, fill.qty, price)
        except (ArithmeticError, TypeError, ValueError) as exc:
            raise ValueError(f"{path}.fee cannot be replayed: {exc}") from exc
        if fee != expected_fee:
            _issue(
                issues,
                "fill_fee_mismatch",
                f"{path}.fee",
                _money_text(expected_fee),
                _money_text(fee),
            )
        notional = quantize_money(_exact(Decimal(fill.qty), price))
        key = (fill.bucket_id, fill.symbol)
        position = positions.get(key)
        if fill.side == "buy":
            cash[fill.bucket_id] -= notional + fee
            existing_qty = position["qty"] if position else 0
            new_qty = existing_qty + fill.qty
            if existing_qty == 0 or position is None:
                basis = price
            else:
                basis = _ratio(
                    _exact(Decimal(existing_qty), position["avg_cost"])
                    + _exact(Decimal(fill.qty), price),
                    Decimal(new_qty),
                )
            positions[key] = {
                "qty": new_qty,
                "avg_cost": _money_even(basis),
                "currency": bucket.currency,
            }
        else:
            available = position["qty"] if position else 0
            if fill.qty > available:
                _issue(
                    issues,
                    "insufficient_position",
                    f"{path}.qty",
                    available,
                    fill.qty,
                )
            cash[fill.bucket_id] += notional - fee
            if position is None:
                continue
            new_qty = available - fill.qty
            if new_qty <= 0:
                positions.pop(key, None)
            else:
                positions[key]["qty"] = new_qty
        if (
            cash[fill.bucket_id] < 0
            and fill.bucket_id not in unverified_cash_buckets
        ):
            _issue(
                issues,
                "negative_cash",
                path,
                ">= 0",
                _money_text(cash[fill.bucket_id]),
            )


def _check_plan_outcomes(
    issues: list[dict[str, Any]],
    document: PortfolioResult,
) -> None:
    rows: list[tuple[str, int, Any]] = []
    rows.extend(("fills", index, row) for index, row in enumerate(document.fills))
    rows.extend(
        ("rejected_orders", index, row)
        for index, row in enumerate(document.rejected_orders)
    )
    rows.extend(
        ("canceled_orders", index, row)
        for index, row in enumerate(document.canceled_orders)
    )
    counts = Counter(row.plan_order_id for _, _, row in rows)
    seen: set[str] = set()
    for kind, index, row in rows:
        if row.plan_order_id in seen:
            code = "duplicate_fill" if kind == "fills" else "duplicate_order_outcome"
            _issue(
                issues,
                code,
                f"{kind}[{index}].plan_order_id",
                "one terminal outcome per plan order",
                counts[row.plan_order_id],
            )
        seen.add(row.plan_order_id)

    plan = document.plan
    if isinstance(plan, ExplicitOrdersPlan):
        plan_rows: dict[str, Any] = {}
        for index, order in enumerate(plan.orders):
            if order.order_id in plan_rows:
                _issue(
                    issues,
                    "duplicate_plan_order_id",
                    f"plan.orders[{index}].order_id",
                    "unique order_id",
                    order.order_id,
                )
            plan_rows[order.order_id] = order
        for kind, index, row in rows:
            order = plan_rows.get(row.plan_order_id)
            path = f"{kind}[{index}]"
            if order is None:
                _issue(
                    issues,
                    "unknown_plan_order_id",
                    f"{path}.plan_order_id",
                    "declared plan order",
                    row.plan_order_id,
                )
                continue
            fields = {
                "bucket_id": order.bucket_id,
                "symbol": order.symbol,
                "currency": order.currency,
                "side": order.side,
                "qty": order.qty,
            }
            actual = {name: getattr(row, name) for name in fields}
            if actual != fields:
                _issue(
                    issues,
                    "order_outcome_mismatch",
                    path,
                    fields,
                    actual,
                )
        for plan_order_id in plan_rows:
            if plan_order_id not in seen:
                _issue(
                    issues,
                    "missing_order_outcome",
                    f"plan.orders[{plan_order_id}]",
                    "exactly one terminal outcome",
                    None,
                )
    elif isinstance(plan, TargetWeightsPlan):
        target_keys = {(row.bucket_id, row.symbol) for row in plan.target_weights}
        expected_date = document.trade_date.strftime("%Y%m%d")
        for kind, index, row in rows:
            path = f"{kind}[{index}]"
            match = _GENERATED_ORDER_ID.match(row.plan_order_id)
            if match is None:
                _issue(
                    issues,
                    "generated_order_id_mismatch",
                    f"{path}.plan_order_id",
                    "pt2-YYYYMMDD-<bucket>-<side>-<symbol>",
                    row.plan_order_id,
                )
                continue
            day, bucket_id, side, symbol = match.groups()
            actual = {
                "trade_date": day,
                "bucket_id": bucket_id,
                "side": side,
                "symbol": symbol,
            }
            expected = {
                "trade_date": expected_date,
                "bucket_id": row.bucket_id,
                "side": row.side,
                "symbol": row.symbol,
            }
            if actual != expected:
                _issue(
                    issues,
                    "generated_order_id_mismatch",
                    f"{path}.plan_order_id",
                    expected,
                    actual,
                )
            if (row.bucket_id, row.symbol) not in target_keys:
                _issue(
                    issues,
                    "unexpected_plan_order",
                    path,
                    "declared target",
                    {"bucket_id": row.bucket_id, "symbol": row.symbol},
                )

    expected_complete = not document.rejected_orders and not document.canceled_orders
    if document.complete != expected_complete:
        _issue(
            issues,
            "complete_mismatch",
            "complete",
            expected_complete,
            document.complete,
        )


def _check_end_state(
    issues: list[dict[str, Any]],
    document: PortfolioResult,
    cash: dict[str, Decimal],
    positions: dict[tuple[str, str], dict[str, Any]],
    *,
    unverified_cash_buckets: set[str],
) -> None:
    end_cash, end_positions = _state_maps(document.end_portfolio)
    opening_buckets = {
        bucket.bucket_id: bucket for bucket in document.opening_portfolio.buckets
    }
    for bucket in document.end_portfolio.buckets:
        expected_bucket = opening_buckets.get(bucket.bucket_id)
        if expected_bucket is None:
            continue
        bucket_path = f"end_portfolio.buckets.{bucket.bucket_id}"
        if expected_bucket.market != bucket.market:
            _issue(
                issues,
                "end_bucket_mismatch",
                f"{bucket_path}.market",
                expected_bucket.market,
                bucket.market,
            )
        if expected_bucket.currency != bucket.currency:
            _issue(
                issues,
                "end_bucket_mismatch",
                f"{bucket_path}.currency",
                expected_bucket.currency,
                bucket.currency,
            )
    for bucket_id in sorted(set(cash) | set(end_cash)):
        if bucket_id in unverified_cash_buckets:
            continue
        path = f"end_portfolio.buckets.{bucket_id}.cash"
        if bucket_id not in end_cash:
            _issue(issues, "end_cash_mismatch", path, _money_text(cash[bucket_id]), None)
            continue
        if bucket_id not in cash:
            _issue(issues, "end_cash_mismatch", path, None, _money_text(end_cash[bucket_id]))
            continue
        if cash[bucket_id] != end_cash[bucket_id]:
            _issue(
                issues,
                "end_cash_mismatch",
                path,
                _money_text(cash[bucket_id]),
                _money_text(end_cash[bucket_id]),
            )
    for key in sorted(set(positions) | set(end_positions)):
        bucket_id, symbol = key
        path = f"end_portfolio.buckets.{bucket_id}.positions[{symbol}]"
        expected = positions.get(key)
        actual = end_positions.get(key)
        if actual is not None and actual["qty"] == 0:
            _issue(issues, "zero_end_position", f"{path}.qty", "nonzero or omitted", 0)
        if expected is None:
            if actual is not None and actual["qty"] != 0:
                _issue(
                    issues,
                    "unexpected_end_position",
                    path,
                    None,
                    actual["qty"],
                )
            continue
        if actual is None:
            _issue(issues, "missing_end_position", path, expected["qty"], None)
            continue
        if expected["qty"] != actual["qty"]:
            _issue(
                issues,
                "end_position_qty_mismatch",
                f"{path}.qty",
                expected["qty"],
                actual["qty"],
            )
        if expected["avg_cost"] != actual["avg_cost"]:
            _issue(
                issues,
                "end_position_avg_cost_mismatch",
                f"{path}.avg_cost",
                _money_text(expected["avg_cost"]),
                _money_text(actual["avg_cost"]),
            )
        if expected["currency"] != actual["currency"]:
            _issue(
                issues,
                "end_position_currency_mismatch",
                f"{path}.currency",
                expected["currency"],
                actual["currency"],
            )


def _analytics_checks(
    issues: list[dict[str, Any]],
    document: PortfolioResult,
    cash: dict[str, Decimal],
    positions: dict[tuple[str, str], dict[str, Any]],
    not_verified: list[str],
) -> None:
    analytics = document.analytics
    if analytics is None:
        not_verified.append(
            "analytics is absent; NAV, exposure and attribution arithmetic was not recomputed."
        )
        return

    nav_base = Decimal(analytics.nav_base)
    if analytics.base_currency != document.base_currency:
        _issue(
            issues,
            "analytics_nav_mismatch",
            "analytics.base_currency",
            document.base_currency,
            analytics.base_currency,
        )
    if analytics.valuation_at != document.valuation_at:
        _issue(
            issues,
            "analytics_nav_mismatch",
            "analytics.valuation_at",
            document.valuation_at.isoformat(),
            analytics.valuation_at.isoformat(),
        )
    cash_by_bucket: dict[str, Decimal] = {}
    cash_exact_by_bucket: dict[str, Decimal] = {}
    for index, row in enumerate(analytics.cash_rows):
        path = f"analytics.cash_rows[{index}]"
        bucket_cash = cash.get(row.bucket_id)
        if bucket_cash is None:
            _issue(issues, "analytics_cash_mismatch", f"{path}.bucket_id", "declared bucket", row.bucket_id)
            continue
        if Decimal(row.amount) != bucket_cash:
            _issue(
                issues,
                "analytics_cash_mismatch",
                f"{path}.amount",
                _money_text(bucket_cash),
                _money_text(Decimal(row.amount)),
            )
        rate = Decimal(row.fx.rate)
        exact = _exact(bucket_cash, rate)
        value = _money_even(exact)
        if Decimal(row.exact_value_base) != exact:
            _issue(
                issues,
                "analytics_rounding_mismatch",
                f"{path}.exact_value_base",
                _text(exact),
                _text(Decimal(row.exact_value_base)),
            )
        if Decimal(row.value_base) != value:
            _issue(
                issues,
                "analytics_rounding_mismatch",
                f"{path}.value_base",
                _money_text(value),
                _money_text(Decimal(row.value_base)),
            )
        if Decimal(row.rounding_residual) != exact - value:
            _issue(
                issues,
                "analytics_rounding_mismatch",
                f"{path}.rounding_residual",
                _text(exact - value),
                _text(Decimal(row.rounding_residual)),
            )
        cash_by_bucket[row.bucket_id] = value
        cash_exact_by_bucket[row.bucket_id] = exact

    position_value_by_bucket: dict[str, Decimal] = {}
    position_exact_by_bucket: dict[str, Decimal] = {}
    local_value_by_bucket: dict[str, Decimal] = {}
    position_rows: dict[tuple[str, str], Any] = {}
    for index, row in enumerate(analytics.position_rows):
        path = f"analytics.position_rows[{index}]"
        key = (row.bucket_id, row.symbol)
        if key in position_rows:
            _issue(
                issues,
                "analytics_position_mismatch",
                f"{path}.symbol",
                "one row per position",
                row.symbol,
            )
        position_rows[key] = row
        holding = positions.get(key)
        if holding is None:
            _issue(
                issues,
                "analytics_position_mismatch",
                path,
                "held position",
                {"bucket_id": row.bucket_id, "symbol": row.symbol},
            )
            continue
        if row.qty != holding["qty"]:
            _issue(
                issues,
                "analytics_position_mismatch",
                f"{path}.qty",
                holding["qty"],
                row.qty,
            )
        price = Decimal(row.price)
        if price <= 0:
            _issue(issues, "analytics_position_mismatch", f"{path}.price", "> 0", row.price)
            continue
        exact_local = _exact(Decimal(row.qty), price)
        local_value = _money_even(exact_local)
        rate = Decimal(row.fx.rate)
        exact_base = _exact(local_value, rate)
        value_base = _money_even(exact_base)
        if Decimal(row.local_value) != local_value:
            _issue(
                issues,
                "analytics_position_mismatch",
                f"{path}.local_value",
                _money_text(local_value),
                _money_text(Decimal(row.local_value)),
            )
        if Decimal(row.exact_value_base) != exact_base:
            _issue(
                issues,
                "analytics_rounding_mismatch",
                f"{path}.exact_value_base",
                _text(exact_base),
                _text(Decimal(row.exact_value_base)),
            )
        if Decimal(row.value_base) != value_base:
            _issue(
                issues,
                "analytics_position_mismatch",
                f"{path}.value_base",
                _money_text(value_base),
                _money_text(Decimal(row.value_base)),
            )
        if Decimal(row.rounding_residual) != exact_base - value_base:
            _issue(
                issues,
                "analytics_rounding_mismatch",
                f"{path}.rounding_residual",
                _text(exact_base - value_base),
                _text(Decimal(row.rounding_residual)),
            )
        expected_weight = _weight(_ratio(value_base, nav_base)) if nav_base > 0 else _ZERO
        if Decimal(row.weight) != expected_weight:
            _issue(
                issues,
                "analytics_exposure_mismatch",
                f"{path}.weight",
                format(expected_weight, ".12f"),
                row.weight,
            )
        position_value_by_bucket[row.bucket_id] = (
            position_value_by_bucket.get(row.bucket_id, _ZERO) + value_base
        )
        position_exact_by_bucket[row.bucket_id] = (
            position_exact_by_bucket.get(row.bucket_id, _ZERO) + exact_base
        )
        local_value_by_bucket[row.bucket_id] = (
            local_value_by_bucket.get(row.bucket_id, _ZERO) + local_value
        )

    expected_keys = {key for key, value in positions.items() if value["qty"] != 0}
    for key in sorted(expected_keys):
        if key not in position_rows:
            _issue(
                issues,
                "analytics_position_mismatch",
                f"analytics.position_rows[{key[0]}.{key[1]}]",
                "held position row",
                None,
            )

    bucket_exposures: dict[str, Any] = {}
    for index, row in enumerate(analytics.bucket_exposures):
        path = f"analytics.bucket_exposures[{index}]"
        bucket_exposures[row.bucket_id] = row
        cash_base = cash_by_bucket.get(row.bucket_id, _ZERO)
        cash_exact = cash_exact_by_bucket.get(row.bucket_id, _ZERO)
        position_value = position_value_by_bucket.get(row.bucket_id, _ZERO)
        position_exact = position_exact_by_bucket.get(row.bucket_id, _ZERO)
        if Decimal(row.cash_base) != cash_base:
            _issue(
                issues,
                "analytics_exposure_mismatch",
                f"{path}.cash_base",
                _money_text(cash_base),
                _money_text(Decimal(row.cash_base)),
            )
        if Decimal(row.position_value_base) != position_value:
            _issue(
                issues,
                "analytics_exposure_mismatch",
                f"{path}.position_value_base",
                _money_text(position_value),
                _money_text(Decimal(row.position_value_base)),
            )
        rounding = Decimal(row.valuation_rounding)
        value_base = cash_base + position_value + rounding
        if Decimal(row.value_base) != value_base:
            _issue(
                issues,
                "analytics_exposure_mismatch",
                f"{path}.value_base",
                _money_text(value_base),
                _money_text(Decimal(row.value_base)),
            )
        exact_value = cash_exact + position_exact
        if Decimal(row.exact_value_base) != exact_value:
            _issue(
                issues,
                "analytics_rounding_mismatch",
                f"{path}.exact_value_base",
                _text(exact_value),
                _text(Decimal(row.exact_value_base)),
            )
        if Decimal(row.rounding_residual) != exact_value - value_base:
            _issue(
                issues,
                "analytics_rounding_mismatch",
                f"{path}.rounding_residual",
                _text(exact_value - value_base),
                _text(Decimal(row.rounding_residual)),
            )

    for result_row in document.bucket_results:
        exposure = bucket_exposures.get(result_row.bucket_id)
        if exposure is None:
            _issue(
                issues,
                "bucket_nav_mismatch",
                f"bucket_results[{result_row.bucket_id}].nav_base",
                "analytics bucket exposure",
                None,
            )
            continue
        if Decimal(result_row.nav_base) != Decimal(exposure.value_base):
            _issue(
                issues,
                "bucket_nav_mismatch",
                f"bucket_results[{result_row.bucket_id}].nav_base",
                exposure.value_base,
                result_row.nav_base,
            )
        if (
            result_row.market != exposure.market
            or result_row.currency != exposure.currency
        ):
            _issue(
                issues,
                "bucket_row_mismatch",
                f"bucket_results[{result_row.bucket_id}]",
                {
                    "market": exposure.market,
                    "currency": exposure.currency,
                },
                {
                    "market": result_row.market,
                    "currency": result_row.currency,
                },
            )
        expected_rate_id = (
            None
            if result_row.currency == document.base_currency
            else exposure.fx.rate_id
        )
        if result_row.fx_rate_id != expected_rate_id:
            _issue(
                issues,
                "bucket_fx_mismatch",
                f"bucket_results[{result_row.bucket_id}].fx_rate_id",
                expected_rate_id,
                result_row.fx_rate_id,
            )
        if Decimal(result_row.position_value) != local_value_by_bucket.get(
            result_row.bucket_id, _ZERO
        ):
            _issue(
                issues,
                "bucket_position_value_mismatch",
                f"bucket_results[{result_row.bucket_id}].position_value",
                _money_text(local_value_by_bucket.get(result_row.bucket_id, _ZERO)),
                result_row.position_value,
            )

    cash_total = sum(cash_by_bucket.values(), _ZERO)
    position_total = sum(position_value_by_bucket.values(), _ZERO)
    exact_total = sum(cash_exact_by_bucket.values(), _ZERO) + sum(
        position_exact_by_bucket.values(), _ZERO
    )
    rounding_total = sum(
        (Decimal(row.valuation_rounding) for row in analytics.bucket_exposures), _ZERO
    )
    reported_total = cash_total + position_total + rounding_total
    conversion_rounding = sum(
        (Decimal(row.rounding_residual_base) for row in analytics.conversion_rows),
        _ZERO,
    )
    bridge = analytics.nav_bridge
    checks = (
        ("cash_base", Decimal(analytics.cash_base), cash_total),
        ("position_value_base", Decimal(analytics.position_value_base), position_total),
        ("valuation_rounding", Decimal(analytics.valuation_rounding), rounding_total),
        ("nav_base", nav_base, reported_total),
        ("exact_nav_base", Decimal(analytics.exact_nav_base), exact_total),
        ("rounding_residual", Decimal(analytics.rounding_residual), exact_total - reported_total),
    )
    for field_name, actual, expected in checks:
        if actual != expected:
            _issue(
                issues,
                "analytics_nav_mismatch",
                f"analytics.{field_name}",
                _text(expected),
                _text(actual),
            )
    bridge_checks = (
        ("cash_base", Decimal(bridge.cash_base), cash_total),
        ("position_value_base", Decimal(bridge.position_value_base), position_total),
        ("valuation_rounding", Decimal(bridge.valuation_rounding), rounding_total),
        ("nav_base", Decimal(bridge.nav_base), reported_total),
        ("exact_nav_base", Decimal(bridge.exact_nav_base), exact_total),
        ("rounding_residual", Decimal(bridge.rounding_residual), exact_total - reported_total),
        ("conversion_rounding_base", Decimal(bridge.conversion_rounding_base), conversion_rounding),
    )
    for field_name, actual, expected in bridge_checks:
        if actual != expected:
            _issue(
                issues,
                "analytics_nav_mismatch",
                f"analytics.nav_bridge.{field_name}",
                _text(expected),
                _text(actual),
            )
    if nav_base != Decimal(bridge.nav_base):
        _issue(
            issues,
            "analytics_nav_mismatch",
            "analytics.nav_base",
            bridge.nav_base,
            analytics.nav_base,
        )
    bucket_nav_total = sum(
        (Decimal(row.nav_base) for row in document.bucket_results), _ZERO
    )
    if bucket_nav_total != nav_base:
        _issue(
            issues,
            "analytics_nav_mismatch",
            "analytics.nav_base",
            _money_text(bucket_nav_total),
            analytics.nav_base,
        )

    _check_exposure_rollups(
        issues,
        analytics,
        bucket_exposures,
        cash_by_bucket,
        position_value_by_bucket,
        nav_base,
        "currency",
    )
    _check_exposure_rollups(
        issues,
        analytics,
        bucket_exposures,
        cash_by_bucket,
        position_value_by_bucket,
        nav_base,
        "market",
    )
    _check_sector_exposures(issues, analytics, position_rows)
    _check_concentration(issues, analytics, position_rows, nav_base)
    _check_attribution(
        issues,
        document,
        cash,
        positions,
        not_verified,
    )


def _check_exposure_rollups(
    issues: list[dict[str, Any]],
    analytics: Any,
    bucket_exposures: dict[str, Any],
    cash_by_bucket: dict[str, Decimal],
    position_value_by_bucket: dict[str, Decimal],
    nav_base: Decimal,
    kind: str,
) -> None:
    rows = (
        analytics.currency_exposures
        if kind == "currency"
        else analytics.market_exposures
    )
    grouped: dict[str, dict[str, Decimal | list[str]]] = {}
    for bucket_id, exposure in bucket_exposures.items():
        key = getattr(exposure, kind)
        entry = grouped.setdefault(
            key,
            {
                "cash": _ZERO,
                "position": _ZERO,
                "rounding": _ZERO,
                "value": _ZERO,
                "buckets": [],
            },
        )
        entry["cash"] += Decimal(exposure.cash_base)
        entry["position"] += Decimal(exposure.position_value_base)
        entry["rounding"] += Decimal(exposure.valuation_rounding)
        entry["value"] += Decimal(exposure.value_base)
        entry["buckets"].append(bucket_id)
    seen: set[str] = set()
    for index, row in enumerate(rows):
        path = f"analytics.{kind}_exposures[{index}]"
        key = getattr(row, kind)
        if key in seen:
            _issue(issues, "analytics_exposure_mismatch", path, "one row per group", key)
        seen.add(key)
        entry = grouped.get(key)
        if entry is None:
            _issue(issues, "analytics_exposure_mismatch", path, "declared group", key)
            continue
        expected = {
            "cash_base": entry["cash"],
            "position_value_base": entry["position"],
            "valuation_rounding": entry["rounding"],
            "value_base": entry["value"],
        }
        for field_name, value in expected.items():
            if Decimal(getattr(row, field_name)) != value:
                _issue(
                    issues,
                    "analytics_exposure_mismatch",
                    f"{path}.{field_name}",
                    _money_text(value),
                    getattr(row, field_name),
                )
        expected_weight = _weight(_ratio(entry["value"], nav_base)) if nav_base > 0 else _ZERO
        if Decimal(row.weight) != expected_weight:
            _issue(
                issues,
                "analytics_exposure_mismatch",
                f"{path}.weight",
                format(expected_weight, ".12f"),
                row.weight,
            )
        expected_buckets = tuple(sorted(entry["buckets"]))
        if row.bucket_ids != expected_buckets:
            _issue(
                issues,
                "analytics_exposure_mismatch",
                f"{path}.bucket_ids",
                list(expected_buckets),
                list(row.bucket_ids),
            )
    for key in sorted(set(grouped) - seen):
        _issue(
            issues,
            "analytics_exposure_mismatch",
            f"analytics.{kind}_exposures[{key}]",
            "published group",
            None,
        )


def _check_sector_exposures(
    issues: list[dict[str, Any]],
    analytics: Any,
    position_rows: dict[tuple[str, str], Any],
) -> None:
    assignment: dict[tuple[str, str], int] = {}
    position_value_base = Decimal(analytics.position_value_base)
    for index, row in enumerate(analytics.sector_exposures):
        path = f"analytics.sector_exposures[{index}]"
        values = _ZERO
        for bucket_id in row.bucket_ids:
            for symbol in row.symbols:
                key = (bucket_id, symbol)
                position = position_rows.get(key)
                if position is None:
                    continue
                if key in assignment:
                    _issue(
                        issues,
                        "analytics_exposure_mismatch",
                        f"{path}.symbols",
                        "one sector per position",
                        list(key),
                    )
                    continue
                assignment[key] = index
                values += Decimal(position.value_base)
        if Decimal(row.value_base) != values:
            _issue(
                issues,
                "analytics_exposure_mismatch",
                f"{path}.value_base",
                _money_text(values),
                row.value_base,
            )
        if position_value_base > 0:
            expected_weight = _weight(_ratio(values, position_value_base))
            if Decimal(row.weight_of_positions) != expected_weight:
                _issue(
                    issues,
                    "analytics_exposure_mismatch",
                    f"{path}.weight_of_positions",
                    format(expected_weight, ".12f"),
                    row.weight_of_positions,
                )
    for key in sorted(set(position_rows) - set(assignment)):
        _issue(
            issues,
            "analytics_exposure_mismatch",
            f"analytics.sector_exposures[{key[0]}.{key[1]}]",
            "one sector bucket",
            None,
        )


def _check_concentration(
    issues: list[dict[str, Any]],
    analytics: Any,
    position_rows: dict[tuple[str, str], Any],
    nav_base: Decimal,
) -> None:
    concentration = analytics.concentration
    path = "analytics.concentration"
    if concentration.position_count != len(position_rows):
        _issue(
            issues,
            "analytics_exposure_mismatch",
            f"{path}.position_count",
            len(position_rows),
            concentration.position_count,
        )
    weights: list[Decimal] = []
    published: dict[tuple[str, str], tuple[Decimal, Decimal]] = {}
    for key, row in position_rows.items():
        value = Decimal(row.value_base)
        exact_weight = _ratio(value, nav_base) if nav_base > 0 else _ZERO
        weights.append(exact_weight)
        published[key] = (value, _weight(exact_weight))
    for index, row in enumerate(concentration.position_weights):
        key = (row.bucket_id, row.symbol)
        item_path = f"{path}.position_weights[{index}]"
        expected = published.get(key)
        if expected is None:
            _issue(issues, "analytics_exposure_mismatch", item_path, "held position", list(key))
            continue
        if Decimal(row.value_base) != expected[0]:
            _issue(
                issues,
                "analytics_exposure_mismatch",
                f"{item_path}.value_base",
                _money_text(expected[0]),
                row.value_base,
            )
        if Decimal(row.weight) != expected[1]:
            _issue(
                issues,
                "analytics_exposure_mismatch",
                f"{item_path}.weight",
                format(expected[1], ".12f"),
                row.weight,
            )
    ordered = sorted(weights, reverse=True)
    expected_top1 = _weight(ordered[0]) if ordered else _ZERO
    expected_top5 = _weight(sum(ordered[:5], _ZERO))
    expected_hhi = _weight(sum((value * value for value in weights), _ZERO))
    if Decimal(concentration.top_1) != expected_top1:
        _issue(
            issues,
            "analytics_exposure_mismatch",
            f"{path}.top_1",
            format(expected_top1, ".12f"),
            concentration.top_1,
        )
    if Decimal(concentration.top_5) != expected_top5:
        _issue(
            issues,
            "analytics_exposure_mismatch",
            f"{path}.top_5",
            format(expected_top5, ".12f"),
            concentration.top_5,
        )
    if Decimal(concentration.hhi) != expected_hhi:
        _issue(
            issues,
            "analytics_exposure_mismatch",
            f"{path}.hhi",
            format(expected_hhi, ".12f"),
            concentration.hhi,
        )


def _check_attribution(
    issues: list[dict[str, Any]],
    document: PortfolioResult,
    cash: dict[str, Decimal],
    positions: dict[tuple[str, str], dict[str, Any]],
    not_verified: list[str],
) -> None:
    analytics = document.analytics
    if analytics is None or analytics.attribution is None:
        not_verified.append(
            "analytics.attribution is absent; one-day contribution and weight identities were not recomputed."
        )
        return
    attribution = analytics.attribution
    try:
        recomputed = reconcile_attribution(attribution)
    except (ArithmeticError, TypeError, ValueError) as exc:
        _issue(
            issues,
            "attribution_unverifiable",
            "analytics.attribution",
            "recomputable rows",
            str(exc),
        )
        return
    for item in recomputed:
        _issue(
            issues,
            item.reason,
            f"analytics.{item.path}",
            "recomputed attribution row",
            item.detail,
        )
    if not attribution.reconciliation.reconciled:
        _issue(
            issues,
            "attribution_reconciliation_failed",
            "analytics.attribution.reconciliation.reconciled",
            True,
            False,
        )
    if attribution.reconciliation.issues:
        _issue(
            issues,
            "attribution_reconciliation_failed",
            "analytics.attribution.reconciliation.issues",
            "empty",
            len(attribution.reconciliation.issues),
        )
    if not attribution.weights.reconciled:
        _issue(
            issues,
            "attribution_weights_mismatch",
            "analytics.attribution.weights.reconciled",
            True,
            False,
        )
    if Decimal(attribution.rounding_residual) != Decimal(
        attribution.expected_rounding_residual
    ):
        _issue(
            issues,
            "attribution_rounding_residual_mismatch",
            "analytics.attribution.rounding_residual",
            attribution.expected_rounding_residual,
            attribution.rounding_residual,
        )
    if Decimal(attribution.nav.end_nav_base) != Decimal(analytics.nav_base):
        _issue(
            issues,
            "attribution_nav_mismatch",
            "analytics.attribution.nav.end_nav_base",
            analytics.nav_base,
            attribution.nav.end_nav_base,
        )
    if Decimal(attribution.nav.end_exact_nav_base) != Decimal(
        analytics.nav_bridge.exact_nav_base
    ):
        _issue(
            issues,
            "attribution_nav_mismatch",
            "analytics.attribution.nav.end_exact_nav_base",
            analytics.nav_bridge.exact_nav_base,
            attribution.nav.end_exact_nav_base,
        )
    if attribution.nav.start_at != document.planning_at:
        _issue(
            issues,
            "attribution_nav_mismatch",
            "analytics.attribution.nav.start_at",
            document.planning_at.isoformat(),
            attribution.nav.start_at.isoformat(),
        )
    if attribution.nav.end_at != document.valuation_at:
        _issue(
            issues,
            "attribution_nav_mismatch",
            "analytics.attribution.nav.end_at",
            document.valuation_at.isoformat(),
            attribution.nav.end_at.isoformat(),
        )

    fills = {fill.plan_order_id: fill for fill in document.fills}
    fee_ids = Counter(row.plan_order_id for row in attribution.fee_effects)
    if fee_ids != Counter(fills.keys()):
        _issue(
            issues,
            "attribution_fill_mismatch",
            "analytics.attribution.fee_effects",
            sorted(fills),
            sorted(fee_ids),
        )
    for index, row in enumerate(attribution.fee_effects):
        fill = fills.get(row.plan_order_id)
        path = f"analytics.attribution.fee_effects[{index}]"
        if fill is None:
            continue
        expected = {
            "bucket_id": fill.bucket_id,
            "symbol": fill.symbol,
            "side": fill.side,
            "qty": fill.qty,
            "execution_price": fill.price,
            "fee_local": fill.fee,
        }
        actual = {
            "bucket_id": row.bucket_id,
            "symbol": row.symbol,
            "side": row.side,
            "qty": row.qty,
            "execution_price": row.execution_price,
            "fee_local": row.fee_local,
        }
        if Decimal(row.execution_price) != Decimal(fill.price):
            actual["execution_price"] = row.execution_price
        if Decimal(row.fee_local) != Decimal(fill.fee):
            actual["fee_local"] = row.fee_local
        if actual != expected:
            _issue(
                issues,
                "attribution_fill_mismatch",
                path,
                expected,
                actual,
            )

    rounding_ids = Counter(
        row.plan_order_id for row in attribution.execution_rounding
    )
    if rounding_ids != Counter(fills.keys()):
        _issue(
            issues,
            "attribution_fill_mismatch",
            "analytics.attribution.execution_rounding",
            sorted(fills),
            sorted(rounding_ids),
        )
    for index, row in enumerate(attribution.execution_rounding):
        fill = fills.get(row.plan_order_id)
        if fill is None:
            continue
        path = f"analytics.attribution.execution_rounding[{index}]"
        exact_notional = _exact(Decimal(fill.qty), Decimal(fill.price))
        notional = quantize_money(exact_notional)
        if Decimal(row.exact_notional_local) != exact_notional:
            _issue(
                issues,
                "attribution_execution_rounding_mismatch",
                f"{path}.exact_notional_local",
                _text(exact_notional),
                row.exact_notional_local,
            )
        if Decimal(row.notional_local) != notional:
            _issue(
                issues,
                "attribution_execution_rounding_mismatch",
                f"{path}.notional_local",
                _money_text(notional),
                row.notional_local,
            )
        if Decimal(row.rounding_local) != exact_notional - notional:
            _issue(
                issues,
                "attribution_execution_rounding_mismatch",
                f"{path}.rounding_local",
                _text(exact_notional - notional),
                row.rounding_local,
            )

    _, opening_positions = _state_maps(document.opening_portfolio)
    traded: dict[tuple[str, str], int] = {}
    for fill in document.fills:
        key = (fill.bucket_id, fill.symbol)
        sign = fill.qty if fill.side == "buy" else -fill.qty
        traded[key] = traded.get(key, 0) + sign
    for index, row in enumerate(attribution.symbol_contributions):
        path = f"analytics.attribution.symbol_contributions[{index}]"
        key = (row.bucket_id, row.symbol)
        opening = opening_positions.get(key)
        ending = positions.get(key)
        expected_opening = opening["qty"] if opening else 0
        expected_ending = ending["qty"] if ending else 0
        if row.opening_qty != expected_opening:
            _issue(
                issues,
                "attribution_position_mismatch",
                f"{path}.opening_qty",
                expected_opening,
                row.opening_qty,
            )
        if row.ending_qty != expected_ending:
            _issue(
                issues,
                "attribution_position_mismatch",
                f"{path}.ending_qty",
                expected_ending,
                row.ending_qty,
            )
        if row.traded_qty != traded.get(key, 0):
            _issue(
                issues,
                "attribution_position_mismatch",
                f"{path}.traded_qty",
                traded.get(key, 0),
                row.traded_qty,
            )
    covered = {
        (row.bucket_id, row.symbol) for row in attribution.symbol_contributions
    }
    for key in sorted(set(opening_positions) | set(positions)):
        if key not in covered:
            _issue(
                issues,
                "attribution_position_mismatch",
                f"analytics.attribution.symbol_contributions[{key[0]}.{key[1]}]",
                "one row per instrument",
                None,
            )


def _expected_end_portfolio(
    document: PortfolioResult,
    cash: dict[str, Decimal],
    positions: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    rows = []
    for bucket in document.opening_portfolio.buckets:
        bucket_id = bucket.bucket_id
        bucket_positions = []
        for (position_bucket, symbol), position in sorted(positions.items()):
            if position_bucket != bucket_id or position["qty"] == 0:
                continue
            bucket_positions.append(
                {
                    "symbol": symbol,
                    "qty": position["qty"],
                    "avg_cost": _money_text(position["avg_cost"]),
                    "currency": position["currency"],
                }
            )
        rows.append(
            {
                "bucket_id": bucket_id,
                "cash": _money_text(cash[bucket_id]),
                "positions": bucket_positions,
            }
        )
    return {"buckets": rows}


def reconcile_portfolio_document(
    account_state: Any, result: Any
) -> dict[str, Any]:
    """Replay one pt-v2.0 portfolio document against its opening portfolio."""
    document = _parse_result(result)
    opening_state = _parse_account_state(account_state)
    issues: list[dict[str, Any]] = []
    not_verified: list[str] = [
        "Caller-declared valuation marks and direct FX pairs were replayed from the document only; they were not re-fetched or compared with an independent market source.",
        "plan_hash, planning_data_hash, execution_data_fingerprint and document_hash were not recomputed because the raw request bars, sessions and fee snapshots are absent.",
        "This is a ledger and document-internal arithmetic audit, not a broker, venue or live-account verification.",
    ]

    _check_duplicate_buckets(issues, opening_state, "opening_portfolio.buckets")
    _check_duplicate_buckets(
        issues, document.opening_portfolio, "result.opening_portfolio.buckets"
    )
    _compare_states(
        issues,
        opening_state,
        document.opening_portfolio,
        "opening_portfolio",
    )
    try:
        PortfolioLedger.from_state(document.opening_portfolio)
    except PortfolioRequestError as exc:
        raise ValueError(
            f"result.opening_portfolio is invalid: {exc.reason} at {exc.path}"
        ) from exc
    fee_rules, buckets = _fee_rules(document.opening_portfolio)
    cash, positions = _state_maps(document.opening_portfolio)

    conversions_replayed, unverified_cash_buckets = _apply_conversions(
        issues, document, buckets, cash, not_verified
    )
    _check_post_conversion(
        issues, document, cash, positions, conversions_replayed
    )
    _check_plan_outcomes(issues, document)
    _replay_fills(
        issues,
        document,
        buckets,
        fee_rules,
        cash,
        positions,
        unverified_cash_buckets=unverified_cash_buckets,
    )
    _check_end_state(
        issues,
        document,
        cash,
        positions,
        unverified_cash_buckets=unverified_cash_buckets,
    )

    for index, row in enumerate(document.bucket_results):
        path = f"bucket_results[{index}]"
        bucket = buckets.get(row.bucket_id)
        if bucket is None:
            _issue(issues, "bucket_row_mismatch", path, "declared bucket", row.bucket_id)
            continue
        if row.cash != _money_text(cash[row.bucket_id]) and row.bucket_id not in unverified_cash_buckets:
            _issue(
                issues,
                "bucket_cash_mismatch",
                f"{path}.cash",
                _money_text(cash[row.bucket_id]),
                row.cash,
            )
        if row.session.market != row.market:
            _issue(
                issues,
                "bucket_row_mismatch",
                f"{path}.session.market",
                row.market,
                row.session.market,
            )
    reported_buckets = {row.bucket_id for row in document.bucket_results}
    for bucket_id in sorted(set(cash) - reported_buckets):
        _issue(
            issues,
            "bucket_row_mismatch",
            f"bucket_results[{bucket_id}]",
            "one row per bucket",
            None,
        )

    _analytics_checks(issues, document, cash, positions, not_verified)

    return {
        "status": "ok",
        "tool": "paper_trade_reconcile",
        "reconciled": not issues,
        "summary": {
            "fills_checked": len(document.fills),
            "bucket_rows_checked": len(document.bucket_results),
            "conversions_checked": len(document.conversions),
            "nav_rows_checked": 1 if document.analytics is not None else 0,
            "issue_count": len(issues),
        },
        "expected_end_portfolio": _expected_end_portfolio(
            document, cash, positions
        ),
        "issues": issues,
        "not_verified": not_verified,
    }
