"""
Tests for research/pipeline/stage3_backtest.py pure-logic helpers.

TDD: these tests are written BEFORE the implementation.

Stage 3 calls subprocess (backtest runner) and filesystem I/O — none of that
is tested via actual processes. Only the pure, deterministic logic is exercised:

  (a) build_run_config()             — correct config.json dict for a run
  (b) find_signal_engine()           — returns path if source exists, else None
  (c) build_stub_signal_engine()     — valid Python with SignalEngine.generate
  (d) stub passes AST validator      — agent/backtest/runner._validate_signal_engine_source
  (e) verify_run_artifacts()         — checks artifacts/ dir has at least one .csv
  (f) compute_exit_code()            — 0 on full success, 1 on any failure
  (g) list_pending_runs()            — parses strategy_runs.json entries correctly
  (h) symbol_to_short()              — "BTC-USDT-SWAP" -> "btc"

Pytest is run from research/ as:
    cd research && python -m pytest tests/
"""

from __future__ import annotations

import ast
import json
import sys
import types
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Bootstrap: research/ must be on sys.path.
_THIS_FILE = Path(__file__).resolve()
_RESEARCH_DIR = _THIS_FILE.parents[1]   # research/
_REPO_ROOT = _RESEARCH_DIR.parent       # repo root

for _p in (_RESEARCH_DIR, _REPO_ROOT):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

