"""Write-target directive state composed into the agent loop."""

from __future__ import annotations


from typing import Any, Iterable, Mapping

from src.product.write_targets import pending_write_directive, record_written_target


class WriteTargetState:
    """Own the per-run set of files written by the model.

    Args:
        memory: Workspace state supplying the current run directory.
        runtime: Model settings used for write provenance.
        model_source: Initial source label for the configured model.
        registry: Tool registry supplying authorized file roots.
    """

    def __init__(self, memory, runtime, model_source, *, registry) -> None:
        self.registry = registry
        self.memory = memory
        self.runtime = runtime
        self.active_model_id = runtime.configured_model
        self.active_model_source = model_source
        self.written_files: set[str] = set()
        self.earlier_attempts_started: float | None = None

    def reset(self) -> None:
        """Clear the target ledger for a new run; a continued task keeps its earlier attempts."""
        self.written_files = set()

    def continue_attempts(self, items: Iterable[Any]) -> None:
        """Count files written by earlier attempts of the same task as written.

        Args:
            items: Persisted thread items of the task's earlier attempts; each carries ``ts``.
        """
        self.earlier_attempts_started = min((item.ts for item in items), default=None)

    def record(self, arguments: Mapping[str, Any]) -> None:
        """Record a write and its model provenance.

        Args:
            arguments: Successful write or edit arguments containing a path or file_path.
        """
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
        """Build the pending-write directive for the current run.

        Args:
            user_message: User prompt from which to extract requested target paths.
            run_started_wall: Run start as a Unix timestamp for comparing file modification
                times. A continued task compares against its first attempt's start instead.

        Returns:
            The directive when none of the named targets qualifies as written, otherwise
            an empty string. Prompts without a recognized write request also return empty.
        """
        if self.earlier_attempts_started is not None:
            run_started_wall = min(run_started_wall, self.earlier_attempts_started)
        return pending_write_directive(
            user_message, run_started_wall, written_files=self.written_files,
            run_dir=self.memory.run_dir,
        )
