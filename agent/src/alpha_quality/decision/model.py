from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class HardFailureCode(str, Enum):
    LOOKAHEAD_DETECTED = "LOOKAHEAD_DETECTED"
    TEST_SET_CONTAMINATED = "TEST_SET_CONTAMINATED"
    NON_REPRODUCIBLE = "NON_REPRODUCIBLE"
    PIT_CONTRACT_MISSING = "PIT_CONTRACT_MISSING"
    COST_EXCEEDS_ALPHA = "COST_EXCEEDS_ALPHA"
    EXECUTION_RETURN_MISSING = "EXECUTION_RETURN_MISSING"
    DUPLICATE_ALPHA = "DUPLICATE_ALPHA"
    SCORECARD_OVERRIDE_ATTEMPT = "SCORECARD_OVERRIDE_ATTEMPT"


class AdvisoryCode(str, Enum):
    RECENT_DECAY = "RECENT_DECAY"
    HIGH_TURNOVER = "HIGH_TURNOVER"
    EXPOSURE_CONCENTRATION = "EXPOSURE_CONCENTRATION"
    HIGH_PBO_PROXY = "HIGH_PBO_PROXY"
    LOW_DSR_PROXY = "LOW_DSR_PROXY"


class QualityDecision(str, Enum):
    REJECT = "reject"
    RESEARCH_ONLY = "research_only"
    CANDIDATE_ZOO = "candidate_zoo"
    PAPER_CANDIDATE = "paper_candidate"


@dataclass(frozen=True)
class AlphaQualityDecisionContext:
    trial_entries: list[Any] = field(default_factory=list)
    trial_count: int = 0
    selected_p_value: float | None = None
    pit_contract_present: bool = True
    survivorship_bias: bool = False
    duplicate_alpha: bool = False
    caller_claimed_decision: QualityDecision | None = None
    total_quality_score: float = 0.0
    allow_missing_execution_return: bool = False


@dataclass(frozen=True)
class AlphaQualityDecision:
    schema_version: str
    factor_id: str
    decision: QualityDecision
    hard_failures: list[HardFailureCode]
    warnings: list[AdvisoryCode]
    cap_reasons: list[HardFailureCode]
    total_quality_score: float

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["decision"] = self.decision.value
        payload["hard_failures"] = [code.value for code in self.hard_failures]
        payload["warnings"] = [code.value for code in self.warnings]
        payload["cap_reasons"] = [code.value for code in self.cap_reasons]
        return payload

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )


def normalize_hard_failure(value: str | HardFailureCode) -> HardFailureCode | None:
    if isinstance(value, HardFailureCode):
        return value
    try:
        return HardFailureCode(value)
    except ValueError:
        return None
