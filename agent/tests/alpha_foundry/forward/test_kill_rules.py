from __future__ import annotations

from datetime import date, datetime, timezone

from src.alpha_foundry.forward.kill_rules import evaluate_forward_status
from src.alpha_foundry.forward.model import ForwardObservation, ForwardTrackingPlan


def _plan(**kwargs: object) -> ForwardTrackingPlan:
    defaults = {
        "plan_id": "plan-1",
        "factor_id": "factor-1",
        "hypothesis_id": "hypothesis-1",
        "accepted_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "frozen_factor_definition_hash": "sha256:factor",
        "frozen_config_hash": "",
        "observation_frequency": "weekly",
        "min_observations_required": 4,
        "expected_rank_ic": 0.04,
        "status": "paper_tracking",
    }
    defaults.update(kwargs)
    return ForwardTrackingPlan(**defaults)


def _obs(obs_id: int, rank_ic: float) -> ForwardObservation:
    return ForwardObservation(
        observation_id=f"obs-{obs_id}",
        plan_id="plan-1",
        period_start=date(2025, 1, obs_id),
        period_end=date(2025, 1, obs_id),
        realized_rank_ic=rank_ic,
        observation_hash=f"sha256:{obs_id}",
        previous_observation_hash=None,
        created_at=datetime(2025, 1, obs_id, tzinfo=timezone.utc),
    )


def test_consecutive_negative_ic_kills_plan() -> None:
    plan = _plan(kill_rule_params={"consecutive_negative_ic_n": 3})
    observations = [_obs(1, -0.01), _obs(2, -0.02), _obs(3, -0.01)]

    assert evaluate_forward_status(plan, observations) == "killed"


def test_no_promotion_before_min_observations() -> None:
    plan = _plan(min_observations_required=4)
    observations = [_obs(1, 0.05), _obs(2, 0.04), _obs(3, 0.06)]

    assert evaluate_forward_status(plan, observations) == "paper_tracking"


def test_promotes_after_enough_observations_and_expected_ic() -> None:
    plan = _plan(min_observations_required=3, expected_rank_ic=0.04)
    observations = [_obs(1, 0.05), _obs(2, 0.04), _obs(3, 0.06)]

    assert evaluate_forward_status(plan, observations) == "promoted"


def test_decays_when_realized_ic_ratio_breaks_threshold() -> None:
    plan = _plan(
        min_observations_required=3,
        expected_rank_ic=0.10,
        kill_rule_params={"realized_vs_expected_ratio_min": 0.30},
    )
    observations = [_obs(1, 0.02), _obs(2, 0.01), _obs(3, 0.02)]

    assert evaluate_forward_status(plan, observations) == "decayed"
