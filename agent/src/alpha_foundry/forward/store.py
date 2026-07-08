from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from src.alpha_foundry.forward.model import ForwardObservation


class ForwardStoreMutationError(RuntimeError):
    """Raised when callers attempt to mutate append-only observations."""


class ForwardStoreAppendError(RuntimeError):
    """Raised when an observation cannot be appended safely."""


class OutOfOrderObservationError(ForwardStoreAppendError):
    """Raised when an observation period would break plan order."""


class ForwardObservationStore:
    _lock = threading.Lock()

    def __init__(self, path: str | Path | None = None) -> None:
        env_path = os.environ.get("VIBE_TRADING_FORWARD_STORE_PATH")
        self.path = Path(path or env_path or "forward_observations.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, observation: ForwardObservation) -> ForwardObservation:
        with self._lock:
            records = self.list()
            if any(item.observation_id == observation.observation_id for item in records):
                raise ForwardStoreAppendError(
                    f"observation already exists: {observation.observation_id}"
                )
            plan_records = [item for item in records if item.plan_id == observation.plan_id]
            previous_hash = None
            if plan_records:
                last = plan_records[-1]
                if observation.period_start <= last.period_end:
                    raise OutOfOrderObservationError(
                        "observation periods must append in increasing order"
                    )
                previous_hash = last.observation_hash
            prepared = observation.with_hash(previous_hash)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    json.dumps(
                        prepared.to_dict(),
                        sort_keys=True,
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                    )
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            return prepared

    def list(self, *, plan_id: str | None = None) -> list[ForwardObservation]:
        if not self.path.exists():
            return []
        records: list[ForwardObservation] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                observation = ForwardObservation.from_dict(json.loads(stripped))
                if plan_id is None or observation.plan_id == plan_id:
                    records.append(observation)
        return records

    def update(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        raise ForwardStoreMutationError("forward observation store is append-only")

    def delete(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        raise ForwardStoreMutationError("forward observation store is append-only")
