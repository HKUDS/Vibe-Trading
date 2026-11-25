"""Immutable typed values for the internal pt-v2.0 portfolio contract."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
)
from pydantic_core import PydanticCustomError

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]
DecimalString: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$"),
]
NonEmptyString: TypeAlias = Annotated[str, StringConstraints(min_length=1)]
Market: TypeAlias = Literal["cn_a", "hk", "us"]
Currency: TypeAlias = Literal["CNY", "HKD", "USD"]


def _wire_datetime(value: JsonValue | datetime) -> JsonValue | datetime:
    """Reject non-string JSON timestamps while accepting parsed datetimes."""
    if isinstance(value, str | datetime):
        return value
    raise PydanticCustomError("invalid_timestamp", "Timestamp must be a string")


WireDatetime: TypeAlias = Annotated[AwareDatetime, BeforeValidator(_wire_datetime)]


class PortfolioModel(BaseModel):
    """Strict, frozen model configuration shared by every wire value."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class PortfolioPosition(PortfolioModel):
    symbol: NonEmptyString
    qty: int = Field(strict=True, ge=0)
    avg_cost: DecimalString
    currency: Currency


class FeeParameter(PortfolioModel):
    name: NonEmptyString
    value: DecimalString


class FeeModel(PortfolioModel):
    currency: Currency | None = None
    parameters: tuple[FeeParameter, ...] = Field(min_length=1)

    @field_validator("parameters", mode="before")
    @classmethod
    def freeze_parameters(cls, value: JsonValue) -> JsonValue | tuple[JsonObject, ...]:
        """Convert the public object into an immutable, sorted parameter tuple."""
        if isinstance(value, dict):
            return tuple(
                {"name": name, "value": parameter}
                for name, parameter in sorted(value.items())
            )
        return value

    @field_serializer("parameters")
    def serialize_parameters(self, parameters: tuple[FeeParameter, ...]) -> dict[str, str]:
        return {parameter.name: parameter.value for parameter in parameters}


class PortfolioBucket(PortfolioModel):
    bucket_id: NonEmptyString
    market: Market
    currency: Currency
    cash: DecimalString
    positions: tuple[PortfolioPosition, ...]
    fee_model: FeeModel | None = None


class PortfolioState(PortfolioModel):
    buckets: tuple[PortfolioBucket, ...] = Field(min_length=1)


class MarketSession(PortfolioModel):
    market: Market
    status: Literal["open", "closed"]
    source: NonEmptyString
    as_of: WireDatetime


class FxSnapshot(PortfolioModel):
    rate_id: NonEmptyString
    from_currency: Currency = Field(alias="from")
    to_currency: Currency = Field(alias="to")
    rate: DecimalString
    as_of: WireDatetime
    source: NonEmptyString


class FxConversion(PortfolioModel):
    rate_id: NonEmptyString
    from_bucket_id: NonEmptyString
    to_bucket_id: NonEmptyString
    amount: DecimalString


class PortfolioOrder(PortfolioModel):
    order_id: NonEmptyString
    bucket_id: NonEmptyString
    symbol: NonEmptyString
    currency: Currency
    side: Literal["buy", "sell"]
    qty: int = Field(strict=True, gt=0)
    limit: DecimalString | None = None


class TargetWeight(PortfolioModel):
    bucket_id: NonEmptyString
    symbol: NonEmptyString
    currency: Currency
    weight: DecimalString


class BenchmarkObservation(PortfolioModel):
    observed_at: WireDatetime
    value: DecimalString
    currency: Currency
    rate_id: NonEmptyString | None = None


class BenchmarkInput(PortfolioModel):
    benchmark_id: NonEmptyString
    start: BenchmarkObservation
    end: BenchmarkObservation


class SectorInput(PortfolioModel):
    bucket_id: NonEmptyString
    symbol: NonEmptyString
    sector: NonEmptyString


class ExplicitOrdersPlan(PortfolioModel):
    kind: Literal["orders"] = "orders"
    orders: tuple[PortfolioOrder, ...]


