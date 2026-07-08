from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.alpha_foundry.forward.model import (
    ForwardPlanFrozenError,
    ForwardPlanValidationError,
    ForwardTrackingPlan,
)


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
    }
    defaults.update(kwargs)
    return ForwardTrackingPlan(**defaults)


def test_half_life_requires_enough_min_observations() -> None:
    with pytest.raises(ForwardPlanValidationError):
        _plan(
            min_observations_required=10,
            signal_half_life_observation_periods=6,
        )


def test_kill_rule_params_are_part_of_frozen_config_hash() -> None:
    original = _plan(kill_rule_params={"consecutive_negative_ic_n": 3})
    changed = original.with_kill_rule_params({"consecutive_negative_ic_n": 5})

    assert original.frozen_config_hash != changed.frozen_config_hash


def test_kill_rules_cannot_change_after_plan_starts() -> None:
    started = _plan().start()

    with pytest.raises(ForwardPlanFrozenError):
        started.with_kill_rule_params({"consecutive_negative_ic_n": 5})
