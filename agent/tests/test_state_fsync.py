"""Durability regression: RunStateStore._write_json must fsync.

A crash between write() and the kernel flushing its page cache can leave
state.json truncated or empty. _write_json now writes in binary mode and
fsyncs the file descriptor before closing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.core.state as state_mod
from src.core.state import RunStateStore


def test_write_json_calls_fsync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fsynced: list[int] = []
    real_fsync = state_mod.os.fsync

    def spy(fd: int) -> None:
        fsynced.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(state_mod.os, "fsync", spy)

    target = tmp_path / "state.json"
    RunStateStore._write_json(target, {"status": "success"})

    assert fsynced, "fsync was not called on _write_json"
    assert json.loads(target.read_text(encoding="utf-8")) == {"status": "success"}


def test_write_json_roundtrips_unicode(tmp_path: Path) -> None:
    target = tmp_path / "req.json"
    RunStateStore._write_json(target, {"prompt": "买入 A 股"})
    assert json.loads(target.read_text(encoding="utf-8"))["prompt"] == "买入 A 股"
