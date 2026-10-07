"""``read_file`` says where it may read, and lists a directory it is given.

Regression (2026-09-29, a live risk-parity run on DeepSeek V4): the model went
looking for the backtest engine's source — ``../../agent/src/backtest``, the
checkout's absolute path, ``skills/../backtest/engine.py`` — and every attempt
got "File not found or path escapes workspace". Each spelling was a new call,
so none was blocked, and none was an observation: eight rounds later the run
stopped with ``no_progress`` after 93 seconds, before any backtest ran. The
message said neither which of the two had happened nor where reading is
allowed, so the model kept guessing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tools.read_file_tool import ReadFileTool


@pytest.fixture()
def run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    run = tmp_path / "run"
    (run / "artifacts").mkdir(parents=True)
    (run / "artifacts" / "metrics.csv").write_text("sharpe\n0.69\n", encoding="utf-8")
    (run / "artifacts" / ".archived_backtest.json").write_text("{}", encoding="utf-8")
    return run


def _read(path: str, run: Path) -> dict:
    return json.loads(ReadFileTool().execute(path=path, run_dir=str(run)))


@pytest.mark.parametrize(
    "path",
    ["../../agent/src/backtest", "skills/../backtest/engine.py", "/etc/hosts"],
)
def test_a_path_outside_the_readable_roots_is_refused_as_such(run_dir: Path, path: str) -> None:
    body = _read(path, run_dir)

    assert body["status"] == "error"
    assert body["error_code"] == "outside_readable_roots"
    # The refusal carries the way forward, not just the verdict.
    assert "run directory" in body["error"] and "skills/" in body["error"]
    assert "load_skill" in body["error"]


def test_a_missing_file_inside_a_root_is_not_found(run_dir: Path) -> None:
    body = _read("artifacts/equity.csv", run_dir)

    assert body["error_code"] == "not_found"
    assert "load_skill" in body["error"]


def test_a_directory_is_answered_with_its_entries(run_dir: Path) -> None:
    listing = _read("artifacts", run_dir)
    skill = _read("skills/strategy-generate", run_dir)

    assert listing["status"] == "ok" and listing["kind"] == "directory"
    assert listing["entries"] == ["metrics.csv"]  # dotfiles stay out
    assert "SKILL.md" in skill["entries"]


def test_a_file_still_reads_as_before(run_dir: Path) -> None:
    body = _read("artifacts/metrics.csv", run_dir)

    assert body["status"] == "ok"
    assert body["content"] == "sharpe\n0.69\n"
