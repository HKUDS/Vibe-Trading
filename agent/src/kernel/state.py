"""Run activity shared by the scheduler and its cancellation observers."""
from dataclasses import dataclass, field
from threading import Event
from time import time


@dataclass
class RunActivity:
    cancel: Event
    iteration: int = 0
    done: Event = field(default_factory=Event)
    last_activity: float = 0.0
    stall_reason: str | None = None

    def touch(self) -> None:
        self.last_activity = time()

    def start(self) -> None:
        self.done = Event()
        self.stall_reason = None
        self.touch()
