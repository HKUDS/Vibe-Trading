"""Specialist definition data model for domain sub-agents.

A specialist is a domain-scoped sub-agent the main agent can delegate to via
the ``delegate_to_specialist`` tool: a small hard-enforced tool whitelist, a
routing description made of trigger conditions and NOT-for anti-triggers, and
a behavior prompt carrying the boundary / output / honesty contracts.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")

# Tools a specialist may never hold. These are structural exclusions, not
# policy: recursion into delegation or swarm orchestration would compound two
# delegation channels; shell and order-write tools break the specialist
# safety boundary; session/goal/memory/skill-mutation tools belong to the
# caller's own context, not a child's.
FORBIDDEN_SPECIALIST_TOOLS: frozenset[str] = frozenset(
    {
        # recursion / orchestration
        "delegate_to_specialist",
        "run_swarm",
        "run_research_autopilot",
        "scheduled_research",
        # shell family
        "bash",
        "background_run",
        "check_background",
        "cancel_background",
        # session / goal / memory state owned by the caller's loop
        "start_research_goal",
        "get_research_goal",
        "add_goal_evidence",
        "update_research_goal_status",
        "session_search",
        "remember",
        "compact",
        # skill self-modification
        "save_skill",
        "patch_skill",
        "delete_skill",
        "skill_file",
        # order placement and mandate mutation — no specialist ever writes
        "trading_place_order",
        "trading_cancel_order",
        "propose_mandate_profiles",
        "etoro_copy_start",
        "etoro_copy_close",
        "etoro_copy_poll",
        "etoro_copy_precheck",
        "etoro_close_position",
        "etoro_cancel_close_order",
        "etoro_edit_position_stops",
        # disposable-cache rebuild (operator action, not specialist work)
        "refresh_strategy_evidence",
    }
)


class SpecialistSpec(BaseModel):
    """One domain specialist definition (bundled YAML or user override).

    Attributes:
        name: Stable identifier used as the ``delegate_to_specialist`` target.
        description: Routing signal shown to the main agent — trigger
            conditions and NOT-for anti-triggers, never capability boasts.
        prompt: Behavior contract injected as the specialist's system prompt.
        tools: Hard whitelist of internal (local) tool names. MCP-served
            (``mcp_*``) tools are not supported in v1.
        skills: Skill names loadable via ``load_skill``. Empty means no
            skills are loadable and no skill catalog is shown — the
            specialist path deliberately diverges from the swarm worker's
            "empty = unrestricted" convention.
        max_iterations: Specialist ReAct-loop iteration budget.
        timeout_seconds: Wall-clock budget for one delegation.
        model_name: Optional model override; ``None`` inherits the run's model.
    """

    name: str
    description: str
    prompt: str
    tools: list[str] = Field(min_length=1)
    skills: list[str] = Field(default_factory=list)
    max_iterations: int = Field(default=25, ge=1, le=100)
    timeout_seconds: int = Field(default=600, ge=1, le=1800)
    model_name: str | None = None

    @field_validator("name")
    @classmethod
    def _name_shape(cls, value: str) -> str:
        if not _NAME_RE.match(value):
            raise ValueError(
                f"specialist name must match {_NAME_RE.pattern}: {value!r}"
            )
        return value

    @field_validator("tools")
    @classmethod
    def _no_forbidden_tools(cls, value: list[str]) -> list[str]:
        blocked = sorted(FORBIDDEN_SPECIALIST_TOOLS.intersection(value))
        if blocked:
            raise ValueError(
                f"specialist whitelist may never include {blocked} "
                "(recursion, orchestration, shell, session-state and "
                "order-write tools are structural exclusions)"
            )
        return value

    @field_validator("description", "prompt")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be non-empty")
        return value
