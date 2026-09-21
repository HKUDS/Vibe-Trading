"""Per-run tool observations, independent of the activity watchdog."""

from __future__ import annotations

import hashlib
import json

NO_PROGRESS_LIMIT = 8
#: Identical failures tolerated before an exact repeat is refused. Blocking
#: on the FIRST one makes a transient failure permanent: a rate limit, a
#: network blip or the 1800s tool timeout says nothing about the arguments,
#: and only a successful *mutating* call clears the ledger -- which a pure
#: research run may never make. The second identical failure is the one that
#: shows the call itself is the problem. #1353's loop reissued the same
#: rejected path ~35 times, so a threshold of 2 still kills it well inside
#: NO_PROGRESS_LIMIT.
FAILURE_BLOCK_THRESHOLD = 2
RECOVERY_MESSAGE = (
    "I stopped because repeated tool attempts did not produce new information. "
    "I cannot reliably answer from the previous summary alone. Please provide "
    "the artifact path or confirm that you want to rerun the missing research step."
)


class ToolProgress:
    """Bound repeated discovery without treating activity as new evidence."""

    def __init__(self) -> None:
        self.failed: dict[tuple[str, str], int] = {}
        self._observations: set[tuple[str, str | None, str]] = set()
        self._new_observation = False
        self._context_restored = False
        self._context_restore_grace_used = False
        self.stalled_iterations = 0

    def record(
        self,
        name: str,
        key: tuple[str, str] | None,
        result: str,
        *,
        success: bool,
        is_readonly: bool = True,
    ) -> None:
        """Record an executed call; synthetic skips must not enter this ledger."""
        if not success:
            if key is not None:
                self.failed[key] = self.failed.get(key, 0) + 1
            return
        if not is_readonly:
            self.failed.clear()
        if not is_readonly and key is None:
            self._new_observation = True
            return
        try:
            result = json.dumps(json.loads(result), sort_keys=True, ensure_ascii=False)
        except (ValueError, TypeError):
            pass
        observation = (
            name,
            None if is_readonly else key[1],
            hashlib.sha256(result.encode("utf-8")).hexdigest(),
        )
        if observation not in self._observations:
            self._observations.add(observation)
            self._new_observation = True

    def mark_context_restored(self) -> None:
        """Grant one run-scoped grace iteration after compaction restores evidence.

        Replaying a cached readonly result is not a new external observation, so
        it must never reset the no-progress history indefinitely. The first
        restoration in a run may hold the current stall count for one iteration
        so the model gets a chance to consume the restored payload; later
        restorations do not extend the budget. A genuinely new observation still
        resets the stall chain through :meth:`record`.
        """
        if self._context_restore_grace_used:
            return
        self._context_restore_grace_used = True
        self._context_restored = True

    def is_blocked(self, key: tuple[str, str]) -> bool:
        """Whether this exact call failed often enough to refuse a repeat.

        Args:
            key: Canonical call identity (name, serialized arguments).

        Returns:
            ``True`` once the identity reached :data:`FAILURE_BLOCK_THRESHOLD`
            failures without an intervening successful mutation.
        """
        return self.failed.get(key, 0) >= FAILURE_BLOCK_THRESHOLD

    def finish_iteration(self) -> bool:
        """Return whether the run exhausted its consecutive no-progress budget."""
        if self._new_observation:
            self.stalled_iterations = 0
        elif self._context_restored:
            # One grace iteration: preserve, but do not erase, prior stall
            # history. This lets the next model turn see the restored evidence
            # without allowing replay-only loops to run forever.
            pass
        else:
            self.stalled_iterations += 1
        self._new_observation = False
        self._context_restored = False
        return self.stalled_iterations >= NO_PROGRESS_LIMIT
