"""YAML case schema for deterministic agent evals."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


CASE_SCHEMA_VERSION = "1.0.0"


class AgentEvalSetup(BaseModel):
    """Flexible per-case setup for fake IO and governance context."""

    model_config = ConfigDict(extra="allow")

    surface: str = "local_api"
    governance_mode: Literal["off", "observe", "warn", "enforce"] = "enforce"
    scenario: str | None = None


class AgentEvalExpected(BaseModel):
    """Expected policy/security/quant boundaries for one eval case."""

    model_config = ConfigDict(extra="forbid")

    must_call: list[str] = Field(default_factory=list)
    must_not_call: list[str] = Field(default_factory=list)
    must_warn_codes: list[str] = Field(default_factory=list)
    must_deny_codes: list[str] = Field(default_factory=list)
    must_not_claim: list[str] = Field(default_factory=list)
    required_trace_events: list[str] = Field(default_factory=list)
    required_artifacts: list[str] = Field(default_factory=list)
    final_status: Literal["allowed", "denied", "skipped", "failed"]
    conclusion_cap: str | None = None


class AgentEvalCase(BaseModel):
    """Schema-versioned deterministic eval case loaded from YAML."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = CASE_SCHEMA_VERSION
    id: str
    prompt: str
    setup: AgentEvalSetup = Field(default_factory=AgentEvalSetup)
    expected: AgentEvalExpected
    tags: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=30, ge=1, le=300)

    @field_validator("id")
    @classmethod
    def _id_is_stable_token(cls, value: str) -> str:
        if not value or not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError("id must be a stable token")
        return value


def load_case(path: str | Path) -> AgentEvalCase:
    """Load one YAML eval case."""
    raw = Path(path).read_text(encoding="utf-8")
    data: Any = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError(f"case file must contain a YAML object: {path}")
    return AgentEvalCase.model_validate(data)


def load_cases(path: str | Path) -> list[AgentEvalCase]:
    """Load all YAML eval cases in deterministic filename order."""
    root = Path(path)
    return [load_case(item) for item in sorted(root.glob("*.yaml"))]
