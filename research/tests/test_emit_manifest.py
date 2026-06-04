"""
Tests for research/emit_manifest.py pure-logic helpers.

All tests are self-contained — no real filesystem I/O beyond tmp_path, no
subprocess calls, no LLM calls.

Covers:
  (a) metrics_csv_to_backtest_metrics  — happy path, missing file, abs drawdown
  (b) compute_gate                     — all pass, sharpe fail, fatal oos/fee
  (c) derive_red_flags                 — each individual flag, no flags, oos below IS
  (d) build_spec_block                 — structure, validates SpecBlock schema
  (e) build_backtest_block             — in_sample, oos, regime_runs, base missing
  (f) build_strategy_manifest          — structure, gate when backtest, diagnosis loaded
  (g) verify_manifest                  — valid → ok, missing → fail, schema fail → fail
  (h) compute_exit_code                — empty→1, all ok→0, any fail→1
  (i) print_summary                    — smoke test (no crash)
  (j) _determine_pipeline_stage        — stage 2/3/4/5 logic
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

# ── Bootstrap ───────────────────────────────────────────────────────────────────
_THIS_FILE = Path(__file__).resolve()
_RESEARCH_DIR = _THIS_FILE.parents[1]   # research/
_REPO_ROOT = _RESEARCH_DIR.parent       # repo root

for _p in (_RESEARCH_DIR, _REPO_ROOT):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

_DASHBOARD_SCHEMAS = _REPO_ROOT / "dashboard" / "server"
if str(_DASHBOARD_SCHEMAS) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_SCHEMAS))

# ── Imports under test ──────────────────────────────────────────────────────────
from emit_manifest import (  # noqa: E402
    ManifestCheckResult,
    _determine_pipeline_stage,
    build_backtest_block,
    build_spec_block,
    build_strategy_manifest,
    compute_exit_code,
    compute_gate,
    derive_red_flags,
    emit_manifest_for_strategy,
    metrics_csv_to_backtest_metrics,
    print_summary,
    verify_manifest,
)

from schemas import (  # noqa: E402
    BacktestBlock,
    BacktestMetrics,
    GateBlock,
    RedFlagCode,
    SpecBlock,
    StrategyManifest,
)

from pipeline.strategy_runs import StrategyRunsEntry  # noqa: E402


# ─── Helpers ───────────────────────────────────────────────────────────────────


def _write_metrics_csv(path: Path, row: dict) -> None:
    """Write a minimal 1-row metrics.csv."""
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = list(row.keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(",".join(headers) + "\n")
        f.write(",".join(str(row[h]) for h in headers) + "\n")


def _good_metrics_row() -> dict:
    return {
        "sharpe": "2.0",
        "max_drawdown": "-0.08",
        "trades": "150",
        "profit_factor": "2.0",
        "total_return": "0.35",
        "win_rate": "0.55",
    }


def _make_entry(
    base_run: str | None = "base_run",
    oos_runs: tuple[str, ...] = (),
    regime_runs: dict | None = None,
    stress_runs: dict | None = None,
    symbol: str = "BTC-USDT-SWAP",
    spec_yaml: str = "research/strategies/s1.yaml",
    sweep_run: str | None = None,
    walk_forward_runs: tuple[str, ...] = (),
) -> StrategyRunsEntry:
    import types

    return StrategyRunsEntry(
        symbol=symbol,
        spec_yaml=spec_yaml,
        base_run=base_run,
        regime_runs=types.MappingProxyType(regime_runs or {}),
        stress_runs=types.MappingProxyType(stress_runs or {}),
        oos_runs=oos_runs,
        sweep_run=sweep_run,
        walk_forward_runs=walk_forward_runs,
    )


def _make_good_backtest(
    is_sharpe: float = 2.0,
    is_drawdown: float = 0.08,
    is_trades: int = 200,
    is_pf: float = 2.0,
    is_return: float = 0.40,
    oos_sharpe: float | None = 1.5,
    oos_drawdown: float | None = 0.08,
    oos_trades: int | None = 200,
    oos_pf: float | None = 2.0,
    include_stress: bool = True,
) -> BacktestBlock:
    from schemas import BenchmarkBlock, CostStressBlock, CostStressLevel

    in_s = BacktestMetrics(
        source_run="base_run",
        sharpe=is_sharpe,
        max_drawdown=is_drawdown,
        trades=is_trades,
        profit_factor=is_pf,
        total_return=is_return,
    )
    oos = (
        BacktestMetrics(
            source_run="oos_run",
            sharpe=oos_sharpe,
            max_drawdown=oos_drawdown,
            trades=oos_trades,
            profit_factor=oos_pf,
        )
        if oos_sharpe is not None
        else None
    )
    # Provide passing cost_stress by default so alpha_not_fee_illusion gate can pass.
    cost_stress: CostStressBlock | None = None
    if include_stress:
        cost_stress = CostStressBlock(
            source_run="stress_run",
            levels=[
                CostStressLevel(
                    label="3x_fees",
                    source_run="stress_run",
                    fee_multiplier=3.0,
                    sharpe=1.0,  # positive → passes alpha_not_fee_illusion
                )
            ],
        )
    return BacktestBlock(in_sample=in_s, oos=oos, cost_stress=cost_stress)


# ─── (a) metrics_csv_to_backtest_metrics ───────────────────────────────────────


class TestMetricsCsvToBacktestMetrics:

    def test_happy_path_returns_backtest_metrics(self, tmp_path):
        csv = tmp_path / "artifacts" / "metrics.csv"
        _write_metrics_csv(csv, _good_metrics_row())
        result = metrics_csv_to_backtest_metrics("my_run", csv)
        assert result is not None
        assert result.source_run == "my_run"

    def test_sharpe_parsed(self, tmp_path):
        csv = tmp_path / "artifacts" / "metrics.csv"
        _write_metrics_csv(csv, _good_metrics_row())
        result = metrics_csv_to_backtest_metrics("r", csv)
        assert result.sharpe == pytest.approx(2.0)

    def test_drawdown_abs_conversion_negative_in(self, tmp_path):
        """CSV stores -0.08; BacktestMetrics must store +0.08."""
        csv = tmp_path / "artifacts" / "metrics.csv"
        row = _good_metrics_row()
        row["max_drawdown"] = "-0.08"
        _write_metrics_csv(csv, row)
        result = metrics_csv_to_backtest_metrics("r", csv)
        assert result.max_drawdown == pytest.approx(0.08)

    def test_drawdown_abs_conversion_positive_in(self, tmp_path):
        """CSV stores +0.08; BacktestMetrics must also store +0.08."""
        csv = tmp_path / "artifacts" / "metrics.csv"
        row = _good_metrics_row()
        row["max_drawdown"] = "0.08"
        _write_metrics_csv(csv, row)
        result = metrics_csv_to_backtest_metrics("r", csv)
        assert result.max_drawdown == pytest.approx(0.08)

    def test_drawdown_large_value_clamped_to_one(self, tmp_path):
        """Values > 1.0 after abs() are clamped to 1.0 for schema compliance."""
        csv = tmp_path / "artifacts" / "metrics.csv"
        row = _good_metrics_row()
        row["max_drawdown"] = "-1.5"
        _write_metrics_csv(csv, row)
        result = metrics_csv_to_backtest_metrics("r", csv)
        assert result.max_drawdown == pytest.approx(1.0)

    def test_missing_file_returns_none(self, tmp_path):
        csv = tmp_path / "does_not_exist" / "metrics.csv"
        result = metrics_csv_to_backtest_metrics("r", csv)
        assert result is None

    def test_empty_csv_returns_none(self, tmp_path):
        csv = tmp_path / "empty.csv"
        csv.write_text("", encoding="utf-8")
        result = metrics_csv_to_backtest_metrics("r", csv)
        assert result is None

    def test_header_only_csv_returns_none(self, tmp_path):
        csv = tmp_path / "header_only.csv"
        csv.write_text("sharpe,max_drawdown\n", encoding="utf-8")
        result = metrics_csv_to_backtest_metrics("r", csv)
        assert result is None

    def test_trades_field_populated(self, tmp_path):
        csv = tmp_path / "metrics.csv"
        _write_metrics_csv(csv, _good_metrics_row())
        result = metrics_csv_to_backtest_metrics("r", csv)
        assert result.trades == 150

    def test_trade_count_fallback_key(self, tmp_path):
        """Some CSVs use 'trade_count' instead of 'trades'."""
        csv = tmp_path / "metrics.csv"
        row = {
            "sharpe": "1.8",
            "max_drawdown": "-0.05",
            "trade_count": "120",
            "profit_factor": "1.7",
            "total_return": "0.20",
            "win_rate": "0.52",
        }
        _write_metrics_csv(csv, row)
        result = metrics_csv_to_backtest_metrics("r", csv)
        assert result.trades == 120

    def test_source_run_stored(self, tmp_path):
        csv = tmp_path / "metrics.csv"
        _write_metrics_csv(csv, _good_metrics_row())
        result = metrics_csv_to_backtest_metrics("special_run", csv)
        assert result.source_run == "special_run"

    def test_partial_metrics_allowed(self, tmp_path):
        """Missing optional fields do not raise; they are None."""
        csv = tmp_path / "metrics.csv"
        _write_metrics_csv(csv, {"sharpe": "1.6", "max_drawdown": "-0.07"})
        result = metrics_csv_to_backtest_metrics("r", csv)
        assert result is not None
        assert result.sharpe == pytest.approx(1.6)
        assert result.trades is None


# ─── (b) compute_gate ──────────────────────────────────────────────────────────


class TestComputeGate:

    def test_all_pass_returns_overall_pass_true(self):
        bt = _make_good_backtest()
        gate = compute_gate(bt)
        assert gate.overall_pass is True
        assert gate.fatal_fail is False

    def test_sharpe_fail_sets_overall_pass_false(self):
        # OOS-aware: gate evaluates oos_sharpe against walk-forward threshold (1.0)
        bt = _make_good_backtest(oos_sharpe=0.5)
        gate = compute_gate(bt)
        assert gate.overall_pass is False

    def test_drawdown_fail_sets_overall_pass_false(self):
        # OOS-aware: gate evaluates oos_drawdown
        bt = _make_good_backtest(oos_drawdown=0.20)
        gate = compute_gate(bt)
        assert gate.overall_pass is False

    def test_trades_fail_sets_overall_pass_false(self):
        # OOS-aware: gate evaluates oos_trades against OOS threshold (30)
        bt = _make_good_backtest(oos_trades=5)
        gate = compute_gate(bt)
        assert gate.overall_pass is False

    def test_profit_factor_fail_sets_overall_pass_false(self):
        # OOS-aware: gate evaluates oos_pf
        bt = _make_good_backtest(oos_pf=1.2)
        gate = compute_gate(bt)
        assert gate.overall_pass is False

    def test_oos_sharpe_negative_sets_fatal_fail(self):
        bt = _make_good_backtest(oos_sharpe=-0.2)
        gate = compute_gate(bt)
        assert gate.fatal_fail is True

    def test_oos_sharpe_zero_sets_fatal_fail(self):
        bt = _make_good_backtest(oos_sharpe=0.0)
        gate = compute_gate(bt)
        assert gate.fatal_fail is True

    def test_oos_sharpe_none_oos_sharpe_positive_fails(self):
        """No OOS run means oos_sharpe_positive cannot pass."""
        bt = _make_good_backtest(oos_sharpe=None)
        gate = compute_gate(bt)
        # oos_sharpe_positive fails (actual=None) → fatal_fail
        assert gate.fatal_fail is True

    def test_alpha_fee_illusion_sets_fatal_fail(self):
        from schemas import CostStressBlock, CostStressLevel
        # Stress run sharpe negative → alpha_not_fee_illusion FATAL fails
        cost_stress = CostStressBlock(
            source_run="stress",
            levels=[CostStressLevel(label="3x_fees", source_run="stress",
                                    fee_multiplier=3.0, sharpe=-0.2)],
        )
        bt = BacktestBlock(
            in_sample=BacktestMetrics(source_run="base_run", sharpe=2.0,
                                      max_drawdown=0.08, trades=200, profit_factor=2.0),
            oos=BacktestMetrics(source_run="oos_run", sharpe=1.5),
            cost_stress=cost_stress,
        )
        gate = compute_gate(bt)
        assert gate.fatal_fail is True

    def test_gate_flags_are_consistent_validator(self):
        """GateBlock model_validator must not raise for well-formed output."""
        bt = _make_good_backtest()
        gate = compute_gate(bt)
        # Re-validate via Pydantic
        GateBlock.model_validate(gate.model_dump())

    def test_six_thresholds_always_present(self):
        bt = _make_good_backtest()
        gate = compute_gate(bt)
        assert len(gate.thresholds) == 6

    def test_threshold_names_correct(self):
        bt = _make_good_backtest()
        gate = compute_gate(bt)
        names = {t.name for t in gate.thresholds}
        assert "min_sharpe" in names
        assert "max_drawdown" in names
        assert "min_trades" in names
        assert "min_profit_factor" in names
        assert "oos_sharpe_positive" in names
        assert "alpha_not_fee_illusion" in names

    def test_fatal_thresholds_marked(self):
        bt = _make_good_backtest()
        gate = compute_gate(bt)
        fatal_names = {t.name for t in gate.thresholds if t.fatal}
        assert "oos_sharpe_positive" in fatal_names
        assert "alpha_not_fee_illusion" in fatal_names

    def test_source_run_is_in_sample_source(self):
        bt = _make_good_backtest()
        gate = compute_gate(bt)
        assert gate.source_run == "base_run"


# ─── (c) derive_red_flags ──────────────────────────────────────────────────────


class TestDeriveRedFlags:

    def test_no_red_flags_on_good_metrics(self):
        bt = _make_good_backtest(is_return=0.40, is_trades=200, is_pf=2.0,
                                  is_sharpe=2.0, oos_sharpe=1.8)
        flags = derive_red_flags(bt)
        assert flags == []

    def test_oos_sharpe_far_below_is(self):
        bt = _make_good_backtest(is_sharpe=2.0, oos_sharpe=0.8)  # 0.8 < 0.5*2.0=1.0
        flags = derive_red_flags(bt)
        assert RedFlagCode.OOS_SHARPE_FAR_BELOW_IS in flags

    def test_underperforms_hodl(self):
        from schemas import BenchmarkBlock
        bt = _make_good_backtest()
        # Inject benchmark showing strategy lost to HODL
        bt = BacktestBlock(
            in_sample=bt.in_sample,
            oos=bt.oos,
            cost_stress=bt.cost_stress,
            benchmark=BenchmarkBlock(
                source_run="base_run",
                strategy_return=0.10,
                hodl_return=0.30,
                excess_return=-0.20,
                beats_hodl=False,
            ),
        )
        flags = derive_red_flags(bt)
        assert RedFlagCode.UNDERPERFORMS_HODL in flags

    def test_too_few_trades(self):
        bt = _make_good_backtest(is_trades=50)
        flags = derive_red_flags(bt)
        assert RedFlagCode.TOO_FEW_TRADES in flags

    def test_alpha_is_fee_illusion(self):
        from schemas import CostStressBlock, CostStressLevel
        # IS sharpe=2.0; at 3x fees sharpe=0.5 → drop = (2.0-0.5)/2.0 = 75% > 50%
        cost_stress = CostStressBlock(
            source_run="stress",
            levels=[
                CostStressLevel(label="3x_fees", source_run="stress", fee_multiplier=3.0, sharpe=0.5),
            ],
        )
        bt = BacktestBlock(
            in_sample=BacktestMetrics(source_run="base", sharpe=2.0, max_drawdown=0.08,
                                      trades=200, profit_factor=2.0),
            oos=BacktestMetrics(source_run="oos", sharpe=1.5),
            cost_stress=cost_stress,
        )
        flags = derive_red_flags(bt)
        assert RedFlagCode.ALPHA_IS_FEE_ILLUSION in flags

    def test_overfit_suspect(self):
        bt = _make_good_backtest(is_sharpe=3.0, oos_sharpe=1.0)  # 3.0 > 2*1.0
        flags = derive_red_flags(bt)
        assert RedFlagCode.OVERFIT_SUSPECT in flags

    def test_no_overfit_when_oos_is_none(self):
        bt = _make_good_backtest(is_sharpe=3.0, oos_sharpe=None)
        flags = derive_red_flags(bt)
        assert RedFlagCode.OVERFIT_SUSPECT not in flags

    def test_oos_far_below_is_not_triggered_when_close(self):
        bt = _make_good_backtest(is_sharpe=2.0, oos_sharpe=1.2)  # 1.2 > 0.5*2.0=1.0
        flags = derive_red_flags(bt)
        assert RedFlagCode.OOS_SHARPE_FAR_BELOW_IS not in flags

    def test_multiple_flags_all_returned(self):
        # too_few_trades + oos_far_below_is both triggered
        bt = _make_good_backtest(is_sharpe=2.0, is_trades=50, oos_sharpe=0.5)
        flags = derive_red_flags(bt)
        assert RedFlagCode.TOO_FEW_TRADES in flags
        assert RedFlagCode.OOS_SHARPE_FAR_BELOW_IS in flags

    def test_result_is_sorted(self):
        bt = _make_good_backtest(is_return=-0.05, is_trades=50)
        flags = derive_red_flags(bt)
        assert flags == sorted(flags, key=lambda x: x.value)

    def test_no_oos_no_oos_flags(self):
        bt = _make_good_backtest(oos_sharpe=None)
        flags = derive_red_flags(bt)
        assert RedFlagCode.OOS_SHARPE_FAR_BELOW_IS not in flags
        assert RedFlagCode.OVERFIT_SUSPECT not in flags


# ─── (d) build_spec_block ──────────────────────────────────────────────────────


class TestBuildSpecBlock:

    def test_strategy_id_stored(self):
        spec = build_spec_block("my_strat", "BTC", None)
        assert spec.strategy_id == "my_strat"

    def test_symbol_stored(self):
        spec = build_spec_block("my_strat", "ETH", None)
        assert spec.symbol == "ETH"

    def test_spec_yaml_default_when_none(self):
        spec = build_spec_block("my_strat", "BTC", None)
        assert "my_strat" in spec.spec_yaml

    def test_spec_yaml_relative_path(self, tmp_path):
        fake_yaml = _REPO_ROOT / "research" / "strategies" / "test.yaml"
        spec = build_spec_block("s1", "BTC", fake_yaml)
        # Should be relative and use forward slashes
        assert not spec.spec_yaml.startswith(str(_REPO_ROOT))
        assert "\\" not in spec.spec_yaml

    def test_validates_against_spec_block_schema(self):
        spec = build_spec_block("strat_x", "BTC", None)
        SpecBlock.model_validate(spec.model_dump())

    def test_outside_repo_path_stored_as_str(self, tmp_path):
        """Path outside repo root falls back to str(path)."""
        outside = tmp_path / "outside" / "strategy.yaml"
        spec = build_spec_block("s1", "BTC", outside)
        assert "outside" in spec.spec_yaml or "strategy.yaml" in spec.spec_yaml


# ─── (e) build_backtest_block ──────────────────────────────────────────────────


class TestBuildBacktestBlock:

    def test_in_sample_populated_from_base_run(self, tmp_path):
        runs_root = tmp_path / "runs"
        csv = runs_root / "base" / "artifacts" / "metrics.csv"
        _write_metrics_csv(csv, _good_metrics_row())
        entry = _make_entry(base_run="base")
        bt = build_backtest_block(entry, runs_root)
        assert bt is not None
        assert bt.in_sample.source_run == "base"

    def test_oos_populated_from_first_oos_run(self, tmp_path):
        runs_root = tmp_path / "runs"
        base_csv = runs_root / "base" / "artifacts" / "metrics.csv"
        oos_csv = runs_root / "oos1" / "artifacts" / "metrics.csv"
        _write_metrics_csv(base_csv, _good_metrics_row())
        _write_metrics_csv(oos_csv, _good_metrics_row())
        entry = _make_entry(base_run="base", oos_runs=("oos1",))
        bt = build_backtest_block(entry, runs_root)
        assert bt.oos is not None
        assert bt.oos.source_run == "oos1"

    def test_oos_none_when_no_oos_runs(self, tmp_path):
        runs_root = tmp_path / "runs"
        base_csv = runs_root / "base" / "artifacts" / "metrics.csv"
        _write_metrics_csv(base_csv, _good_metrics_row())
        entry = _make_entry(base_run="base", oos_runs=())
        bt = build_backtest_block(entry, runs_root)
        assert bt.oos is None

    def test_oos_none_when_oos_csv_missing(self, tmp_path):
        runs_root = tmp_path / "runs"
        base_csv = runs_root / "base" / "artifacts" / "metrics.csv"
        _write_metrics_csv(base_csv, _good_metrics_row())
        entry = _make_entry(base_run="base", oos_runs=("oos_missing",))
        bt = build_backtest_block(entry, runs_root)
        assert bt.oos is None

    def test_base_run_none_returns_none(self, tmp_path):
        runs_root = tmp_path / "runs"
        entry = _make_entry(base_run=None)
        bt = build_backtest_block(entry, runs_root)
        assert bt is None

    def test_base_metrics_missing_returns_none(self, tmp_path):
        runs_root = tmp_path / "runs"
        entry = _make_entry(base_run="missing_run")
        bt = build_backtest_block(entry, runs_root)
        assert bt is None

    def test_regime_runs_populate_by_regime(self, tmp_path):
        runs_root = tmp_path / "runs"
        base_csv = runs_root / "base" / "artifacts" / "metrics.csv"
        bull_csv = runs_root / "bull_run" / "artifacts" / "metrics.csv"
        _write_metrics_csv(base_csv, _good_metrics_row())
        _write_metrics_csv(bull_csv, _good_metrics_row())
        entry = _make_entry(base_run="base", regime_runs={"bull": "bull_run"})
        bt = build_backtest_block(entry, runs_root)
        assert len(bt.by_regime) == 1
        assert bt.by_regime[0].regime == "bull"
        assert bt.by_regime[0].source_run == "bull_run"

    def test_regime_runs_missing_csv_skipped(self, tmp_path):
        runs_root = tmp_path / "runs"
        base_csv = runs_root / "base" / "artifacts" / "metrics.csv"
        _write_metrics_csv(base_csv, _good_metrics_row())
        entry = _make_entry(base_run="base", regime_runs={"bear": "bear_run"})
        bt = build_backtest_block(entry, runs_root)
        assert bt.by_regime == []

    def test_stress_runs_populate_cost_stress(self, tmp_path):
        runs_root = tmp_path / "runs"
        base_csv = runs_root / "base" / "artifacts" / "metrics.csv"
        stress_csv = runs_root / "stress1" / "artifacts" / "metrics.csv"
        _write_metrics_csv(base_csv, _good_metrics_row())
        stress_row = {**_good_metrics_row(), "fee_multiplier": "3.0"}
        _write_metrics_csv(stress_csv, stress_row)
        entry = _make_entry(base_run="base", stress_runs={"3x_fees": "stress1"})
        bt = build_backtest_block(entry, runs_root)
        assert bt.cost_stress is not None
        assert len(bt.cost_stress.levels) == 1
        assert bt.cost_stress.levels[0].label == "3x_fees"

    def test_no_stress_runs_cost_stress_is_none(self, tmp_path):
        runs_root = tmp_path / "runs"
        base_csv = runs_root / "base" / "artifacts" / "metrics.csv"
        _write_metrics_csv(base_csv, _good_metrics_row())
        entry = _make_entry(base_run="base", stress_runs={})
        bt = build_backtest_block(entry, runs_root)
        assert bt.cost_stress is None

    def test_drawdown_abs_in_regime_metrics(self, tmp_path):
        runs_root = tmp_path / "runs"
        base_csv = runs_root / "base" / "artifacts" / "metrics.csv"
        bull_csv = runs_root / "bull" / "artifacts" / "metrics.csv"
        _write_metrics_csv(base_csv, _good_metrics_row())
        regime_row = _good_metrics_row()
        regime_row["max_drawdown"] = "-0.12"
        _write_metrics_csv(bull_csv, regime_row)
        entry = _make_entry(base_run="base", regime_runs={"bull": "bull"})
        bt = build_backtest_block(entry, runs_root)
        assert bt.by_regime[0].max_drawdown == pytest.approx(0.12)

    def test_benchmark_populated_when_benchmark_return_in_csv(self, tmp_path):
        runs_root = tmp_path / "runs"
        base_csv = runs_root / "base" / "artifacts" / "metrics.csv"
        row = {**_good_metrics_row(), "benchmark_return": "0.20", "excess_return": "0.15"}
        _write_metrics_csv(base_csv, row)
        entry = _make_entry(base_run="base")
        bt = build_backtest_block(entry, runs_root)
        assert bt.benchmark is not None
        assert bt.benchmark.source_run == "base"
        assert bt.benchmark.hodl_return == pytest.approx(0.20)
        assert bt.benchmark.excess_return == pytest.approx(0.15)

    def test_benchmark_beats_hodl_true_when_strategy_wins(self, tmp_path):
        runs_root = tmp_path / "runs"
        base_csv = runs_root / "base" / "artifacts" / "metrics.csv"
        row = {**_good_metrics_row(), "total_return": "0.40", "benchmark_return": "0.20"}
        _write_metrics_csv(base_csv, row)
        entry = _make_entry(base_run="base")
        bt = build_backtest_block(entry, runs_root)
        assert bt.benchmark is not None
        assert bt.benchmark.beats_hodl is True

    def test_benchmark_beats_hodl_false_when_strategy_loses(self, tmp_path):
        runs_root = tmp_path / "runs"
        base_csv = runs_root / "base" / "artifacts" / "metrics.csv"
        row = {**_good_metrics_row(), "total_return": "0.10", "benchmark_return": "0.40"}
        _write_metrics_csv(base_csv, row)
        entry = _make_entry(base_run="base")
        bt = build_backtest_block(entry, runs_root)
        assert bt.benchmark is not None
        assert bt.benchmark.beats_hodl is False

    def test_benchmark_none_when_no_benchmark_return_column(self, tmp_path):
        runs_root = tmp_path / "runs"
        base_csv = runs_root / "base" / "artifacts" / "metrics.csv"
        _write_metrics_csv(base_csv, _good_metrics_row())  # no benchmark_return column
        entry = _make_entry(base_run="base")
        bt = build_backtest_block(entry, runs_root)
        assert bt.benchmark is None

    def test_underperforms_hodl_flag_set_via_benchmark(self, tmp_path):
        runs_root = tmp_path / "runs"
        base_csv = runs_root / "base" / "artifacts" / "metrics.csv"
        row = {**_good_metrics_row(), "total_return": "0.05", "benchmark_return": "0.40"}
        _write_metrics_csv(base_csv, row)
        entry = _make_entry(base_run="base")
        bt = build_backtest_block(entry, runs_root)
        assert bt.benchmark is not None
        assert bt.benchmark.beats_hodl is False
        from emit_manifest import derive_red_flags
        flags = derive_red_flags(bt)
        assert RedFlagCode.UNDERPERFORMS_HODL in flags


# ─── (e2) TestOosSourceFallback ────────────────────────────────────────────────


class TestOosSourceFallback:

    def test_walk_forward_used_when_oos_runs_empty(self, tmp_path):
        """oos_runs empty + walk_forward_runs present → oos populated from wf run."""
        runs_root = tmp_path / "runs"
        base_csv = runs_root / "base" / "artifacts" / "metrics.csv"
        wf_csv = runs_root / "wf_oos" / "artifacts" / "metrics.csv"
        _write_metrics_csv(base_csv, _good_metrics_row())
        _write_metrics_csv(wf_csv, _good_metrics_row())
        entry = _make_entry(base_run="base", oos_runs=(), walk_forward_runs=("wf_oos",))
        bt = build_backtest_block(entry, runs_root)
        assert bt is not None
        assert bt.oos is not None
        assert bt.oos.source_run == "wf_oos"

    def test_oos_runs_takes_precedence_over_walk_forward(self, tmp_path):
        """When both oos_runs and walk_forward_runs present, oos_runs wins."""
        runs_root = tmp_path / "runs"
        base_csv = runs_root / "base" / "artifacts" / "metrics.csv"
        oos_csv = runs_root / "explicit_oos" / "artifacts" / "metrics.csv"
        wf_csv = runs_root / "wf_run" / "artifacts" / "metrics.csv"
        _write_metrics_csv(base_csv, _good_metrics_row())
        _write_metrics_csv(oos_csv, _good_metrics_row())
        _write_metrics_csv(wf_csv, _good_metrics_row())
        entry = _make_entry(
            base_run="base",
            oos_runs=("explicit_oos",),
            walk_forward_runs=("wf_run",),
        )
        bt = build_backtest_block(entry, runs_root)
        assert bt is not None
        assert bt.oos is not None
        assert bt.oos.source_run == "explicit_oos"

    def test_oos_none_when_both_empty(self, tmp_path):
        """oos_runs and walk_forward_runs both empty → oos is None."""
        runs_root = tmp_path / "runs"
        base_csv = runs_root / "base" / "artifacts" / "metrics.csv"
        _write_metrics_csv(base_csv, _good_metrics_row())
        entry = _make_entry(base_run="base", oos_runs=(), walk_forward_runs=())
        bt = build_backtest_block(entry, runs_root)
        assert bt is not None
        assert bt.oos is None


# ─── (e3) TestOosAwareGate ─────────────────────────────────────────────────────


class TestOosAwareGate:
    """Tests for OOS-aware gate evaluation in compute_gate."""

    def _make_oos_backtest(
        self,
        oos_sharpe: float = 1.016,
        oos_drawdown: float = 0.091,
        oos_trades: int = 49,
        oos_pf: float = 1.539,
        is_sharpe: float = 2.0,
        include_stress: bool = False,
        stress_sharpe: float | None = None,
    ) -> "BacktestBlock":
        from schemas import BacktestMetrics, BacktestBlock, CostStressBlock, CostStressLevel

        in_s = BacktestMetrics(
            source_run="base_run",
            sharpe=is_sharpe,
            max_drawdown=0.08,
            trades=200,
            profit_factor=2.0,
        )
        oos = BacktestMetrics(
            source_run="oos_run",
            sharpe=oos_sharpe,
            max_drawdown=oos_drawdown,
            trades=oos_trades,
            profit_factor=oos_pf,
        )
        cost_stress = None
        if include_stress and stress_sharpe is not None:
            cost_stress = CostStressBlock(
                source_run="stress_run",
                levels=[CostStressLevel(
                    label="3x_fees",
                    source_run="stress_run",
                    fee_multiplier=3.0,
                    sharpe=stress_sharpe,
                )],
            )
        return BacktestBlock(in_sample=in_s, oos=oos, cost_stress=cost_stress)

    def test_oos_sharpe_1016_passes_with_threshold_10(self):
        """OOS sharpe 1.016 → min_sharpe actual=1.016 threshold=1.0 passed."""
        bt = self._make_oos_backtest(oos_sharpe=1.016)
        gate = compute_gate(bt)
        sharpe_t = next(t for t in gate.thresholds if t.name == "min_sharpe")
        assert sharpe_t.threshold == pytest.approx(1.0)
        assert sharpe_t.actual == pytest.approx(1.016)
        assert sharpe_t.passed is True

    def test_oos_trades_49_passes_with_threshold_30(self):
        """OOS trades 49 → min_trades threshold=30 passed."""
        bt = self._make_oos_backtest(oos_trades=49)
        gate = compute_gate(bt)
        trades_t = next(t for t in gate.thresholds if t.name == "min_trades")
        assert trades_t.threshold == pytest.approx(30.0)
        assert trades_t.actual == pytest.approx(49.0)
        assert trades_t.passed is True

    def test_oos_drawdown_091_passes(self):
        """OOS dd 0.091 → max_drawdown passed (≤ 0.10)."""
        bt = self._make_oos_backtest(oos_drawdown=0.091)
        gate = compute_gate(bt)
        dd_t = next(t for t in gate.thresholds if t.name == "max_drawdown")
        assert dd_t.threshold == pytest.approx(0.10)
        assert dd_t.actual == pytest.approx(0.091)
        assert dd_t.passed is True

    def test_legacy_thresholds_unchanged_when_no_oos(self):
        """Legacy (oos None): min_sharpe threshold=1.5, min_trades threshold=100."""
        from schemas import BacktestMetrics, BacktestBlock, CostStressBlock, CostStressLevel

        in_s = BacktestMetrics(
            source_run="base",
            sharpe=1.6,
            max_drawdown=0.08,
            trades=120,
            profit_factor=2.0,
        )
        cost_stress = CostStressBlock(
            source_run="s",
            levels=[CostStressLevel(
                label="3x_fees", source_run="s", fee_multiplier=3.0, sharpe=1.0
            )],
        )
        bt = BacktestBlock(in_sample=in_s, oos=None, cost_stress=cost_stress)
        gate = compute_gate(bt)
        sharpe_t = next(t for t in gate.thresholds if t.name == "min_sharpe")
        trades_t = next(t for t in gate.thresholds if t.name == "min_trades")
        assert sharpe_t.threshold == pytest.approx(1.5)
        assert trades_t.threshold == pytest.approx(100.0)
        # In-sample values used
        assert sharpe_t.actual == pytest.approx(1.6)
        assert trades_t.actual == pytest.approx(120.0)

    def test_no_stress_alpha_fatal_false_fatal_fail_not_set(self):
        """No stress data → alpha_not_fee_illusion fatal=false; fatal_fail not set."""
        bt = self._make_oos_backtest(include_stress=False)
        gate = compute_gate(bt)
        alpha_t = next(t for t in gate.thresholds if t.name == "alpha_not_fee_illusion")
        assert alpha_t.fatal is False
        assert alpha_t.actual is None
        assert gate.fatal_fail is False

    def test_stress_negative_alpha_fatal_true_fatal_fail_true(self):
        """Stress worst -0.5 → alpha_not_fee_illusion fatal=true, passed=false, fatal_fail=true."""
        bt = self._make_oos_backtest(include_stress=True, stress_sharpe=-0.5)
        gate = compute_gate(bt)
        alpha_t = next(t for t in gate.thresholds if t.name == "alpha_not_fee_illusion")
        assert alpha_t.fatal is True
        assert alpha_t.passed is False
        assert gate.fatal_fail is True

    def test_stress_positive_alpha_passed(self):
        """Stress worst 0.4 → alpha_not_fee_illusion passed=true."""
        bt = self._make_oos_backtest(include_stress=True, stress_sharpe=0.4)
        gate = compute_gate(bt)
        alpha_t = next(t for t in gate.thresholds if t.name == "alpha_not_fee_illusion")
        assert alpha_t.passed is True
        assert alpha_t.fatal is True

    def test_eth_s5_shaped_no_fatal_fail(self):
        """eth_s5-shaped: OOS sharpe 1.016, dd 0.091, trades 49, pf 1.539, no stress → fatal_fail=false."""
        bt = self._make_oos_backtest(
            oos_sharpe=1.016,
            oos_drawdown=0.091,
            oos_trades=49,
            oos_pf=1.539,
            include_stress=False,
        )
        gate = compute_gate(bt)
        assert gate.fatal_fail is False
        # oos_sharpe_positive passes (1.016 > 0)
        oos_t = next(t for t in gate.thresholds if t.name == "oos_sharpe_positive")
        assert oos_t.passed is True
        assert oos_t.fatal is True


# ─── (f) build_strategy_manifest ───────────────────────────────────────────────


class TestBuildStrategyManifest:

    def _minimal_entry(self) -> StrategyRunsEntry:
        return _make_entry(base_run=None)

    def test_basic_structure_keys(self, tmp_path):
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        entry = self._minimal_entry()
        result = build_strategy_manifest("s1", "BTC", entry, tmp_path / "runs", manifests_dir)
        assert result["strategy_id"] == "s1"
        assert result["symbol"] == "BTC"
        assert "generated_at" in result
        assert "spec" in result
        assert "pipeline_stage" in result

    def test_gate_present_when_backtest_available(self, tmp_path):
        runs_root = tmp_path / "runs"
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        base_csv = runs_root / "base" / "artifacts" / "metrics.csv"
        oos_csv = runs_root / "oos1" / "artifacts" / "metrics.csv"
        _write_metrics_csv(base_csv, _good_metrics_row())
        _write_metrics_csv(oos_csv, _good_metrics_row())
        entry = _make_entry(base_run="base", oos_runs=("oos1",))
        result = build_strategy_manifest("s1", "BTC", entry, runs_root, manifests_dir)
        assert result.get("gate") is not None

    def test_gate_none_when_no_backtest(self, tmp_path):
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        entry = _make_entry(base_run=None)
        result = build_strategy_manifest("s1", "BTC", entry, tmp_path / "runs", manifests_dir)
        assert result.get("gate") is None
        assert result.get("backtest") is None

    def test_diagnosis_loaded_when_file_exists(self, tmp_path):
        manifests_dir = tmp_path / "manifests"
        strat_dir = manifests_dir / "s1"
        strat_dir.mkdir(parents=True)
        diag = {
            "source_run": "base",
            "recommended_action": "proceed",
            "summary": "Looks good.",
            "findings": [],
        }
        (strat_dir / "diagnosis.json").write_text(json.dumps(diag), encoding="utf-8")
        entry = _make_entry(base_run=None)
        result = build_strategy_manifest("s1", "BTC", entry, tmp_path / "runs", manifests_dir)
        assert result.get("diagnosis") is not None
        assert result["diagnosis"]["recommended_action"] == "proceed"

    def test_pipeline_stage_3_when_diagnosis_exists(self, tmp_path):
        manifests_dir = tmp_path / "manifests"
        strat_dir = manifests_dir / "s1"
        strat_dir.mkdir(parents=True)
        diag = {
            "source_run": "base",
            "recommended_action": "proceed",
            "summary": None,
            "findings": [],
        }
        (strat_dir / "diagnosis.json").write_text(json.dumps(diag), encoding="utf-8")
        entry = _make_entry(base_run=None)
        result = build_strategy_manifest("s1", "BTC", entry, tmp_path / "runs", manifests_dir)
        assert result["pipeline_stage"] == 3

    def test_pipeline_stage_4_when_optimization_exists(self, tmp_path):
        manifests_dir = tmp_path / "manifests"
        strat_dir = manifests_dir / "s1"
        strat_dir.mkdir(parents=True)
        diag = {
            "source_run": "base",
            "recommended_action": "proceed",
            "summary": None,
            "findings": [],
        }
        opt = {
            "source_run": "sweep1",
            "method": "grid",
            "swept_params": ["fast_ma"],
            "best_params": {"fast_ma": 10.0},
            "improvement_summary": "Better",
        }
        (strat_dir / "diagnosis.json").write_text(json.dumps(diag), encoding="utf-8")
        (strat_dir / "optimization.json").write_text(json.dumps(opt), encoding="utf-8")
        entry = _make_entry(base_run=None)
        result = build_strategy_manifest("s1", "BTC", entry, tmp_path / "runs", manifests_dir)
        assert result["pipeline_stage"] == 4

    def test_schema_version_is_1(self, tmp_path):
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        entry = _make_entry(base_run=None)
        result = build_strategy_manifest("s1", "BTC", entry, tmp_path / "runs", manifests_dir)
        assert result["schema_version"] == 1

    def test_manifest_validates_against_strategy_manifest_schema(self, tmp_path):
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        entry = _make_entry(base_run=None)
        result = build_strategy_manifest("s1", "BTC", entry, tmp_path / "runs", manifests_dir)
        StrategyManifest.model_validate(result)


# ─── (g) verify_manifest ───────────────────────────────────────────────────────


class TestVerifyManifest:

    def _write_valid_manifest(self, path: Path, strategy_id: str = "s1") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        spec = {
            "strategy_id": strategy_id,
            "symbol": "BTC",
            "spec_yaml": "research/strategies/s1.yaml",
        }
        manifest = {
            "schema_version": 1,
            "strategy_id": strategy_id,
            "symbol": "BTC",
            "generated_at": "2026-01-01T00:00:00Z",
            "pipeline_stage": 2,
            "spec": spec,
        }
        path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_valid_manifest_returns_ok(self, tmp_path):
        path = tmp_path / "s1" / "manifest.json"
        self._write_valid_manifest(path)
        result = verify_manifest(path)
        assert result.ok is True
        assert result.error is None

    def test_missing_manifest_returns_fail(self, tmp_path):
        path = tmp_path / "s1" / "manifest.json"
        result = verify_manifest(path)
        assert result.ok is False
        assert result.error is not None

    def test_invalid_json_returns_fail(self, tmp_path):
        path = tmp_path / "s1" / "manifest.json"
        path.parent.mkdir(parents=True)
        path.write_text("{invalid json", encoding="utf-8")
        result = verify_manifest(path)
        assert result.ok is False

    def test_schema_violation_returns_fail(self, tmp_path):
        path = tmp_path / "s1" / "manifest.json"
        path.parent.mkdir(parents=True)
        # pipeline_stage outside [1,5]
        bad = {
            "schema_version": 1,
            "strategy_id": "s1",
            "symbol": "BTC",
            "generated_at": "2026-01-01T00:00:00Z",
            "pipeline_stage": 99,
            "spec": {
                "strategy_id": "s1",
                "symbol": "BTC",
                "spec_yaml": "research/strategies/s1.yaml",
            },
        }
        path.write_text(json.dumps(bad), encoding="utf-8")
        result = verify_manifest(path)
        assert result.ok is False

    def test_strategy_id_taken_from_parent_dir(self, tmp_path):
        path = tmp_path / "my_strategy" / "manifest.json"
        self._write_valid_manifest(path, strategy_id="my_strategy")
        result = verify_manifest(path)
        assert result.strategy_id == "my_strategy"


# ─── (h) compute_exit_code ─────────────────────────────────────────────────────


class TestComputeExitCode:

    def test_empty_results_returns_1(self):
        assert compute_exit_code([]) == 1

    def test_all_ok_returns_0(self):
        results = [
            ManifestCheckResult(strategy_id="s1", ok=True),
            ManifestCheckResult(strategy_id="s2", ok=True),
        ]
        assert compute_exit_code(results) == 0

    def test_any_fail_returns_1(self):
        results = [
            ManifestCheckResult(strategy_id="s1", ok=True),
            ManifestCheckResult(strategy_id="s2", ok=False, error="oops"),
        ]
        assert compute_exit_code(results) == 1

    def test_all_fail_returns_1(self):
        results = [
            ManifestCheckResult(strategy_id="s1", ok=False, error="e1"),
            ManifestCheckResult(strategy_id="s2", ok=False, error="e2"),
        ]
        assert compute_exit_code(results) == 1

    def test_single_ok_returns_0(self):
        assert compute_exit_code([ManifestCheckResult(strategy_id="s1", ok=True)]) == 0

    def test_single_fail_returns_1(self):
        assert compute_exit_code([ManifestCheckResult(strategy_id="s1", ok=False, error="e")]) == 1


# ─── (i) print_summary ─────────────────────────────────────────────────────────


class TestPrintSummary:

    def test_smoke_no_crash_empty(self, capsys):
        print_summary([])
        out = capsys.readouterr().out
        assert "no strategies" in out

    def test_smoke_no_crash_mixed(self, capsys):
        results = [
            ManifestCheckResult(strategy_id="s1", ok=True),
            ManifestCheckResult(strategy_id="s2", ok=False, error="bad file"),
        ]
        print_summary(results)
        out = capsys.readouterr().out
        assert "s1" in out
        assert "s2" in out

    def test_all_pass_message(self, capsys):
        results = [ManifestCheckResult(strategy_id="s1", ok=True)]
        print_summary(results)
        out = capsys.readouterr().out
        assert "PASSED" in out

    def test_fail_message(self, capsys):
        results = [ManifestCheckResult(strategy_id="s1", ok=False, error="err")]
        print_summary(results)
        out = capsys.readouterr().out
        assert "FAILED" in out


# ─── (j) _determine_pipeline_stage ────────────────────────────────────────────


class TestDeterminePipelineStage:

    def test_default_stage_2(self, tmp_path):
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        stage = _determine_pipeline_stage("s1", manifests_dir)
        assert stage == 2

    def test_stage_3_with_diagnosis(self, tmp_path):
        manifests_dir = tmp_path / "manifests"
        strat_dir = manifests_dir / "s1"
        strat_dir.mkdir(parents=True)
        diag = {
            "source_run": None,
            "recommended_action": "proceed",
            "summary": None,
            "findings": [],
        }
        (strat_dir / "diagnosis.json").write_text(json.dumps(diag), encoding="utf-8")
        stage = _determine_pipeline_stage("s1", manifests_dir)
        assert stage == 3

    def test_stage_4_with_optimization(self, tmp_path):
        manifests_dir = tmp_path / "manifests"
        strat_dir = manifests_dir / "s1"
        strat_dir.mkdir(parents=True)
        diag = {
            "source_run": None,
            "recommended_action": "proceed",
            "summary": None,
            "findings": [],
        }
        opt = {
            "source_run": None,
            "method": "grid",
            "swept_params": [],
            "best_params": {},
            "improvement_summary": None,
        }
        (strat_dir / "diagnosis.json").write_text(json.dumps(diag), encoding="utf-8")
        (strat_dir / "optimization.json").write_text(json.dumps(opt), encoding="utf-8")
        stage = _determine_pipeline_stage("s1", manifests_dir)
        assert stage == 4

    def test_stage_5_with_selection_selected_true(self, tmp_path):
        from datetime import datetime, timezone

        manifests_dir = tmp_path / "manifests"
        strat_dir = manifests_dir / "s1"
        strat_dir.mkdir(parents=True)
        diag = {
            "source_run": None,
            "recommended_action": "proceed",
            "summary": None,
            "findings": [],
        }
        opt = {
            "source_run": None,
            "method": "grid",
            "swept_params": [],
            "best_params": {},
            "improvement_summary": None,
        }
        (strat_dir / "diagnosis.json").write_text(json.dumps(diag), encoding="utf-8")
        (strat_dir / "optimization.json").write_text(json.dumps(opt), encoding="utf-8")
        selection = {
            "schema_version": 1,
            "generated_at": "2026-01-01T00:00:00Z",
            "method": "sharpe_rank",
            "ranking": [
                {
                    "strategy_id": "s1",
                    "symbol": "BTC",
                    "rank": 1,
                    "score": 2.5,
                    "selected": True,
                }
            ],
        }
        (manifests_dir / "selection.json").write_text(json.dumps(selection), encoding="utf-8")
        stage = _determine_pipeline_stage("s1", manifests_dir)
        assert stage == 5

    def test_stage_not_5_when_selected_false(self, tmp_path):
        manifests_dir = tmp_path / "manifests"
        strat_dir = manifests_dir / "s1"
        strat_dir.mkdir(parents=True)
        opt = {
            "source_run": None,
            "method": "grid",
            "swept_params": [],
            "best_params": {},
            "improvement_summary": None,
        }
        (strat_dir / "optimization.json").write_text(json.dumps(opt), encoding="utf-8")
        selection = {
            "schema_version": 1,
            "generated_at": "2026-01-01T00:00:00Z",
            "method": "sharpe_rank",
            "ranking": [
                {
                    "strategy_id": "s1",
                    "symbol": "BTC",
                    "rank": 1,
                    "score": 2.5,
                    "selected": False,
                }
            ],
        }
        (manifests_dir / "selection.json").write_text(json.dumps(selection), encoding="utf-8")
        stage = _determine_pipeline_stage("s1", manifests_dir)
        assert stage == 4


# ─── (k) emit_manifest_for_strategy ───────────────────────────────────────────


class TestEmitManifestForStrategy:

    def test_returns_path_file_exists_schema_valid(self, tmp_path):
        """valid inputs → returned path is correct, file exists, content validates."""
        runs_root = tmp_path / "runs"
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()

        # Create a minimal metrics.csv so BacktestBlock is populated.
        base_csv = runs_root / "base_run" / "artifacts" / "metrics.csv"
        _write_metrics_csv(base_csv, _good_metrics_row())

        entry = _make_entry(base_run="base_run", oos_runs=())
        strategy_id = "test_strat"

        returned_path = emit_manifest_for_strategy(
            strategy_id=strategy_id,
            entry=entry,
            runs_root=runs_root,
            manifests_dir=manifests_dir,
        )

        # Returned path must point to manifests_dir / strategy_id / manifest.json
        assert returned_path == manifests_dir / strategy_id / "manifest.json"

        # File must exist on disk
        assert returned_path.exists()

        # Content must validate against StrategyManifest schema
        StrategyManifest.model_validate_json(returned_path.read_text(encoding="utf-8"))

    def test_output_dir_created_automatically(self, tmp_path):
        """strategy sub-directory must be created automatically if it did not exist."""
        runs_root = tmp_path / "runs"
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()

        strategy_id = "new_strat"
        strat_dir = manifests_dir / strategy_id

        # Confirm the sub-directory does NOT exist before the call.
        assert not strat_dir.exists()

        entry = _make_entry(base_run=None)

        emit_manifest_for_strategy(
            strategy_id=strategy_id,
            entry=entry,
            runs_root=runs_root,
            manifests_dir=manifests_dir,
        )

        # Sub-directory and manifest.json must now exist.
        assert strat_dir.exists()
        assert (strat_dir / "manifest.json").exists()