class TargetWeightsPlan(PortfolioModel):
    kind: Literal["target_weights"] = "target_weights"
    target_weights: tuple[TargetWeight, ...]
    rebalance_band: DecimalString = "0"


PortfolioPlan: TypeAlias = ExplicitOrdersPlan | TargetWeightsPlan


class PortfolioRequest(PortfolioModel):
    tool: Literal["paper_trade_step"]
    schema_version: Literal["pt-v2.0"]
    mode: Literal["portfolio"]
    account_id: NonEmptyString
    base_currency: Currency
    trade_date: date
    planning_at: WireDatetime
    valuation_at: WireDatetime
    interval: Literal["1d"] = "1d"
    fill_model: Literal["all_or_none"] = "all_or_none"
    portfolio_state: PortfolioState
    sessions: tuple[MarketSession, ...]
    fx_snapshots: tuple[FxSnapshot, ...] = ()
    fx_conversions: tuple[FxConversion, ...] = ()
    orders: tuple[PortfolioOrder, ...] | None = None
    target_weights: tuple[TargetWeight, ...] | None = None
    rebalance_band: DecimalString = "0"
    benchmark: BenchmarkInput | None = None
    sectors: tuple[SectorInput, ...] = ()

    @property
    def plan(self) -> PortfolioPlan:
        """Expose the orders-XOR-target-weights branch as a discriminated union."""
        if self.orders is not None:
            return ExplicitOrdersPlan(orders=self.orders)
        assert self.target_weights is not None
        return TargetWeightsPlan(
            target_weights=self.target_weights,
            rebalance_band=self.rebalance_band,
        )


class PortfolioIssue(PortfolioModel):
    reason: NonEmptyString
    path: NonEmptyString
    detail: NonEmptyString
    bucket_id: NonEmptyString | None = None


class PortfolioErrorResult(PortfolioModel):
    status: Literal["error"] = "error"
    tool: Literal["paper_trade_step"] = "paper_trade_step"
    schema_version: Literal["pt-v2.0"] = "pt-v2.0"
    mode: Literal["portfolio"] = "portfolio"
    account_id: str
    code: Literal["INVALID_REQUEST", "PAPER_DATA_NOT_READY"]
    error: PortfolioIssue


class OrderEvent(PortfolioModel):
    plan_order_id: NonEmptyString
    bucket_id: NonEmptyString
    symbol: NonEmptyString
    currency: Currency
    side: Literal["buy", "sell"]
    qty: int = Field(strict=True, gt=0)
    trade_date: date


class PortfolioFill(OrderEvent):
    price: DecimalString
    fee: DecimalString


class PortfolioRejectedOrder(OrderEvent):
    reason_code: NonEmptyString
    detail: str


class PortfolioCanceledOrder(OrderEvent):
    reason_code: NonEmptyString
    detail: str


class BucketResult(PortfolioModel):
    bucket_id: NonEmptyString
    market: Market
    currency: Currency
    session: MarketSession
    cash: DecimalString
    position_value: DecimalString
    nav_base: DecimalString
    fx_rate_id: NonEmptyString | None = None


class PortfolioHashes(PortfolioModel):
    plan_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    planning_data_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    execution_data_fingerprint: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    document_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class AnalyticsMarkReference(PortfolioModel):
    """One dated valuation mark, never an inferred or carried-forward guess."""

    price_date: date
    source: NonEmptyString
    as_of: WireDatetime


class AnalyticsFxReference(PortfolioModel):
    """One direct FX pair (or the explicit base-currency identity) used here."""

    rate_id: NonEmptyString
    from_currency: Currency
    to_currency: Currency
    rate: DecimalString
    as_of: WireDatetime
    source: NonEmptyString


class AnalyticsProvenance(PortfolioModel):
    """Dated marks and direct pairs behind one aggregate analytics value."""

    price_dates: tuple[date, ...]
    fx: tuple[AnalyticsFxReference, ...]


