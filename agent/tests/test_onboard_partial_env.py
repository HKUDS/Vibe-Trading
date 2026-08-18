"""POSIX permission and durability tests for the onboarding ``.env.partial``.

``.env.partial`` holds half-entered onboarding answers, which include API keys,
so it must never be world-readable and must never be destroyed by a failed
write — it exists precisely to survive a crash mid-onboarding.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from cli import onboard
from tests.module_os_helpers import patch_module_os

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="POSIX file modes are not meaningful on Windows"
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    """Point ``Path.home()`` at a temp dir so no real ~/.vibe-trading is touched."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    assert onboard._env_dir() == home / ".vibe-trading"
    return home


def test_new_partial_is_owner_only(fake_home):
    onboard._save_partial({"TUSHARE_TOKEN": "secret-token"})

    partial = onboard._partial_path()
    assert partial.read_text(encoding="utf-8") == "TUSHARE_TOKEN=secret-token\n"
    assert _mode(partial) == 0o600


def test_pre_existing_world_readable_partial_is_tightened(fake_home):
    partial = onboard._partial_path()
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_text("TUSHARE_TOKEN=leaked\n", encoding="utf-8")
    partial.chmod(0o644)

    onboard._save_partial({"TUSHARE_TOKEN": "rotated"})

    assert partial.read_text(encoding="utf-8") == "TUSHARE_TOKEN=rotated\n"
    assert _mode(partial) == 0o600


def test_failed_write_preserves_the_previous_partial(fake_home, monkeypatch):
    onboard._save_partial({"TUSHARE_TOKEN": "first-answer"})
    partial = onboard._partial_path()

    def explode(*args, **kwargs):
        raise OSError(28, "No space left on device")

    patch_module_os(monkeypatch, onboard, fdopen=explode)
    onboard._save_partial({"TUSHARE_TOKEN": "second-answer"})

    # The recovery state survives: a failed save must not leave the user with
    # nothing, which is what unlinking or truncating the destination would do.
    assert partial.read_text(encoding="utf-8") == "TUSHARE_TOKEN=first-answer\n"
    assert _mode(partial) == 0o600
    # A half-written temp file must not be left behind either — it would hold the
    # same secrets under a name nothing ever cleans up.
    assert [p.name for p in onboard._env_dir().iterdir()] == [".env.partial"]


def test_no_temp_files_are_left_behind(fake_home):
    onboard._save_partial({"TUSHARE_TOKEN": "a"})
    onboard._save_partial({"TUSHARE_TOKEN": "b"})

    assert [p.name for p in onboard._env_dir().iterdir()] == [".env.partial"]


def test_finalize_removes_the_partial_and_writes_owner_only_env(fake_home):
    onboard._save_partial({"TUSHARE_TOKEN": "draft"})

    env_path = onboard._finalize({"TUSHARE_TOKEN": "final"})

    assert env_path.read_text(encoding="utf-8") == "TUSHARE_TOKEN=final\n"
    assert _mode(env_path) == 0o600
    assert not onboard._partial_path().exists()
    assert [p.name for p in onboard._env_dir().iterdir()] == [".env"]
