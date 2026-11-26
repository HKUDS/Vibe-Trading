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

from src.tools.path_utils import FileRoots
from src.config.accessor import get_env_config


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
    return json.loads(ReadFileTool(roots=FileRoots.from_config(get_env_config().api)).execute(path=path, run_dir=str(run)))


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


def test_a_complete_read_is_not_marked_partial(run_dir: Path) -> None:
    assert not _read("artifacts/metrics.csv", run_dir).get("truncated")


def _read_limited(path: str, run: Path, limit: int | None) -> dict:
    tool = ReadFileTool(roots=FileRoots.from_config(get_env_config().api))
    return json.loads(tool.execute(path=path, run_dir=str(run), limit=limit))


@pytest.mark.parametrize("line_limit", [None, 1])
def test_partial_file_preview_names_the_complete_input(run_dir: Path, line_limit: int | None) -> None:
    original = json.dumps({"bars": [1] * 20000}) + "\nsecond line\n"
    (run_dir / "data.json").write_text(original, encoding="utf-8")

    body = _read_limited("data.json", run_dir, line_limit)

    assert body["truncated"] is True
    assert body["total_chars"] == len(original)
    assert "original file" in body["message"]
    assert len(body["content"]) < len(original)
    assert Path(body["path"]).read_text(encoding="utf-8") == original


def test_line_limit_marks_partial_even_below_character_cap(run_dir: Path) -> None:
    body = _read_limited("artifacts/metrics.csv", run_dir, 1)

    assert body["content"] == "sharpe\n"
    assert body["truncated"] is True
    assert body["total_lines"] == 2
    assert body["returned_lines"] == 1
    assert body["total_chars"] == len("sharpe\n0.69\n")


def _numbered(run: Path, count: int = 2000) -> str:
    original = "".join(f"line {i:06d} " + "x" * 40 + "\n" for i in range(count))
    (run / "numbered.txt").write_text(original, encoding="utf-8")
    return original


def _read_window(run: Path, **arguments) -> dict:
    tool = ReadFileTool(roots=FileRoots.from_config(get_env_config().api))
    return json.loads(tool.execute(path="numbered.txt", run_dir=str(run), **arguments))


def test_returned_lines_counts_what_the_character_cap_left(run_dir: Path) -> None:
    """A line limit cut again by the character cap reports the complete lines.

    Args:
        run_dir: Allowed directory containing the test file.
    """
    original = _numbered(run_dir)

    body = _read_window(run_dir, limit=1500)

    held = body["content"].removesuffix("\n... (truncated)")
    assert len(held) < len("".join(original.splitlines(keepends=True)[:1500]))
    assert body["returned_lines"] == held.count("\n")
    assert body["returned_lines"] < 1500
    assert body["total_lines"] == 2000


def test_offset_continues_a_partial_read_to_the_end(run_dir: Path) -> None:
    """Following the returned offsets reconstructs every line.

    Args:
        run_dir: Allowed directory containing the test file.
    """
    original = _numbered(run_dir)
    first = _read_window(run_dir, offset=0)
    next_offset = first["next_offset"]
    assert next_offset == first["returned_lines"] > 0
    second = _read_window(run_dir, offset=next_offset)
    assert second["offset"] == next_offset
    assert second["next_offset"] == next_offset + second["returned_lines"]
    last = _read_window(run_dir, offset=second["next_offset"])
    assert "next_offset" not in last
    assert first["content"].removesuffix("\n... (truncated)") + (
        second["content"].removesuffix("\n... (truncated)") + last["content"]
    ) == original


def test_offset_and_limit_select_a_line_window(run_dir: Path) -> None:
    """A nonzero offset applies before the requested line limit.

    Args:
        run_dir: Allowed directory containing the test file.
    """
    original = _numbered(run_dir, count=10)

    body = _read_window(run_dir, offset=3, limit=2)

    assert body["content"] == "".join(original.splitlines(keepends=True)[3:5])
    assert (body["offset"], body["returned_lines"], body["next_offset"], body["total_lines"]) == (3, 2, 5, 10)
    assert body["truncated"] is True
    last = _read_window(run_dir, offset=8)
    assert last["content"] == "".join(original.splitlines(keepends=True)[8:])
    assert last["truncated"] is True and "next_offset" not in last


@pytest.mark.parametrize("offset", [-1, 10, 11, "2", True])
def test_offset_outside_the_file_is_an_error(run_dir: Path, offset) -> None:
    """Reject an invalid offset with no content.

    Args:
        run_dir: Allowed directory containing the test file.
        offset: Invalid offset supplied by the caller.
    """
    _numbered(run_dir, count=10)

    body = _read_window(run_dir, offset=offset)

    assert body["status"] == "error"
    assert body["error_code"] == "invalid_offset"
    assert "content" not in body


def test_character_cursor_continues_an_oversized_line(run_dir: Path) -> None:
    """A line longer than the character cap can be read through its end.

    Args:
        run_dir: Allowed directory containing the test file.
    """
    original = "x" * 70_000 + "\nlast line without a newline"
    (run_dir / "numbered.txt").write_text(original, encoding="utf-8")
    first = _read_window(run_dir)
    assert first["next_offset"] == 0
    assert first["next_char_offset"] == first["returned_chars"]
    assert first["returned_lines"] == 0
    last = _read_window(run_dir, offset=first["next_offset"], char_offset=first["next_char_offset"])
    assert "next_offset" not in last
    assert last["returned_lines"] == 2
    assert first["content"][:first["returned_chars"]] + last["content"] == original
