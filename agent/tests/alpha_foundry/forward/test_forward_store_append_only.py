from __future__ import annotations

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