class AnalyticsCashRow(PortfolioModel):
    """One bucket's local cash translated through its declared direct pair."""

    bucket_id: NonEmptyString
    market: Market
    currency: Currency
    valuation_date: date
    amount: DecimalString
    fx: AnalyticsFxReference
    value_base: DecimalString
    exact_value_base: DecimalString
    rounding_residual: DecimalString


class AnalyticsPositionRow(PortfolioModel):
    """One held position's marked value, FX translation and NAV weight."""

    bucket_id: NonEmptyString
    market: Market
    currency: Currency
    symbol: NonEmptyString
    qty: int = Field(strict=True, ge=0)
    price: DecimalString
    mark: AnalyticsMarkReference
    local_value: DecimalString
    fx: AnalyticsFxReference
    value_base: DecimalString
    exact_value_base: DecimalString
    rounding_residual: DecimalString
    weight: DecimalString


class AnalyticsConversionRow(PortfolioModel):
    """One settled conversion's exact amount and explicit rounding evidence."""

    rate_id: NonEmptyString
    from_bucket_id: NonEmptyString
    to_bucket_id: NonEmptyString
    from_currency: Currency
    to_currency: Currency
    source_amount: DecimalString
    rate: DecimalString
    exact_converted: DecimalString
    converted_amount: DecimalString
    rounding_residual_local: DecimalString
    valuation_fx: AnalyticsFxReference
    rounding_residual_base: DecimalString


class AnalyticsBucketExposure(PortfolioModel):
    """One bucket's cash, marked positions and the residual from rounding."""

    bucket_id: NonEmptyString
    market: Market
    currency: Currency
    cash_base: DecimalString
    position_value_base: DecimalString
    valuation_rounding: DecimalString
    value_base: DecimalString
    exact_value_base: DecimalString
    rounding_residual: DecimalString
    fx: AnalyticsFxReference
    provenance: AnalyticsProvenance


class AnalyticsCurrencyExposure(PortfolioModel):
    """One settlement currency's share of base NAV."""

    currency: Currency
    cash_base: DecimalString
    position_value_base: DecimalString
    valuation_rounding: DecimalString
    value_base: DecimalString
    weight: DecimalString
    bucket_ids: tuple[NonEmptyString, ...]
    provenance: AnalyticsProvenance


class AnalyticsMarketExposure(PortfolioModel):
    """One canonical market's share of base NAV."""

    market: Market
    cash_base: DecimalString
    position_value_base: DecimalString
    valuation_rounding: DecimalString
    value_base: DecimalString
    weight: DecimalString
    bucket_ids: tuple[NonEmptyString, ...]
    provenance: AnalyticsProvenance


class AnalyticsPositionWeight(PortfolioModel):
    """One position's base value and its share of NAV."""

    bucket_id: NonEmptyString
    symbol: NonEmptyString
    value_base: DecimalString
    weight: DecimalString


class AnalyticsConcentration(PortfolioModel):
    """Top-1/top-5/HHI over position value divided by base NAV."""

    position_count: int = Field(strict=True, ge=0)
    top_1: DecimalString
    top_5: DecimalString
    hhi: DecimalString
    position_weights: tuple[AnalyticsPositionWeight, ...]
    provenance: AnalyticsProvenance


class AnalyticsSectorExposure(PortfolioModel):
    """Caller-declared sector value, including the explicit unclassified bucket."""

    sector: NonEmptyString
    value_base: DecimalString
    weight_of_positions: DecimalString
    bucket_ids: tuple[NonEmptyString, ...]
    symbols: tuple[NonEmptyString, ...]
    provenance: AnalyticsProvenance


class AnalyticsBenchmarkObservation(PortfolioModel):
    """One caller-declared benchmark level with its direct-pair translation."""

    observed_at: WireDatetime
    value: DecimalString
    currency: Currency
    value_base: DecimalString
    exact_value_base: DecimalString
    rounding_residual: DecimalString
    fx: AnalyticsFxReference


