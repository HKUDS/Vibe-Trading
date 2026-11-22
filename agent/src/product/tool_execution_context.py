"""Trusted tool catalog and user-derived policy inputs for the current turn."""
from __future__ import annotations

from dataclasses import dataclass
from src.agent.tools import ToolRegistry
from src.product.resources.memory import WorkspaceMemory
from src.product.identity.ledger import IdentityLedger
from src.product.data_window import UserDataWindow


@dataclass
class ToolEnvironment:
    registry: ToolRegistry
    memory: WorkspaceMemory
    identity: IdentityLedger | None = None
    data_window: UserDataWindow | None = None
    session_id: str = ""
