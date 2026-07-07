"""Data reliability exceptions."""

from __future__ import annotations

from typing import Any


class AllSourcesOpenError(Exception):
    """Raised when every non-local fallback source is circuit-open."""

    error_code = "DATA_ALL_SOURCES_OPEN"

    def __init__(
        self,
        message: str,
        *,
        chain: list[str],
        breaker_states: dict[str, str],
        audit_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.chain = chain
        self.breaker_states = breaker_states
        self.audit_id = audit_id

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation."""
        return {
            "error_code": self.error_code,
            "message": str(self),
            "chain": list(self.chain),
            "breaker_states": dict(self.breaker_states),
            "audit_id": self.audit_id,
        }
