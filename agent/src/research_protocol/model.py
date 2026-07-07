"""Strongly typed research protocol models."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.reliability.data.contracts import DataSetContract


ProtocolStatus = Literal["draft", "registered", "retired"]
AssetClass = Literal["ashare", "us_equity", "hk_equity", "crypto", "futures", "macro", "other"]


class FilterSpec(BaseModel):
    """A canonical universe filter."""

    model_config = ConfigDict(allow_inf_nan=False)

    field: str
    op: Literal["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "between"]
    value_json: str

    @field_validator("value_json")
    @classmethod
    def _value_json_is_canonical_json(cls, value: str) -> str:
        try:
            json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("value_json must be valid JSON") from exc
        return value


class UniverseSpec(BaseModel):
    """Point-in-time research universe definition."""

    model_config = ConfigDict(allow_inf_nan=False, arbitrary_types_allowed=False)

    asset_class: AssetClass
    universe_name: str | None = None
    symbols: list[str] | None = None
    historical_membership_source: str | None = None
    point_in_time: bool = False
    filters: list[FilterSpec] = Field(default_factory=list)


class SplitSpec(BaseModel):
    """Train/validation/test split policy."""

    model_config = ConfigDict(allow_inf_nan=False)

    method: Literal["holdout", "walk_forward", "rolling", "expanding"]
    train_start: date | None = None
    train_end: date | None = None
    validation_start: date | None = None
    validation_end: date | None = None
    test_start: date | None = None
    test_end: date | None = None
    fold_count: int | None = None
    min_effective_folds: int | None = None


class BenchmarkSpec(BaseModel):
    """Benchmark policy for alpha/tradability claims."""

    model_config = ConfigDict(allow_inf_nan=False)

    primary: str
    comparators: list[str] = Field(default_factory=list)
    source: str | None = None
    pit_membership_required: bool = True
    rebalance_frequency: str | None = None


class CostModelSpec(BaseModel):
    """Transaction cost and stress assumptions."""

    model_config = ConfigDict(allow_inf_nan=False)

    commission_bps: float | None = None
    slippage_bps: float | None = None
    spread_bps: float | None = None
    tax_bps: float | None = None
    min_fee: float | None = None
    borrow_fee_bps: float | None = None
    stress_bps: list[float] = Field(default_factory=lambda: [0, 5, 10, 25, 50, 100])


class ExecutionAssumptions(BaseModel):
    """Execution timing and fill assumptions."""

    model_config = ConfigDict(allow_inf_nan=False)

    signal_time_field: str | None = None
    decision_delay: str | None = None
    order_type: str | None = None
    fill_price: str | None = None
    allow_partial_fill: bool = True
    liquidity_cap_adv_pct: float | None = None


class EvaluationPlan(BaseModel):
    """Metrics and anti-overfit validation plan."""

    model_config = ConfigDict(allow_inf_nan=False)

    metrics: list[str]
    oos_required: bool = True
    ic_horizons: list[int] = Field(default_factory=lambda: [1, 5, 20])
    regime_label_artifact_ref: str | None = None
    min_walk_forward_folds: int | None = None
    neutralization: Literal["none", "industry", "size", "industry_size"] = "none"
    random_control_required: bool = True
    regime_tests_required: bool = False
    crowding_tests_required: bool = False


class ResearchProtocol(BaseModel):
    """A typed research experiment design."""

    model_config = ConfigDict(allow_inf_nan=False, arbitrary_types_allowed=False)

    protocol_id: str
    protocol_hash: str = ""
    schema_version: str
    status: ProtocolStatus = "draft"
    goal_id: str | None = None
    session_id: str | None = None
    hypothesis_id: str | None = None
    hypothesis: str
    universe: UniverseSpec
    data_requirements: list[DataSetContract]
    split_policy: SplitSpec
    benchmark_policy: BenchmarkSpec | None = None
    cost_model: CostModelSpec | None = None
    execution_assumptions: ExecutionAssumptions | None = None
    evaluation_plan: EvaluationPlan
    created_at: datetime
    registered_at: datetime | None = None
    created_by: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _reject_non_json_values(cls, value: Any) -> Any:
        _reject_pandas_or_nonfinite(value, path="$")
        return value

    @field_validator("created_at", "registered_at")
    @classmethod
    def _datetime_must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime fields must be timezone-aware")
        return value.astimezone(timezone.utc)


def _reject_pandas_or_nonfinite(value: Any, *, path: str) -> None:
    module = type(value).__module__
    name = type(value).__name__
    if module.startswith("pandas.") and name in {"DataFrame", "Series"}:
        raise ValueError(f"{path}: pandas objects are not allowed in ResearchProtocol")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path}: floats must be finite")
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_pandas_or_nonfinite(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple, set)):
        for index, item in enumerate(value):
            _reject_pandas_or_nonfinite(item, path=f"{path}[{index}]")
