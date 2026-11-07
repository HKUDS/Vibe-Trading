"""Bounded experiment requests; unknown settings fail at every entry point."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CostScenario(RequestModel):
    name: str = Field(min_length=1, max_length=80)
    fee_multiplier: float = Field(default=1, ge=0, le=100)
    extra_slippage_bps: float = Field(default=0, ge=0, lt=10000)


class CostRequest(RequestModel):
    run_dir: str = Field(min_length=1, max_length=4096)
    scenarios: list[CostScenario] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_names(self):
        if len({row.name for row in self.scenarios}) != len(self.scenarios):
            raise ValueError("scenario names must be distinct")
        return self


class Candidate(RequestModel):
    name: str = Field(min_length=1, max_length=80)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def finite_scalar_parameters(self):
        if len(self.parameters) > 20:
            raise ValueError("at most 20 constructor parameters are supported")
        for name, value in self.parameters.items():
            if not name.isidentifier() or name.startswith("_"):
                raise ValueError("parameter names must be public Python identifiers")
            if value is not None and not isinstance(value, (int, float, str, bool)):
                raise ValueError("constructor parameters must be JSON scalars")
            if isinstance(value, (int, float)) and not math.isfinite(value):
                raise ValueError("constructor parameters must be finite")
        return self


class WalkForwardRequest(RequestModel):
    run_dir: str = Field(min_length=1, max_length=4096)
    candidates: list[Candidate] = Field(min_length=1, max_length=12)
    train_bars: int = Field(ge=5, le=100000)
    test_bars: int = Field(ge=2, le=10000)
    holdout_bars: int = Field(default=0, ge=0, le=10000)
    max_folds: int = Field(default=5, ge=1, le=12)
    objective: Literal["sharpe", "total_return"] = "sharpe"
    training: Literal["rolling", "expanding"] = "rolling"

    @model_validator(mode="after")
    def unique_candidates(self):
        if len({row.name for row in self.candidates}) != len(self.candidates):
            raise ValueError("candidate names must be distinct")
        return self


class AuditRequest(RequestModel):
    alpha_ids: list[str] | None = Field(default=None, min_length=1, max_length=600)


class ReplayRequest(RequestModel):
    run_dir: str = Field(min_length=1, max_length=4096)
    case_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)
    trace_dir: str | None = Field(default=None, max_length=4096)


REQUEST_MODELS = {
    "cost_sensitivity": CostRequest,
    "walk_forward": WalkForwardRequest,
    "factor_audit": AuditRequest,
    "replay": ReplayRequest,
}
