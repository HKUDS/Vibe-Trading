"""Workspace memory: shared state across tool calls within a single run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class WorkspaceMemory:
    """Shared workspace state between tools during a single agent run."""

    run_dir: Optional[str] = None
    session_workspace: Optional[str] = None
    counters: Dict[str, int] = field(default_factory=dict)

    def increment(self, key: str) -> int:
        """Increment a counter and return the new value."""
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    def to_summary(self) -> str:
        """Generate a state summary for the LLM."""
        lines: list[str] = []
        if self.run_dir:
            lines.append(f"- run_dir: {self.run_dir}")
        if self.session_workspace:
            lines.append(f"- session_workspace: {self.session_workspace}")
        if self.counters:
            counter_parts = [f"{k}={v}" for k, v in self.counters.items()]
            lines.append(f"- counters: {', '.join(counter_parts)}")
        return "\n".join(lines) if lines else "(empty state)"
