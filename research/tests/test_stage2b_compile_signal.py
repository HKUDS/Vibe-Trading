"""Unit tests for research/pipeline/stage2b_compile_signal.py (Task 4).

Coverage:
  (a) valid YAML → signal_engine.py written; first line contains yaml-hash comment
  (b) manual escape hatch present → file not overwritten
  (c) invalid YAML → CompileResult status="fail"
  (d) --dry-run → no files created
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap — mirror pipeline bootstrap so imports resolve from anywhere.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_RESEARCH_DIR = _HERE.parents[1]   # research/
_REPO_ROOT = _RESEARCH_DIR.parent  # repo root
_AGENT_DIR = _REPO_ROOT / "agent"
_DASHBOARD_SCHEMAS = _REPO_ROOT / "dashboard" / "server"

for _p in (str(_RESEARCH_DIR), str(_REPO_ROOT), str(_AGENT_DIR), str(_DASHBOARD_SCHEMAS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from pipeline.stage2b_compile_signal import (  # noqa: E402
    CompileResult,
    _check_manual_escape_hatch,
    _compile_one,
    _extract_factor_names,
    _render_smoke_test,
)
from dashboard.server.schemas import IndicatorSpec, StrategySpec  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_MINIMAL_YAML = textwrap.dedent("""\
    name: test_strat
    archetype: multi_factor_consensus
    symbol: ETH-USDT-SWAP
    timeframe_signal: 8h
    indicators:
      funding_rate:
        source: stage1:funding_rate
        smoothing: sma_3
    entry_long:
      description: Enter long
      conditions:
        - funding_rate_zscore_30d <= -1.5
    entry_short:
      description: Enter short
      conditions:
        - funding_rate_zscore_30d >= 1.5
    exit_rules:
      - condition: time_based
        max_hold_hours: 120
      - condition: take_profit_pct
        value: 6.0
      - condition: stop_loss_pct
        value: 3.0
