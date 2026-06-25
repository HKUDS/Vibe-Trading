"""Env override tool: set runtime env vars with immediate + persistent effect."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.core.env_overrides import set_env_override as _set_env_override


class SetEnvOverrideTool(BaseTool):
    """Set a runtime environment variable with immediate and persistent effect."""

    name = "set_env_override"
    description = (
        "Set a runtime environment variable. Takes effect immediately in the "
        "current session AND persists to .env for future restarts."
    )
    parameters = {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Environment variable name"},
            "value": {"type": "string", "description": "New value"},
        },
        "required": ["key", "value"],
    }
    repeatable = True
    is_readonly = False

    def execute(self, **kwargs: Any) -> str:
        """Set an env var immediately and persist to .env.

        Args:
            **kwargs: Must include key and value.

        Returns:
            JSON string with status, key, value, persisted.
        """
        key = kwargs["key"]
        value = kwargs["value"]
        result = _set_env_override(key, value)
        return json.dumps(result, ensure_ascii=False)
