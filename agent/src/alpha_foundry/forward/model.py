from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime
from math import ceil
from typing import Any, Literal

from src.research_ledger.hash_utils import canonical_json_hash, json_safe


class ForwardPlanValidationError(ValueError):
    """Raised when a forward plan violates frozen tracking requirements."""


class ForwardPlanFrozenError(RuntimeError):
    """Raised when a started forward plan is modified."""


DEFAULT_KILL_RULE_PARAMS = {
    "consecutive_negative_ic_n": 3,
    "ic_decay_threshold_pct": 0.30,
    "realized_vs_expected_ratio_min": 0.30,
}

ForwardStatus = Literal[
    "candidate",
    "paper_tracking",
    "promoted",
    "decayed",
    "killed",
    "retired",
]


@dataclass(frozen=True)
class ForwardTrackingPlan:
    plan_id: str
    factor_id: str
    hypothesis_id: str
    accepted_at: datetime
    frozen_factor_definition_hash: str
    frozen_config_hash: str
    observation_frequency: Literal["weekly", "monthly", "quarterly"]
    min_observations_required: int
    expected_rank_ic: float
    expected_ic_decay_threshold_pct: float = 0.30
    signal_half_life_observation_periods: int | None = None
    kill_rule_params: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_KILL_RULE_PARAMS))
    status: ForwardStatus = "candidate"
    schema_version: str = "2.1.0"

    def __post_init__(self) -> None:
        if self.min_observations_required < 1:
            raise ForwardPlanValidationError("min_observations_required must be >= 1")
        if self.signal_half_life_observation_periods is not None:
            required = max(12, ceil(2 * self.signal_half_life_observation_periods))
            if self.min_observations_required < required:
                raise ForwardPlanValidationError(
                    "min_observations_required must cover half-life validation"
                )
        params = dict(DEFAULT_KILL_RULE_PARAMS)
        params.update(self.kill_rule_params)
        object.__setattr__(self, "kill_rule_params", params)
        if not self.frozen_config_hash:
            object.__setattr__(self, "frozen_config_hash", self.compute_frozen_config_hash())

    def compute_frozen_config_hash(self) -> str:
        return canonical_json_hash(
            {
                "factor_id": self.factor_id,
                "hypothesis_id": self.hypothesis_id,
                "frozen_factor_definition_hash": self.frozen_factor_definition_hash,
                "observation_frequency": self.observation_frequency,
                "min_observations_required": self.min_observations_required,
                "expected_rank_ic": self.expected_rank_ic,
                "expected_ic_decay_threshold_pct": self.expected_ic_decay_threshold_pct,
                "signal_half_life_observation_periods": self.signal_half_life_observation_periods,
                "kill_rule_params": self.kill_rule_params,
            }
        )

    def with_kill_rule_params(self, params: dict[str, Any]) -> "ForwardTrackingPlan":
        if self.status != "candidate":
            raise ForwardPlanFrozenError("kill_rule_params cannot change after plan starts")
        return replace(self, kill_rule_params=dict(params), frozen_config_hash="")

    def start(self) -> "ForwardTrackingPlan":
        return replace(self, status="paper_tracking")

    def to_dict(self) -> dict[str, Any]:
        return json_safe(asdict(self))


@dataclass(frozen=True)
class ForwardObservation:
    observation_id: str
    plan_id: str
    period_start: date
    period_end: date
    realized_rank_ic: float | None = None
    realized_return: float | None = None
    realized_turnover: float | None = None
    realized_cost_bps: float | None = None
    observation_hash: str = ""
    previous_observation_hash: str | None = None
    created_at: datetime | None = None
    schema_version: str = "2.1.0"

    def __post_init__(self) -> None:
        if self.period_end < self.period_start:
            raise ForwardPlanValidationError("period_end must be on or after period_start")

    def with_hash(self, previous_observation_hash: str | None) -> "ForwardObservation":
        prepared = replace(
            self,
            previous_observation_hash=previous_observation_hash,
            observation_hash="",
        )
        digest = canonical_json_hash(prepared.to_dict(), exclude_keys=("observation_hash",))
        return replace(prepared, observation_hash=digest)

    def to_dict(self) -> dict[str, Any]:
        return json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ForwardObservation":
        data = dict(payload)
        if isinstance(data.get("period_start"), str):
            data["period_start"] = date.fromisoformat(data["period_start"])
        if isinstance(data.get("period_end"), str):
            data["period_end"] = date.fromisoformat(data["period_end"])
        created = data.get("created_at")
        if isinstance(created, str):
            data["created_at"] = datetime.fromisoformat(created.replace("Z", "+00:00"))
        return cls(**data)