""")

_INVALID_YAML = "not_a_mapping: [broken\n"  # will fail yaml.safe_load


def _make_entry(spec_yaml_path: Path) -> dict:
    """Build a strategy_runs-style entry dict pointing at the given YAML path."""
    # Use repo-relative path string, as strategy_runs.json stores it.
    rel = spec_yaml_path.relative_to(_REPO_ROOT)
    return {
        "symbol": "ETH-USDT-SWAP",
        "spec_yaml": rel.as_posix(),
        "base_run": None,
        "regime_runs": {},
        "stress_runs": {},
        "oos_runs": [],
        "sweep_run": None,
    }


# ---------------------------------------------------------------------------
# (a) valid YAML → file written; first line contains yaml-hash comment
# ---------------------------------------------------------------------------

class TestValidYaml:
    def test_signal_engine_written(self, tmp_path: Path, monkeypatch):
        """Compiling a valid YAML writes signal_engine.py into the code dir."""
        # Write spec YAML inside a fake repo structure so relative path resolves.
        spec_yaml = tmp_path / "research" / "strategies" / "strategy_test_strat.yaml"
        spec_yaml.parent.mkdir(parents=True)
        spec_yaml.write_text(_MINIMAL_YAML, encoding="utf-8")

        entry = {
            "symbol": "ETH-USDT-SWAP",
            "spec_yaml": "research/strategies/strategy_test_strat.yaml",
            "base_run": None,
            "regime_runs": {},
            "stress_runs": {},
            "oos_runs": [],
            "sweep_run": None,
        }

        # Patch _REPO_ROOT and subprocess (skip actual pytest run).
        with (
            patch("pipeline.stage2b_compile_signal._REPO_ROOT", tmp_path),
            patch("pipeline.stage2b_compile_signal.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = _compile_one("test_strat", entry)

        assert result.status == "ok", result.message

        signal_engine = (
            tmp_path / "research" / "strategies" / "code" / "test_strat" / "signal_engine.py"
        )
        assert signal_engine.exists(), "signal_engine.py was not written"

        first_line = signal_engine.read_text(encoding="utf-8").splitlines()[0]
        assert "yaml-hash" in first_line or "yaml_hash" in first_line or "sha256" in first_line, (
            f"Expected yaml-hash comment on first line, got: {first_line!r}"
        )

    def test_test_file_written(self, tmp_path: Path, monkeypatch):
        """Compiling a valid YAML writes test_signal_engine.py alongside it."""
        spec_yaml = tmp_path / "research" / "strategies" / "strategy_test_strat.yaml"
        spec_yaml.parent.mkdir(parents=True)
        spec_yaml.write_text(_MINIMAL_YAML, encoding="utf-8")

        entry = {
            "symbol": "ETH-USDT-SWAP",
            "spec_yaml": "research/strategies/strategy_test_strat.yaml",
            "base_run": None,
            "regime_runs": {},
            "stress_runs": {},
            "oos_runs": [],
            "sweep_run": None,
        }

        with (
            patch("pipeline.stage2b_compile_signal._REPO_ROOT", tmp_path),
            patch("pipeline.stage2b_compile_signal.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = _compile_one("test_strat", entry)

        assert result.status == "ok", result.message

        test_file = (
            tmp_path / "research" / "strategies" / "code" / "test_strat" / "test_signal_engine.py"
        )
        assert test_file.exists(), "test_signal_engine.py was not written"
        content = test_file.read_text(encoding="utf-8")
        assert "def test_generate_returns_series" in content


# ---------------------------------------------------------------------------
# (b) manual escape hatch present → file not overwritten
# ---------------------------------------------------------------------------

class TestManualEscapeHatch:
    def test_file_not_overwritten(self, tmp_path: Path):
        """When escape hatch is present, _compile_one returns skip and leaves the file."""
        spec_yaml = tmp_path / "research" / "strategies" / "strategy_test_strat.yaml"
        spec_yaml.parent.mkdir(parents=True)
        spec_yaml.write_text(_MINIMAL_YAML, encoding="utf-8")

        # Create a signal_engine.py with the escape-hatch comment.
        code_dir = tmp_path / "research" / "strategies" / "code" / "test_strat"
        code_dir.mkdir(parents=True)
        sentinel_content = "# manual: do-not-overwrite\n# preserved content\n"
        (code_dir / "signal_engine.py").write_text(sentinel_content, encoding="utf-8")

        entry = {
            "symbol": "ETH-USDT-SWAP",
            "spec_yaml": "research/strategies/strategy_test_strat.yaml",
            "base_run": None,
            "regime_runs": {},
            "stress_runs": {},
            "oos_runs": [],
            "sweep_run": None,
        }

        with patch("pipeline.stage2b_compile_signal._REPO_ROOT", tmp_path):
            result = _compile_one("test_strat", entry)

        assert result.status == "skip"
        assert "escape hatch" in result.message

        # File must be unchanged.
        actual = (code_dir / "signal_engine.py").read_text(encoding="utf-8")
        assert actual == sentinel_content, "signal_engine.py was overwritten despite escape hatch"

    def test_escape_hatch_detection_false_when_missing(self, tmp_path: Path):
        """_check_manual_escape_hatch returns False if file doesn't exist."""
        assert _check_manual_escape_hatch(tmp_path / "nonexistent.py") is False

    def test_escape_hatch_detection_true_when_present(self, tmp_path: Path):
        """_check_manual_escape_hatch returns True if marker in first 5 lines."""
        p = tmp_path / "signal_engine.py"
        p.write_text("# manual: do-not-overwrite\npass\n")
        assert _check_manual_escape_hatch(p) is True

    def test_escape_hatch_detection_false_when_marker_beyond_line5(self, tmp_path: Path):
        """_check_manual_escape_hatch returns False if marker is after line 5."""
        p = tmp_path / "signal_engine.py"
        lines = ["# line {}\n".format(i) for i in range(10)]
        lines[7] = "# manual: do-not-overwrite\n"
        p.write_text("".join(lines))
        assert _check_manual_escape_hatch(p) is False


# ---------------------------------------------------------------------------
# (c) invalid YAML → CompileResult status="fail"
# ---------------------------------------------------------------------------

class TestInvalidYaml:
    def test_invalid_yaml_returns_fail(self, tmp_path: Path):
        """A malformed YAML file causes _compile_one to return status='fail'."""
        spec_yaml = tmp_path / "research" / "strategies" / "strategy_bad.yaml"
        spec_yaml.parent.mkdir(parents=True)
        # Write a YAML that parses fine but fails StrategySpec validation.
        spec_yaml.write_text("just_a_string: true\n", encoding="utf-8")

        entry = {
            "symbol": "ETH-USDT-SWAP",
            "spec_yaml": "research/strategies/strategy_bad.yaml",
            "base_run": None,
            "regime_runs": {},
            "stress_runs": {},
            "oos_runs": [],
            "sweep_run": None,
        }

        with patch("pipeline.stage2b_compile_signal._REPO_ROOT", tmp_path):
            result = _compile_one("bad_strat", entry)

        assert result.status == "fail"
        assert result.message  # error message is non-empty

    def test_missing_spec_yaml_returns_fail(self, tmp_path: Path):
        """A missing spec_yaml path causes _compile_one to return status='fail'."""
        entry = {
            "symbol": "ETH-USDT-SWAP",
            "spec_yaml": "research/strategies/strategy_nonexistent.yaml",
            "base_run": None,
            "regime_runs": {},
            "stress_runs": {},
            "oos_runs": [],
            "sweep_run": None,
        }

        with patch("pipeline.stage2b_compile_signal._REPO_ROOT", tmp_path):
            result = _compile_one("missing_strat", entry)

        assert result.status == "fail"
        assert "not found" in result.message.lower() or "FileNotFoundError" in result.message


