"""edit_file contract: old_text must match exactly once unless replace_all is set."""

from __future__ import annotations

from src.tools.path_utils import FileRoots
from src.config.accessor import get_env_config


import json
from pathlib import Path

import pytest

from src.tools.edit_file_tool import EditFileTool


@pytest.fixture()
def run_dir(tmp_path: Path, monkeypatch) -> Path:
    """A run directory registered as an allowed run root."""
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    return tmp_path


def _edit(run_dir: Path, **kwargs) -> dict:
    """Run edit_file against ``notes.md`` in ``run_dir`` and parse the envelope."""
    return json.loads(EditFileTool(roots=FileRoots.from_config(get_env_config().api)).execute(path="notes.md", run_dir=str(run_dir), **kwargs))


def _write(run_dir: Path, text: str) -> Path:
    target = run_dir / "notes.md"
    target.write_text(text, encoding="utf-8")
    return target


def test_unique_match_is_replaced(run_dir: Path) -> None:
    target = _write(run_dir, "alpha beta gamma")

    body = _edit(run_dir, old_text="beta", new_text="BETA")

    assert body["status"] == "ok"
    assert body["replacements"] == 1
    assert target.read_text(encoding="utf-8") == "alpha BETA gamma"


def test_zero_matches_is_the_existing_error(run_dir: Path) -> None:
    target = _write(run_dir, "alpha beta")

    body = _edit(run_dir, old_text="delta", new_text="x")

    assert body["status"] == "error"
    assert "old_text not found in notes.md" in body["error"]
    assert target.read_text(encoding="utf-8") == "alpha beta"


def test_multiple_matches_without_replace_all_is_refused_and_file_unchanged(run_dir: Path) -> None:
    target = _write(run_dir, "x = 1\ny = 1\nz = 1\n")

    body = _edit(run_dir, old_text="= 1", new_text="= 2")

    assert body["status"] == "error"
    assert "3" in body["error"]
    assert "replace_all" in body["error"]
    assert "context" in body["error"]
    assert target.read_text(encoding="utf-8") == "x = 1\ny = 1\nz = 1\n"


@pytest.mark.parametrize(
    ("text", "old_text"),
    [("aaa", "aa"), ("    \n    \n    \n", "    \n    \n")],
    ids=["letters", "repeated-indented-blank-lines"],
)
def test_overlapping_matches_are_ambiguous_and_refused(run_dir: Path, text: str, old_text: str) -> None:
    # Two start offsets, one non-overlapping occurrence: str.count says 1.
    target = _write(run_dir, text)

    body = _edit(run_dir, old_text=old_text, new_text="X")

    assert body["status"] == "error"
    assert "2 places" in body["error"]
    assert target.read_text(encoding="utf-8") == text


def test_replace_all_on_overlapping_matches_replaces_left_to_right(run_dir: Path) -> None:
    target = _write(run_dir, "aaaa")

    body = _edit(run_dir, old_text="aa", new_text="b", replace_all=True)

    assert body["status"] == "ok"
    assert body["replacements"] == 2
    assert target.read_text(encoding="utf-8") == "bb"


def test_line_endings_outside_the_edit_are_kept_byte_for_byte(run_dir: Path) -> None:
    target = run_dir / "notes.md"
    target.write_bytes(b"line1\r\nline2\r\nline3\n")

    body = _edit(run_dir, old_text="line1\r\nline2", new_text="LINE1\r\nline2")

    assert body["status"] == "ok"
    assert target.read_bytes() == b"LINE1\r\nline2\r\nline3\n"


def test_multiple_matches_with_replace_all_replaces_every_one_and_reports_count(run_dir: Path) -> None:
    target = _write(run_dir, "x = 1\ny = 1\nz = 1\n")

    body = _edit(run_dir, old_text="= 1", new_text="= 2", replace_all=True)

    assert body["status"] == "ok"
    assert body["replacements"] == 3
    assert "3" in body["message"]
    assert target.read_text(encoding="utf-8") == "x = 2\ny = 2\nz = 2\n"


def test_replace_all_with_a_single_match_still_works(run_dir: Path) -> None:
    target = _write(run_dir, "only once")

    body = _edit(run_dir, old_text="once", new_text="twice", replace_all=True)

    assert body["status"] == "ok"
    assert body["replacements"] == 1
    assert target.read_text(encoding="utf-8") == "only twice"


def test_replace_all_with_zero_matches_is_still_an_error(run_dir: Path) -> None:
    target = _write(run_dir, "alpha")

    body = _edit(run_dir, old_text="beta", new_text="x", replace_all=True)

    assert body["status"] == "error"
    assert target.read_text(encoding="utf-8") == "alpha"


def test_identical_old_and_new_text_is_an_error_not_a_noop(run_dir: Path) -> None:
    target = _write(run_dir, "alpha beta")

    body = _edit(run_dir, old_text="beta", new_text="beta")

    assert body["status"] == "error"
    assert "identical" in body["error"]
    assert target.read_text(encoding="utf-8") == "alpha beta"


def test_empty_old_text_is_an_error(run_dir: Path) -> None:
    target = _write(run_dir, "alpha")

    body = _edit(run_dir, old_text="", new_text="prefix-")

    assert body["status"] == "error"
    assert "empty" in body["error"]
    assert target.read_text(encoding="utf-8") == "alpha"


@pytest.mark.parametrize("value", ["false", "true", 1, None])
def test_non_boolean_replace_all_is_refused(run_dir: Path, value) -> None:
    """A string "false" is truthy in Python; it must not silently mean replace-all."""
    target = _write(run_dir, "a a")

    body = _edit(run_dir, old_text="a", new_text="b", replace_all=value)

    assert body["status"] == "error"
    assert "replace_all" in body["error"]
    assert target.read_text(encoding="utf-8") == "a a"


def test_schema_declares_replace_all_as_optional_boolean() -> None:
    schema = EditFileTool.parameters

    assert schema["properties"]["replace_all"]["type"] == "boolean"
    assert "replace_all" not in schema["required"]
    assert "first occurrence" not in EditFileTool.description


def test_path_outside_roots_is_still_refused(run_dir: Path, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("outside") / "secret.md"
    outside.write_text("keep keep", encoding="utf-8")

    raw = EditFileTool(roots=FileRoots.from_config(get_env_config().api)).execute(
        path=str(outside), old_text="keep", new_text="gone", replace_all=True, run_dir=str(run_dir)
    )
    body = json.loads(raw)

    assert body["status"] == "error"
    assert outside.read_text(encoding="utf-8") == "keep keep"


def test_missing_file_is_still_reported(run_dir: Path) -> None:
    body = _edit(run_dir, old_text="a", new_text="b")

    assert body["status"] == "error"
    assert "File not found" in body["error"]
