"""Strategy and factor artifact store — Protocol + in-memory reference implementation.

The ``StrategyStoreProtocol`` defines the abstract interface for persisting
strategy/factor artifacts, bench results, and decay snapshots.  Concrete
backends (SQLite, DuckDB, JSON, …) will be decided by the community via
GitHub Issue #455.

``InMemoryStrategyStore`` is a fully functional reference implementation backed
by Python dicts and lists, suitable for tests and as a template for concrete
backends.
"""

from __future__ import annotations

import copy
import threading
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from functools import wraps
from typing import Callable, Sequence, TypeVar, runtime_checkable
from typing import Protocol

from src.strategy_store.models import (
    Artifact,
    ArtifactStatus,
    ArtifactType,
    BenchResult,
    DecaySnapshot,
    DecaySignal,
    ValidationStatus,
    validate_validation_status_transition,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _new_artifact_id() -> str:
    """Generate a unique artifact identifier."""
    return f"art_{uuid.uuid4().hex[:12]}"


F = TypeVar("F", bound=Callable)


def _synchronized(method: F) -> F:
    """Serialize access to shared in-memory state."""

    @wraps(method)
    def wrapper(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Protocol — abstract store interface
# ---------------------------------------------------------------------------


@runtime_checkable
class StrategyStoreProtocol(Protocol):
    """Abstract interface for the strategy/factor artifact store.

    Concrete implementations may use SQLite, DuckDB, JSON, or any other backend.
    The community will decide on the production backend via GitHub Issue #455.
    """

    # --- Artifact CRUD ---

    def register_artifact(self, artifact: Artifact) -> str:
        """Register a new artifact. Returns the artifact_id."""
        ...

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        """Get a single artifact by ID. Returns None if not found."""
        ...

    def list_artifacts(
        self,
        *,
        type: ArtifactType | None = None,
        status: ArtifactStatus | None = None,
        universe: str | None = None,
        limit: int = 100,
    ) -> Sequence[Artifact]:
        """List artifacts with optional filters."""
        ...

    def update_status(
        self,
        artifact_id: str,
        status: ArtifactStatus,
        *,
        reason: str | None = None,
    ) -> Artifact | None:
        """Transition an artifact to a new status. Returns updated artifact or None."""
        ...

    def update_artifact(self, artifact: Artifact) -> Artifact | None:
        """Replace an artifact record. Returns updated artifact or None if not found."""
        ...

    # --- Bench history ---

    def record_bench(self, result: BenchResult) -> int:
        """Record a bench result. Returns the result ID."""
        ...

    def get_bench_history(
        self, artifact_id: str, *, limit: int = 50
    ) -> Sequence[BenchResult]:
        """Get bench history for an artifact, newest first."""
        ...

    # --- Decay snapshots ---

    def record_decay_snapshot(self, snapshot: DecaySnapshot) -> int:
        """Record a decay monitoring snapshot. Returns the snapshot ID."""
        ...

    def get_decay_history(
        self, artifact_id: str, *, limit: int = 20
    ) -> Sequence[DecaySnapshot]:
        """Get decay snapshots for an artifact, newest first."""
        ...


# ---------------------------------------------------------------------------
# In-memory reference implementation
# ---------------------------------------------------------------------------


class InMemoryStrategyStore:
    """Dict/list-backed reference implementation of ``StrategyStoreProtocol``.

    Thread-safe via ``threading.RLock``.  Intended for tests and as a template
    for concrete persistent backends.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._artifacts: dict[str, Artifact] = {}
        self._bench_results: list[BenchResult] = []
        self._decay_snapshots: list[DecaySnapshot] = []
        self._bench_counter: int = 0
        self._decay_counter: int = 0

    # -- Artifact CRUD -------------------------------------------------------

    @_synchronized
    def register_artifact(self, artifact: Artifact) -> str:
        """Register a new artifact, assigning an ID and timestamps.

        Returns:
            The assigned ``artifact_id``.
        """
        for existing in self._artifacts.values():
            if existing.name == artifact.name and existing.universe == artifact.universe:
                raise ValueError(
                    f"artifact '{artifact.name}' already exists in "
                    f"universe '{artifact.universe}'"
                )
        # A brand-new record has no prior validation history, so its implicit
        # "current" state is UNVALIDATED — registering directly with
        # validation_status=APPROVED would skip the VALIDATED step.
        validate_validation_status_transition(
            ValidationStatus.UNVALIDATED, artifact.validation_status
        )
        now = _now_iso()
        artifact_id = artifact.id or _new_artifact_id()
        stored = replace(
            artifact,
            id=artifact_id,
            created_at=artifact.created_at or now,
            updated_at=now,
        )
        self._artifacts[artifact_id] = stored
        return artifact_id

    @_synchronized
    def get_artifact(self, artifact_id: str) -> Artifact | None:
        """Return a single artifact by ID, or ``None``."""
        return self._artifacts.get(artifact_id)

    @_synchronized
    def list_artifacts(
        self,
        *,
        type: ArtifactType | None = None,
        status: ArtifactStatus | None = None,
        universe: str | None = None,
        limit: int = 100,
    ) -> Sequence[Artifact]:
        """List artifacts with composable filters, newest first."""
        results: list[Artifact] = []
        for art in self._artifacts.values():
            if type is not None and art.type != type:
                continue
            if status is not None and art.status != status:
                continue
            if universe is not None and art.universe != universe:
                continue
            results.append(art)

        # Sort by created_at descending (newest first).
        results.sort(key=lambda a: a.created_at or "", reverse=True)
        return results[:limit]

    @_synchronized
    def update_status(
        self,
        artifact_id: str,
        status: ArtifactStatus,
        *,
        reason: str | None = None,
    ) -> Artifact | None:
        """Transition an artifact to a new status.

        Sets ``disabled_at`` and ``disabled_reason`` when transitioning to
        ``DISABLED``.  Returns the updated artifact, or ``None`` if not found.
        """
        existing = self._artifacts.get(artifact_id)
        if existing is None:
            return None

        now = _now_iso()
        updates: dict = {
            "status": status,
            "updated_at": now,
        }

        if status is ArtifactStatus.DISABLED:
            updates["disabled_at"] = now
            if reason is not None:
                updates["disabled_reason"] = reason
        else:
            # Clear disabled fields when moving out of DISABLED.
            if existing.status is ArtifactStatus.DISABLED:
                updates["disabled_at"] = None
                updates["disabled_reason"] = None

        updated = replace(existing, **updates)
        self._artifacts[artifact_id] = updated
        return updated

    @_synchronized
    def update_artifact(self, artifact: Artifact) -> Artifact | None:
        """Replace an artifact record.

        Returns the updated artifact, or ``None`` if the ID is not found.
        """
        existing = self._artifacts.get(artifact.id)
        if existing is None:
            return None

        # Structural enforcement of the validation state machine: an
        # unvalidated model can never be updated straight into APPROVED.
        validate_validation_status_transition(
            existing.validation_status, artifact.validation_status
        )

        now = _now_iso()
        stored = replace(artifact, updated_at=now)
        self._artifacts[artifact.id] = stored
        return stored

    # -- Bench history -------------------------------------------------------

    @_synchronized
    def record_bench(self, result: BenchResult) -> int:
        """Record a bench result, assigning an auto-increment ID.

        Returns:
            The assigned result ID.
        """
        self._bench_counter += 1
        now = _now_iso()
        stored = replace(
            result,
            id=self._bench_counter,
            created_at=result.created_at or now,
        )
        self._bench_results.append(stored)
        return stored.id

    @_synchronized
    def get_bench_history(
        self, artifact_id: str, *, limit: int = 50
    ) -> Sequence[BenchResult]:
        """Return bench results for an artifact, newest first."""
        matched = [r for r in self._bench_results if r.artifact_id == artifact_id]
        matched.sort(key=lambda r: r.created_at or "", reverse=True)
        return matched[:limit]

    # -- Decay snapshots -----------------------------------------------------

    @_synchronized
    def record_decay_snapshot(self, snapshot: DecaySnapshot) -> int:
        """Record a decay monitoring snapshot, assigning an auto-increment ID.

        Returns:
            The assigned snapshot ID.
        """
        self._decay_counter += 1
        now = _now_iso()
        stored = replace(
            snapshot,
            id=self._decay_counter,
            created_at=snapshot.created_at or now,
        )
        self._decay_snapshots.append(stored)
        return stored.id

    @_synchronized
    def get_decay_history(
        self, artifact_id: str, *, limit: int = 20
    ) -> Sequence[DecaySnapshot]:
        """Return decay snapshots for an artifact, newest first."""
        matched = [s for s in self._decay_snapshots if s.artifact_id == artifact_id]
        matched.sort(key=lambda s: s.created_at or "", reverse=True)
        return matched[:limit]
