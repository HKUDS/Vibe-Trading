from __future__ import annotations

from dataclasses import dataclass

from src.alpha_foundry.forward.model import ForwardObservation, ForwardTrackingPlan


@dataclass(frozen=True)
class ForwardEvaluation:
    observation_count: int
    mean_realized_rank_ic: float | None
    realized_vs_expected_ratio: float | None
    consecutive_negative_ic: int


def evaluate_observations(
    plan: ForwardTrackingPlan,
    observations: list[ForwardObservation],
) -> ForwardEvaluation:
    scoped = sorted(
        [obs for obs in observations if obs.plan_id == plan.plan_id],
        key=lambda obs: (obs.period_end, obs.observation_id),
    )
    rank_ics = [obs.realized_rank_ic for obs in scoped if obs.realized_rank_ic is not None]
    mean_ic = float(sum(rank_ics) / len(rank_ics)) if rank_ics else None
    ratio = None
    if mean_ic is not None and plan.expected_rank_ic != 0:
        ratio = mean_ic / plan.expected_rank_ic

    consecutive_negative = 0
    for obs in reversed(scoped):
        if obs.realized_rank_ic is None or obs.realized_rank_ic >= 0:
            break
        consecutive_negative += 1

    return ForwardEvaluation(
        observation_count=len(scoped),
        mean_realized_rank_ic=mean_ic,
        realized_vs_expected_ratio=ratio,
        consecutive_negative_ic=consecutive_negative,
    )