from pipeline.stage3_backtest import (   # noqa: E402
    BacktestRunResult,
    build_run_config,
    build_stub_signal_engine,
    compute_exit_code,
    find_signal_engine,
    list_pending_runs,
    symbol_to_short,
    verify_run_artifacts,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_research_config(period: int = 730, interval: str = "1H"):
    """Return a minimal ResearchConfig-like namespace for tests."""
    from pipeline.config import ResearchConfig, SymbolConfig, FeesConfig
    return ResearchConfig(
        symbols=(
            SymbolConfig(name="btc", okx_swap="BTC-USDT-SWAP", ccxt_bybit="BTC/USDT:USDT"),
        ),
        period=period,
        interval=interval,
        data_source="okx",
        engine="daily",
        fees=FeesConfig(maker_rate=0.0002, taker_rate=0.00055, slippage=0.0005),
        horizons_h=(8, 24, 72, 168),
    )


def _make_strategy_entry(
    strategy_id: str = "btc_s1_test",
    symbol: str = "BTC-USDT-SWAP",
    base_run: str | None = "btc_s1_base",
    regime_runs: dict | None = None,
    oos_runs: list | None = None,
):
    """Return a minimal StrategyRunsEntry-like object."""
    from pipeline.strategy_runs import StrategyRunsEntry
    return StrategyRunsEntry(
        symbol=symbol,
        spec_yaml="research/strategies/strategy_S1.yaml",
        base_run=base_run,
        regime_runs=types.MappingProxyType(regime_runs or {}),
        stress_runs=types.MappingProxyType({}),
        oos_runs=tuple(oos_runs or []),
        sweep_run=None,
    )


# ---------------------------------------------------------------------------
# (a) build_run_config
# ---------------------------------------------------------------------------

class TestBuildRunConfig:
    """build_run_config(symbol, cfg) -> dict conforming to BacktestConfigSchema."""

    def test_base_run_structure(self):
        cfg = _make_research_config(period=730, interval="1H")
        result = build_run_config(symbol="BTC-USDT-SWAP", cfg=cfg)
        assert "codes" in result
        assert "start_date" in result
        assert "end_date" in result
        assert "source" in result
        assert "interval" in result
        assert "engine" in result

    def test_codes_contains_symbol(self):
        cfg = _make_research_config()
        result = build_run_config(symbol="BTC-USDT-SWAP", cfg=cfg)
        assert result["codes"] == ["BTC-USDT-SWAP"]

    def test_source_always_okx(self):
        cfg = _make_research_config()
        result = build_run_config(symbol="BTC-USDT-SWAP", cfg=cfg)
        assert result["source"] == "okx"

    def test_engine_always_daily(self):
        cfg = _make_research_config()
        result = build_run_config(symbol="BTC-USDT-SWAP", cfg=cfg)
        assert result["engine"] == "daily"

    def test_interval_from_config(self):
        cfg = _make_research_config(interval="4H")
        result = build_run_config(symbol="BTC-USDT-SWAP", cfg=cfg)
        assert result["interval"] == "4H"

    def test_end_date_is_today(self):
        fixed_today = date(2024, 1, 15)
        cfg = _make_research_config(period=730)
        result = build_run_config(symbol="BTC-USDT-SWAP", cfg=cfg, today=fixed_today)
        assert result["end_date"] == fixed_today.isoformat()

    def test_start_date_is_period_days_before_today(self):
        period = 730
        fixed_today = date(2024, 1, 15)
        cfg = _make_research_config(period=period)
        result = build_run_config(symbol="BTC-USDT-SWAP", cfg=cfg, today=fixed_today)
        expected_start = (fixed_today - timedelta(days=period)).isoformat()
        assert result["start_date"] == expected_start

    def test_oos_run_config_structure(self):
        """OOS run config uses the same schema; structure must be identical."""
        cfg = _make_research_config(period=365, interval="1H")
        result = build_run_config(symbol="BTC-USDT-SWAP", cfg=cfg)
        for key in ("codes", "start_date", "end_date", "source", "interval", "engine"):
            assert key in result, f"Missing key: {key}"

    def test_start_date_before_end_date(self):
        cfg = _make_research_config(period=730)
        result = build_run_config(symbol="BTC-USDT-SWAP", cfg=cfg)
        assert result["start_date"] < result["end_date"]


# ---------------------------------------------------------------------------
# (b) find_signal_engine
# ---------------------------------------------------------------------------

class TestFindSignalEngine:
    """find_signal_engine(strategies_code_dir, strategy_id) -> Path | None."""

    def test_found(self, tmp_path):
        strategy_id = "btc_s1_test"
        code_dir = tmp_path / "strategies" / "code" / strategy_id
        code_dir.mkdir(parents=True)
        se_file = code_dir / "signal_engine.py"
        se_file.write_text("class SignalEngine:\n    def generate(self, data_map): return {}\n")
        result = find_signal_engine(tmp_path / "strategies" / "code", strategy_id)
        assert result == se_file

    def test_not_found(self, tmp_path):
        result = find_signal_engine(tmp_path / "strategies" / "code", "btc_s1_nonexistent")
        assert result is None

    def test_returns_path_object(self, tmp_path):
        strategy_id = "btc_s1_test"
        code_dir = tmp_path / "strategies" / "code" / strategy_id
        code_dir.mkdir(parents=True)
        se_file = code_dir / "signal_engine.py"
        se_file.write_text("class SignalEngine: pass\n")
        result = find_signal_engine(tmp_path / "strategies" / "code", strategy_id)
        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# (c) build_stub_signal_engine
# ---------------------------------------------------------------------------

class TestBuildStubSignalEngine:
    """build_stub_signal_engine() -> str with valid Python."""

    def test_returns_string(self):
        result = build_stub_signal_engine()
        assert isinstance(result, str)

    def test_valid_python_syntax(self):
        source = build_stub_signal_engine()
        # Must not raise SyntaxError
        tree = ast.parse(source)
        assert tree is not None

    def test_contains_signal_engine_class(self):
        source = build_stub_signal_engine()
        tree = ast.parse(source)
        class_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        assert "SignalEngine" in class_names

    def test_contains_generate_method(self):
        source = build_stub_signal_engine()
        tree = ast.parse(source)
        method_names = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        ]
        assert "generate" in method_names

    def test_generate_takes_data_map_param(self):
        source = build_stub_signal_engine()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "generate":
                arg_names = [a.arg for a in node.args.args]
                assert "data_map" in arg_names
                return
        pytest.fail("generate() method not found")


# ---------------------------------------------------------------------------
# (d) stub passes AST validator
# ---------------------------------------------------------------------------

