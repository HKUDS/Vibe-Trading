from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from backtest import validation


def test_rejects_missing_run_dir_argument() -> None:
    with pytest.raises(SystemExit, match="Usage: python -m backtest.validation <run_dir>"):
        validation._parse_run_dir(["validation"])


def test_rejects_blank_run_dir() -> None:
    with pytest.raises(SystemExit, match="run_dir must be a non-empty path"):
        validation._parse_run_dir(["validation", "   "])


def test_rejects_malformed_run_dir() -> None:
    with pytest.raises(SystemExit, match="Invalid run_dir path:"):
        validation._parse_run_dir(["validation", "\0bad"])


def test_rejects_missing_directory() -> None:
    missing_dir = Path(tempfile.gettempdir()) / "validation-cli-missing-dir"

    with pytest.raises(SystemExit, match=rf"run_dir does not exist: .*{missing_dir.name}"):
        validation._parse_run_dir(["validation", str(missing_dir)])


def test_rejects_non_directory_path() -> None:
    with tempfile.NamedTemporaryFile() as handle:
        with pytest.raises(SystemExit, match=rf"run_dir is not a directory: .*{Path(handle.name).name}"):
            validation._parse_run_dir(["validation", handle.name])


def test_accepts_existing_directory() -> None:
    with tempfile.TemporaryDirectory() as run_dir:
        parsed = validation._parse_run_dir(["validation", run_dir])

    assert parsed == Path(run_dir)
