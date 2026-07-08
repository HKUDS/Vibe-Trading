from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class MechanismTemplate:
    candidate_id: str
    formula: str
    kind: Literal["candidate", "control"]
    rationale: str


ASHARE_LIQUIDITY_REVERSAL_TEMPLATES = [
    MechanismTemplate(
        candidate_id="raw_reversal_baseline",
        formula="rank(neg(ret_1d))",
        kind="candidate",
        rationale="Short-horizon reversal baseline.",
    ),
    MechanismTemplate(
        candidate_id="volume_conditioned_reversal",
        formula="rank(mul(neg(ret_1d), volume_shock(volume, 20)))",
        kind="candidate",
        rationale="Reversal conditional on abnormal volume.",
    ),
    MechanismTemplate(
        candidate_id="amount_conditioned_reversal",
        formula="rank(mul(neg(ret_1d), volume_shock(amount, 20)))",
        kind="candidate",
        rationale="Reversal conditional on abnormal traded amount.",
    ),
    MechanismTemplate(
        candidate_id="decay_smoothed_reversal",
        formula="rank(decay_linear(mul(neg(ret_1d), volume_shock(volume, 20)), 5))",
        kind="candidate",
        rationale="Smoothed liquidity-shock reversal.",
    ),
    MechanismTemplate(
        candidate_id="delayed_reversal_controlled",
        formula="rank(delay(mul(neg(ret_1d), volume_shock(amount, 20)), 1))",
        kind="candidate",
        rationale="Delayed signal for execution-lag realism.",
    ),
    MechanismTemplate(
        candidate_id="zscore_reversal_variant",
        formula="zscore(mul(neg(ret_1d), volume_shock(volume, 20)))",
        kind="candidate",
        rationale="Standardized reversal variant.",
    ),
    MechanismTemplate(
        candidate_id="duplicate_control",
        formula="rank(neg(ret_1d))",
        kind="control",
        rationale="Duplicate public/baseline alpha control.",
    ),
    MechanismTemplate(
        candidate_id="future_control",
        formula="rank(future_return)",
        kind="control",
        rationale="Deliberately invalid future-data control.",
    ),
    MechanismTemplate(
        candidate_id="noise_control",
        formula="rank(volume)",
        kind="control",
        rationale="Mechanism-light volume-only control.",
    ),
]
