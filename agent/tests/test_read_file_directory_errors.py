"""Directory read failures follow the same JSON error contract as file reads."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.tools.read_file_tool import ReadFileTool


def test_unlistable_directory_returns_tool_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A supported directory path may fail during the actual listing operation."""
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    run = tmp_path / "run"
    directory = run / "artifacts"
    directory.mkdir(parents=True)
    (directory / "report.txt").write_text("report", encoding="utf-8")
    real_iterdir = Path.iterdir

    def denied_iterdir(path: Path) -> Iterator[Path]:
        if path == directory:
            raise PermissionError("fixture directory cannot be listed")
        return real_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", denied_iterdir)
    result = json.loads(ReadFileTool().execute(path="artifacts", run_dir=str(run)))
    assert result["status"] == "error"
    assert "fixture directory cannot be listed" in result["error"]
    # A listing error does not broaden the allowed roots or prevent file reads.
    control = json.loads(
        ReadFileTool().execute(path="artifacts/report.txt", run_dir=str(run))
    )
    assert control["status"] == "ok"
    assert control["content"] == "report"