class TestStubPassesASTValidator:
    """Confirm build_stub_signal_engine() is accepted by runner._validate_signal_engine_source."""

    def test_stub_passes_validator(self, tmp_path):
        # Add agent/ to sys.path for this test
        agent_dir = _REPO_ROOT / "agent"
        agent_dir_str = str(agent_dir)
        had_agent = agent_dir_str in sys.path
        if not had_agent:
            sys.path.insert(0, agent_dir_str)
        try:
            try:
                from backtest.runner import _validate_signal_engine_source
            except ImportError:
                pytest.skip("agent/backtest/runner not available")
            stub_source = build_stub_signal_engine()
            se_file = tmp_path / "signal_engine.py"
            se_file.write_text(stub_source, encoding="utf-8")
            # Must not raise
            _validate_signal_engine_source(se_file)
        finally:
            if not had_agent and agent_dir_str in sys.path:
                sys.path.remove(agent_dir_str)


# ---------------------------------------------------------------------------
# (e) verify_run_artifacts
# ---------------------------------------------------------------------------

class TestVerifyRunArtifacts:
    """verify_run_artifacts(run_dir) -> BacktestRunResult."""

    def test_pass_with_csv(self, tmp_path):
        run_dir = tmp_path / "btc_s1_base"
        artifacts = run_dir / "artifacts"
        artifacts.mkdir(parents=True)
        (artifacts / "metrics.csv").write_text("sharpe,0.5\n")
        result = verify_run_artifacts(run_dir)
        assert result.ok is True

    def test_fail_no_artifacts_dir(self, tmp_path):
        run_dir = tmp_path / "btc_s1_base"
        run_dir.mkdir(parents=True)
        result = verify_run_artifacts(run_dir)
        assert result.ok is False
        assert "artifacts" in result.error.lower() or result.error

    def test_fail_empty_artifacts_dir(self, tmp_path):
        run_dir = tmp_path / "btc_s1_base"
        artifacts = run_dir / "artifacts"
        artifacts.mkdir(parents=True)
        # No files in artifacts
        result = verify_run_artifacts(run_dir)
        assert result.ok is False

    def test_fail_no_csv_in_artifacts(self, tmp_path):
        run_dir = tmp_path / "btc_s1_base"
        artifacts = run_dir / "artifacts"
        artifacts.mkdir(parents=True)
        (artifacts / "notes.txt").write_text("no csv here")
        result = verify_run_artifacts(run_dir)
        assert result.ok is False

    def test_result_contains_run_name(self, tmp_path):
        run_dir = tmp_path / "btc_s1_base"
        artifacts = run_dir / "artifacts"
        artifacts.mkdir(parents=True)
        (artifacts / "metrics.csv").write_text("sharpe,0.5\n")
        result = verify_run_artifacts(run_dir)
        assert result.run_name == "btc_s1_base"


# ---------------------------------------------------------------------------
# (f) compute_exit_code
# ---------------------------------------------------------------------------

class TestComputeExitCode:
    """compute_exit_code(results) -> 0 on success, 1 on any failure."""

    def _ok_result(self, name: str = "btc_s1_base") -> BacktestRunResult:
        return BacktestRunResult(run_name=name, ok=True, error=None)

    def _fail_result(self, name: str = "btc_s1_base") -> BacktestRunResult:
        return BacktestRunResult(run_name=name, ok=False, error="no artifacts")

    def test_all_ok_returns_0(self):
        results = [self._ok_result("run1"), self._ok_result("run2")]
        assert compute_exit_code(results) == 0

    def test_any_fail_returns_1(self):
        results = [self._ok_result("run1"), self._fail_result("run2")]
        assert compute_exit_code(results) == 1

    def test_all_fail_returns_1(self):
        results = [self._fail_result("run1"), self._fail_result("run2")]
        assert compute_exit_code(results) == 1

    def test_empty_returns_1(self):
        assert compute_exit_code([]) == 1

    def test_single_ok_returns_0(self):
        assert compute_exit_code([self._ok_result()]) == 0

    def test_single_fail_returns_1(self):
        assert compute_exit_code([self._fail_result()]) == 1


# ---------------------------------------------------------------------------
# (g) list_pending_runs
# ---------------------------------------------------------------------------