class AnalyticsBenchmark(PortfolioModel):
    """One-day benchmark return, portfolio return and their exact deviation."""

    benchmark_id: NonEmptyString
    start: AnalyticsBenchmarkObservation
    end: AnalyticsBenchmarkObservation
    benchmark_return: DecimalString
    exact_benchmark_return: DecimalString
    portfolio_start_nav_base: DecimalString
    portfolio_start_exact_nav_base: DecimalString
    portfolio_start_rounding_residual: DecimalString
    portfolio_end_nav_base: DecimalString
    portfolio_end_exact_nav_base: DecimalString
    portfolio_return: DecimalString
    exact_portfolio_return: DecimalString
    deviation: DecimalString
    exact_deviation: DecimalString


class AnalyticsAttributionNav(PortfolioModel):
    """Opening and ending exact NAV around one completed trading day."""

    start_at: WireDatetime
    end_at: WireDatetime
    start_nav_base: DecimalString
    start_exact_nav_base: DecimalString
    start_rounding_residual: DecimalString
    end_nav_base: DecimalString
    end_exact_nav_base: DecimalString
    end_rounding_residual: DecimalString
    nav_change_reported: DecimalString
    nav_change_exact: DecimalString


class AnalyticsSymbolContribution(PortfolioModel):
    """One instrument's market, currency and trade-cash contribution."""

    bucket_id: NonEmptyString
    market: Market
    currency: Currency
    symbol: NonEmptyString
    opening_qty: int = Field(strict=True, ge=0)
    ending_qty: int = Field(strict=True, ge=0)
    traded_qty: int = Field(strict=True)
    opening_price: DecimalString
    ending_price: DecimalString
    opening_mark: AnalyticsMarkReference
    ending_mark: AnalyticsMarkReference
    opening_fx: AnalyticsFxReference
    ending_fx: AnalyticsFxReference
    opening_local_value: DecimalString
    ending_local_value: DecimalString
    opening_value_base: DecimalString
    ending_value_base: DecimalString
    trade_cash_base: DecimalString
    market_contribution_base: DecimalString
    currency_contribution_base: DecimalString
    total_contribution_base: DecimalString
    outcome: Literal["unchanged", "opened", "increased", "reduced", "closed"]


class AnalyticsCashFxEffect(PortfolioModel):
    """One bucket's opening-cash FX revaluation, explicitly valued at both ends."""

    bucket_id: NonEmptyString
    market: Market
    currency: Currency
    opening_cash: DecimalString
    ending_cash: DecimalString
    opening_fx: AnalyticsFxReference
    ending_fx: AnalyticsFxReference
    cash_fx_effect_base: DecimalString


class AnalyticsConversionEffect(PortfolioModel):
    """One settled conversion's source, target and conversion-rounding effects."""

    rate_id: NonEmptyString
    from_bucket_id: NonEmptyString
    to_bucket_id: NonEmptyString
    from_currency: Currency
    to_currency: Currency
    source_amount: DecimalString
    rate: DecimalString
    exact_converted: DecimalString
    converted_amount: DecimalString
    rounding_residual_local: DecimalString
    source_fx: AnalyticsFxReference
    target_fx: AnalyticsFxReference
    source_effect_base: DecimalString
    target_effect_base: DecimalString
    conversion_effect_base: DecimalString
    rounding_loss_base: DecimalString


class AnalyticsFeeEffect(PortfolioModel):
    """One fill's local fee translated to a signed base-currency effect."""

    plan_order_id: NonEmptyString
    bucket_id: NonEmptyString
    symbol: NonEmptyString
    side: Literal["buy", "sell"]
    qty: int = Field(strict=True, gt=0)
    execution_price: DecimalString
    fee_local: DecimalString
    fx: AnalyticsFxReference
    fee_effect_base: DecimalString


class AnalyticsExecutionRounding(PortfolioModel):
    """One fill's exact notional versus its two-decimal execution cash notional."""

    plan_order_id: NonEmptyString
    bucket_id: NonEmptyString
    symbol: NonEmptyString
    side: Literal["buy", "sell"]
    qty: int = Field(strict=True, gt=0)
    execution_price: DecimalString
    exact_notional_local: DecimalString
    notional_local: DecimalString
    rounding_local: DecimalString
    fx: AnalyticsFxReference
    rounding_effect_base: DecimalString


