"""Governance budget accounting."""

from __future__ import annotations

import time

from pydantic import BaseModel, Field

from src.governance.manifest import RiskLevel


class BudgetExceeded(Exception):
    """Raised when a governance budget is exceeded."""


class BudgetSnapshot(BaseModel):
    max_tool_calls: int | None = None
    max_parallel_readonly_calls: int | None = None
    max_runtime_seconds: float | None = None
    max_network_calls: int | None = None
    max_bytes_read: int | None = None
    max_artifacts_written: int | None = None
    max_llm_tokens_or_cost: float | None = None
    max_backtest_trials: int | None = None
    max_external_mcp_calls: int | None = None

    tool_calls: int = 0
    parallel_readonly_calls: int = 0
    network_calls: int = 0
    bytes_read: int = 0
    artifacts_written: int = 0
    artifact_bytes_written: int = 0
    llm_tokens_or_cost: float = 0
    backtest_trials: int = 0
    external_mcp_calls: int = 0
    started_at: float = Field(default_factory=time.monotonic)


class BudgetManager:
    """Mutable helper for checking execution budgets."""

    def __init__(self, snapshot: BudgetSnapshot | None = None) -> None:
        self.snapshot = snapshot or BudgetSnapshot()

    def record_tool_call(self, *, risk_level: RiskLevel) -> None:
        self._check_runtime()
        self._increment("tool_calls", "max_tool_calls")
        if risk_level == RiskLevel.R2_NETWORK:
            self._increment("network_calls", "max_network_calls")

    def record_parallel_readonly_call(self) -> None:
        self._increment("parallel_readonly_calls", "max_parallel_readonly_calls")

    def record_bytes_read(self, byte_count: int) -> None:
        self.snapshot.bytes_read += max(0, int(byte_count))
        self._check_limit("bytes_read", "max_bytes_read")

    def record_artifact_written(self, byte_count: int = 0) -> None:
        self._increment("artifacts_written", "max_artifacts_written")
        self.snapshot.artifact_bytes_written += max(0, int(byte_count))

    def record_llm_tokens_or_cost(self, amount: float) -> None:
        self.snapshot.llm_tokens_or_cost += max(0.0, float(amount))
        self._check_limit("llm_tokens_or_cost", "max_llm_tokens_or_cost")

    def record_backtest_trial(self) -> None:
        self._increment("backtest_trials", "max_backtest_trials")

    def record_external_mcp_call(self) -> None:
        self._increment("external_mcp_calls", "max_external_mcp_calls")

    def _increment(self, field_name: str, limit_name: str) -> None:
        setattr(self.snapshot, field_name, int(getattr(self.snapshot, field_name)) + 1)
        self._check_limit(field_name, limit_name)

    def _check_limit(self, field_name: str, limit_name: str) -> None:
        limit = getattr(self.snapshot, limit_name)
        if limit is not None and getattr(self.snapshot, field_name) > limit:
            raise BudgetExceeded(f"{field_name} exceeded {limit_name}={limit}")

    def _check_runtime(self) -> None:
        limit = self.snapshot.max_runtime_seconds
        if limit is not None and (time.monotonic() - self.snapshot.started_at) > limit:
            raise BudgetExceeded(f"runtime exceeded max_runtime_seconds={limit}")