class TestListPendingRuns:
    """list_pending_runs(strategy_id, entry) -> list of (run_name, strategy_id, symbol) tuples."""

    def test_base_run_included(self):
        entry = _make_strategy_entry(base_run="btc_s1_base")
        runs = list_pending_runs("btc_s1_test", entry)
        run_names = [r[0] for r in runs]
        assert "btc_s1_base" in run_names

    def test_null_base_run_skipped(self):
        entry = _make_strategy_entry(base_run=None)
        runs = list_pending_runs("btc_s1_test", entry)
        # None should not appear
        for run_name, _, _ in runs:
            assert run_name is not None

    def test_regime_runs_included(self):
        entry = _make_strategy_entry(
            base_run=None,
            regime_runs={"bull": "btc_s1_bull", "bear": "btc_s1_bear"},
        )
        runs = list_pending_runs("btc_s1_test", entry)
        run_names = [r[0] for r in runs]
        assert "btc_s1_bull" in run_names
        assert "btc_s1_bear" in run_names

    def test_oos_runs_included(self):
        entry = _make_strategy_entry(
            base_run=None,
            oos_runs=["btc_s1_oos_2023", "btc_s1_oos_2024"],
        )
        runs = list_pending_runs("btc_s1_test", entry)
        run_names = [r[0] for r in runs]
        assert "btc_s1_oos_2023" in run_names
        assert "btc_s1_oos_2024" in run_names

    def test_stress_and_sweep_not_included(self):
        """stress_runs and sweep_run are NOT processed by stage3."""
        from pipeline.strategy_runs import StrategyRunsEntry
        entry = StrategyRunsEntry(
            symbol="BTC-USDT-SWAP",
            spec_yaml="research/strategies/strategy_S1.yaml",
            base_run=None,
            regime_runs=types.MappingProxyType({}),
            stress_runs=types.MappingProxyType({"3x_fees": "btc_s1_base_stress"}),
            oos_runs=(),
            sweep_run="btc_s1_sweep",
        )
        runs = list_pending_runs("btc_s1_test", entry)
        run_names = [r[0] for r in runs]
        assert "btc_s1_base_stress" not in run_names
        assert "btc_s1_sweep" not in run_names

    def test_each_run_tuple_has_strategy_id_and_symbol(self):
        entry = _make_strategy_entry(base_run="btc_s1_base", symbol="BTC-USDT-SWAP")
        runs = list_pending_runs("btc_s1_test", entry)
        for run_name, strategy_id, symbol in runs:
            assert strategy_id == "btc_s1_test"
            assert symbol == "BTC-USDT-SWAP"

    def test_all_base_plus_regime_plus_oos(self):
        entry = _make_strategy_entry(
            base_run="btc_s1_base",
            regime_runs={"bull": "btc_s1_bull"},
            oos_runs=["btc_s1_oos_2023"],
        )
        runs = list_pending_runs("btc_s1_test", entry)
        run_names = [r[0] for r in runs]
        assert "btc_s1_base" in run_names
        assert "btc_s1_bull" in run_names
        assert "btc_s1_oos_2023" in run_names
        assert len(run_names) == 3


# ---------------------------------------------------------------------------
# (h) symbol_to_short
# ---------------------------------------------------------------------------

class TestSymbolToShort:
    """symbol_to_short(symbol) -> short lowercase name."""

    def test_btc_usdt_swap(self):
        assert symbol_to_short("BTC-USDT-SWAP") == "btc"

    def test_eth_usdt_swap(self):
        assert symbol_to_short("ETH-USDT-SWAP") == "eth"

    def test_sol_usdt_swap(self):
        assert symbol_to_short("SOL-USDT-SWAP") == "sol"

    def test_lowercase_input(self):
        assert symbol_to_short("btc-usdt-swap") == "btc"

    def test_returns_lowercase(self):
        result = symbol_to_short("BTC-USDT-SWAP")
        assert result == result.lower()

    def test_symbol_to_short_no_hyphen(self):
        assert symbol_to_short("BTC") == "btc"
