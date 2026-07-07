"""Governance configuration helpers."""

from __future__ import annotations

import os

from src.governance.decisions import GovernanceMode
from src.governance.manifest import ToolSurface


VALID_MODES: set[str] = {"off", "observe", "warn", "enforce"}


def get_governance_mode(default: GovernanceMode = "observe") -> GovernanceMode:
    value = os.getenv("VIBE_TRADING_GOVERNANCE_MODE", default).strip().lower()
    if value not in VALID_MODES:
        return default
    return value  # type: ignore[return-value]


def parse_surface(value: str | ToolSurface | None, *, default: ToolSurface = ToolSurface.LOCAL_API) -> ToolSurface:
    if isinstance(value, ToolSurface):
        return value
    if value:
        try:
            return ToolSurface(str(value))
        except ValueError:
            pass
    return default
