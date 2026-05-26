"""Integration test: stage2 YAML → stage2b compile → importable signal_engine.

Scenario:
  1. A strategy YAML produced by stage2 (mocked) is written to a temp directory.
  2. _compile_one() processes it (with subprocess pytest mocked to skip actual run).
  3. Assertions verify that signal_engine.py and test_signal_engine.py exist
     and that the generated signal_engine.py can be imported as a module.

Marked with @pytest.mark.integration to allow selective exclusion in CI.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_RESEARCH_DIR = _HERE.parents[1]
_REPO_ROOT = _RESEARCH_DIR.parent
_AGENT_DIR = _REPO_ROOT / "agent"
_DASHBOARD_SCHEMAS = _REPO_ROOT / "dashboard" / "server"

for _p in (str(_RESEARCH_DIR), str(_REPO_ROOT), str(_AGENT_DIR), str(_DASHBOARD_SCHEMAS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from pipeline.stage2b_compile_signal import _compile_one  # noqa: E402

# ---------------------------------------------------------------------------
# Minimal strategy YAML that mirrors what stage2 emits.
# Uses a simple zscore DSL condition so the compiler can render entry blocks.
# ---------------------------------------------------------------------------
_STAGE2_YAML = textwrap.dedent("""\
    name: eth_s1_integration_test
    archetype: multi_factor_consensus
    symbol: ETH-USDT-SWAP
    timeframe_signal: 8h
    indicators:
      funding_rate:
        source: stage1:funding_rate
        smoothing: sma_3
      basis:
        source: stage1:basis
        smoothing: sma_3
    entry_long:
      description: Enter long when funding and basis are in fear regime.
      conditions:
        - funding_rate_zscore_30d <= -1.5 persist 2/3
        - basis_zscore_30d <= -1.5 persist 2/3
    entry_short:
      description: Enter short when funding and basis are in greed regime.
      conditions:
        - funding_rate_zscore_30d >= 1.5 persist 2/3
        - basis_zscore_30d >= 1.5 persist 2/3
    exit_rules:
      - condition: time_based
        max_hold_hours: 120
      - condition: take_profit_pct
        value: 6.0
      - condition: stop_loss_pct
        value: 3.0
""")


@pytest.mark.integration
class TestStage2ToStage2bIntegration:
    """End-to-end: stage2 YAML → stage2b compile → importable engine."""

    def test_signal_engine_and_test_file_created(self, tmp_path: Path):
        """signal_engine.py and test_signal_engine.py are written to the code dir."""
        # Simulate stage2 writing a strategy YAML.
        strat_id = "eth_s1_integration_test"
        strategies_dir = tmp_path / "research" / "strategies"
        strategies_dir.mkdir(parents=True)
        yaml_path = strategies_dir / f"strategy_{strat_id}.yaml"
        yaml_path.write_text(_STAGE2_YAML, encoding="utf-8")

        entry = {
            "symbol": "ETH-USDT-SWAP",
            "spec_yaml": f"research/strategies/strategy_{strat_id}.yaml",
            "base_run": None,
            "regime_runs": {},
            "stress_runs": {},
            "oos_runs": [],
            "sweep_run": None,
        }

        # Patch _REPO_ROOT so all paths resolve under tmp_path.
        # Patch subprocess.run so the pytest smoke test is not actually executed
        # (that would require the full research environment in tmp_path).
        with (
            patch("pipeline.stage2b_compile_signal._REPO_ROOT", tmp_path),
            patch("pipeline.stage2b_compile_signal.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="1 passed", stderr="")
            result = _compile_one(strat_id, entry)

        assert result.status == "ok", f"Expected ok, got fail: {result.message}"

        code_dir = tmp_path / "research" / "strategies" / "code" / strat_id
        signal_engine_path = code_dir / "signal_engine.py"
        test_path = code_dir / "test_signal_engine.py"

        assert signal_engine_path.exists(), "signal_engine.py not created"
        assert test_path.exists(), "test_signal_engine.py not created"

    def test_signal_engine_is_importable(self, tmp_path: Path):
        """The generated signal_engine.py can be loaded via importlib without error."""
        strat_id = "eth_s1_integration_test"
        strategies_dir = tmp_path / "research" / "strategies"
        strategies_dir.mkdir(parents=True)
        yaml_path = strategies_dir / f"strategy_{strat_id}.yaml"
        yaml_path.write_text(_STAGE2_YAML, encoding="utf-8")

        entry = {
            "symbol": "ETH-USDT-SWAP",
            "spec_yaml": f"research/strategies/strategy_{strat_id}.yaml",
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
            mock_run.return_value = MagicMock(returncode=0, stdout="1 passed", stderr="")
            result = _compile_one(strat_id, entry)

        assert result.status == "ok", result.message

        signal_engine_path = (
            tmp_path / "research" / "strategies" / "code" / strat_id / "signal_engine.py"
        )

        # Dynamically import the generated file.
        module_name = f"_integration_signal_engine_{strat_id}"
        spec = importlib.util.spec_from_file_location(module_name, signal_engine_path)
        module = importlib.util.module_from_spec(spec)

        # The generated engine imports lib.factor_io at call time (inside generate()),
        # not at module load time — so we only need to ensure the module itself imports
        # cleanly (no NameError / SyntaxError at import).
        spec.loader.exec_module(module)

        assert hasattr(module, "SignalEngine"), (
            "Generated signal_engine.py is missing the SignalEngine class"
        )

    def test_yaml_hash_embedded_in_signal_engine(self, tmp_path: Path):
        """The generated signal_engine.py contains the SHA-256 hash of the YAML."""
        import hashlib

        strat_id = "eth_s1_integration_test"
        strategies_dir = tmp_path / "research" / "strategies"
        strategies_dir.mkdir(parents=True)
        yaml_path = strategies_dir / f"strategy_{strat_id}.yaml"
        yaml_path.write_text(_STAGE2_YAML, encoding="utf-8")

        entry = {
            "symbol": "ETH-USDT-SWAP",
            "spec_yaml": f"research/strategies/strategy_{strat_id}.yaml",
            "base_run": None,
            "regime_runs": {},
            "stress_runs": {},
            "oos_runs": [],
            "sweep_run": None,
        }

        expected_hash = hashlib.sha256(_STAGE2_YAML.encode("utf-8")).hexdigest()

        with (
            patch("pipeline.stage2b_compile_signal._REPO_ROOT", tmp_path),
            patch("pipeline.stage2b_compile_signal.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="1 passed", stderr="")
            result = _compile_one(strat_id, entry)

        assert result.status == "ok", result.message

        signal_engine_path = (
            tmp_path / "research" / "strategies" / "code" / strat_id / "signal_engine.py"
        )
        content = signal_engine_path.read_text(encoding="utf-8")
        assert expected_hash in content, (
            f"Expected YAML hash {expected_hash!r} to appear in signal_engine.py"
        )
