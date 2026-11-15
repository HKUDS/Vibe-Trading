"""Private dotenv I/O shared by CLI and HTTP settings, without HTTP dependencies."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Dict


def _atomic_write_secret(path: Path, content: str, *, allow_in_place: bool = True) -> None:
    """Write *content* to *path* atomically with 0600 permissions.

    The file holds provider API keys, so a crash mid-write must never leave a
    half-written or world-readable secret. The primary path writes to a sibling
    temp file (created 0600 by ``mkstemp``) and ``os.replace``s it onto the
    target — an atomic swap on the same filesystem.

    Fallback: when the parent directory is read-only (the ``.env`` is
    bind-mounted into a container whose rootfs is ``read_only: true``, so no
    sibling temp file can be created) the swap is impossible. There we write in
    place, still enforcing 0600; atomicity is sacrificed for that one edge but
    the secret still persists and stays owner-only.
    """
    data = content.encode("utf-8")
    try:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.", suffix=".tmp")
    except OSError:
        if not allow_in_place:
            raise
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return
    try:
        try:
            handle = os.fdopen(fd, "wb")
        except BaseException:
            os.close(fd)
            raise
        with handle:
            handle.write(data)
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), 0o600)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    finally:
        # Remove any uncommitted secret, including failed writes.
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def _ensure_agent_env_file(path: Path | None = None) -> Path:
    """Ensure the selected settings dotenv exists with private permissions."""
    env_path = path or (Path.home() / ".vibe-trading" / ".env")
    env_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not env_path.exists():
        _atomic_write_secret(env_path, "# Created by Vibe-Trading Web UI settings.\n")
    return env_path


def _strip_env_value(value: str) -> str:
    """Remove basic dotenv quotes and inline comments."""
    value = value.strip()
    if value[:1] in {"'", '"'}:
        q = value[0]
        i = 1
        while i < len(value):
            if value[i] == "\\" and i + 1 < len(value):
                i += 2
                continue
            if value[i] == q:
                return value[1:i].strip()
            i += 1
        return value
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value.strip()


def _dotenv_key(raw_key: str) -> str:
    """Return the canonical env key, stripping an optional ``export `` prefix.

    python-dotenv accepts ``export KEY=value``; Settings must too so reads and
    upserts hit the same key users set when sourcing a shell-style dotenv.
    """
    key = raw_key.strip()
    if key.lower().startswith("export "):
        key = key[7:].strip()
    return key


def _read_env_values(path: Path) -> Dict[str, str]:
    """Read active KEY=value entries from a dotenv file."""
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = _dotenv_key(key)
        if key:
            values[key] = _strip_env_value(value)
    return values


def _format_env_value(value: str) -> str:
    """Format a dotenv value without allowing multiline injection."""
    if "\n" in value or "\r" in value:
        raise ValueError("Environment values cannot contain newlines")
    value = value.strip()
    if not value:
        return ""
    if any(ch.isspace() for ch in value) or "#" in value:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _write_env_values(path: Path, updates: Dict[str, str]) -> None:
    """Upsert active dotenv values while preserving comments and ordering."""
    _ensure_agent_env_file(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    # Last active KEY= wins on read; update that line so upserts stick.
    last_active: Dict[str, int] = {}
    for index, raw in enumerate(lines):
        stripped = raw.lstrip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key = _dotenv_key(stripped.split("=", 1)[0])
        if key in updates:
            last_active[key] = index
    seen: set[str] = set()
    for key, index in last_active.items():
        stripped = lines[index].lstrip()
        prefix = "export " if stripped.lower().startswith("export ") else ""
        lines[index] = f"{prefix}{key}={_format_env_value(updates[key])}"
        seen.add(key)
    missing = [key for key in updates if key not in seen]
    if missing:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# Updated from Web UI")
        for key in missing:
            lines.append(f"{key}={_format_env_value(updates[key])}")
    _atomic_write_secret(path, "\n".join(lines) + "\n")


def render_env(values: dict[str, str]) -> str:
    """Render a new dotenv body using the same escaping rules as settings edits."""
    return "\n".join(f"{key}={_format_env_value(value)}" for key, value in values.items() if value) + "\n"
