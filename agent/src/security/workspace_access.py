"""Security workspace access compatibility helpers for channel adapters."""

from __future__ import annotations

WORKSPACE_SCOPE_METADATA_KEY = "_workspace_scope"


class WorkspaceScopeError(ValueError):
    """Raised when a path is outside the allowed workspace scope."""

    @property
    def message(self) -> str:
        """Compatibility accessor for ported channel code."""
        return str(self)
