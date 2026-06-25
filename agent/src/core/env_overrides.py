"""Runtime environment variable overrides with immediate + persistent effect."""

from __future__ import annotations

import os
from pathlib import Path


def set_env_override(key: str, value: str) -> dict:
    """Set an environment variable immediately AND persist to .env file.

    Args:
        key: Environment variable name.
        value: New value.

    Returns:
        dict with status, key, value, persisted (bool).
    """
    # 1. Immediate in-process effect
    os.environ[key] = value

    # 2. Persist to .env file
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    persisted = False

    if env_path.exists():
        lines = env_path.read_text().splitlines()
        updated = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{key}=") or stripped.startswith(f"# {key}="):
                lines[i] = f"{key}={value}"
                updated = True
                break
        if not updated:
            lines.append(f"{key}={value}")
        env_path.write_text("\n".join(lines) + "\n")
        persisted = True
    else:
        # Create .env if it doesn't exist
        env_path.write_text(f"{key}={value}\n")
        persisted = True

    return {"status": "ok", "key": key, "value": value, "persisted": persisted}
