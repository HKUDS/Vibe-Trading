"""PIT violation schema."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PITViolation(BaseModel):
    """Structured PIT warning or violation."""

    code: str
    severity: Literal["info", "warning", "hard_failure"] = "warning"
    message: str
    hard_failure: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
