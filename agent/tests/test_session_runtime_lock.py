"""One live session service per sessions directory (``src.session.runtime_lock``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.session.runtime_lock import (
    LOCK_FILENAME,
    SessionsDirInUseError,
    claim_sessions_dir,
    release_sessions_dir,
)


def test_a_second_owner_is_refused_until_the_first_releases(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    claim_sessions_dir(sessions, "first")
    try:
        assert (sessions / LOCK_FILENAME).is_file()
        # Another spelling of the same directory is the same claim.
        with pytest.raises(SessionsDirInUseError, match="already served by first"):
            claim_sessions_dir(tmp_path / "." / "sessions", "second")
        release_sessions_dir(sessions, "second")  # Not its claim: no effect.
        with pytest.raises(SessionsDirInUseError):
            claim_sessions_dir(sessions, "second")
        assert claim_sessions_dir(sessions, "first") == sessions.resolve()
    finally:
        release_sessions_dir(sessions, "first")
    claim_sessions_dir(sessions, "second")
    release_sessions_dir(sessions, "second")


def test_an_owner_moving_to_another_directory_gives_up_the_previous_one(tmp_path: Path) -> None:
    claim_sessions_dir(tmp_path / "a", "server")
    claim_sessions_dir(tmp_path / "b", "server")
    try:
        claim_sessions_dir(tmp_path / "a", "client")
        release_sessions_dir(tmp_path / "a", "client")
        with pytest.raises(SessionsDirInUseError):
            claim_sessions_dir(tmp_path / "b", "client")
    finally:
        release_sessions_dir(tmp_path / "b", "server")
