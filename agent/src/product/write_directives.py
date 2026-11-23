"""Write-target directive state composed into the agent loop."""

from __future__ import annotations


from typing import Any, Mapping

from src.product.write_targets import pending_write_directive, record_written_target


class WriteTargetState:
    """Own the per-run set of files written by the model."""

    def __init__(self, memory, runtime, model_source, *, registry) -> None:
        self.registry = registry
        self.memory = memory
        self.runtime = runtime
        self.active_model_id = runtime.configured_model
        self.active_model_source = model_source
        self.written_files: set[str] = set()

    def reset(self) -> None:
        """Clear the target ledger for a new run."""
        self.written_files = set()

    def record(self, arguments: Mapping[str, Any]) -> None:
        """Record a write and its model provenance."""
        record_written_target(
            arguments,
            written_files=self.written_files,
            run_dir=self.memory.run_dir,
            llm_runtime=self.runtime,
            active_model_id=self.active_model_id,
            active_model_source=self.active_model_source,
            roots=self.registry.policy.file_roots,
        )

    def pending(self, user_message: str, run_started_wall: float) -> str:
        """Return the pending-write directive for the current run."""
        return pending_write_directive(
            user_message, run_started_wall, written_files=self.written_files
        )