class AnalyticsMarketContribution(PortfolioModel):
    """One canonical market's complete one-day contribution view."""

    market: Market
    position_contribution_base: DecimalString
    cash_fx_effect_base: DecimalString
    conversion_effect_base: DecimalString
    fee_effect_base: DecimalString
    total_contribution_base: DecimalString
    bucket_ids: tuple[NonEmptyString, ...]


class AnalyticsCurrencyContribution(PortfolioModel):
    """One settlement currency's complete one-day contribution view."""

    currency: Currency
    position_contribution_base: DecimalString
    cash_fx_effect_base: DecimalString
    conversion_effect_base: DecimalString
    fee_effect_base: DecimalString
    total_contribution_base: DecimalString
    bucket_ids: tuple[NonEmptyString, ...]


class AnalyticsWeightRow(PortfolioModel):
    """One instrument's target, planned and realized weight tie-out."""

    bucket_id: NonEmptyString
    market: Market
    currency: Currency
    symbol: NonEmptyString
    target_weight: DecimalString | None = None
    planned_weight: DecimalString
    planned_at_end_weight: DecimalString
    realized_weight: DecimalString
    target_gap: DecimalString | None = None
    lot_gap: DecimalString
    price_gap: DecimalString
    reject_gap: DecimalString
    planned_value_base: DecimalString
    planned_at_end_value_base: DecimalString
    realized_value_base: DecimalString
    planned_qty: int = Field(strict=True, ge=0)
    realized_qty: int = Field(strict=True, ge=0)
    qty_gap: int = Field(strict=True)
    outcome: Literal["filled", "rejected", "canceled", "not_ordered"]


class AnalyticsWeightReconciliation(PortfolioModel):
    """Target/planned/realized weights plus their declared rounding residual."""

    planning_nav_base: DecimalString
    planning_exact_nav_base: DecimalString
    planning_rounding_residual: DecimalString
    target_weight_total: DecimalString | None = None
    target_cash_weight: DecimalString | None = None
    planned_weight_total: DecimalString
    planned_cash_weight: DecimalString
    realized_weight_total: DecimalString
    realized_cash_weight: DecimalString
    valuation_rounding_weight: DecimalString
    lot_gap_total: DecimalString
    price_gap_total: DecimalString
    reject_gap_total: DecimalString
    cash_gap: DecimalString
    weight_rounding_residual: DecimalString
    weight_rounding_tolerance: DecimalString
    reconciled: bool
    weight_basis: Literal["planning_marks"] = "planning_marks"
    realized_weight_status: Literal["end_ledger_valuation"] = "end_ledger_valuation"
    rows: tuple[AnalyticsWeightRow, ...]


class AnalyticsReconciliationCheck(PortfolioModel):
    """One named attribution check and its deterministic verdict."""

    name: NonEmptyString
    passed: bool
    detail: str = ""


class AnalyticsAttributionReconciliation(PortfolioModel):
    """Explicit reconciliation verdict; a falsy result is never a success."""

    reconciled: bool
    checks: tuple[AnalyticsReconciliationCheck, ...]
    issues: tuple[PortfolioIssue, ...]
    not_verified: tuple[str, ...]


class AnalyticsAttribution(PortfolioModel):
    """Optional exact one-day contribution, FX and weight-gap evidence."""

    scope: Literal["one_day"] = "one_day"
    formula_version: Literal["pt-attribution-v1"] = "pt-attribution-v1"
    base_currency: Currency
    nav: AnalyticsAttributionNav
    symbol_contributions: tuple[AnalyticsSymbolContribution, ...]
    cash_fx_effects: tuple[AnalyticsCashFxEffect, ...]
    conversion_effects: tuple[AnalyticsConversionEffect, ...]
    fee_effects: tuple[AnalyticsFeeEffect, ...]
    execution_rounding: tuple[AnalyticsExecutionRounding, ...]
    market_contributions: tuple[AnalyticsMarketContribution, ...]
    currency_contributions: tuple[AnalyticsCurrencyContribution, ...]
    position_contribution_base: DecimalString
    cash_fx_effect_base: DecimalString
    conversion_effect_base: DecimalString
    fee_effect_base: DecimalString
    rounding_residual: DecimalString
    expected_rounding_residual: DecimalString
    weights: AnalyticsWeightReconciliation
    reconciliation: AnalyticsAttributionReconciliation
    provenance: AnalyticsProvenance


