"""
Tests for research/pipeline/stage4_optimize.py pure-logic helpers.

All tests are self-contained — no real filesystem I/O (beyond tmp_path),
no real subprocess calls. Subprocess calls are mocked.

Covers:
  (a) swarm_target_from_ticker        — strip -SWAP, no suffix unchanged, lowercase preserved
  (b) build_swarm_vars                — keys present, goal contains YAML/diagnosis/metrics
  (c) parse_swarm_run_id              — valid run id found, no match → None
  (d) extract_swarm_report            — Final Report marker present/absent
  (e) parse_optimization_from_report  — known params found, float extraction, empty/garbage
  (f) build_optimization_block        — structure matches schema, validates
  (g) verify_optimization             — valid file ok, missing ok=False, bad JSON, schema fail
  (h) compute_exit_code               — empty → 1, all ok → 0, any fail → 1
  (i) print_summary                   — smoke test (no crash)
  (j) integration (_optimize_strategy) — valid swarm output, missing diagnosis.json,
                                         missing YAML, swarm timeout → fallback

Pytest is run from research/ as:
    cd research && python -m pytest tests/test_stage4_optimize.py -v
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Bootstrap: research/ and repo root must be on sys.path.
_THIS_FILE = Path(__file__).resolve()
_RESEARCH_DIR = _THIS_FILE.parents[1]   # research/
_REPO_ROOT = _RESEARCH_DIR.parent       # repo root

for _p in (_RESEARCH_DIR, _REPO_ROOT):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

# Also add dashboard/server/ for schemas.
_DASHBOARD_SCHEMAS = _REPO_ROOT / "dashboard" / "server"
if str(_DASHBOARD_SCHEMAS) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_SCHEMAS))

from schemas import OptimizationBlock  # noqa: E402

from pipeline.stage4_optimize import (  # noqa: E402
    OptimizationCheckResult,
    _optimize_strategy,
    build_optimization_block,
    build_swarm_vars,
    compute_exit_code,
    extract_swarm_report,
    parse_optimization_from_report,
    parse_swarm_run_id,
    print_summary,
    swarm_target_from_ticker,
    verify_optimization,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_SAMPLE_YAML = """\
name: btc_s1_multi_factor_consensus
archetype: multi_factor_consensus
hypothesis: Test hypothesis.
symbol: BTC-USDT-SWAP
timeframe_signal: 8h
hold_period:
  min_hours: 24
  max_hours: 120
indicators:
  funding_rate:
    source: okx:funding-rate-history
    smoothing: sma_3
parameter_search_ranges:
  lookback_days:
    - 60
    - 120
    - 30
  entry_high_pct:
    - 75
    - 90
    - 5
  entry_low_pct:
    - 10
    - 25
    - 5
  persistence_last_n:
    - 3
    - 5
    - 1
expected_behavior:
  trades_per_year_estimate: 80
