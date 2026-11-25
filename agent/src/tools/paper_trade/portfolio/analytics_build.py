"""Top-level portfolio analytics builder for one validated end ledger.

Recomputes the NAV bridge from the prepared marks and direct FX pairs, builds
cash/position/conversion rows, exposure and concentration roll-ups, the
optional benchmark and the one-day attribution, and checks every published
identity before returning the analytics object.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from .analytics_attribution import _attribution
from .analytics_benchmark import _benchmark
from .analytics_common import (
    _ZERO_WEIGHT,
    _PositionBuild,
    _exact_product,
    _exact_sum,
    _exact_text,
    _fx_reference,
    _invariant,
    _money,
    _price_text,
    _rate_text,
    _ratio,
    _reject,
    _weight,
)
from .analytics_exposure import (
    _bucket_provenance,
    _concentration,
    _currency_exposures,
    _market_exposures,
    _marks_by_bucket,
    _provenance,
    _sector_exposures,
)
from .data import PreparedPortfolioData
from .fx import FxConversionEvent, FxRateBook
from .ledger import PortfolioLedger, value_ledger
from .models import (
    AnalyticsBucketExposure,
    AnalyticsCashRow,
    AnalyticsConversionRow,
    AnalyticsMarkReference,
    AnalyticsNavBridge,
    AnalyticsPositionRow,
    PortfolioAnalytics,
    PortfolioRequest,
)
from .numeric import MONEY_SPEC, WEIGHT_SPEC, canonical_decimal
from .orchestrator import ExecutionCancellation, ExecutionFill, ExecutionRejection
from .order_plan import OrderPlan


def build_portfolio_analytics(
    request: PortfolioRequest,
    ledger: PortfolioLedger,
    prepared: PreparedPortfolioData,
    *,
    conversion_events: Sequence[FxConversionEvent] = (),
    opening_ledger: PortfolioLedger | None = None,
    post_conversion_ledger: PortfolioLedger | None = None,
    fills: Sequence[ExecutionFill] = (),
    rejected_orders: Sequence[ExecutionRejection] = (),
    canceled_orders: Sequence[ExecutionCancellation] = (),
    plan: OrderPlan | None = None,
) -> PortfolioAnalytics:
    """Build exact analytics for one validated end ledger and its marks.

    The ledger bridge is recomputed here from the same prepared marks and
    direct FX pairs, so the published NAV can only equal the Decimal ledger
    arithmetic. Any missing mark/pair raises the existing declared request
    error; any internal identity mismatch raises an internal stage error and
    no partial analytics document is returned.
    """
    base_currency = request.base_currency
    book = FxRateBook.from_snapshots(request.fx_snapshots, at=request.valuation_at)
    marks = _marks_by_bucket(prepared)
    mark_values = {
        symbol: mark.price
        for bucket_marks in marks.values()
        for symbol, mark in bucket_marks.items()
    }
    ledger_bridge = value_ledger(
        ledger,
        mark_values,
        book,
        base_currency=base_currency,
    )
    bridge_by_id = {row.bucket_id: row for row in ledger_bridge.rows}
    nav_base = ledger_bridge.total.reported_base
    exact_nav_base = ledger_bridge.total.exact_base

    cash_rows: list[AnalyticsCashRow] = []
    position_builds: list[_PositionBuild] = []
    cash_exact_by_bucket: dict[str, Decimal] = {}
    for bucket in ledger.buckets:
        bridge_row = bridge_by_id.get(bucket.bucket_id)
        if bridge_row is None:
            _invariant(
                "valuation_bucket_mismatch",
                f"analytics.buckets.{bucket.bucket_id}",
            )
        fx_path = f"analytics.buckets.{bucket.bucket_id}.fx_rate_id"
        fx, rate = _fx_reference(
            bucket.currency,
            base_currency,
            book,
            request.valuation_at,
            path=fx_path,
        )
        cash_exact = _exact_product(bucket.cash, rate)
        cash_value = _money(cash_exact, f"analytics.cash.{bucket.bucket_id}.value_base")
        cash_exact_by_bucket[bucket.bucket_id] = cash_exact
        cash_rows.append(
            AnalyticsCashRow(
                bucket_id=bucket.bucket_id,
                market=bucket.market,
                currency=bucket.currency,
                valuation_date=request.trade_date,
                amount=canonical_decimal(
                    bucket.cash,
                    MONEY_SPEC,
                    f"analytics.cash.{bucket.bucket_id}.amount",
                ),
                fx=fx,
                value_base=canonical_decimal(
                    cash_value,
                    MONEY_SPEC,
                    f"analytics.cash.{bucket.bucket_id}.value_base",
                ),
                exact_value_base=_exact_text(
                    cash_exact,
                    f"analytics.cash.{bucket.bucket_id}.exact_value_base",
                ),
                rounding_residual=_exact_text(
                    cash_exact - cash_value,
                    f"analytics.cash.{bucket.bucket_id}.rounding_residual",
                ),
            )
        )

        bucket_marks = marks.get(bucket.bucket_id, {})
        for position in sorted(bucket.positions, key=lambda row: row.symbol):
            mark = bucket_marks.get(position.symbol)
            if mark is None:
                _reject(
                    "missing_valuation_mark",
                    f"analytics.marks.{bucket.bucket_id}.{position.symbol}",
                    bucket_id=bucket.bucket_id,
                    detail="every held instrument needs a declared valuation mark",
                )
            exact_local = _exact_product(Decimal(position.qty), mark.price)
            local_value = _money(
                exact_local,
                f"analytics.positions.{bucket.bucket_id}.{position.symbol}.local_value",
            )
            exact_base = _exact_product(exact_local, rate)
            value_base = _money(
                exact_base,
                f"analytics.positions.{bucket.bucket_id}.{position.symbol}.value_base",
            )
            weight = (
                _weight(
                    _ratio(value_base, nav_base),
                    f"analytics.positions.{bucket.bucket_id}.{position.symbol}.weight",
                )
                if nav_base > 0
                else _weight(_ZERO_WEIGHT, f"analytics.positions.{bucket.bucket_id}.{position.symbol}.weight")
            )
            position_builds.append(
                _PositionBuild(
                    row=AnalyticsPositionRow(
                        bucket_id=bucket.bucket_id,
                        market=bucket.market,
                        currency=bucket.currency,
                        symbol=position.symbol,
                        qty=position.qty,
                        price=_price_text(
                            mark.price,
                            f"analytics.positions.{bucket.bucket_id}.{position.symbol}.price",
                        ),
                        mark=AnalyticsMarkReference(
                            price_date=mark.price_date,
                            source=mark.source,
                            as_of=mark.as_of,
                        ),
                        local_value=canonical_decimal(
                            local_value,
                            MONEY_SPEC,
                            f"analytics.positions.{bucket.bucket_id}.{position.symbol}.local_value",
                        ),
                        fx=fx,
                        value_base=canonical_decimal(
                            value_base,
                            MONEY_SPEC,
                            f"analytics.positions.{bucket.bucket_id}.{position.symbol}.value_base",
                        ),
                        exact_value_base=_exact_text(
                            exact_base,
                            f"analytics.positions.{bucket.bucket_id}.{position.symbol}.exact_value_base",
                        ),
                        rounding_residual=_exact_text(
                            exact_base - value_base,
                            f"analytics.positions.{bucket.bucket_id}.{position.symbol}.rounding_residual",
                        ),
                        weight=canonical_decimal(
                            weight,
                            WEIGHT_SPEC,
                            f"analytics.positions.{bucket.bucket_id}.{position.symbol}.weight",
                        ),
                    ),
                    exact_base=exact_base,
                )
            )

    position_rows = tuple(build.row for build in position_builds)
    positions_by_bucket: dict[str, list[AnalyticsPositionRow]] = {}
    for row in position_rows:
        positions_by_bucket.setdefault(row.bucket_id, []).append(row)
    cash_by_bucket = {row.bucket_id: row for row in cash_rows}

    bucket_exposures: list[AnalyticsBucketExposure] = []
    for bucket in ledger.buckets:
        bridge_row = bridge_by_id[bucket.bucket_id]
        cash = cash_by_bucket[bucket.bucket_id]
        bucket_positions = positions_by_bucket.get(bucket.bucket_id, [])
        cash_base = Decimal(cash.value_base)
        position_value_base = _exact_sum(
            Decimal(row.value_base) for row in bucket_positions
        )
        reported = bridge_row.reported_base
        valuation_rounding = reported - cash_base - position_value_base
        if _money(valuation_rounding, "analytics.buckets.valuation_rounding") != (
            valuation_rounding
        ):
            _invariant(
                "bucket_exposure_rounding_mismatch",
                f"analytics.buckets.{bucket.bucket_id}.valuation_rounding",
            )
        bucket_exposures.append(
            AnalyticsBucketExposure(
                bucket_id=bucket.bucket_id,
                market=bucket.market,
                currency=bucket.currency,
                cash_base=canonical_decimal(
                    cash_base,
                    MONEY_SPEC,
                    f"analytics.buckets.{bucket.bucket_id}.cash_base",
                ),
                position_value_base=canonical_decimal(
                    position_value_base,
                    MONEY_SPEC,
                    f"analytics.buckets.{bucket.bucket_id}.position_value_base",
                ),
                valuation_rounding=canonical_decimal(
                    valuation_rounding,
                    MONEY_SPEC,
                    f"analytics.buckets.{bucket.bucket_id}.valuation_rounding",
                ),
                value_base=canonical_decimal(
                    reported,
                    MONEY_SPEC,
                    f"analytics.buckets.{bucket.bucket_id}.value_base",
                ),
                exact_value_base=_exact_text(
                    bridge_row.exact_base,
                    f"analytics.buckets.{bucket.bucket_id}.exact_value_base",
                ),
                rounding_residual=_exact_text(
                    bridge_row.residual,
                    f"analytics.buckets.{bucket.bucket_id}.rounding_residual",
                ),
                fx=cash.fx,
                provenance=_bucket_provenance(cash, bucket_positions),
            )
        )

    cash_base = _exact_sum(Decimal(row.value_base) for row in cash_rows)
    position_value_base = _exact_sum(
        Decimal(row.value_base) for row in position_rows
    )
    exact_cash_base = _exact_sum(
        Decimal(row.exact_value_base) for row in cash_rows
    )
    exact_position_base = _exact_sum(
        Decimal(build.exact_base) for build in position_builds
    )
    valuation_rounding = nav_base - cash_base - position_value_base
    if exact_cash_base + exact_position_base != exact_nav_base:
        _invariant(
            "analytics_exact_nav_mismatch",
            "analytics.exact_nav_base",
            "exact cash plus exact marked positions must equal the ledger exact NAV",
        )
    if cash_base + position_value_base + valuation_rounding != nav_base:
        _invariant("analytics_nav_bridge_mismatch", "analytics.nav_bridge")

    conversion_rows: list[AnalyticsConversionRow] = []
    conversion_rounding_base = Decimal(0)
    for index, event in enumerate(conversion_events):
        path = f"analytics.conversions[{index}]"
        fx, rate = _fx_reference(
            event.to_currency,
            base_currency,
            book,
            request.valuation_at,
            path=f"{path}.fx_rate_id",
        )
        residual_base = _exact_product(event.residual, rate)
        conversion_rounding_base += residual_base
        conversion_rows.append(
            AnalyticsConversionRow(
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
                valuation_fx=fx,
                rounding_residual_base=_exact_text(
                    residual_base,
                    f"{path}.rounding_residual_base",
                ),
            )
        )

    currency_exposures = _currency_exposures(
        bucket_exposures,
        nav_base=nav_base,
    )
    market_exposures = _market_exposures(bucket_exposures, nav_base=nav_base)
    sector_exposures = _sector_exposures(
        request,
        ledger,
        position_rows,
        position_value_base=position_value_base,
    )
    concentration = _concentration(position_rows, nav_base=nav_base)

    if _exact_sum(Decimal(row.value_base) for row in currency_exposures) != nav_base:
        _invariant("analytics_currency_nav_mismatch", "analytics.currency_exposures")
    if _exact_sum(Decimal(row.value_base) for row in market_exposures) != nav_base:
        _invariant("analytics_market_nav_mismatch", "analytics.market_exposures")
    if _exact_sum(Decimal(row.value_base) for row in sector_exposures) != (
        position_value_base
    ):
        _invariant("analytics_sector_value_mismatch", "analytics.sector_exposures")

    warnings: tuple[str, ...] = ()
    if nav_base <= 0:
        warnings = (
            "portfolio NAV is not positive; position weights and concentration are reported as zero",
        )

    benchmark = _benchmark(
        request,
        opening_ledger=opening_ledger,
        prepared=prepared,
        base_currency=base_currency,
        book=book,
        nav_base=nav_base,
        exact_nav_base=exact_nav_base,
    )
    if opening_ledger is None:
        _reject(
            "missing_attribution_input",
            "attribution.opening_ledger",
            detail="attribution needs the actual opening ledger",
        )
    if post_conversion_ledger is None:
        _reject(
            "missing_attribution_input",
            "attribution.post_conversion_ledger",
            detail="attribution needs the actual post-conversion ledger",
        )
    if plan is None:
        _reject(
            "missing_attribution_input",
            "attribution.plan",
            detail="attribution needs the executed order plan",
        )
    attribution = _attribution(
        request,
        prepared=prepared,
        opening_ledger=opening_ledger,
        post_conversion_ledger=post_conversion_ledger,
        end_ledger=ledger,
        conversion_events=conversion_events,
        fills=fills,
        rejected_orders=rejected_orders,
        canceled_orders=canceled_orders,
        plan=plan,
        cash_rows=cash_rows,
        position_rows=position_rows,
        valuation_rounding=valuation_rounding,
        nav_base=nav_base,
        exact_nav_base=exact_nav_base,
        book=book,
        marks=marks,
    )
    benchmark_fx = () if benchmark is None else (benchmark.start.fx, benchmark.end.fx)
    fx_references = tuple(
        reference
        for row in (*cash_rows, *position_rows)
        for reference in (row.fx,)
    ) + benchmark_fx + attribution.provenance.fx

    return PortfolioAnalytics(
        base_currency=base_currency,
        valuation_at=request.valuation_at,
        nav_base=canonical_decimal(nav_base, MONEY_SPEC, "analytics.nav_base"),
        cash_base=canonical_decimal(cash_base, MONEY_SPEC, "analytics.cash_base"),
        position_value_base=canonical_decimal(
            position_value_base,
            MONEY_SPEC,
            "analytics.position_value_base",
        ),
        valuation_rounding=canonical_decimal(
            valuation_rounding,
            MONEY_SPEC,
            "analytics.valuation_rounding",
        ),
        exact_nav_base=_exact_text(exact_nav_base, "analytics.exact_nav_base"),
        rounding_residual=_exact_text(
            exact_nav_base - nav_base,
            "analytics.rounding_residual",
        ),
        nav_bridge=AnalyticsNavBridge(
            cash_base=canonical_decimal(
                cash_base,
                MONEY_SPEC,
                "analytics.nav_bridge.cash_base",
            ),
            position_value_base=canonical_decimal(
                position_value_base,
                MONEY_SPEC,
                "analytics.nav_bridge.position_value_base",
            ),
            valuation_rounding=canonical_decimal(
                valuation_rounding,
                MONEY_SPEC,
                "analytics.nav_bridge.valuation_rounding",
            ),
            nav_base=canonical_decimal(
                nav_base,
                MONEY_SPEC,
                "analytics.nav_bridge.nav_base",
            ),
            exact_nav_base=_exact_text(
                exact_nav_base,
                "analytics.nav_bridge.exact_nav_base",
            ),
            rounding_residual=_exact_text(
                exact_nav_base - nav_base,
                "analytics.nav_bridge.rounding_residual",
            ),
            conversion_rounding_base=_exact_text(
                conversion_rounding_base,
                "analytics.nav_bridge.conversion_rounding_base",
            ),
        ),
        cash_rows=tuple(cash_rows),
        position_rows=position_rows,
        conversion_rows=tuple(conversion_rows),
        bucket_exposures=tuple(bucket_exposures),
        currency_exposures=currency_exposures,
        market_exposures=market_exposures,
        concentration=concentration,
        sector_exposures=sector_exposures,
        provenance=_provenance(
            (row.mark.price_date for row in position_rows),
            fx_references,
        ),
        benchmark=benchmark,
        attribution=attribution,
        warnings=warnings,
    )
