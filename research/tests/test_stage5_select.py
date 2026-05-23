"""Tests for research/pipeline/stage5_select.py.

Covers:
- clamp: in range, at boundaries, below lo, above hi
- score_strategy: all present → correct value, None inputs, edge cases
- is_eligible: various file/action combinations
- build_selection_entry: structure, rank ge=1, schema validation
- build_selection_manifest: schema_version, generated_at, ranking
- verify_selection: valid / missing / invalid schema
- compute_exit_code: True → 0, False → 1
- print_summary: no crash
- Integration: 2 strategies (proceed + back_to_stage_4) → correct ranking
              all back_to_stage_2 → empty selection
              empty strategy_runs → empty selection
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

# ── Path bootstrap (mirrors the pattern used in stage runners) ─────────────────
_THIS = Path(__file__).resolve()
_TESTS_DIR = _THIS.parent        # research/tests/
_RESEARCH_DIR = _TESTS_DIR.parent  # research/
_REPO_ROOT = _RESEARCH_DIR.parent  # repo root

for _p in [str(_RESEARCH_DIR), str(_REPO_ROOT / "dashboard" / "server")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from pipeline.stage5_select import (  # noqa: E402
    SelectionCheckResult,
    build_selection_entry,
    build_selection_manifest,
    clamp,
    compute_exit_code,
    is_eligible,
    print_summary,
    score_strategy,
    verify_selection,
)
from schemas import SelectionEntry, SelectionManifest  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════════
# clamp
# ═══════════════════════════════════════════════════════════════════════════════


class TestClamp:
    def test_in_range_returns_value(self):
        assert clamp(1.0, 0.0, 2.0) == 1.0

    def test_at_lower_boundary(self):
        assert clamp(0.0, 0.0, 2.0) == 0.0

    def test_at_upper_boundary(self):
        assert clamp(2.0, 0.0, 2.0) == 2.0

    def test_below_lo_returns_lo(self):
        assert clamp(-5.0, 0.0, 2.0) == 0.0

    def test_above_hi_returns_hi(self):
        assert clamp(99.0, 0.0, 2.0) == 2.0

    def test_fractional_values(self):
        result = clamp(0.75, 0.5, 1.0)
        assert result == pytest.approx(0.75)

    def test_lo_equals_hi(self):
        assert clamp(5.0, 3.0, 3.0) == 3.0


# ═══════════════════════════════════════════════════════════════════════════════
# score_strategy
# ═══════════════════════════════════════════════════════════════════════════════


class TestScoreStrategy:
    def test_all_none_returns_zero(self):
        assert score_strategy(None, None, None, None) == pytest.approx(0.0)

    def test_none_sharpe_zero_contribution(self):
        # Only profit_factor = 1.5 contributes (component = 0.2 * 1.0 = 0.2)
        result = score_strategy(None, None, 1.5, None)
        assert result == pytest.approx(0.2)

    def test_none_drawdown_zero_contribution(self):
        # Only sharpe = 1.5 contributes: 0.4 * clamp(1.0, 0, 2) = 0.4
        result = score_strategy(1.5, None, None, None)
        assert result == pytest.approx(0.4)

    def test_none_profit_factor_zero_contribution(self):
        # trade_count = 100 → 0.1 * 1.0 = 0.1
        result = score_strategy(None, None, None, 100.0)
        assert result == pytest.approx(0.1)

    def test_all_at_threshold_values(self):
        # sharpe=1.5 → 0.4*1.0=0.4
        # drawdown=0.0 → 0.3*clamp(1.0,0,2)=0.3
        # profit_factor=1.5 → 0.2*1.0=0.2
        # trade_count=100 → 0.1*1.0=0.1
        result = score_strategy(1.5, 0.0, 1.5, 100.0)
        assert result == pytest.approx(1.0)

    def test_negative_sharpe_clamped_to_zero(self):
        # sharpe = -5.0 → clamp(-3.33, 0, 2) = 0 → contribution = 0
        result = score_strategy(-5.0, None, None, None)
        assert result == pytest.approx(0.0)

    def test_negative_drawdown_uses_abs(self):
        # drawdown = -0.10 → abs = 0.10 → 1 - 0.10/0.10 = 0 → 0.3*0 = 0
        result = score_strategy(None, -0.10, None, None)
        assert result == pytest.approx(0.0)

    def test_positive_drawdown_uses_abs(self):
        # drawdown = 0.10 → abs = 0.10 → same as -0.10
        result_pos = score_strategy(None, 0.10, None, None)
        result_neg = score_strategy(None, -0.10, None, None)
        assert result_pos == pytest.approx(result_neg)

    def test_zero_drawdown_max_contribution(self):
        # drawdown=0 → 1.0 - 0/0.10 = 1.0 → 0.3*1.0 = 0.3
        result = score_strategy(None, 0.0, None, None)
        assert result == pytest.approx(0.3)

    def test_high_sharpe_clamped_at_two(self):
        # sharpe = 100 → clamp(66.67, 0, 2) = 2 → 0.4*2=0.8
        result = score_strategy(100.0, None, None, None)
        assert result == pytest.approx(0.8)

    def test_high_trade_count_clamped_at_two(self):
        # trade_count=1000 → clamp(10.0, 0, 2)=2 → 0.1*2=0.2
        result = score_strategy(None, None, None, 1000.0)
        assert result == pytest.approx(0.2)

    def test_all_at_max_gives_two(self):
        # sharpe=3.0 → 0.4*2=0.8; drawdown=0 → 0.3*1=0.3 (wait, 1-0/0.10=1.0); pf=3.0 → 0.2*2=0.4; tc=200 → 0.1*2=0.2
        # total = 0.8 + 0.3*clamp(1.0, 0, 2) + 0.4 + 0.2
        # = 0.8 + 0.3 + 0.4 + 0.2 = 1.7... not 2.0
        # Actually max score: sharpe=inf → 0.8, drawdown=large_neg → 0.0 ... or drawdown=0 → 0.3
        # max = 0.8 + 0.6 + 0.4 + 0.2 = 2.0 (when drawdown component clamps to 2)
        # drawdown that gives clamp result 2: 1 - |d|/0.10 = 2 → |d|=-0.10 (impossible)
        # clamp(1 - |d|/0.10, 0, 2) with |d|=0 → 1.0, never reaches 2.0
        # So max = 0.8 + 0.3 + 0.4 + 0.2 = 1.7 for drawdown=0, high everything else
        result = score_strategy(3.0, 0.0, 3.0, 200.0)
        assert result == pytest.approx(0.8 + 0.3 + 0.4 + 0.2)

    def test_exact_formula_values(self):
        # sharpe=2.25 → 2.25/1.5=1.5 → 0.4*1.5=0.6
        # drawdown=0.05 → 1-0.05/0.10=0.5 → 0.3*0.5=0.15
        # pf=3.0 → clamp(2.0, 0, 2)=2 → 0.2*2=0.4
        # tc=50 → 50/100=0.5 → 0.1*0.5=0.05
        # total = 0.6 + 0.15 + 0.4 + 0.05 = 1.2
        result = score_strategy(2.25, 0.05, 3.0, 50.0)
        assert result == pytest.approx(1.2)


# ═══════════════════════════════════════════════════════════════════════════════
# is_eligible
# ═══════════════════════════════════════════════════════════════════════════════


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class TestIsEligible:
    def test_all_files_proceed_is_eligible(self, tmp_path: Path):
        diag = tmp_path / "s1" / "diagnosis.json"
        opt = tmp_path / "s1" / "optimization.json"
        met = tmp_path / "runs" / "base" / "artifacts" / "metrics.csv"

        _write_json(diag, {"recommended_action": "proceed"})
        _write_json(opt, {"method": "sweep"})
        met.parent.mkdir(parents=True, exist_ok=True)
        met.write_text("sharpe,max_drawdown\n2.0,0.05\n", encoding="utf-8")

        eligible, reason = is_eligible(diag, opt, met)
        assert eligible is True
        assert reason == "eligible"

    def test_back_to_stage_4_is_eligible(self, tmp_path: Path):
        diag = tmp_path / "s1" / "diagnosis.json"
        opt = tmp_path / "s1" / "optimization.json"
        met = tmp_path / "runs" / "base" / "artifacts" / "metrics.csv"

        _write_json(diag, {"recommended_action": "back_to_stage_4"})
        _write_json(opt, {})
        met.parent.mkdir(parents=True, exist_ok=True)
        met.write_text("sharpe\n1.0\n", encoding="utf-8")

        eligible, reason = is_eligible(diag, opt, met)
        assert eligible is True

    def test_back_to_stage_2_not_eligible(self, tmp_path: Path):
        diag = tmp_path / "s1" / "diagnosis.json"
        opt = tmp_path / "s1" / "optimization.json"
        met = tmp_path / "runs" / "base" / "artifacts" / "metrics.csv"

        _write_json(diag, {"recommended_action": "back_to_stage_2"})
        _write_json(opt, {})
        met.parent.mkdir(parents=True, exist_ok=True)
        met.write_text("sharpe\n-1.0\n", encoding="utf-8")

        eligible, reason = is_eligible(diag, opt, met)
        assert eligible is False
        assert "back_to_stage_2" in reason

    def test_missing_diagnosis_not_eligible(self, tmp_path: Path):
        diag = tmp_path / "s1" / "diagnosis.json"  # does not exist
        opt = tmp_path / "s1" / "optimization.json"
        met = tmp_path / "runs" / "base" / "artifacts" / "metrics.csv"

        _write_json(opt, {})
        met.parent.mkdir(parents=True, exist_ok=True)
        met.write_text("sharpe\n2.0\n", encoding="utf-8")

        eligible, reason = is_eligible(diag, opt, met)
        assert eligible is False
        assert "diagnosis.json missing" in reason

    def test_missing_optimization_not_eligible(self, tmp_path: Path):
        diag = tmp_path / "s1" / "diagnosis.json"
        opt = tmp_path / "s1" / "optimization.json"  # does not exist
        met = tmp_path / "runs" / "base" / "artifacts" / "metrics.csv"

        _write_json(diag, {"recommended_action": "proceed"})
        met.parent.mkdir(parents=True, exist_ok=True)
        met.write_text("sharpe\n2.0\n", encoding="utf-8")

        eligible, reason = is_eligible(diag, opt, met)
        assert eligible is False
        assert "optimization.json missing" in reason

    def test_missing_metrics_not_eligible(self, tmp_path: Path):
        diag = tmp_path / "s1" / "diagnosis.json"
        opt = tmp_path / "s1" / "optimization.json"
        met = tmp_path / "runs" / "base" / "artifacts" / "metrics.csv"  # does not exist

        _write_json(diag, {"recommended_action": "proceed"})
        _write_json(opt, {})

        eligible, reason = is_eligible(diag, opt, met)
        assert eligible is False
        assert "metrics.csv missing" in reason


# ═══════════════════════════════════════════════════════════════════════════════
# build_selection_entry
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildSelectionEntry:
    def test_correct_structure(self):
        entry = build_selection_entry("btc_s1", "BTC", 1, 0.871, True)
        assert entry["strategy_id"] == "btc_s1"
        assert entry["symbol"] == "BTC"
        assert entry["rank"] == 1
        assert entry["score"] == pytest.approx(0.871)
        assert entry["selected"] is True

    def test_rank_one_valid(self):
        entry = build_selection_entry("s1", "ETH", 1, 0.5, False)
        # Must validate against SelectionEntry (rank >= 1)
        validated = SelectionEntry.model_validate(entry)
        assert validated.rank == 1

    def test_selected_false(self):
        entry = build_selection_entry("s2", "BTC", 2, 0.3, False)
        assert entry["selected"] is False
        validated = SelectionEntry.model_validate(entry)
        assert validated.selected is False

    def test_validates_against_schema(self):
        entry = build_selection_entry("btc_s1_funding_carry", "BTC", 3, 0.118, False)
        validated = SelectionEntry.model_validate(entry)
        assert validated.strategy_id == "btc_s1_funding_carry"


# ═══════════════════════════════════════════════════════════════════════════════
# build_selection_manifest
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildSelectionManifest:
    def test_schema_version_is_one(self):
        manifest = build_selection_manifest([], "test_method")
        assert manifest["schema_version"] == 1

    def test_generated_at_is_string(self):
        manifest = build_selection_manifest([], "test_method")
        assert isinstance(manifest["generated_at"], str)

    def test_generated_at_contains_timezone(self):
        manifest = build_selection_manifest([], "test_method")
        # ISO-8601 with timezone info (UTC offset or 'Z' or '+00:00')
        ts = manifest["generated_at"]
        assert "+" in ts or "Z" in ts or ts.endswith("+00:00")

    def test_ranking_is_list(self):
        manifest = build_selection_manifest([], "m")
        assert isinstance(manifest["ranking"], list)

    def test_method_stored(self):
        manifest = build_selection_manifest([], "weighted_composite_score_v1")
        assert manifest["method"] == "weighted_composite_score_v1"

    def test_entries_stored(self):
        e1 = build_selection_entry("s1", "BTC", 1, 0.9, True)
        manifest = build_selection_manifest([e1], "m")
        assert len(manifest["ranking"]) == 1
        assert manifest["ranking"][0]["strategy_id"] == "s1"

    def test_validates_against_schema(self):
        e1 = build_selection_entry("btc_s1", "BTC", 1, 0.8, True)
        e2 = build_selection_entry("btc_s2", "BTC", 2, 0.4, False)
        manifest = build_selection_manifest([e1, e2], "weighted_composite_score_v1")
        validated = SelectionManifest.model_validate(manifest)
        assert len(validated.ranking) == 2

    def test_empty_ranking_validates(self):
        manifest = build_selection_manifest([], "weighted_composite_score_v1")
        validated = SelectionManifest.model_validate(manifest)
        assert validated.ranking == []


# ═══════════════════════════════════════════════════════════════════════════════
# verify_selection
# ═══════════════════════════════════════════════════════════════════════════════


class TestVerifySelection:
    def test_valid_file_returns_ok(self, tmp_path: Path):
        sel_path = tmp_path / "selection.json"
        manifest = build_selection_manifest([], "weighted_composite_score_v1")
        sel_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = verify_selection(sel_path)
        assert result.ok is True
        assert result.error is None

    def test_missing_file_returns_not_ok(self, tmp_path: Path):
        sel_path = tmp_path / "selection.json"
        result = verify_selection(sel_path)
        assert result.ok is False
        assert result.error is not None
        assert "missing" in result.error

    def test_invalid_json_returns_not_ok(self, tmp_path: Path):
        sel_path = tmp_path / "selection.json"
        sel_path.write_text("not valid json!!!", encoding="utf-8")
        result = verify_selection(sel_path)
        assert result.ok is False
        assert result.error is not None

    def test_schema_violation_returns_not_ok(self, tmp_path: Path):
        sel_path = tmp_path / "selection.json"
        # schema_version=99 violates le=1
        invalid = {"schema_version": 99, "generated_at": "2026-01-01T00:00:00Z", "ranking": []}
        sel_path.write_text(json.dumps(invalid), encoding="utf-8")
        result = verify_selection(sel_path)
        assert result.ok is False
        assert "schema validation failed" in (result.error or "")

    def test_valid_with_entries_returns_ok(self, tmp_path: Path):
        sel_path = tmp_path / "selection.json"
        e = build_selection_entry("s1", "BTC", 1, 0.9, True)
        manifest = build_selection_manifest([e], "weighted_composite_score_v1")
        sel_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = verify_selection(sel_path)
        assert result.ok is True


# ═══════════════════════════════════════════════════════════════════════════════
# compute_exit_code
# ═══════════════════════════════════════════════════════════════════════════════


class TestComputeExitCode:
    def test_true_returns_zero(self):
        assert compute_exit_code(True) == 0

    def test_false_returns_one(self):
        assert compute_exit_code(False) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# print_summary
# ═══════════════════════════════════════════════════════════════════════════════


class TestPrintSummary:
    def test_no_crash_empty(self, capsys):
        print_summary([], 0)
        captured = capsys.readouterr()
        assert "Stage 5 Selection" in captured.out

    def test_no_crash_with_entries(self, capsys):
        e1 = build_selection_entry("btc_s1", "BTC", 1, 0.9, True)
        e2 = build_selection_entry("btc_s2", "BTC", 2, 0.4, False)
        print_summary([e1, e2], 3)
        captured = capsys.readouterr()
        assert "btc_s1" in captured.out
        assert "btc_s2" in captured.out

    def test_shows_total_strategies(self, capsys):
        print_summary([], 5)
        captured = capsys.readouterr()
        assert "5" in captured.out


# ═══════════════════════════════════════════════════════════════════════════════
# Integration tests
# ═══════════════════════════════════════════════════════════════════════════════


def _make_strategy_runs_json(strategies: dict) -> dict:
    """Build a strategy_runs.json content dict."""
    result = {}
    for sid, info in strategies.items():
        result[sid] = {
            "symbol": info.get("symbol", "BTC-USDT-SWAP"),
            "spec_yaml": f"research/strategies/{sid}.yaml",
            "base_run": info.get("base_run"),
            "regime_runs": {},
            "stress_runs": {},
            "oos_runs": [],
            "sweep_run": None,
        }
    return result


def _setup_strategy(
    tmp_path: Path,
    strategy_id: str,
    action: str,
    sharpe: float = 2.0,
    drawdown: float = 0.05,
    profit_factor: float = 1.8,
    trade_count: float = 150.0,
    base_run: str = "base_run_1",
) -> None:
    """Create the necessary files for one strategy in tmp_path."""
    manifests = tmp_path / "research" / "manifests" / strategy_id
    manifests.mkdir(parents=True, exist_ok=True)

    (manifests / "diagnosis.json").write_text(
        json.dumps({"recommended_action": action, "summary": None, "findings": []}),
        encoding="utf-8",
    )
    (manifests / "optimization.json").write_text(
        json.dumps({"method": "sweep", "swept_params": [], "best_params": {}}),
        encoding="utf-8",
    )

    artifacts = tmp_path / "runs" / base_run / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "metrics.csv").write_text(
        f"sharpe,max_drawdown,profit_factor,trade_count\n"
        f"{sharpe},{drawdown},{profit_factor},{trade_count}\n",
        encoding="utf-8",
    )


class TestIntegration:
    """Integration tests exercising the core selection logic without main()."""

    def _run_selection(
        self,
        tmp_path: Path,
        strategies: dict,
    ) -> dict:
        """Run the selection logic and return the parsed selection.json."""
        from pipeline.stage5_select import (
            is_eligible,
            score_strategy,
            build_selection_entry,
            build_selection_manifest,
            SELECTION_METHOD,
        )
        from pipeline.stage3_diagnose import read_metrics_csv

        manifests_dir = tmp_path / "research" / "manifests"
        runs_root = tmp_path / "runs"
        selection_path = manifests_dir / "selection.json"

        candidates = []
        for sid, info in strategies.items():
            base_run = info.get("base_run")
            if base_run is None:
                continue

            diag = manifests_dir / sid / "diagnosis.json"
            opt = manifests_dir / sid / "optimization.json"
            met = runs_root / base_run / "artifacts" / "metrics.csv"

            eligible, _ = is_eligible(diag, opt, met)
            if not eligible:
                continue

            metrics = read_metrics_csv(met)
            if metrics is None:
                continue

            score = score_strategy(
                metrics.get("sharpe"),
                metrics.get("max_drawdown"),
                metrics.get("profit_factor"),
                metrics.get("trade_count"),
            )
            diag_data = json.loads(diag.read_text(encoding="utf-8"))
            action = diag_data.get("recommended_action", "")
            selected_flag = action == "proceed"
            symbol = info.get("symbol", "BTC").split("-")[0]
            candidates.append((sid, symbol, score, selected_flag))

        candidates.sort(key=lambda c: c[2], reverse=True)

        entries = [
            build_selection_entry(sid, sym, rank, score, sel)
            for rank, (sid, sym, score, sel) in enumerate(candidates, start=1)
        ]

        manifest = build_selection_manifest(entries, SELECTION_METHOD)
        manifests_dir.mkdir(parents=True, exist_ok=True)
        selection_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        return json.loads(selection_path.read_text(encoding="utf-8"))

    def test_proceed_and_back_to_stage4_ranking(self, tmp_path: Path):
        """One proceed + one back_to_stage_4 → selection.json with rank 1 and 2."""
        strategies = {
            "btc_s1_proceed": {"symbol": "BTC-USDT-SWAP", "base_run": "run_s1"},
            "btc_s2_back4": {"symbol": "BTC-USDT-SWAP", "base_run": "run_s2"},
        }
        _setup_strategy(tmp_path, "btc_s1_proceed", "proceed",
                        sharpe=2.5, drawdown=0.03, profit_factor=2.0, trade_count=200,
                        base_run="run_s1")
        _setup_strategy(tmp_path, "btc_s2_back4", "back_to_stage_4",
                        sharpe=1.0, drawdown=0.12, profit_factor=1.2, trade_count=80,
                        base_run="run_s2")

        result = self._run_selection(tmp_path, strategies)

        assert result["schema_version"] == 1
        ranking = result["ranking"]
        assert len(ranking) == 2

        # Rank 1 should be the proceed strategy (higher score)
        rank1 = next(e for e in ranking if e["rank"] == 1)
        rank2 = next(e for e in ranking if e["rank"] == 2)

        assert rank1["strategy_id"] == "btc_s1_proceed"
        assert rank1["selected"] is True
        assert rank2["strategy_id"] == "btc_s2_back4"
        assert rank2["selected"] is False
        assert rank1["score"] > rank2["score"]

    def test_all_back_to_stage2_gives_empty_selection(self, tmp_path: Path):
        """All back_to_stage_2 → empty selection."""
        strategies = {
            "btc_s1_bad": {"symbol": "BTC-USDT-SWAP", "base_run": "run_bad"},
        }
        _setup_strategy(tmp_path, "btc_s1_bad", "back_to_stage_2",
                        base_run="run_bad")

        result = self._run_selection(tmp_path, strategies)
        assert result["ranking"] == []

    def test_empty_strategies_gives_empty_selection(self, tmp_path: Path):
        """No strategies → empty selection.json."""
        result = self._run_selection(tmp_path, {})
        assert result["ranking"] == []
        assert result["schema_version"] == 1

    def test_selection_validates_against_schema(self, tmp_path: Path):
        """Output must always validate against SelectionManifest schema."""
        strategies = {
            "btc_s1": {"symbol": "BTC-USDT-SWAP", "base_run": "run1"},
        }
        _setup_strategy(tmp_path, "btc_s1", "proceed", base_run="run1")

        result = self._run_selection(tmp_path, strategies)
        # Should not raise
        validated = SelectionManifest.model_validate(result)
        assert len(validated.ranking) == 1

    def test_proceed_strategy_selected_true(self, tmp_path: Path):
        """Strategy with proceed action → selected=True."""
        strategies = {"btc_s1": {"symbol": "BTC", "base_run": "run1"}}
        _setup_strategy(tmp_path, "btc_s1", "proceed", base_run="run1")
        result = self._run_selection(tmp_path, strategies)
        assert result["ranking"][0]["selected"] is True

    def test_back_to_stage4_selected_false(self, tmp_path: Path):
        """Strategy with back_to_stage_4 action → selected=False."""
        strategies = {"btc_s1": {"symbol": "BTC", "base_run": "run1"}}
        _setup_strategy(tmp_path, "btc_s1", "back_to_stage_4", base_run="run1")
        result = self._run_selection(tmp_path, strategies)
        assert result["ranking"][0]["selected"] is False

    def test_higher_score_gets_lower_rank_number(self, tmp_path: Path):
        """Higher score always gets rank 1 (rank 1 = best)."""
        strategies = {
            "s_high": {"symbol": "BTC", "base_run": "run_high"},
            "s_low": {"symbol": "BTC", "base_run": "run_low"},
        }
        # s_high gets much better metrics
        _setup_strategy(tmp_path, "s_high", "proceed",
                        sharpe=3.0, drawdown=0.01, profit_factor=3.0, trade_count=500,
                        base_run="run_high")
        _setup_strategy(tmp_path, "s_low", "proceed",
                        sharpe=0.5, drawdown=0.20, profit_factor=0.8, trade_count=20,
                        base_run="run_low")

        result = self._run_selection(tmp_path, strategies)
        ranking = result["ranking"]
        assert ranking[0]["strategy_id"] == "s_high"
        assert ranking[0]["rank"] == 1
        assert ranking[1]["strategy_id"] == "s_low"
        assert ranking[1]["rank"] == 2