class AnalyticsNavBridge(PortfolioModel):
    """Cash plus marked positions plus explicit valuation rounding equals NAV."""

    cash_base: DecimalString
    position_value_base: DecimalString
    valuation_rounding: DecimalString
    nav_base: DecimalString
    exact_nav_base: DecimalString
    rounding_residual: DecimalString
    conversion_rounding_base: DecimalString


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_none(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_drop_none(item) for item in value]
    return value


class PortfolioAnalytics(PortfolioModel):
    """Optional exact post-valuation evidence attached to a portfolio step."""

    base_currency: Currency
    valuation_at: WireDatetime
    nav_base: DecimalString
    cash_base: DecimalString
    position_value_base: DecimalString
    valuation_rounding: DecimalString
    exact_nav_base: DecimalString
    rounding_residual: DecimalString
    nav_bridge: AnalyticsNavBridge
    cash_rows: tuple[AnalyticsCashRow, ...]
    position_rows: tuple[AnalyticsPositionRow, ...]
    conversion_rows: tuple[AnalyticsConversionRow, ...]
    bucket_exposures: tuple[AnalyticsBucketExposure, ...]
    currency_exposures: tuple[AnalyticsCurrencyExposure, ...]
    market_exposures: tuple[AnalyticsMarketExposure, ...]
    concentration: AnalyticsConcentration
    sector_exposures: tuple[AnalyticsSectorExposure, ...]
    provenance: AnalyticsProvenance
    benchmark: AnalyticsBenchmark | None = None
    attribution: AnalyticsAttribution | None = None
    warnings: tuple[str, ...] = ()
    unclassified_sector: Literal["unclassified"] = "unclassified"


class PortfolioResult(PortfolioModel):
    status: Literal["success"] = "success"
    tool: Literal["paper_trade_step"] = "paper_trade_step"
    schema_version: Literal["pt-v2.0"] = "pt-v2.0"
    mode: Literal["portfolio"] = "portfolio"
    account_id: NonEmptyString
    base_currency: Currency
    trade_date: date
    planning_at: WireDatetime
    valuation_at: WireDatetime
    opening_portfolio: PortfolioState
    post_conversion_portfolio: PortfolioState
    end_portfolio: PortfolioState
    sessions: tuple[MarketSession, ...]
    conversions: tuple[FxConversion, ...]
    plan: PortfolioPlan
    bucket_results: tuple[BucketResult, ...]
    fills: tuple[PortfolioFill, ...]
    rejected_orders: tuple[PortfolioRejectedOrder, ...]
    canceled_orders: tuple[PortfolioCanceledOrder, ...]
    warnings: tuple[str, ...]
    errors: tuple[PortfolioIssue, ...]
    complete: bool
    hashes: PortfolioHashes
    analytics: PortfolioAnalytics | None = None

    @field_serializer("analytics", when_used="json")
    def serialize_analytics(
        self,
        analytics: PortfolioAnalytics | None,
    ) -> dict[str, Any] | None:
        """Keep the new analytics shape explicit while old documents omit it."""
        if analytics is None:
            return None
        omit_none = analytics.benchmark is None and "benchmark" not in (
            analytics.model_fields_set
        )
        dumped = analytics.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=omit_none,
        )
        attribution = dumped.pop("attribution", None)
        if attribution is not None or "attribution" in analytics.model_fields_set:
            dumped["attribution"] = _drop_none(attribution)
        return dumped


PortfolioDocument: TypeAlias = PortfolioResult | PortfolioErrorResult
