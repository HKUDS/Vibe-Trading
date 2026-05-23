"""Branded entity ID with validation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EntityId:
    """Immutable entity identifier."""

    value: str

    def __post_init__(self) -> None:
        if not self.value or not isinstance(self.value, str):
            raise ValueError("EntityId must be a non-empty string")
        # Validate UUID format (optional but recommended)
        try:
            uuid.UUID(self.value)
        except ValueError:
            raise ValueError(f"EntityId must be a valid UUID, got: {self.value}")

    @classmethod
    def generate(cls) -> EntityId:
        """Generate a new random entity ID."""
        return cls(str(uuid.uuid4()))

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"EntityId({self.value!r})"
