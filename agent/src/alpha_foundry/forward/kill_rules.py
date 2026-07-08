from __future__ import annotations

from src.alpha_foundry.forward.evaluator import evaluate_observations
from src.alpha_foundry.forward.model import ForwardObservation, ForwardTrackingPlan


def evaluate_forward_status(
    plan: ForwardTrackingPlan,
    observations: list[ForwardObservation],
) -> str:
    evaluation = evaluate_observations(plan, observations)
    params = plan.kill_rule_params

    negative_n = int(params.get("consecutive_negative_ic_n", 3))
    if negative_n > 0 and evaluation.consecutive_negative_ic >= negative_n:
        return "killed"

    if evaluation.observation_count < plan.min_observations_required:
        return "paper_tracking" if plan.status == "candidate" else plan.status

    ratio = evaluation.realized_vs_expected_ratio
    if ratio is None:
        return "paper_tracking"

    ratio_min = float(params.get("realized_vs_expected_ratio_min", 0.30))
    decay_threshold = float(params.get("ic_decay_threshold_pct", 0.30))
    if ratio < ratio_min or ratio < (1.0 - decay_threshold):
        return "decayed"

    return "promoted"