# ---------------------------------------------------------------------------
# (d) --dry-run → no files created
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_no_files_created_on_dry_run(self, tmp_path: Path):
        """With dry_run=True, _compile_one does not write any files."""
        spec_yaml = tmp_path / "research" / "strategies" / "strategy_test_strat.yaml"
        spec_yaml.parent.mkdir(parents=True)
        spec_yaml.write_text(_MINIMAL_YAML, encoding="utf-8")

        entry = {
            "symbol": "ETH-USDT-SWAP",
            "spec_yaml": "research/strategies/strategy_test_strat.yaml",
            "base_run": None,
            "regime_runs": {},
            "stress_runs": {},
            "oos_runs": [],
            "sweep_run": None,
        }

        with patch("pipeline.stage2b_compile_signal._REPO_ROOT", tmp_path):
            result = _compile_one("test_strat", entry, dry_run=True)

        assert result.status == "ok"
        assert result.message == "dry-run"

        code_dir = tmp_path / "research" / "strategies" / "code" / "test_strat"
        assert not (code_dir / "signal_engine.py").exists(), (
            "signal_engine.py must not be created in dry-run mode"
        )
        assert not (code_dir / "test_signal_engine.py").exists(), (
            "test_signal_engine.py must not be created in dry-run mode"
        )

    def test_dry_run_does_not_call_subprocess(self, tmp_path: Path):
        """With dry_run=True, subprocess.run is never called."""
        spec_yaml = tmp_path / "research" / "strategies" / "strategy_test_strat.yaml"
        spec_yaml.parent.mkdir(parents=True)
        spec_yaml.write_text(_MINIMAL_YAML, encoding="utf-8")

        entry = {
            "symbol": "ETH-USDT-SWAP",
            "spec_yaml": "research/strategies/strategy_test_strat.yaml",
            "base_run": None,
            "regime_runs": {},
            "stress_runs": {},
            "oos_runs": [],
            "sweep_run": None,
        }

        with (
            patch("pipeline.stage2b_compile_signal._REPO_ROOT", tmp_path),
            patch("pipeline.stage2b_compile_signal.subprocess.run") as mock_run,
        ):
            _compile_one("test_strat", entry, dry_run=True)
            mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# Additional unit tests for helpers
# ---------------------------------------------------------------------------

class TestExtractFactorNames:
    def test_extracts_stage1_factor_names(self):
        spec = StrategySpec.model_validate({
            "name": "s",
            "archetype": "a",
            "symbol": "ETH-USDT-SWAP",
            "timeframe_signal": "8h",
            "indicators": {
                "funding_rate": {"source": "stage1:funding_rate", "smoothing": "none"},
                "basis": {"source": "stage1:basis", "smoothing": "sma_3"},
            },
            "exit_rules": [{"condition": "time_based", "max_hold_hours": 24}],
        })
        names = _extract_factor_names(spec)
        assert set(names) == {"funding_rate", "basis"}


class TestRenderSmokeTest:
    def test_renders_valid_python(self):
        import ast as ast_mod

        spec = StrategySpec.model_validate({
            "name": "s",
            "archetype": "a",
            "symbol": "ETH-USDT-SWAP",
            "timeframe_signal": "8h",
            "indicators": {
                "funding_rate": {"source": "stage1:funding_rate", "smoothing": "none"},
            },
            "exit_rules": [{"condition": "time_based", "max_hold_hours": 24}],
        })
        source = _render_smoke_test(spec, "test_strat")
        ast_mod.parse(source)  # must not raise

    def test_smoke_test_contains_symbol(self):
        spec = StrategySpec.model_validate({
            "name": "s",
            "archetype": "a",
            "symbol": "ETH-USDT-SWAP",
            "timeframe_signal": "8h",
            "indicators": {
                "funding_rate": {"source": "stage1:funding_rate", "smoothing": "sma_3"},
            },
            "exit_rules": [{"condition": "time_based", "max_hold_hours": 24}],
        })
        source = _render_smoke_test(spec, "test_strat")
        assert "ETH-USDT-SWAP" in source

    def test_smoke_test_contains_factor_names(self):
        spec = StrategySpec.model_validate({
            "name": "s",
            "archetype": "a",
            "symbol": "ETH-USDT-SWAP",
            "timeframe_signal": "8h",
            "indicators": {
                "my_factor": {"source": "stage1:my_factor", "smoothing": "none"},
            },
            "exit_rules": [{"condition": "time_based", "max_hold_hours": 24}],
        })
        source = _render_smoke_test(spec, "test_strat")
        assert "my_factor" in source
