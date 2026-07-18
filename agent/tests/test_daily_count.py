"""Daily order-counter serialization tests with no broker transport."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import src.live.paths as live_paths
from src.live.daily_count import daily_order_lock

pytestmark = pytest.mark.unit


def _child_lock_attempt(repo_root: Path, home: Path) -> subprocess.CompletedProcess[str]:
    script = """
from src.live.daily_count import DailyOrderLockUnavailable, daily_order_lock
try:
    with daily_order_lock("alpaca"):
        print("acquired")
except DailyOrderLockUnavailable:
    print("blocked")
"""
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PYTHONPATH"] = str(repo_root / "agent")
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )


def test_daily_order_lock_is_cross_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lock held here denies another process, then becomes available."""
    runtime_root = tmp_path / ".vibe-trading"
    monkeypatch.setattr(live_paths, "get_runtime_root", lambda: runtime_root)
    repo_root = Path(__file__).resolve().parents[2]

    with daily_order_lock("alpaca"):
        blocked = _child_lock_attempt(repo_root, tmp_path)
    acquired = _child_lock_attempt(repo_root, tmp_path)

    assert blocked.stdout.strip() == "blocked"
    assert acquired.stdout.strip() == "acquired"
