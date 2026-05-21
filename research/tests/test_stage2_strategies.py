"""
Tests for research/pipeline/stage2_strategies.py pure-logic helpers.

Stage 2 calls a Vibe-Trading LLM swarm — that call costs money, is
non-deterministic, and needs API keys, so it is NEVER exercised here. The
swarm subprocess is always stubbed/mocked. Only the pure, deterministic
logic is tested:

  (a) select_usable_factors()   — drop factors whose verdict == reject
  (b) swarm_target_from_ticker()/build_swarm_vars()
                                — correct target + JSON-context injection
  (c) parse_swarm_result()      — swarm run-id retrieval from CLI output
  (d) build_strategy_spec()     — prose-aware deterministic YAML scaffold
  (e) build_generation_block()  — GenerationBlock-aligned handoff dict
  (f) verify_outputs()/compute_exit_code()/print_summary()
                                — output verification + exit-code logic

Pytest is run from research/ as:
    cd research && python -m pytest tests/
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

# Bootstrap: research/ and dashboard/server/ must be on sys.path.
_RESEARCH_DIR = Path(__file__).resolve().parents[1]  # research/
_REPO_ROOT = _RESEARCH_DIR.parent
_DASHBOARD_SCHEMAS = _REPO_ROOT / "dashboard" / "server"

for _p in (_RESEARCH_DIR, _DASHBOARD_SCHEMAS):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

from pipeline.stage2_strategies import (  # noqa: E402
    DEFAULT_TIMEFRAME,
    GeneratedStrategy,
    StrategyCheckResult,
    build_generation_block,
    build_strategy_spec,
    build_swarm_vars,
    check_strategy,
    compute_exit_code,
    extract_swarm_report,
    parse_swarm_result,
    print_summary,
    select_usable_factors,
    swarm_target_from_ticker,
    verify_outputs,
)
from schemas import FactorManifest, GenerationBlock  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _factor(name: str, verdict: str, ic8: float = 0.07) -> dict:
    """Return one FactorEntry dict with the given name and verdict."""
    return {
        "name": name,
        "ic_by_horizon": {"8": ic8, "24": ic8 * 0.8, "72": ic8 * 1.1, "168": ic8},
        "ir": 0.5,
        "sample_size": 5000,
        "cross_regime_ic": None,
        "stability": None,
        "verdict": verdict,
    }


def _manifest_dict(symbol: str = "BTC", factors: list[dict] | None = None) -> dict:
    """Return a FactorManifest dict; default has one single_use + one reject."""
    if factors is None:
        factors = [
            _factor("funding_rate", "single_use", 0.12),
            _factor("fng", "ensemble_only", 0.07),
            _factor("oi_change", "reject", 0.02),
        ]
    return {
        "schema_version": 1,
        "symbol": symbol.upper(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period_days": 730,
        "horizons_h": [8, 24, 72, 168],
        "factors": factors,
    }


def _manifest(symbol: str = "BTC", factors: list[dict] | None = None) -> FactorManifest:
    return FactorManifest.model_validate(_manifest_dict(symbol, factors))


# ---------------------------------------------------------------------------
# (a) select_usable_factors
# ---------------------------------------------------------------------------


class TestSelectUsableFactors:
    """select_usable_factors(manifest) -> list[FactorEntry] without verdict=reject."""

    def test_drops_reject_verdict(self):
        manifest = _manifest()
        usable = select_usable_factors(manifest)
        names = {f.name for f in usable}
        assert "oi_change" not in names  # reject dropped
        assert names == {"funding_rate", "fng"}

    def test_keeps_single_use_and_ensemble_only(self):
        manifest = _manifest(
            factors=[
                _factor("a", "single_use"),
                _factor("b", "ensemble_only"),
            ]
        )
        usable = select_usable_factors(manifest)
        assert len(usable) == 2

    def test_all_rejected_returns_empty(self):
        manifest = _manifest(
            factors=[_factor("a", "reject"), _factor("b", "reject")]
        )
        assert select_usable_factors(manifest) == []

    def test_preserves_input_order(self):
        manifest = _manifest(
            factors=[
                _factor("z", "single_use"),
                _factor("m", "reject"),
                _factor("a", "ensemble_only"),
            ]
        )
        usable = select_usable_factors(manifest)
        assert [f.name for f in usable] == ["z", "a"]


# ---------------------------------------------------------------------------
# (b) swarm_target_from_ticker / build_swarm_vars
# ---------------------------------------------------------------------------


class TestSwarmTargetFromTicker:
    """swarm_target_from_ticker(okx_swap) -> grounding-friendly target token."""

    def test_strips_swap_suffix(self):
        # grounding.py regex matches BASE-USDT, not BASE-USDT-SWAP.
        assert swarm_target_from_ticker("BTC-USDT-SWAP") == "BTC-USDT"

    def test_passthrough_without_swap_suffix(self):
        assert swarm_target_from_ticker("ETH-USDT") == "ETH-USDT"

    def test_uppercased(self):
        assert swarm_target_from_ticker("sol-usdt-swap") == "SOL-USDT"


class TestBuildSwarmVars:
    """build_swarm_vars(target, factors, ...) -> dict for --swarm-run VARS_JSON."""

    def test_target_is_clean_token(self):
        manifest = _manifest()
        usable = select_usable_factors(manifest)
        vars_ = build_swarm_vars("BTC-USDT", usable)
        # target MUST stay a clean symbol token so swarm grounding can
        # regex-detect it (grounding.py _SYMBOL_PATTERNS). The factor
        # context must NOT pollute it.
        assert vars_["target"] == "BTC-USDT"

    def test_factor_context_injected_into_timeframe(self):
        manifest = _manifest()
        usable = select_usable_factors(manifest)
        vars_ = build_swarm_vars("BTC-USDT", usable)
        # The selected-factor JSON is injected as decision context via the
        # timeframe variable (the only free-form var that reaches a
        # prompt_template without breaking grounding).
        assert DEFAULT_TIMEFRAME in vars_["timeframe"]
        assert "funding_rate" in vars_["timeframe"]
        assert "fng" in vars_["timeframe"]
        # rejected factor must not leak into the context
        assert "oi_change" not in vars_["timeframe"]

    def test_injected_context_contains_valid_json(self):
        manifest = _manifest()
        usable = select_usable_factors(manifest)
        vars_ = build_swarm_vars("BTC-USDT", usable)
        # The context block must embed a machine-parseable JSON array so a
        # reader (human or LLM) sees structured data, not just prose.
        text = vars_["timeframe"]
        start = text.index("[")
        end = text.rindex("]") + 1
        parsed = json.loads(text[start:end])
        assert isinstance(parsed, list)
        assert {f["name"] for f in parsed} == {"funding_rate", "fng"}
        assert all("verdict" in f and "ic_by_horizon" in f for f in parsed)

    def test_vars_are_all_strings(self):
        # CLI VARS_JSON is json.loads()'d into a dict[str, str]; non-string
        # values would break prompt_template.format_map.
        manifest = _manifest()
        usable = select_usable_factors(manifest)
        vars_ = build_swarm_vars("BTC-USDT", usable)
        assert all(isinstance(v, str) for v in vars_.values())

    def test_empty_factors_still_builds_vars(self):
        vars_ = build_swarm_vars("BTC-USDT", [])
        assert vars_["target"] == "BTC-USDT"
        assert DEFAULT_TIMEFRAME in vars_["timeframe"]

    def test_custom_timeframe_respected(self):
        vars_ = build_swarm_vars("BTC-USDT", [], timeframe="intraday")
        assert vars_["timeframe"].startswith("intraday")


# ---------------------------------------------------------------------------
# (c) parse_swarm_result
# ---------------------------------------------------------------------------


class TestParseSwarmResult:
    """parse_swarm_result(stdout) -> run id string or None."""

    def test_extracts_run_id_from_starting_line(self):
        stdout = (
            "Starting swarm: crypto_trading_desk\n"
            "Variables: {\"target\": \"BTC-USDT\"}\n"
        )
        # cmd_swarm_run_live prints the preset name then assigns run.id;
        # the run id format is swarm-YYYYMMDD-HHMMSS-<hex8>.
        stdout += "swarm-20260522-101530-ab12cd34\n"
        assert parse_swarm_result(stdout) == "swarm-20260522-101530-ab12cd34"

    def test_returns_none_when_no_run_id(self):
        assert parse_swarm_result("nothing useful here\n") is None

    def test_returns_first_run_id_when_multiple(self):
        stdout = (
            "swarm-20260522-101530-aaaaaaaa\n"
            "swarm-20260522-101533-bbbbbbbb\n"
        )
        assert parse_swarm_result(stdout) == "swarm-20260522-101530-aaaaaaaa"

    def test_handles_empty_output(self):
        assert parse_swarm_result("") is None


class TestExtractSwarmReport:
    """extract_swarm_report(stdout) -> prose desk analysis."""

    def test_extracts_after_final_report_marker(self):
        stdout = (
            "Starting swarm: crypto_trading_desk\n"
            "swarm-20260522-101530-ab12cd34\n"
            "── Final Report ──\n"
            "Desk recommends fading funding extremes.\n"
            "COMPLETED\n"
        )
        report = extract_swarm_report(stdout)
        # The box-drawing decoration around the header must be stripped.
        assert not report.startswith("─")
        assert not report.startswith("-")
        assert "Desk recommends fading funding extremes." in report

    def test_falls_back_to_full_text_without_marker(self):
        stdout = "no marker here, just analysis prose\n"
        report = extract_swarm_report(stdout)
        assert "analysis prose" in report

    def test_handles_empty(self):
        assert extract_swarm_report("") == ""

    def test_output_is_bounded(self):
        stdout = "Final Report\n" + ("x" * 10000)
        report = extract_swarm_report(stdout)
        assert len(report) <= 4000


# ---------------------------------------------------------------------------
# (d) build_strategy_spec
# ---------------------------------------------------------------------------


class TestBuildStrategySpec:
    """build_strategy_spec(...) -> (strategy_id, yaml_text) deterministic scaffold."""

    def test_returns_id_and_yaml(self):
        manifest = _manifest()
        usable = select_usable_factors(manifest)
        sid, yaml_text = build_strategy_spec(
            symbol="btc",
            ticker="BTC-USDT-SWAP",
            usable_factors=usable,
            swarm_rationale="Desk recommends contrarian funding fade.",
            seq=1,
        )
        assert isinstance(sid, str) and sid
        assert isinstance(yaml_text, str) and yaml_text

    def test_strategy_id_follows_convention(self):
        # strategy_runs.py documents <coin>_s<N>_<archetype>.
        manifest = _manifest()
        usable = select_usable_factors(manifest)
        sid, _ = build_strategy_spec(
            symbol="btc", ticker="BTC-USDT-SWAP",
            usable_factors=usable, swarm_rationale="x", seq=2,
        )
        assert sid.startswith("btc_s2_")

    def test_yaml_parses_and_has_required_keys(self):
        # The generated YAML must match the schema of the existing
        # research/strategies/strategy_S*.yaml files.
        manifest = _manifest()
        usable = select_usable_factors(manifest)
        _, yaml_text = build_strategy_spec(
            symbol="btc", ticker="BTC-USDT-SWAP",
            usable_factors=usable, swarm_rationale="x", seq=1,
        )
        doc = yaml.safe_load(yaml_text)
        for key in (
            "name", "archetype", "hypothesis", "symbol", "timeframe_signal",
            "hold_period", "indicators", "entry_long", "entry_short",
            "exit_rules", "position_sizing", "parameter_search_ranges",
            "expected_behavior", "caveats",
        ):
            assert key in doc, f"generated strategy YAML missing key: {key}"

    def test_yaml_symbol_matches_ticker(self):
        manifest = _manifest()
        usable = select_usable_factors(manifest)
        _, yaml_text = build_strategy_spec(
            symbol="btc", ticker="BTC-USDT-SWAP",
            usable_factors=usable, swarm_rationale="x", seq=1,
        )
        doc = yaml.safe_load(yaml_text)
        assert doc["symbol"] == "BTC-USDT-SWAP"

    def test_yaml_indicators_cover_usable_factors_only(self):
        # Indicators block is derived from the usable factors; the rejected
        # factor must not appear.
        manifest = _manifest()
        usable = select_usable_factors(manifest)
        _, yaml_text = build_strategy_spec(
            symbol="btc", ticker="BTC-USDT-SWAP",
            usable_factors=usable, swarm_rationale="x", seq=1,
        )
        doc = yaml.safe_load(yaml_text)
        assert set(doc["indicators"].keys()) == {"funding_rate", "fng"}

    def test_swarm_rationale_recorded_in_caveats_or_hypothesis(self):
        manifest = _manifest()
        usable = select_usable_factors(manifest)
        _, yaml_text = build_strategy_spec(
            symbol="btc", ticker="BTC-USDT-SWAP",
            usable_factors=usable,
            swarm_rationale="DESK_MARKER_TEXT",
            seq=1,
        )
        assert "DESK_MARKER_TEXT" in yaml_text

    def test_seq_changes_strategy_id(self):
        manifest = _manifest()
        usable = select_usable_factors(manifest)
        sid1, _ = build_strategy_spec(
            symbol="btc", ticker="BTC-USDT-SWAP",
            usable_factors=usable, swarm_rationale="x", seq=1,
        )
        sid3, _ = build_strategy_spec(
            symbol="btc", ticker="BTC-USDT-SWAP",
            usable_factors=usable, swarm_rationale="x", seq=3,
        )
        assert sid1 != sid3

    def test_raises_on_no_usable_factors(self):
        # A strategy with zero usable factors is meaningless; the builder
        # must refuse rather than emit a degenerate spec.
        with pytest.raises(ValueError):
            build_strategy_spec(
                symbol="btc", ticker="BTC-USDT-SWAP",
                usable_factors=[], swarm_rationale="x", seq=1,
            )


# ---------------------------------------------------------------------------
# (e) build_generation_block
# ---------------------------------------------------------------------------


class TestBuildGenerationBlock:
    """build_generation_block(...) -> dict aligned with GenerationBlock schema."""

    def test_validates_against_generation_block_schema(self):
        manifest = _manifest()
        usable = select_usable_factors(manifest)
        block = build_generation_block(
            run_id="swarm-20260522-101530-ab12cd34",
            usable_factors=usable,
            rationale="desk prose",
        )
        # Must validate cleanly against the dashboard schema so task 2.12
        # (emit_manifest.py) can drop it into StrategyManifest.generation.
        GenerationBlock.model_validate(block)

    def test_method_names_the_swarm(self):
        block = build_generation_block(
            run_id="swarm-x", usable_factors=[], rationale="r",
        )
        assert "crypto_trading_desk" in block["method"]

    def test_factors_used_lists_usable_factor_names(self):
        manifest = _manifest()
        usable = select_usable_factors(manifest)
        block = build_generation_block(
            run_id="swarm-x", usable_factors=usable, rationale="r",
        )
        assert set(block["factors_used"]) == {"funding_rate", "fng"}

    def test_source_run_carries_swarm_run_id(self):
        block = build_generation_block(
            run_id="swarm-20260522-101530-ab12cd34",
            usable_factors=[], rationale="r",
        )
        assert block["source_run"] == "swarm-20260522-101530-ab12cd34"

    def test_rationale_recorded(self):
        block = build_generation_block(
            run_id="swarm-x", usable_factors=[], rationale="DESK_PROSE_MARKER",
        )
        assert block["rationale"] == "DESK_PROSE_MARKER"

    def test_none_run_id_allowed(self):
        # When the swarm run id could not be parsed, source_run is null but
        # the block must still validate (audit data is best-effort).
        block = build_generation_block(
            run_id=None, usable_factors=[], rationale="r",
        )
        GenerationBlock.model_validate(block)
        assert block["source_run"] is None


# ---------------------------------------------------------------------------
# (f) verify_outputs / check_strategy / compute_exit_code / print_summary
# ---------------------------------------------------------------------------


def _write_generated(tmp_path: Path, sid: str = "btc_s2_funding") -> GeneratedStrategy:
    """Write a valid strategy YAML + generation.json under tmp_path, return handle."""
    strategies_dir = tmp_path / "strategies"
    manifests_dir = tmp_path / "manifests"
    strategies_dir.mkdir(exist_ok=True)
    (manifests_dir / sid).mkdir(parents=True, exist_ok=True)

    manifest = _manifest()
    usable = select_usable_factors(manifest)
    _, yaml_text = build_strategy_spec(
        symbol="btc", ticker="BTC-USDT-SWAP",
        usable_factors=usable, swarm_rationale="x", seq=2,
    )
    yaml_path = strategies_dir / f"strategy_{sid}.yaml"
    yaml_path.write_text(yaml_text, encoding="utf-8")

    gen = build_generation_block(run_id="swarm-x", usable_factors=usable, rationale="r")
    gen_path = manifests_dir / sid / "generation.json"
    gen_path.write_text(json.dumps(gen), encoding="utf-8")

    return GeneratedStrategy(
        strategy_id=sid,
        symbol="btc",
        yaml_path=yaml_path,
        generation_path=gen_path,
    )


class TestCheckStrategy:
    """check_strategy(generated) -> StrategyCheckResult"""

    def test_valid_strategy_passes(self, tmp_path: Path):
        gen = _write_generated(tmp_path)
        result = check_strategy(gen)
        assert result.ok

    def test_missing_yaml_detected(self, tmp_path: Path):
        gen = _write_generated(tmp_path)
        gen.yaml_path.unlink()
        result = check_strategy(gen)
        assert not result.ok
        assert result.error is not None

    def test_missing_generation_json_detected(self, tmp_path: Path):
        gen = _write_generated(tmp_path)
        gen.generation_path.unlink()
        result = check_strategy(gen)
        assert not result.ok

    def test_invalid_generation_json_detected(self, tmp_path: Path):
        gen = _write_generated(tmp_path)
        # break the GenerationBlock contract (missing required 'method')
        gen.generation_path.write_text(json.dumps({"factors_used": []}), encoding="utf-8")
        result = check_strategy(gen)
        assert not result.ok

    def test_corrupt_yaml_detected(self, tmp_path: Path):
        gen = _write_generated(tmp_path)
        gen.yaml_path.write_text("{ not: valid: yaml: ::", encoding="utf-8")
        result = check_strategy(gen)
        assert not result.ok


class TestVerifyOutputs:
    """verify_outputs(generated_list) -> list[StrategyCheckResult]"""

    def test_all_present(self, tmp_path: Path):
        g1 = _write_generated(tmp_path, "btc_s2_a")
        g2 = _write_generated(tmp_path, "btc_s2_b")
        results = verify_outputs([g1, g2])
        assert len(results) == 2
        assert all(r.ok for r in results)

    def test_partial_failure(self, tmp_path: Path):
        g1 = _write_generated(tmp_path, "btc_s2_a")
        g2 = _write_generated(tmp_path, "btc_s2_b")
        g2.yaml_path.unlink()
        results = verify_outputs([g1, g2])
        assert sum(1 for r in results if r.ok) == 1

    def test_empty_list(self):
        assert verify_outputs([]) == []


class TestComputeExitCode:
    """compute_exit_code(results) -> int"""

    def test_zero_on_success(self):
        results = [StrategyCheckResult(strategy_id="a", ok=True)]
        assert compute_exit_code(results) == 0

    def test_nonzero_on_failure(self):
        results = [
            StrategyCheckResult(strategy_id="a", ok=True),
            StrategyCheckResult(strategy_id="b", ok=False, error="missing"),
        ]
        assert compute_exit_code(results) != 0

    def test_nonzero_on_empty(self):
        # Stage 2 producing zero strategies is a failure: there is nothing
        # for downstream stages to backtest.
        assert compute_exit_code([]) != 0

    def test_returns_int(self):
        assert isinstance(compute_exit_code([StrategyCheckResult("a", True)]), int)


class TestPrintSummary:
    """print_summary(results) — smoke test, must not raise."""

    def test_all_pass(self, capsys: pytest.CaptureFixture):
        results = [StrategyCheckResult(strategy_id="btc_s2_a", ok=True)]
        print_summary(results)
        out = capsys.readouterr().out
        assert "OK" in out
        assert "btc_s2_a" in out

    def test_failure_shown(self, capsys: pytest.CaptureFixture):
        results = [StrategyCheckResult(strategy_id="btc_s2_a", ok=False, error="boom")]
        print_summary(results)
        out = capsys.readouterr().out
        assert "FAIL" in out

    def test_empty(self, capsys: pytest.CaptureFixture):
        print_summary([])
        out = capsys.readouterr().out
        assert "0" in out
