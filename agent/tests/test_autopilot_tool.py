"""Tests for Research Autopilot bridge tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.hypotheses import HypothesisRegistry
from src.tools.autopilot_tool import GenerateBacktestConfigTool, _lookup_codes


def _seed_hypothesis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, universe: str):
    """Create a persisted hypothesis in an isolated registry."""
    monkeypatch.setenv("VIBE_TRADING_HYPOTHESES_PATH", str(tmp_path / "hypotheses.json"))
    return HypothesisRegistry().create(
        title="Momentum in target universe",
        thesis="A momentum signal should outperform over the test window.",
        universe=universe,
        signal_definition="Rank by trailing returns and buy the leaders.",
        data_sources=["local"],
    )


def test_lookup_codes_matches_chinext_case_insensitively() -> None:
    """Universe lookup should use the same normalized casing as input handling."""
    assert _lookup_codes("chiNext") == ["399006.SZ"]
    assert _lookup_codes("Chi-Next") == ["399006.SZ"]


def test_generate_backtest_config_writes_safe_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tool should write a config with mapped codes under the run root."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    hypothesis = _seed_hypothesis(tmp_path, monkeypatch, universe="chiNext")

    payload = json.loads(
        GenerateBacktestConfigTool().execute(
            hypothesis_id=hypothesis.hypothesis_id,
            start_date="2026-01-01",
            end_date="2026-01-31",
        )
    )

    assert payload["status"] == "ok"
    assert payload["config"]["codes"] == ["399006.SZ"]
    assert payload["config"]["source"] == "local"
    run_dir = Path(payload["run_dir"])
    assert run_dir.parent == tmp_path / ".vibe-trading" / "runs"
    assert run_dir.name.startswith("autopilot_")
    assert (run_dir / "code").is_dir()
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    assert config["start_date"] == "2026-01-01"


def test_generate_backtest_config_rejects_invalid_date_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invalid date ranges must fail before run artifacts are created."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    hypothesis = _seed_hypothesis(tmp_path, monkeypatch, universe="CSI 300")

    payload = json.loads(
        GenerateBacktestConfigTool().execute(
            hypothesis_id=hypothesis.hypothesis_id,
            start_date="2026-02-01",
            end_date="2026-01-01",
        )
    )

    assert payload["status"] == "error"
    assert "start_date" in payload["error"]
    assert not (tmp_path / ".vibe-trading" / "runs").exists()