"""

_SAMPLE_DIAGNOSIS = {
    "source_run": "btc_s1_base_run",
    "recommended_action": "back_to_stage_4",
    "summary": "Sharpe is below target; parameter sweep needed.",
    "findings": ["Sharpe=0.8 below target 1.5", "drawdown acceptable"],
}

_SAMPLE_METRICS = {
    "btc_s1_base": {
        "sharpe": 0.8,
        "max_drawdown": -0.12,
        "trade_count": 80,
        "profit_factor": 1.2,
    }
}


def _make_research_config():
    """Return a minimal ResearchConfig for tests."""
    from pipeline.config import FeesConfig, ResearchConfig, SymbolConfig
    return ResearchConfig(
        symbols=(
            SymbolConfig(name="btc", okx_swap="BTC-USDT-SWAP", ccxt_bybit="BTC/USDT:USDT"),
        ),
        period=730,
        interval="1H",
        data_source="okx",
        engine="daily",
        fees=FeesConfig(maker_rate=0.0002, taker_rate=0.00055, slippage=0.0005),
        horizons_h=(8, 24, 72, 168),
    )


def _make_strategy_entry(
    strategy_id: str = "btc_s1_multi_factor_consensus",
    symbol: str = "BTC-USDT-SWAP",
    base_run: str | None = "btc_s1_base",
):
    """Return a minimal StrategyRunsEntry for tests."""
    from pipeline.strategy_runs import StrategyRunsEntry
    return StrategyRunsEntry(
        symbol=symbol,
        spec_yaml=f"research/strategies/strategy_{strategy_id}.yaml",
        base_run=base_run,
        regime_runs=types.MappingProxyType({}),
        stress_runs=types.MappingProxyType({}),
        oos_runs=(),
        sweep_run=None,
    )


def _make_valid_optimization_json() -> dict:
    """Return a minimal valid OptimizationBlock dict."""
    return {
        "source_run": "swarm-20240101-120000-abcd1234",
        "method": "quant_strategy_desk swarm (stage 4 optimization)",
        "swept_params": ["lookback_days", "entry_high_pct"],
        "best_params": {"lookback_days": 90.0, "entry_high_pct": 80.0},
        "improvement_summary": "Improved Sharpe by adjusting lookback.",
    }


# ---------------------------------------------------------------------------
# (a) swarm_target_from_ticker
# ---------------------------------------------------------------------------


class TestSwarmTargetFromTicker:
    def test_strips_swap_suffix(self):
        assert swarm_target_from_ticker("BTC-USDT-SWAP") == "BTC-USDT"

    def test_strips_swap_suffix_eth(self):
        assert swarm_target_from_ticker("ETH-USDT-SWAP") == "ETH-USDT"

    def test_no_swap_suffix_unchanged(self):
        assert swarm_target_from_ticker("BTC-USDT") == "BTC-USDT"

    def test_lowercase_preserved(self):
        # Input without -SWAP: case is preserved
        result = swarm_target_from_ticker("btc-usdt")
        assert result == "btc-usdt"

    def test_mixed_case_swap_stripped(self):
        # -SWAP detection is case-insensitive for the suffix check
        result = swarm_target_from_ticker("BTC-USDT-SWAP")
        assert "SWAP" not in result

    def test_strips_whitespace(self):
        assert swarm_target_from_ticker("  BTC-USDT-SWAP  ") == "BTC-USDT"

    def test_other_symbol(self):
        assert swarm_target_from_ticker("SOL-USDT-SWAP") == "SOL-USDT"


# ---------------------------------------------------------------------------
# (b) build_swarm_vars
# ---------------------------------------------------------------------------


class TestBuildSwarmVars:
    def test_returns_dict_with_market_and_goal(self):
        result = build_swarm_vars(
            strategy_id="btc_s1",
            spec_yaml_text=_SAMPLE_YAML,
            diagnosis=_SAMPLE_DIAGNOSIS,
            metrics_by_run=_SAMPLE_METRICS,
            market="BTC-USDT",
        )
        assert "market" in result
        assert "goal" in result

    def test_market_value_is_correct(self):
        result = build_swarm_vars(
            strategy_id="btc_s1",
            spec_yaml_text=_SAMPLE_YAML,
            diagnosis=_SAMPLE_DIAGNOSIS,
            metrics_by_run=_SAMPLE_METRICS,
            market="BTC-USDT",
        )
        assert result["market"] == "BTC-USDT"

    def test_goal_contains_strategy_id(self):
        result = build_swarm_vars(
            strategy_id="btc_s1_special",
            spec_yaml_text=_SAMPLE_YAML,
            diagnosis=_SAMPLE_DIAGNOSIS,
            metrics_by_run=_SAMPLE_METRICS,
            market="BTC-USDT",
        )
        assert "btc_s1_special" in result["goal"]

    def test_goal_contains_yaml_text(self):
        result = build_swarm_vars(
            strategy_id="btc_s1",
            spec_yaml_text=_SAMPLE_YAML,
            diagnosis=_SAMPLE_DIAGNOSIS,
            metrics_by_run=_SAMPLE_METRICS,
            market="BTC-USDT",
        )
        # YAML snippet must appear in goal
        assert "multi_factor_consensus" in result["goal"]

    def test_goal_contains_diagnosis_action(self):
        result = build_swarm_vars(
            strategy_id="btc_s1",
            spec_yaml_text=_SAMPLE_YAML,
            diagnosis=_SAMPLE_DIAGNOSIS,
            metrics_by_run=_SAMPLE_METRICS,
            market="BTC-USDT",
        )
        assert "back_to_stage_4" in result["goal"]

    def test_goal_contains_optimization_instructions(self):
        result = build_swarm_vars(
            strategy_id="btc_s1",
            spec_yaml_text=_SAMPLE_YAML,
            diagnosis=_SAMPLE_DIAGNOSIS,
            metrics_by_run=_SAMPLE_METRICS,
            market="BTC-USDT",
        )
        goal = result["goal"].lower()
        assert "optim" in goal or "parameter" in goal or "sweep" in goal

    def test_goal_yaml_truncated_at_2000(self):
        # Use only "y"s so the truncation boundary is predictable
        long_yaml = "y" * 5000
        result = build_swarm_vars(
            strategy_id="btc_s1",
            spec_yaml_text=long_yaml,
            diagnosis=_SAMPLE_DIAGNOSIS,
            metrics_by_run=_SAMPLE_METRICS,
            market="BTC-USDT",
        )
        # The first 2000 chars of the YAML must appear in the goal
        assert "y" * 2000 in result["goal"]
        # More than 2000 consecutive "y"s should NOT appear (truncated)
        assert "y" * 2001 not in result["goal"]

    def test_empty_metrics_does_not_crash(self):
        result = build_swarm_vars(
            strategy_id="btc_s1",
            spec_yaml_text=_SAMPLE_YAML,
            diagnosis=_SAMPLE_DIAGNOSIS,
            metrics_by_run={},
            market="BTC-USDT",
        )
        assert "market" in result
        assert "goal" in result

    def test_all_values_are_strings(self):
        result = build_swarm_vars(
            strategy_id="btc_s1",
            spec_yaml_text=_SAMPLE_YAML,
            diagnosis=_SAMPLE_DIAGNOSIS,
            metrics_by_run=_SAMPLE_METRICS,
            market="BTC-USDT",
        )
        for v in result.values():
            assert isinstance(v, str)


# ---------------------------------------------------------------------------
# (c) parse_swarm_run_id
# ---------------------------------------------------------------------------


class TestParseSwarmRunId:
    def test_extracts_valid_run_id(self):
        stdout = "Starting run swarm-20240115-143022-ab12cd34 in progress..."
        result = parse_swarm_run_id(stdout)
        assert result == "swarm-20240115-143022-ab12cd34"

    def test_no_run_id_returns_none(self):
        result = parse_swarm_run_id("No run id here.")
        assert result is None

    def test_empty_string_returns_none(self):
        result = parse_swarm_run_id("")
        assert result is None

    def test_none_input_returns_none(self):
        result = parse_swarm_run_id(None)  # type: ignore[arg-type]
        assert result is None

    def test_run_id_in_multiline_stdout(self):
        stdout = "Line 1\nLine 2\nswarm-20260101-120000-deadbeef\nLine 4"
        result = parse_swarm_run_id(stdout)
        assert result == "swarm-20260101-120000-deadbeef"

    def test_returns_first_match(self):
        stdout = "swarm-20240101-000000-aaaaaaaa and swarm-20240102-000000-bbbbbbbb"
        result = parse_swarm_run_id(stdout)
        assert result == "swarm-20240101-000000-aaaaaaaa"


# ---------------------------------------------------------------------------
# (d) extract_swarm_report
# ---------------------------------------------------------------------------


class TestExtractSwarmReport:
    def test_extracts_after_final_report_marker(self):
        stdout = "Preamble...\nFinal Report\nThis is the optimization report."
        report = extract_swarm_report(stdout)
        assert "optimization report" in report
        assert "Preamble" not in report

    def test_strips_box_drawing_after_marker(self):
        stdout = "Some text\nFinal Report\n──────────\nReport body here."
        report = extract_swarm_report(stdout)
        assert "Report body here" in report

    def test_no_marker_returns_tail(self):
        stdout = "A" * 100 + "B" * 4000 + "C" * 100
        report = extract_swarm_report(stdout)
        # Should return the last ~4000 chars (the Bs + Cs)
        assert "C" * 100 in report

    def test_empty_stdout_returns_empty(self):
        assert extract_swarm_report("") == ""

    def test_none_stdout_returns_empty(self):
        assert extract_swarm_report(None) == ""  # type: ignore[arg-type]

    def test_report_bounded_to_4000(self):
        long_text = "X" * 6000
        stdout = f"Final Report\n{long_text}"
        report = extract_swarm_report(stdout)
        assert len(report) <= 4000


# ---------------------------------------------------------------------------
# (e) parse_optimization_from_report
# ---------------------------------------------------------------------------


class TestParseOptimizationFromReport:
    def test_finds_known_param_names(self):
        report = "The optimal lookback_days is 90. entry_high_pct should be 80."
        swept, best = parse_optimization_from_report(report, _SAMPLE_YAML)
        assert "lookback_days" in swept
        assert "entry_high_pct" in swept

    def test_extracts_float_values(self):
        report = "lookback_days: 90\nentry_high_pct: 82.5"
        swept, best = parse_optimization_from_report(report, _SAMPLE_YAML)
        assert best.get("lookback_days") == pytest.approx(90.0)
        assert best.get("entry_high_pct") == pytest.approx(82.5)

    def test_param_equals_syntax(self):
        report = "Set lookback_days = 100 for best results."
        swept, best = parse_optimization_from_report(report, _SAMPLE_YAML)
        assert "lookback_days" in swept
        assert best.get("lookback_days") == pytest.approx(100.0)

    def test_empty_report_returns_empty(self):
        swept, best = parse_optimization_from_report("", _SAMPLE_YAML)
        assert swept == []
        assert best == {}

    def test_no_crash_on_garbage_input(self):
        swept, best = parse_optimization_from_report("!@#$%^&*()", "!!!not yaml!!!")
        assert isinstance(swept, list)
        assert isinstance(best, dict)

    def test_unknown_params_not_included(self):
        report = "completely_unknown_param: 42"
        swept, best = parse_optimization_from_report(report, _SAMPLE_YAML)
        assert "completely_unknown_param" not in swept
        assert "completely_unknown_param" not in best

    def test_empty_yaml_returns_empty(self):
        report = "lookback_days: 90"
        swept, best = parse_optimization_from_report(report, "")
        # No known params from empty YAML, so nothing extracted
        assert swept == []
        assert best == {}

    def test_persistence_last_n_extracted(self):
        report = "persistence_last_n: 4 looks good."
        swept, best = parse_optimization_from_report(report, _SAMPLE_YAML)
        assert "persistence_last_n" in swept
        assert best.get("persistence_last_n") == pytest.approx(4.0)

    def test_multiple_params_in_one_report(self):
        report = (
            "lookback_days: 90\n"
            "entry_high_pct: 80\n"
            "entry_low_pct: 15\n"
        )
        swept, best = parse_optimization_from_report(report, _SAMPLE_YAML)
        assert "lookback_days" in swept
        assert "entry_high_pct" in swept
        assert "entry_low_pct" in swept
        assert len(best) >= 3


# ---------------------------------------------------------------------------
# (f) build_optimization_block
# ---------------------------------------------------------------------------


class TestBuildOptimizationBlock:
    def test_structure_has_all_fields(self):
        block = build_optimization_block(
            run_id="swarm-20240101-120000-abcd1234",
            swept_params=["lookback_days"],
            best_params={"lookback_days": 90.0},
            improvement_summary="Better Sharpe.",
        )
        assert "source_run" in block
        assert "method" in block
        assert "swept_params" in block
        assert "best_params" in block
        assert "improvement_summary" in block

    def test_source_run_value(self):
        block = build_optimization_block(
            run_id="swarm-20240101-120000-abcd1234",
            swept_params=[],
            best_params={},
            improvement_summary=None,
        )
        assert block["source_run"] == "swarm-20240101-120000-abcd1234"

    def test_method_string(self):
        block = build_optimization_block(
            run_id=None,
            swept_params=[],
            best_params={},
            improvement_summary=None,
        )
        assert "quant_strategy_desk" in block["method"]
        assert "stage 4" in block["method"]

    def test_none_run_id(self):
        block = build_optimization_block(
            run_id=None,
            swept_params=[],
            best_params={},
            improvement_summary=None,
        )
        assert block["source_run"] is None

    def test_validates_against_optimization_block_schema(self):
        block = build_optimization_block(
            run_id="swarm-20240101-120000-abcd1234",
            swept_params=["lookback_days", "entry_high_pct"],
            best_params={"lookback_days": 90.0, "entry_high_pct": 80.0},
            improvement_summary="Improved.",
        )
        validated = OptimizationBlock.model_validate(block)
        assert validated.source_run == "swarm-20240101-120000-abcd1234"
        assert "lookback_days" in validated.swept_params

    def test_empty_block_validates_against_schema(self):
        block = build_optimization_block(
            run_id=None,
            swept_params=[],
            best_params={},
            improvement_summary=None,
        )
        validated = OptimizationBlock.model_validate(block)
        assert validated.swept_params == []
        assert validated.best_params == {}

    def test_swept_params_is_list(self):
        block = build_optimization_block(
            run_id=None,
            swept_params=["a", "b"],
            best_params={},
            improvement_summary=None,
        )
        assert isinstance(block["swept_params"], list)

    def test_best_params_is_dict(self):
        block = build_optimization_block(
            run_id=None,
            swept_params=[],
            best_params={"x": 1.0},
            improvement_summary=None,
        )
        assert isinstance(block["best_params"], dict)


# ---------------------------------------------------------------------------
# (g) verify_optimization
# ---------------------------------------------------------------------------


class TestVerifyOptimization:
    def test_valid_file_returns_ok(self, tmp_path):
        sid = "btc_s1_test"
        out_dir = tmp_path / sid
        out_dir.mkdir()
        opt_path = out_dir / "optimization.json"
        opt_path.write_text(
            json.dumps(_make_valid_optimization_json()), encoding="utf-8"
        )
        result = verify_optimization(opt_path)
        assert result.ok is True
        assert result.strategy_id == sid

    def test_missing_file_returns_failure(self, tmp_path):
        sid = "btc_s1_missing"
        out_dir = tmp_path / sid
        out_dir.mkdir()
        opt_path = out_dir / "optimization.json"
        result = verify_optimization(opt_path)
        assert result.ok is False
        assert result.error is not None

    def test_invalid_json_returns_failure(self, tmp_path):
        sid = "btc_s1_badjson"
        out_dir = tmp_path / sid
        out_dir.mkdir()
        opt_path = out_dir / "optimization.json"
        opt_path.write_text("not valid json {{{", encoding="utf-8")
        result = verify_optimization(opt_path)
        assert result.ok is False
        assert "JSON" in (result.error or "")

    def test_schema_failure_returns_failure(self, tmp_path):
        sid = "btc_s1_schema_fail"
        out_dir = tmp_path / sid
        out_dir.mkdir()
        opt_path = out_dir / "optimization.json"
        # extra field forbidden by _Manifest (extra="forbid")
        bad = {**_make_valid_optimization_json(), "unknown_extra_field": "oops"}
        opt_path.write_text(json.dumps(bad), encoding="utf-8")
        result = verify_optimization(opt_path)
        assert result.ok is False

    def test_strategy_id_derived_from_parent_dir(self, tmp_path):
        sid = "eth_s1_some_strategy"
        out_dir = tmp_path / sid
        out_dir.mkdir()
        opt_path = out_dir / "optimization.json"
        opt_path.write_text(
            json.dumps(_make_valid_optimization_json()), encoding="utf-8"
        )
        result = verify_optimization(opt_path)
        assert result.strategy_id == sid


# ---------------------------------------------------------------------------
# (h) compute_exit_code
# ---------------------------------------------------------------------------


class TestComputeExitCode:
    def test_empty_list_returns_1(self):
        assert compute_exit_code([]) == 1

    def test_all_ok_returns_0(self):
        results = [
            OptimizationCheckResult(strategy_id="s1", ok=True),
            OptimizationCheckResult(strategy_id="s2", ok=True),
        ]
        assert compute_exit_code(results) == 0

    def test_any_failure_returns_1(self):
        results = [
            OptimizationCheckResult(strategy_id="s1", ok=True),
            OptimizationCheckResult(strategy_id="s2", ok=False, error="oops"),
        ]
        assert compute_exit_code(results) == 1

    def test_all_failures_returns_1(self):
        results = [
            OptimizationCheckResult(strategy_id="s1", ok=False, error="e1"),
            OptimizationCheckResult(strategy_id="s2", ok=False, error="e2"),
        ]
        assert compute_exit_code(results) == 1

    def test_single_ok_returns_0(self):
        results = [OptimizationCheckResult(strategy_id="s1", ok=True)]
        assert compute_exit_code(results) == 0

    def test_single_failure_returns_1(self):
        results = [OptimizationCheckResult(strategy_id="s1", ok=False, error="e")]
        assert compute_exit_code(results) == 1


# ---------------------------------------------------------------------------
# (i) print_summary
# ---------------------------------------------------------------------------


class TestPrintSummary:
    def test_empty_results_no_crash(self, capsys):
        print_summary([])
        out = capsys.readouterr().out
        assert "Stage-4" in out

    def test_all_ok_summary(self, capsys):
        results = [
            OptimizationCheckResult(strategy_id="s1", ok=True),
            OptimizationCheckResult(strategy_id="s2", ok=True),
        ]
        print_summary(results)
        out = capsys.readouterr().out
        assert "PASSED" in out
        assert "2/2" in out

    def test_failed_summary(self, capsys):
        results = [
            OptimizationCheckResult(strategy_id="s1", ok=False, error="some error"),
        ]
        print_summary(results)
        out = capsys.readouterr().out
        assert "FAILED" in out
        assert "0/1" in out

    def test_mixed_summary(self, capsys):
        results = [
            OptimizationCheckResult(strategy_id="s1", ok=True),
            OptimizationCheckResult(strategy_id="s2", ok=False, error="bad"),
        ]
        print_summary(results)
        out = capsys.readouterr().out
        assert "1/2" in out


# ---------------------------------------------------------------------------
# (j) Integration — _optimize_strategy with mocked run_swarm
# ---------------------------------------------------------------------------

_SWARM_STDOUT_WITH_REPORT = (
    "Starting swarm run swarm-20260522-120000-cafebabe\n"
    "── Final Report ──\n"
    "Optimization findings:\n"
    "lookback_days: 90\n"
    "entry_high_pct: 82\n"
    "Sweeping lookback_days and entry_high_pct will improve Sharpe from 0.8 to 1.4.\n"
)


class TestOptimizeStrategyIntegration:
    def _setup_dirs(self, tmp_path, strategy_id: str):
        """Create strategies_dir and manifests_dir with required files."""
        strategies_dir = tmp_path / "strategies"
        manifests_dir = tmp_path / "manifests"
        strategies_dir.mkdir()
        manifests_dir.mkdir()

        # Write strategy YAML
        yaml_path = strategies_dir / f"strategy_{strategy_id}.yaml"
        yaml_path.write_text(_SAMPLE_YAML, encoding="utf-8")

        # Write diagnosis.json
        diag_dir = manifests_dir / strategy_id
        diag_dir.mkdir(parents=True)
        diag_path = diag_dir / "diagnosis.json"
        diag_path.write_text(
            json.dumps(_SAMPLE_DIAGNOSIS), encoding="utf-8"
        )

        return strategies_dir, manifests_dir

    def test_valid_swarm_output_writes_optimization_json(self, tmp_path):
        strategy_id = "btc_s1_multi_factor_consensus"
        strategies_dir, manifests_dir = self._setup_dirs(tmp_path, strategy_id)
        runs_root = tmp_path / "runs"
        runs_root.mkdir()

        cfg = _make_research_config()
        entry = _make_strategy_entry(strategy_id=strategy_id, base_run=None)

        with patch(
            "pipeline.stage4_optimize.run_swarm",
            return_value=_SWARM_STDOUT_WITH_REPORT,
        ):
            result = _optimize_strategy(
                strategy_id=strategy_id,
                entry=entry,
                cfg=cfg,
                runs_root=runs_root,
                strategies_dir=strategies_dir,
                manifests_dir=manifests_dir,
            )

        assert result.ok is True
        opt_path = manifests_dir / strategy_id / "optimization.json"
        assert opt_path.exists()

    def test_valid_swarm_output_optimization_validates_schema(self, tmp_path):
        strategy_id = "btc_s1_multi_factor_consensus"
        strategies_dir, manifests_dir = self._setup_dirs(tmp_path, strategy_id)
        runs_root = tmp_path / "runs"
        runs_root.mkdir()

        cfg = _make_research_config()
        entry = _make_strategy_entry(strategy_id=strategy_id, base_run=None)

        with patch(
            "pipeline.stage4_optimize.run_swarm",
            return_value=_SWARM_STDOUT_WITH_REPORT,
        ):
            _optimize_strategy(
                strategy_id=strategy_id,
                entry=entry,
                cfg=cfg,
                runs_root=runs_root,
                strategies_dir=strategies_dir,
                manifests_dir=manifests_dir,
            )

        opt_path = manifests_dir / strategy_id / "optimization.json"
        data = json.loads(opt_path.read_text(encoding="utf-8"))
        validated = OptimizationBlock.model_validate(data)
        assert isinstance(validated, OptimizationBlock)

    def test_valid_swarm_output_extracts_run_id(self, tmp_path):
        strategy_id = "btc_s1_multi_factor_consensus"
        strategies_dir, manifests_dir = self._setup_dirs(tmp_path, strategy_id)
        runs_root = tmp_path / "runs"
        runs_root.mkdir()

        cfg = _make_research_config()
        entry = _make_strategy_entry(strategy_id=strategy_id, base_run=None)

        with patch(
            "pipeline.stage4_optimize.run_swarm",
            return_value=_SWARM_STDOUT_WITH_REPORT,
        ):
            _optimize_strategy(
                strategy_id=strategy_id,
                entry=entry,
                cfg=cfg,
                runs_root=runs_root,
                strategies_dir=strategies_dir,
                manifests_dir=manifests_dir,
            )

        opt_path = manifests_dir / strategy_id / "optimization.json"
        data = json.loads(opt_path.read_text(encoding="utf-8"))
        assert data["source_run"] == "swarm-20260522-120000-cafebabe"

    def test_missing_diagnosis_returns_failure(self, tmp_path):
        strategy_id = "btc_s1_no_diagnosis"
        strategies_dir = tmp_path / "strategies"
        manifests_dir = tmp_path / "manifests"
        strategies_dir.mkdir()
        manifests_dir.mkdir()

        # Write strategy YAML but NO diagnosis.json
        yaml_path = strategies_dir / f"strategy_{strategy_id}.yaml"
        yaml_path.write_text(_SAMPLE_YAML, encoding="utf-8")

        cfg = _make_research_config()
        entry = _make_strategy_entry(strategy_id=strategy_id, base_run=None)
        runs_root = tmp_path / "runs"
        runs_root.mkdir()

        with patch("pipeline.stage4_optimize.run_swarm") as mock_swarm:
            result = _optimize_strategy(
                strategy_id=strategy_id,
                entry=entry,
                cfg=cfg,
                runs_root=runs_root,
                strategies_dir=strategies_dir,
                manifests_dir=manifests_dir,
            )
            mock_swarm.assert_not_called()

        assert result.ok is False
        assert "diagnosis" in (result.error or "").lower() or "stage 3" in (result.error or "").lower()

    def test_missing_strategy_yaml_returns_failure(self, tmp_path):
        strategy_id = "btc_s1_no_yaml"
        strategies_dir = tmp_path / "strategies"
        manifests_dir = tmp_path / "manifests"
        strategies_dir.mkdir()
        manifests_dir.mkdir()

        # Write diagnosis.json but NO strategy YAML
        diag_dir = manifests_dir / strategy_id
        diag_dir.mkdir(parents=True)
        diag_path = diag_dir / "diagnosis.json"
        diag_path.write_text(json.dumps(_SAMPLE_DIAGNOSIS), encoding="utf-8")

        cfg = _make_research_config()
        entry = _make_strategy_entry(strategy_id=strategy_id, base_run=None)
        runs_root = tmp_path / "runs"
        runs_root.mkdir()

        with patch("pipeline.stage4_optimize.run_swarm") as mock_swarm:
            result = _optimize_strategy(
                strategy_id=strategy_id,
                entry=entry,
                cfg=cfg,
                runs_root=runs_root,
                strategies_dir=strategies_dir,
                manifests_dir=manifests_dir,
            )
            mock_swarm.assert_not_called()

        assert result.ok is False
        assert "yaml" in (result.error or "").lower() or "YAML" in (result.error or "")

    def test_swarm_timeout_writes_empty_block_ok(self, tmp_path):
        strategy_id = "btc_s1_multi_factor_consensus"
        strategies_dir, manifests_dir = self._setup_dirs(tmp_path, strategy_id)
        runs_root = tmp_path / "runs"
        runs_root.mkdir()

        cfg = _make_research_config()
        entry = _make_strategy_entry(strategy_id=strategy_id, base_run=None)

        with patch(
            "pipeline.stage4_optimize.run_swarm",
            side_effect=subprocess.TimeoutExpired(cmd=["cli.py"], timeout=600),
        ):
            result = _optimize_strategy(
                strategy_id=strategy_id,
                entry=entry,
                cfg=cfg,
                runs_root=runs_root,
                strategies_dir=strategies_dir,
                manifests_dir=manifests_dir,
            )

        # Pipeline should continue (ok=True) with empty block
        assert result.ok is True
        opt_path = manifests_dir / strategy_id / "optimization.json"
        assert opt_path.exists()
        data = json.loads(opt_path.read_text(encoding="utf-8"))
        assert data["swept_params"] == []
        assert data["best_params"] == {}
        assert data["source_run"] is None

    def test_swarm_timeout_block_validates_schema(self, tmp_path):
        strategy_id = "btc_s1_multi_factor_consensus"
        strategies_dir, manifests_dir = self._setup_dirs(tmp_path, strategy_id)
        runs_root = tmp_path / "runs"
        runs_root.mkdir()

        cfg = _make_research_config()
        entry = _make_strategy_entry(strategy_id=strategy_id, base_run=None)

        with patch(
            "pipeline.stage4_optimize.run_swarm",
            side_effect=subprocess.TimeoutExpired(cmd=["cli.py"], timeout=600),
        ):
            _optimize_strategy(
                strategy_id=strategy_id,
                entry=entry,
                cfg=cfg,
                runs_root=runs_root,
                strategies_dir=strategies_dir,
                manifests_dir=manifests_dir,
            )

        opt_path = manifests_dir / strategy_id / "optimization.json"
        data = json.loads(opt_path.read_text(encoding="utf-8"))
        validated = OptimizationBlock.model_validate(data)
        assert isinstance(validated, OptimizationBlock)

    def test_swarm_called_process_error_fallback_ok(self, tmp_path):
        strategy_id = "btc_s1_multi_factor_consensus"
        strategies_dir, manifests_dir = self._setup_dirs(tmp_path, strategy_id)
        runs_root = tmp_path / "runs"
        runs_root.mkdir()

        cfg = _make_research_config()
        entry = _make_strategy_entry(strategy_id=strategy_id, base_run=None)

        with patch(
            "pipeline.stage4_optimize.run_swarm",
            side_effect=subprocess.CalledProcessError(returncode=1, cmd=["cli.py"]),
        ):
            result = _optimize_strategy(
                strategy_id=strategy_id,
                entry=entry,
                cfg=cfg,
                runs_root=runs_root,
                strategies_dir=strategies_dir,
                manifests_dir=manifests_dir,
            )

        assert result.ok is True
        opt_path = manifests_dir / strategy_id / "optimization.json"
        data = json.loads(opt_path.read_text(encoding="utf-8"))
        OptimizationBlock.model_validate(data)  # must not raise
