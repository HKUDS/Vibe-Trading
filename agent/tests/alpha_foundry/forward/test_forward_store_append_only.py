from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from src.alpha_foundry.forward.model import ForwardObservation
from src.alpha_foundry.forward.store import (
    ForwardObservationStore,
    ForwardStoreMutationError,
    OutOfOrderObservationError,
)


def _obs(obs_id: str, start: date, end: date) -> ForwardObservation:
    return ForwardObservation(
        observation_id=obs_id,
        plan_id="plan-1",
        period_start=start,
        period_end=end,
        realized_rank_ic=0.02,
        realized_return=0.01,
        realized_turnover=0.20,
        realized_cost_bps=2.0,
        observation_hash="",
        previous_observation_hash=None,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _obs_for_plan(plan_id: str, obs_id: str, start: date, end: date) -> ForwardObservation:
    obs = _obs(obs_id, start, end)
    return ForwardObservation(
        observation_id=obs.observation_id,
        plan_id=plan_id,
        period_start=obs.period_start,
        period_end=obs.period_end,
        realized_rank_ic=obs.realized_rank_ic,
        realized_return=obs.realized_return,
        realized_turnover=obs.realized_turnover,
        realized_cost_bps=obs.realized_cost_bps,
        observation_hash=obs.observation_hash,
        previous_observation_hash=obs.previous_observation_hash,
        created_at=obs.created_at,
    )


def test_forward_observation_append_only(tmp_path) -> None:
    store = ForwardObservationStore(tmp_path / "forward.jsonl")
    first = store.append(_obs("obs-1", date(2025, 1, 1), date(2025, 1, 7)))
    second = store.append(_obs("obs-2", date(2025, 1, 8), date(2025, 1, 14)))

    assert second.previous_observation_hash == first.observation_hash
    assert len(store.list()) == 2

    with pytest.raises(ForwardStoreMutationError):
        store.update("obs-1", realized_rank_ic=0.99)
    with pytest.raises(ForwardStoreMutationError):
        store.delete("obs-1")


def test_out_of_order_observation_rejected(tmp_path) -> None:
    store = ForwardObservationStore(tmp_path / "forward.jsonl")
    store.append(_obs("obs-1", date(2025, 1, 10), date(2025, 1, 17)))

    with pytest.raises(OutOfOrderObservationError):
        store.append(_obs("obs-2", date(2025, 1, 9), date(2025, 1, 16)))


def test_forward_observation_hash_chain_detects_tampering(tmp_path) -> None:  # noqa: ANN001
    store = ForwardObservationStore(tmp_path / "forward.jsonl")
    store.append(_obs("obs-1", date(2025, 1, 1), date(2025, 1, 7)))
    assert store.verify_hash_chain()

    payload = json.loads((tmp_path / "forward.jsonl").read_text(encoding="utf-8"))
    payload["realized_rank_ic"] = 0.99
    (tmp_path / "forward.jsonl").write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    assert not store.verify_hash_chain()


def test_forward_hash_chain_verifies_interleaved_plans_independently(tmp_path) -> None:  # noqa: ANN001
    store = ForwardObservationStore(tmp_path / "forward.jsonl")
    store.append(_obs_for_plan("plan-a", "a-1", date(2025, 1, 1), date(2025, 1, 7)))
    store.append(_obs_for_plan("plan-b", "b-1", date(2025, 1, 1), date(2025, 1, 7)))
    store.append(_obs_for_plan("plan-a", "a-2", date(2025, 1, 8), date(2025, 1, 14)))

    assert store.verify_hash_chain()
    assert store.verify_hash_chain(plan_id="plan-a")
    assert store.verify_hash_chain(plan_id="plan-b")
