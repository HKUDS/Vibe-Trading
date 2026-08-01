"""Pydantic models for the OpenBB Workspace bridge layer.

Only the ``/agents.json`` manifest needs a model: OpenBB Workspace is a
stateless caller that supplies the full conversation history on every
``/v1/query`` request, so the bridge keeps no cross-request session bookkeeping.
"""

from __future__ import annotations

from typing import Dict

from pydantic import BaseModel, Field


class AgentManifest(BaseModel):
    """A single agent entry in the ``/agents.json`` manifest.

    OpenBB Workspace consumes this structure to discover a custom agent, learn
    which endpoint to call, and which optional features are supported. The field
    set mirrors the published agents.json spec (name / description / image /
    endpoints / features).
    """

    name: str = Field(description="Human readable name of the agent.")
    description: str = Field(description="Short description shown in the UI.")
    image: str = Field(default="", description="URL of the agent avatar image.")
    endpoints: Dict[str, str] = Field(
        description="Map of endpoint kind -> URL, e.g. {'query': '/v1/query'}."
    )
    features: Dict[str, bool] = Field(
        default_factory=dict,
        description="Feature flags such as streaming / widget-dashboard-select.",
    )
