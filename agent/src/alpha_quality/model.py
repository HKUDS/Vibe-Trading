from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from typing import Any, Literal

import numpy as np
import pandas as pd


FEATURE_FLAGS = {
    "VIBE_TRADING_AGS_ENABLED": False,
    "VIBE_TRADING_ALPHA_SCORECARD": False,
    "VIBE_TRADING_TRIAL_LEDGER": False,
    "VIBE_TRADING_ALPHA_FOUNDRY": False,
    "VIBE_TRADING_ADMISSION_GATE": False,
    "VIBE_TRADING_FORWARD_TRACKING": False,
    "VIBE_TRADING_ALPHA_REPORT_API": False,
}

ScorecardScope = Literal["discovery", "final_quality_decision"]


def _safe_json_value(value: Any) -> Any:
    if is_dataclass(value):
        return _safe_json_value(asdict(value))
    if isinstance(value, dict):
        return {str(k): _safe_json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json_value(v) for v in value]
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _safe_json_value(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


@dataclass(frozen=True)
class FactorOutputFrame:
    factor_id: str
    formula: str
    factor: pd.DataFrame
    valid_mask: pd.DataFrame
    tradable_mask: pd.DataFrame
    universe_mask: pd.DataFrame
    metadata: dict[str, Any]
    factor_definition_hash: str

    def aligned(self, returns: pd.DataFrame) -> "FactorOutputFrame":
        dates = self.factor.index.intersection(returns.index)
        symbols = self.factor.columns.intersection(returns.columns)
        return FactorOutputFrame(
            factor_id=self.factor_id,
            formula=self.formula,
            factor=self.factor.loc[dates, symbols],
            valid_mask=self.valid_mask.loc[dates, symbols],
            tradable_mask=self.tradable_mask.loc[dates, symbols],
            universe_mask=self.universe_mask.loc[dates, symbols],
            metadata=dict(self.metadata),
            factor_definition_hash=self.factor_definition_hash,
        )


@dataclass(frozen=True)
class SplitConfig:
    train: tuple[str, str]
    valid: tuple[str, str]
    test: tuple[str, str] | None = None

    def mask_for(self, index: pd.Index, split: Literal["train", "valid", "test"]) -> pd.Series:
        bounds = getattr(self, split)
        if bounds is None:
            return pd.Series(False, index=index)
        start, end = pd.Timestamp(bounds[0]), pd.Timestamp(bounds[1])
        ts_index = pd.DatetimeIndex(index)
        return pd.Series((ts_index >= start) & (ts_index <= end), index=index)


@dataclass(frozen=True)
class ICMetricSummary:
    horizon: int
    rank_ic_mean: float | None
    rank_ic_std: float | None
    rank_icir: float | None
    t_stat: float | None
    t_stat_method: str
    n_obs: int


@dataclass(frozen=True)
class HorizonSplitMetrics:
    horizon: int
    by_split: dict[str, ICMetricSummary]


@dataclass(frozen=True)
class PredictiveMetrics:
    by_horizon: dict[int, HorizonSplitMetrics]


@dataclass(frozen=True)
class CoverageMetrics:
    by_date: dict[str, float]
    mean_coverage: float | None


@dataclass(frozen=True)
class ExecutionMetrics:
    uses_execution_return: bool
    return_mean: float | None = None
    turnover_mean: float | None = None
    cost_bps_mean: float | None = None


@dataclass(frozen=True)
class AlphaQualityScorecard:
    schema_version: str = "alpha_quality_scorecard.v1"
    factor_id: str = ""
    formula: str = ""
    factor_definition_hash: str = ""
    scope: ScorecardScope = "discovery"
    horizons: list[int] = field(default_factory=list)
    predictive: PredictiveMetrics | None = None
    coverage: CoverageMetrics | None = None
    execution: ExecutionMetrics | None = None
    data_snapshot_ref: str | None = None
    trial_ledger_ref: str | None = None
    warnings: list[str] = field(default_factory=list)
    hard_failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _safe_json_value(asdict(self))

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
