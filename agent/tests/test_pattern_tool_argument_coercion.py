"""``PatternTool`` must turn malformed LLM arguments into JSON, not exceptions."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.tools.pattern_tool import PatternTool


@pytest.fixture()
def run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    arts = tmp_path / "artifacts"
    arts.mkdir()
    idx = pd.date_range("2024-01-01", periods=40)
    close = [10 + (i % 7) for i in range(40)]
    pd.DataFrame(
        {"open": close, "high": [c + 1 for c in close], "low": [c - 1 for c in close], "close": close},
        index=idx,
    ).to_csv(arts / "ohlcv_AAA.csv")
    return tmp_path


def _run(run_dir: Path, **kwargs):
    return json.loads(PatternTool().execute(run_dir=str(run_dir), **kwargs))


def test_null_window_uses_default(run_dir: Path) -> None:
    out = _run(run_dir, patterns="peaks_valleys", window=None)
    assert out["status"] == "ok"
    assert out["window"] == 10


def test_numeric_string_window_is_accepted(run_dir: Path) -> None:
    out = _run(run_dir, patterns="peaks_valleys", window="3")
    assert out["status"] == "ok"
    assert out["window"] == 3


@pytest.mark.parametrize("bad", ["abc", 2.5, True, [3]])
def test_non_integer_window_is_a_json_error(run_dir: Path, bad) -> None:
    out = _run(run_dir, patterns="peaks_valleys", window=bad)
    assert out["status"] == "error"
    assert "window" in out["error"]


def test_patterns_list_is_accepted(run_dir: Path) -> None:
    out = _run(run_dir, patterns=["peaks_valleys", "trend_slope"], window=3)
    assert out["status"] == "ok"
    assert out["patterns"] == ["peaks_valleys", "trend_slope"]


def test_null_patterns_means_all(run_dir: Path) -> None:
    out = _run(run_dir, patterns=None, window=3)
    assert out["status"] == "ok"
    assert len(out["patterns"]) == 8


def test_missing_run_dir_is_a_json_error() -> None:
    out = json.loads(PatternTool().execute())
    assert out["status"] == "error"
    assert "run_dir" in out["error"]
