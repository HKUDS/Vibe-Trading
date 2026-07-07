from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest
from pydantic import ValidationError

from src.research_protocol.model import (
    BenchmarkSpec,
    CostModelSpec,
    DataSetContract,
    EvaluationPlan,
    ExecutionAssumptions,
    FilterSpec,
    ResearchProtocol,
    SplitSpec,
    UniverseSpec,
)


def make_protocol(**updates) -> ResearchProtocol:
    payload = {
        "protocol_id": "proto_fixture",
        "schema_version": "1.0.0",
        "status": "draft",
        "goal_id": "goal_abc",
        "session_id": "session_abc",
        "hypothesis_id": "hyp_abc",
        "hypothesis": "CSI300 short-term reversal has positive next-day IC.",
        "universe": UniverseSpec(
            asset_class="ashare",
            universe_name="csi300",
            point_in_time=True,
            filters=[FilterSpec(field="is_st", op="eq", value_json="false")],
        ),
        "data_requirements": [
            DataSetContract(
                dataset_id="tushare:ohlcv:1D",
                asset_class="ashare",
                frequency="1D",
                calendar="SSE",
                fields=["open", "high", "low", "close", "volume"],
                timezone="Asia/Shanghai",
                survivorship_policy="historical_membership",
            )
        ],
        "split_policy": SplitSpec(
            method="walk_forward",
            train_start="2020-01-01",
            train_end="2021-12-31",
            test_start="2022-01-01",
            test_end="2023-12-31",
            fold_count=6,
            min_effective_folds=4,
        ),
        "benchmark_policy": BenchmarkSpec(primary="000300.SH", source="tushare"),
        "cost_model": CostModelSpec(commission_bps=3.0, slippage_bps=5.0, tax_bps=10.0),
        "execution_assumptions": ExecutionAssumptions(
            signal_time_field="close",
            decision_delay="1D",
            order_type="market",
            fill_price="next_open",
        ),
        "evaluation_plan": EvaluationPlan(
            metrics=["rank_ic", "icir"],
            min_walk_forward_folds=4,
            neutralization="industry_size",
            regime_tests_required=True,
            crowding_tests_required=True,
        ),
        "created_at": datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc),
        "created_by": "tester",
    }
    payload.update(updates)
    return ResearchProtocol(**payload)


def test_protocol_json_roundtrip() -> None:
    protocol = make_protocol()

    reloaded = ResearchProtocol.model_validate_json(protocol.model_dump_json())

    assert reloaded == protocol
    assert isinstance(reloaded.universe, UniverseSpec)
    assert isinstance(reloaded.split_policy, SplitSpec)
    assert isinstance(reloaded.evaluation_plan, EvaluationPlan)
    assert reloaded.evaluation_plan.ic_horizons == [1, 5, 20]
    assert reloaded.evaluation_plan.random_control_required is True


def test_registered_protocol_requires_timezone_aware_datetime() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        make_protocol(status="registered", registered_at=datetime(2026, 7, 6, 12, 0))


def test_protocol_rejects_dataframe_or_series_fields() -> None:
    with pytest.raises(ValidationError, match="pandas"):
        make_protocol(metadata={"labels": pd.Series([1, 2, 3])})

    with pytest.raises(ValidationError, match="pandas"):
        make_protocol(metadata={"frame": pd.DataFrame({"x": [1]})})
