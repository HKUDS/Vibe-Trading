"""Canonical prompt hashing for replay-only eval stubs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.reliability.artifacts.hashing import sha256_json


PROMPT_HASH_SCHEMA_VERSION = "1.0.0"


class PromptHashInput(BaseModel):
    """All inputs that define an eval prompt contract."""

    model_config = ConfigDict(allow_inf_nan=False)

    schema_version: str = PROMPT_HASH_SCHEMA_VERSION
    system_prompt: str
    developer_prompt: str | None = None
    user_prompt: str
    prior_turns_summary: str | None = None
    tool_schema_version: str = "1.0.0"
    tool_schema_hash: str | dict[str, Any]
    governance_policy_version: str
    manifest_version: str
    research_protocol_schema_version: str
    scorecard_schema_version: str
    stub_prompt_contract_version: str
    metadata: dict[str, Any] = Field(default_factory=dict)


def compute_prompt_hash(prompt: PromptHashInput) -> str:
    """Return the canonical hash used to select a stub response."""
    return sha256_json({"agent_eval_prompt": prompt.model_dump(mode="json")})
