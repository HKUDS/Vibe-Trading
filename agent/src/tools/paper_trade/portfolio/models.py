"""Immutable typed values for the internal pt-v2.0 portfolio contract."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
)

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


class PortfolioModel(BaseModel):
    """Strict, frozen model configuration shared by every wire value."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class PortfolioPosition(PortfolioModel):
    symbol: NonEmptyString
    qty: int = Field(strict=True, ge=0)
    avg_cost: DecimalString
    currency: NonEmptyString


class FeeParameter(PortfolioModel):
    name: NonEmptyString
    value: DecimalString


class FeeModel(PortfolioModel):
    currency: NonEmptyString | None = None
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
    currency: NonEmptyString
    cash: DecimalString
    positions: tuple[PortfolioPosition, ...] = ()
    fee_model: FeeModel | None = None


class PortfolioState(PortfolioModel):
    buckets: tuple[PortfolioBucket, ...]


class MarketSession(PortfolioModel):
    market: Market
    status: Literal["open", "closed"]
    source: NonEmptyString
    as_of: AwareDatetime


class FxSnapshot(PortfolioModel):
    rate_id: NonEmptyString
    from_currency: NonEmptyString = Field(alias="from")
    to_currency: NonEmptyString = Field(alias="to")
    rate: DecimalString
    as_of: AwareDatetime
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
    currency: NonEmptyString
    side: Literal["buy", "sell"]
    qty: int = Field(strict=True, gt=0)
    limit: DecimalString | None = None


class TargetWeight(PortfolioModel):
    bucket_id: NonEmptyString
    symbol: NonEmptyString
    currency: NonEmptyString
    weight: DecimalString


class BenchmarkObservation(PortfolioModel):
    observed_at: AwareDatetime
    value: DecimalString
    currency: NonEmptyString
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
    base_currency: NonEmptyString
    trade_date: date
    planning_at: AwareDatetime
    valuation_at: AwareDatetime
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
    currency: NonEmptyString
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
    currency: NonEmptyString
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


class PortfolioResult(PortfolioModel):
    status: Literal["success"] = "success"
    tool: Literal["paper_trade_step"] = "paper_trade_step"
    schema_version: Literal["pt-v2.0"] = "pt-v2.0"
    mode: Literal["portfolio"] = "portfolio"
    account_id: NonEmptyString
    base_currency: NonEmptyString
    trade_date: date
    planning_at: AwareDatetime
    valuation_at: AwareDatetime
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


PortfolioDocument: TypeAlias = PortfolioResult | PortfolioErrorResult
