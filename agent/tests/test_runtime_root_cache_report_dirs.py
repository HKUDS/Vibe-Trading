"""Autopilot run dirs, alpha-bench cache/reports and the gildata code cache
must follow ``VIBE_TRADING_HOME`` like the rest of the runtime state."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def custom_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "vt-home"
    monkeypatch.setenv("VIBE_TRADING_HOME", str(root))
    return root


def test_autopilot_run_dir_honors_runtime_root(custom_root: Path) -> None:
    from src.tools import autopilot_tool

    run_dir = autopilot_tool._run_dir_for_hypothesis("hyp-1")
    assert run_dir.parent == custom_root / "runs"
    assert run_dir.name.startswith("autopilot_")


def test_alpha_bench_report_dir_honors_runtime_root(custom_root: Path) -> None:
    from src.tools import alpha_bench_tool

    assert alpha_bench_tool._default_output_dir() == custom_root / "reports"


def test_gildata_code_cache_honors_runtime_root(custom_root: Path) -> None:
    from backtest.loaders import gildata_codes

    assert gildata_codes._cache_path() == custom_root / "cache" / "gildata-codes.json"
