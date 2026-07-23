"""Pydantic models for the OpenBB Workspace bridge layer.

These models describe the ``/agents.json`` manifest advertised to OpenBB
Workspace and the internal bookkeeping used to map an OpenBB conversation onto
a Vibe-Trading session.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict

from pydantic import BaseModel, Field


class AgentManifest(BaseModel):
    """A single agent entry in the ``/agents.json`` manifest.

    OpenBB Workspace consumes this structure to discover a custom agent, learn
    which endpoint to call, and which optional features are supported.
    """

    name: str = Field(description="Human readable name of the agent.")
    description: str = Field(description="Short description shown in the UI.")
    image: str = Field(default="", description="URL of the agent avatar image.")
    endpoints: Dict[str, str] = Field(
        description="Map of endpoint kind -> path, e.g. {'query': '/v1/query'}."
    )
    features: Dict[str, bool] = Field(
        default_factory=dict,
        description="Feature flags such as streaming / widget-dashboard-select.",
    )


class SessionMapping(BaseModel):
    """Maps an OpenBB ``conversation_id`` to a Vibe-Trading ``session_id``."""

    conversation_id: str
    session_id: str
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    message_count: int = Field(
        default=0,
        description="Number of OpenBB messages already replayed into the session.",
    )
