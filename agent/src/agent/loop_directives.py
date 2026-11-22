"""Write-target directive state composed into the agent loop."""

from __future__ import annotations

from typing import Any, Mapping

from src.agent.write_targets import pending_write_directive, record_written_target


class WriteTargetState:
    """Own the per-run set of files written by the model."""

    def __init__(self) -> None:
        self.written_files: set[str] = set()

    def reset(self) -> None:
        """Clear the target ledger for a new run."""
        self.written_files = set()

    def record(self, arguments: Mapping[str, Any], owner: Any) -> None:
        """Record a write and its model provenance."""
        record_written_target(
            arguments,
            written_files=self.written_files,
            run_dir=owner.memory.run_dir,
            llm_runtime=owner._llm_runtime,
            active_model_id=owner._active_model_id,
            active_model_source=owner._active_model_source,
        )

    def pending(self, user_message: str, run_started_wall: float) -> str:
        """Return the pending-write directive for the current run."""
        return pending_write_directive(
            user_message, run_started_wall, written_files=self.written_files
        )
