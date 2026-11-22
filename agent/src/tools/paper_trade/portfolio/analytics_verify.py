"""Independent recomputation of a published one-day attribution document.

Every total is rebuilt from the published raw rows; the function never adjusts
a component to force the identity. Mismatches become field-level issues.
"""

from __future__ import annotations

from decimal import Decimal

from .analytics_common import (
    _attr_decimal,
    _attribution_issue,
    _exact_difference,
    _exact_product,
    _exact_sum,
    _execution_notional,
    _money,
)
from .analytics_weight_verify import _reconcile_weights
from .models import (
    AnalyticsAttribution,
    AnalyticsSymbolContribution,
    PortfolioIssue,
)


def reconcile_attribution(
    attribution: AnalyticsAttribution,
) -> tuple[PortfolioIssue, ...]:
    """Independently recompute a published attribution document.

    Every total is rebuilt from the published raw rows. The function never
    adjusts a component to force the identity; a mismatch becomes an issue.
    """
    issues: list[PortfolioIssue] = []

    def fail(
        reason: str,
        path: str,
        detail: str,
        bucket_id: str | None = None,
    ) -> None:
        issues.append(
            _attribution_issue(
                reason,
                path,
                detail,
                bucket_id=bucket_id,
            )
        )

    def equal(
        actual: Decimal,
        expected: Decimal,
        reason: str,
        path: str,
        detail: str,
        bucket_id: str | None = None,
    ) -> None:
        if actual != expected:
            fail(reason, path, detail, bucket_id)

    nav = attribution.nav
    start_reported = _attr_decimal(nav.start_nav_base)
    start_exact = _attr_decimal(nav.start_exact_nav_base)
    end_reported = _attr_decimal(nav.end_nav_base)
    end_exact = _attr_decimal(nav.end_exact_nav_base)
    equal(
        _attr_decimal(nav.start_rounding_residual),
        _exact_difference(start_exact, start_reported),
        "attribution_nav_mismatch",
        "attribution.nav.start_rounding_residual",
        "start exact NAV must equal reported NAV plus its residual",
    )
    equal(
        _attr_decimal(nav.end_rounding_residual),
        _exact_difference(end_exact, end_reported),
        "attribution_nav_mismatch",
        "attribution.nav.end_rounding_residual",
        "end exact NAV must equal reported NAV plus its residual",
    )
    equal(
        _attr_decimal(nav.nav_change_exact),
        _exact_difference(end_exact, start_exact),
        "attribution_nav_mismatch",
        "attribution.nav.nav_change_exact",
        "the exact NAV change must be end minus start",
    )
    equal(
        _attr_decimal(nav.nav_change_reported),
        _exact_difference(end_reported, start_reported),
        "attribution_nav_mismatch",
        "attribution.nav.nav_change_reported",
        "the reported NAV change must be end minus start",
    )

    cash_by_bucket = {row.bucket_id: row for row in attribution.cash_fx_effects}
    if len(cash_by_bucket) != len(attribution.cash_fx_effects):
        fail(
            "attribution_duplicate_bucket",
            "attribution.cash_fx_effects",
            "a bucket may publish exactly one cash FX row",
        )
    opening_by_bucket: dict[str, Decimal] = {}
    ending_by_bucket: dict[str, Decimal] = {}
    opening_cash_units: dict[str, Decimal] = {}
    ending_cash_units: dict[str, Decimal] = {}
    opening_position_local: dict[str, Decimal] = {}
    ending_position_local: dict[str, Decimal] = {}
    opening_position_money: dict[str, Decimal] = {}
    ending_position_money: dict[str, Decimal] = {}
    symbol_by_key: dict[tuple[str, str], AnalyticsSymbolContribution] = {}
    for index, row in enumerate(attribution.symbol_contributions):
        key = (row.bucket_id, row.symbol)
        if key in symbol_by_key:
            fail(
                "attribution_duplicate_position",
                f"attribution.symbol_contributions[{index}]",
                "a bucket/instrument pair may publish exactly one contribution",
                row.bucket_id,
            )
        symbol_by_key[key] = row
        opening_local = _attr_decimal(row.opening_local_value)
        ending_local = _attr_decimal(row.ending_local_value)
        opening_rate = _attr_decimal(row.opening_fx.rate)
        ending_rate = _attr_decimal(row.ending_fx.rate)
        if (
            row.opening_fx.from_currency != row.currency
            or row.ending_fx.from_currency != row.currency
        ):
            fail(
                "attribution_fx_reference_mismatch",
                f"attribution.symbol_contributions[{index}].opening_fx",
                "position FX references must name the position currency",
                row.bucket_id,
            )
        equal(
            opening_local,
            _exact_product(Decimal(row.opening_qty), _attr_decimal(row.opening_price)),
            "attribution_position_math_mismatch",
            f"attribution.symbol_contributions[{index}].opening_local_value",
            "opening local value must equal quantity times price",
            row.bucket_id,
        )
        equal(
            ending_local,
            _exact_product(Decimal(row.ending_qty), _attr_decimal(row.ending_price)),
            "attribution_position_math_mismatch",
            f"attribution.symbol_contributions[{index}].ending_local_value",
            "ending local value must equal quantity times price",
            row.bucket_id,
        )
        equal(
            _attr_decimal(row.opening_value_base),
            _exact_product(opening_local, opening_rate),
            "attribution_position_math_mismatch",
            f"attribution.symbol_contributions[{index}].opening_value_base",
            "opening base value must equal local value times opening FX",
            row.bucket_id,
        )
        equal(
            _attr_decimal(row.ending_value_base),
            _exact_product(ending_local, ending_rate),
            "attribution_position_math_mismatch",
            f"attribution.symbol_contributions[{index}].ending_value_base",
            "ending base value must equal local value times ending FX",
            row.bucket_id,
        )
        currency_expected = _exact_product(
            opening_local,
            _exact_difference(ending_rate, opening_rate),
        )
        equal(
            _attr_decimal(row.currency_contribution_base),
            currency_expected,
            "attribution_position_math_mismatch",
            f"attribution.symbol_contributions[{index}].currency_contribution_base",
            "currency contribution must revalue opening local value",
            row.bucket_id,
        )
        trade_expected = Decimal(0)
        for fill in attribution.execution_rounding:
            if fill.bucket_id != row.bucket_id or fill.symbol != row.symbol:
                continue
            sign = Decimal(1) if fill.side == "sell" else Decimal(-1)
            trade_expected = _exact_sum(
                (
                    trade_expected,
                    _exact_product(
                        sign * _attr_decimal(fill.exact_notional_local),
                        _attr_decimal(fill.fx.rate),
                    ),
                )
            )
        equal(
            _attr_decimal(row.trade_cash_base),
            trade_expected,
            "attribution_position_math_mismatch",
            f"attribution.symbol_contributions[{index}].trade_cash_base",
            "trade cash must equal signed exact fill notionals at ending FX",
            row.bucket_id,
        )
        equal(
            _attr_decimal(row.market_contribution_base),
            _exact_sum(
                (
                    _exact_difference(
                        _attr_decimal(row.ending_value_base),
                        _attr_decimal(row.opening_value_base),
                    ),
                    -currency_expected,
                    trade_expected,
                )
            ),
            "attribution_position_math_mismatch",
            f"attribution.symbol_contributions[{index}].market_contribution_base",
            "market contribution must equal ending minus opening minus FX plus trade cash",
            row.bucket_id,
        )
        equal(
            _attr_decimal(row.total_contribution_base),
            _exact_sum(
                (
                    _attr_decimal(row.market_contribution_base),
                    _attr_decimal(row.currency_contribution_base),
                )
            ),
            "attribution_position_math_mismatch",
            f"attribution.symbol_contributions[{index}].total_contribution_base",
            "total contribution must equal market plus currency",
            row.bucket_id,
        )
        if row.traded_qty != row.ending_qty - row.opening_qty:
            fail(
                "attribution_position_math_mismatch",
                f"attribution.symbol_contributions[{index}].traded_qty",
                "traded quantity must equal ending quantity minus opening quantity",
                row.bucket_id,
            )
        opening_position_local[row.bucket_id] = _exact_sum(
            (opening_position_local.get(row.bucket_id, Decimal(0)), opening_local)
        )
        ending_position_local[row.bucket_id] = _exact_sum(
            (ending_position_local.get(row.bucket_id, Decimal(0)), ending_local)
        )
        opening_position_money[row.bucket_id] = _exact_sum(
            (
                opening_position_money.get(row.bucket_id, Decimal(0)),
                _money(opening_local, "attribution.reconcile.opening_local"),
            )
        )
        ending_position_money[row.bucket_id] = _exact_sum(
            (
                ending_position_money.get(row.bucket_id, Decimal(0)),
                _money(ending_local, "attribution.reconcile.ending_local"),
            )
        )

    for index, row in enumerate(attribution.cash_fx_effects):
        opening_rate = _attr_decimal(row.opening_fx.rate)
        ending_rate = _attr_decimal(row.ending_fx.rate)
        opening_cash = _attr_decimal(row.opening_cash)
        equal(
            _attr_decimal(row.cash_fx_effect_base),
            _exact_product(
                opening_cash,
                _exact_difference(ending_rate, opening_rate),
            ),
            "attribution_cash_fx_mismatch",
            f"attribution.cash_fx_effects[{index}].cash_fx_effect_base",
            "cash FX must revalue opening cash between the declared direct pairs",
            row.bucket_id,
        )
        opening_cash_units[row.bucket_id] = opening_cash
        ending_cash_units[row.bucket_id] = _attr_decimal(row.ending_cash)
        opening_by_bucket[row.bucket_id] = _exact_sum(
            (
                _attr_decimal(row.opening_cash),
                opening_position_local.get(row.bucket_id, Decimal(0)),
            )
        )
        ending_by_bucket[row.bucket_id] = _exact_sum(
            (
                _attr_decimal(row.ending_cash),
                ending_position_local.get(row.bucket_id, Decimal(0)),
            )
        )

    start_expected = Decimal(0)
    end_expected = Decimal(0)
    start_reported_expected = Decimal(0)
    end_reported_expected = Decimal(0)
    for bucket_id, row in cash_by_bucket.items():
        start_exact_bucket = _exact_product(
            opening_by_bucket.get(bucket_id, Decimal(0)),
            _attr_decimal(row.opening_fx.rate),
        )
        end_exact_bucket = _exact_product(
            ending_by_bucket.get(bucket_id, Decimal(0)),
            _attr_decimal(row.ending_fx.rate),
        )
        start_expected = _exact_sum((start_expected, start_exact_bucket))
        end_expected = _exact_sum((end_expected, end_exact_bucket))
        start_reported_expected = _exact_sum(
            (
                start_reported_expected,
                _money(
                    _exact_product(
                        _exact_sum(
                            (
                                opening_cash_units.get(bucket_id, Decimal(0)),
                                opening_position_money.get(bucket_id, Decimal(0)),
                            )
                        ),
                        _attr_decimal(row.opening_fx.rate),
                    ),
                    "attribution.reconcile.start_reported",
                ),
            )
        )
        end_reported_expected = _exact_sum(
            (
                end_reported_expected,
                _money(
                    _exact_product(
                        _exact_sum(
                            (
                                ending_cash_units.get(bucket_id, Decimal(0)),
                                ending_position_money.get(bucket_id, Decimal(0)),
                            )
                        ),
                        _attr_decimal(row.ending_fx.rate),
                    ),
                    "attribution.reconcile.end_reported",
                ),
            )
        )
    equal(
        start_reported_expected,
        start_reported,
        "attribution_nav_mismatch",
        "attribution.nav.start_nav_base",
        "per-bucket reported opening NAV must sum to start NAV",
    )
    equal(
        end_reported_expected,
        end_reported,
        "attribution_nav_mismatch",
        "attribution.nav.end_nav_base",
        "per-bucket reported ending NAV must sum to end NAV",
    )
    equal(
        start_expected,
        start_exact,
        "attribution_nav_mismatch",
        "attribution.nav.start_exact_nav_base",
        "opening cash and positions at planning marks/FX must equal start NAV",
    )
    equal(
        end_expected,
        end_exact,
        "attribution_nav_mismatch",
        "attribution.nav.end_exact_nav_base",
        "ending cash and positions at valuation marks/FX must equal end NAV",
    )

    conversion_total = Decimal(0)
    conversion_cash: dict[str, Decimal] = {
        bucket_id: opening_cash_units.get(bucket_id, Decimal(0))
        for bucket_id in cash_by_bucket
    }
    for index, row in enumerate(attribution.conversion_effects):
        source_rate = _attr_decimal(row.source_fx.rate)
        target_rate = _attr_decimal(row.target_fx.rate)
        if (
            row.source_fx.from_currency != row.from_currency
            or row.target_fx.from_currency != row.to_currency
        ):
            fail(
                "attribution_fx_reference_mismatch",
                f"attribution.conversion_effects[{index}].source_fx",
                "conversion FX references must name the event currencies",
            )
        exact = _exact_product(_attr_decimal(row.source_amount), _attr_decimal(row.rate))
        equal(
            _attr_decimal(row.exact_converted),
            exact,
            "attribution_conversion_math_mismatch",
            f"attribution.conversion_effects[{index}].exact_converted",
            "exact converted amount must equal source amount times rate",
        )
        equal(
            _attr_decimal(row.rounding_residual_local),
            _exact_difference(exact, _attr_decimal(row.converted_amount)),
            "attribution_conversion_math_mismatch",
            f"attribution.conversion_effects[{index}].rounding_residual_local",
            "conversion rounding must tie exact to credited amount",
        )
        source_effect = _exact_product(-_attr_decimal(row.source_amount), source_rate)
        target_effect = _exact_product(_attr_decimal(row.converted_amount), target_rate)
        equal(
            _attr_decimal(row.source_effect_base),
            source_effect,
            "attribution_conversion_math_mismatch",
            f"attribution.conversion_effects[{index}].source_effect_base",
            "source effect must debit source amount at its ending FX",
        )
        equal(
            _attr_decimal(row.target_effect_base),
            target_effect,
            "attribution_conversion_math_mismatch",
            f"attribution.conversion_effects[{index}].target_effect_base",
            "target effect must credit converted amount at its ending FX",
        )
        equal(
            _attr_decimal(row.conversion_effect_base),
            _exact_sum((source_effect, target_effect)),
            "attribution_conversion_math_mismatch",
            f"attribution.conversion_effects[{index}].conversion_effect_base",
            "conversion effect must be source plus target",
        )
        equal(
            _attr_decimal(row.rounding_loss_base),
            -_exact_product(
                _exact_difference(exact, _attr_decimal(row.converted_amount)),
                target_rate,
            ),
            "attribution_conversion_math_mismatch",
            f"attribution.conversion_effects[{index}].rounding_loss_base",
            "conversion rounding loss must be the unconverted remainder",
        )
        conversion_total = _exact_sum(
            (conversion_total, _attr_decimal(row.conversion_effect_base))
        )
        if row.from_bucket_id in conversion_cash:
            conversion_cash[row.from_bucket_id] = _exact_sum(
                (
                    conversion_cash[row.from_bucket_id],
                    -_attr_decimal(row.source_amount),
                )
            )
        else:
            fail(
                "attribution_conversion_bucket_mismatch",
                f"attribution.conversion_effects[{index}].from_bucket_id",
                "the source bucket has no cash row",
                row.from_bucket_id,
            )
        if row.to_bucket_id in conversion_cash:
            conversion_cash[row.to_bucket_id] = _exact_sum(
                (
                    conversion_cash[row.to_bucket_id],
                    _attr_decimal(row.converted_amount),
                )
            )
        else:
            fail(
                "attribution_conversion_bucket_mismatch",
                f"attribution.conversion_effects[{index}].to_bucket_id",
                "the target bucket has no cash row",
                row.to_bucket_id,
            )

    fee_total = Decimal(0)
    fee_by_order = {}
    for index, row in enumerate(attribution.fee_effects):
        if row.plan_order_id in fee_by_order:
            fail(
                "attribution_duplicate_fill",
                f"attribution.fee_effects[{index}].plan_order_id",
                "one plan order may publish one fee row",
                row.bucket_id,
            )
        fee_by_order[row.plan_order_id] = row
        bucket = cash_by_bucket.get(row.bucket_id)
        if bucket is not None and row.fx.from_currency != bucket.currency:
            fail(
                "attribution_fx_reference_mismatch",
                f"attribution.fee_effects[{index}].fx",
                "fee FX references must name the bucket currency",
                row.bucket_id,
            )
        equal(
            _attr_decimal(row.fee_effect_base),
            _exact_product(-_attr_decimal(row.fee_local), _attr_decimal(row.fx.rate)),
            "attribution_fee_mismatch",
            f"attribution.fee_effects[{index}].fee_effect_base",
            "fee effect must be the negative local fee at ending FX",
            row.bucket_id,
        )
        fee_total = _exact_sum((fee_total, _attr_decimal(row.fee_effect_base)))

    rounding_by_order = {}
    expected_rounding = Decimal(0)
    for index, row in enumerate(attribution.execution_rounding):
        if row.plan_order_id in rounding_by_order:
            fail(
                "attribution_duplicate_fill",
                f"attribution.execution_rounding[{index}].plan_order_id",
                "one plan order may publish one rounding row",
                row.bucket_id,
            )
        rounding_by_order[row.plan_order_id] = row
        bucket = cash_by_bucket.get(row.bucket_id)
        if bucket is not None and row.fx.from_currency != bucket.currency:
            fail(
                "attribution_fx_reference_mismatch",
                f"attribution.execution_rounding[{index}].fx",
                "execution rounding FX references must name the bucket currency",
                row.bucket_id,
            )
        exact = _exact_product(Decimal(row.qty), _attr_decimal(row.execution_price))
        notional = _execution_notional(exact)
        rounding = _exact_difference(exact, notional)
        equal(
            _attr_decimal(row.exact_notional_local),
            exact,
            "attribution_execution_rounding_mismatch",
            f"attribution.execution_rounding[{index}].exact_notional_local",
            "exact notional must equal quantity times execution price",
            row.bucket_id,
        )
        equal(
            _attr_decimal(row.notional_local),
            notional,
            "attribution_execution_rounding_mismatch",
            f"attribution.execution_rounding[{index}].notional_local",
            "execution notional must be the two-decimal ROUND_HALF_UP cash amount",
            row.bucket_id,
        )
        equal(
            _attr_decimal(row.rounding_local),
            rounding,
            "attribution_execution_rounding_mismatch",
            f"attribution.execution_rounding[{index}].rounding_local",
            "rounding must equal exact minus execution notional",
            row.bucket_id,
        )
        signed = rounding if row.side == "buy" else -rounding
        effect = _exact_product(signed, _attr_decimal(row.fx.rate))
        equal(
            _attr_decimal(row.rounding_effect_base),
            effect,
            "attribution_execution_rounding_mismatch",
            f"attribution.execution_rounding[{index}].rounding_effect_base",
            "rounding effect must carry the fill side into base currency",
            row.bucket_id,
        )
        expected_rounding = _exact_sum((expected_rounding, effect))

    for index, row in enumerate(attribution.fee_effects):
        rounding = rounding_by_order.get(row.plan_order_id)
        if rounding is None:
            fail(
                "attribution_missing_fill_row",
                f"attribution.fee_effects[{index}].plan_order_id",
                "every fee row needs its execution rounding row",
                row.bucket_id,
            )
            continue
        if row.bucket_id not in conversion_cash:
            continue
        notional = _attr_decimal(rounding.notional_local)
        fee = _attr_decimal(row.fee_local)
        delta = _exact_difference(notional, fee) if row.side == "sell" else -_exact_sum((notional, fee))
        conversion_cash[row.bucket_id] = _exact_sum((conversion_cash[row.bucket_id], delta))
    for bucket_id, row in cash_by_bucket.items():
        equal(
            conversion_cash.get(bucket_id, Decimal(0)),
            _attr_decimal(row.ending_cash),
            "attribution_cash_replay_mismatch",
            f"attribution.cash_fx_effects.{bucket_id}.ending_cash",
            "opening cash plus conversions and fills must equal ending cash",
            bucket_id,
        )

    position_total = _exact_sum(
        _attr_decimal(row.total_contribution_base)
        for row in attribution.symbol_contributions
    )
    cash_fx_total = _exact_sum(
        _attr_decimal(row.cash_fx_effect_base) for row in attribution.cash_fx_effects
    )
    equal(
        _attr_decimal(attribution.position_contribution_base),
        position_total,
        "attribution_total_mismatch",
        "attribution.position_contribution_base",
        "position total must equal the symbol contribution sum",
    )
    equal(
        _attr_decimal(attribution.cash_fx_effect_base),
        cash_fx_total,
        "attribution_total_mismatch",
        "attribution.cash_fx_effect_base",
        "cash FX total must equal the bucket FX row sum",
    )
    equal(
        _attr_decimal(attribution.conversion_effect_base),
        conversion_total,
        "attribution_total_mismatch",
        "attribution.conversion_effect_base",
        "conversion total must equal the conversion row sum",
    )
    equal(
        _attr_decimal(attribution.fee_effect_base),
        fee_total,
        "attribution_total_mismatch",
        "attribution.fee_effect_base",
        "fee total must equal the fee row sum",
    )
    equal(
        _attr_decimal(attribution.expected_rounding_residual),
        expected_rounding,
        "attribution_execution_rounding_mismatch",
        "attribution.expected_rounding_residual",
        "expected rounding must equal the execution rounding row sum",
    )
    identity_residual = _exact_difference(
        _attr_decimal(nav.nav_change_exact),
        _exact_sum(
            (
                position_total,
                cash_fx_total,
                conversion_total,
                fee_total,
            )
        ),
    )
    equal(
        _attr_decimal(attribution.rounding_residual),
        identity_residual,
        "attribution_identity_mismatch",
        "attribution.rounding_residual",
        "rounding residual must equal the unfitted NAV identity difference",
    )
    equal(
        identity_residual,
        expected_rounding,
        "attribution_rounding_residual_mismatch",
        "attribution.rounding_residual",
        "the identity residual must equal the execution rounding rows",
    )

    def _expected_rolls(rows):
        rolls: dict[str, dict[str, Decimal | set[str]]] = {}
        for row in rows:
            key = row[0]
            values = rolls.setdefault(
                key,
                {
                    "position": Decimal(0),
                    "cash": Decimal(0),
                    "conversion": Decimal(0),
                    "fee": Decimal(0),
                    "buckets": set(),
                },
            )
            values[row[1]] = _exact_sum(
                (values[row[1]], _attr_decimal(row[2]))
            )
            values["buckets"].add(row[3])
        return rolls

    market_inputs: list[tuple[str, str, str, str]] = []
    currency_inputs: list[tuple[str, str, str, str]] = []
    for row in attribution.symbol_contributions:
        market_inputs.append(
            (row.market, "position", row.total_contribution_base, row.bucket_id)
        )
        currency_inputs.append(
            (row.currency, "position", row.total_contribution_base, row.bucket_id)
        )
    for row in attribution.cash_fx_effects:
        market_inputs.append(
            (row.market, "cash", row.cash_fx_effect_base, row.bucket_id)
        )
        currency_inputs.append(
            (row.currency, "cash", row.cash_fx_effect_base, row.bucket_id)
        )
    for row in attribution.conversion_effects:
        source_bucket = cash_by_bucket.get(row.from_bucket_id)
        target_bucket = cash_by_bucket.get(row.to_bucket_id)
        if source_bucket is not None:
            market_inputs.append(
                (source_bucket.market, "conversion", row.source_effect_base, row.from_bucket_id)
            )
            currency_inputs.append(
                (row.from_currency, "conversion", row.source_effect_base, row.from_bucket_id)
            )
        if target_bucket is not None:
            market_inputs.append(
                (target_bucket.market, "conversion", row.target_effect_base, row.to_bucket_id)
            )
            currency_inputs.append(
                (row.to_currency, "conversion", row.target_effect_base, row.to_bucket_id)
            )
    for row in attribution.fee_effects:
        bucket = cash_by_bucket.get(row.bucket_id)
        if bucket is not None:
            market_inputs.append((bucket.market, "fee", row.fee_effect_base, row.bucket_id))
            currency_inputs.append((bucket.currency, "fee", row.fee_effect_base, row.bucket_id))

    for label, published_rows, inputs in (
        ("market", attribution.market_contributions, market_inputs),
        ("currency", attribution.currency_contributions, currency_inputs),
    ):
        expected_rolls = _expected_rolls(inputs)
        published = {row.market if label == "market" else row.currency: row for row in published_rows}
        for key in sorted(set(published) | set(expected_rolls)):
            row = published.get(key)
            expected = expected_rolls.get(key)
            if row is None or expected is None:
                fail(
                    f"attribution_{label}_rollup_mismatch",
                    f"attribution.{label}_contributions.{key}",
                    f"the {label} roll-up row set differs from the raw rows",
                )
                continue
            field_names = {
                "position": "position_contribution_base",
                "cash": "cash_fx_effect_base",
                "conversion": "conversion_effect_base",
                "fee": "fee_effect_base",
            }
            for field, attribute in field_names.items():
                equal(
                    _attr_decimal(getattr(row, attribute)),
                    expected[field],
                    f"attribution_{label}_rollup_mismatch",
                    f"attribution.{label}_contributions.{key}.{field}",
                    f"the {label} {field} roll-up must equal its raw rows",
                )
            equal(
                _attr_decimal(row.total_contribution_base),
                _exact_sum(
                    (
                        expected["position"],
                        expected["cash"],
                        expected["conversion"],
                        expected["fee"],
                    )
                ),
                f"attribution_{label}_rollup_mismatch",
                f"attribution.{label}_contributions.{key}.total",
                f"the {label} total must equal all four effects",
            )
            if tuple(row.bucket_ids) != tuple(sorted(expected["buckets"])):
                fail(
                    f"attribution_{label}_rollup_mismatch",
                    f"attribution.{label}_contributions.{key}.bucket_ids",
                    f"the {label} bucket ids must match the contributing rows",
                )
        equal(
            _exact_sum(
                _attr_decimal(row.total_contribution_base) for row in published_rows
            ) + identity_residual,
            _attr_decimal(nav.nav_change_exact),
            f"attribution_{label}_rollup_mismatch",
            f"attribution.{label}_contributions",
            f"all {label} totals plus the residual must equal the NAV change",
        )

    _reconcile_weights(attribution, cash_by_bucket, symbol_by_key, issues)
    return tuple(issues)
