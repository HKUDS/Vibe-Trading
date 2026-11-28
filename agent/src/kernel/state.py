"""Run activity shared by the scheduler and its cancellation observers."""
from dataclasses import dataclass, field
from threading import Event
from time import time


@dataclass
class RunActivity:
    """Track cancellation, completion, and the most recent activity for a run.

    Args:
        cancel: Event set to request cancellation.
        iteration: Current host iteration counter.
        done: Event set when the run completes.
        last_activity: Unix timestamp of the latest recorded activity.
        stall_reason: Watchdog failure reason, if the run has stalled.
    """
    cancel: Event
    iteration: int = 0
    done: Event = field(default_factory=Event)
    last_activity: float = 0.0
    stall_reason: str | None = None

    def touch(self) -> None:
        """Record activity at the current wall-clock time."""
        self.last_activity = time()

    def start(self) -> None:
        """Replace the completion event, clear the stall reason, and record activity."""
        self.done = Event()
        self.stall_reason = None
        self.touch()
