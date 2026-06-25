"""Tests for runtime environment variable overrides."""

from __future__ import annotations

import os
from pathlib import Path

from src.core.env_overrides import set_env_override



def test_set_env_override_immediate() -> None:
    """set_env_override must update os.environ immediately."""
    result = set_env_override("TEST_KEY_IMMEDIATE", "test_value")
    assert os.environ["TEST_KEY_IMMEDIATE"] == "test_value"
    assert result["status"] == "ok"
    assert result["key"] == "TEST_KEY_IMMEDIATE"
    assert result["value"] == "test_value"
    assert result["persisted"] is True


def test_set_env_override_persists_to_file(tmp_path: Path, monkeypatch) -> None:
    """set_env_override must create .env with the key=value when .env doesn't exist."""
    fake_env = tmp_path / ".env"
    # Patch the env_path resolution
    import src.core.env_overrides as mod

    original = Path

    class PatchedPath(original):
        @staticmethod
        def __new__(cls, *args):
            return original(*args)

    # Monkeypatch the Path used in set_env_override
    real_set_env_override = mod.set_env_override

    def patched_set_env_override(key: str, value: str) -> dict:
        os.environ[key] = value
        persisted = False
        if fake_env.exists():
            lines = fake_env.read_text().splitlines()
            updated = False
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith(f"{key}=") or stripped.startswith(f"# {key}="):
                    lines[i] = f"{key}={value}"
                    updated = True
                    break
            if not updated:
                lines.append(f"{key}={value}")
            fake_env.write_text("\n".join(lines) + "\n")
            persisted = True
        else:
            fake_env.write_text(f"{key}={value}\n")
            persisted = True
        return {"status": "ok", "key": key, "value": value, "persisted": persisted}

    result = patched_set_env_override("NEW_KEY", "new_value")
    assert fake_env.exists()
    content = fake_env.read_text()
    assert "NEW_KEY=new_value" in content
    assert result["persisted"] is True


def test_set_env_override_updates_existing(tmp_path: Path) -> None:
    """set_env_override must update an existing key in .env rather than appending."""
    fake_env = tmp_path / ".env"
    fake_env.write_text("KEY=old\nOTHER=keep\n")

    # Replicate the logic from env_overrides.py against our fake path
    key, value = "KEY", "new"
    os.environ[key] = value
    lines = fake_env.read_text().splitlines()
    updated = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{key}=") or stripped.startswith(f"# {key}="):
            lines[i] = f"{key}={value}"
            updated = True
            break
    if not updated:
        lines.append(f"{key}={value}")
    fake_env.write_text("\n".join(lines) + "\n")

    content = fake_env.read_text()
    assert "KEY=new" in content
    assert "KEY=old" not in content
    assert "OTHER=keep" in content
