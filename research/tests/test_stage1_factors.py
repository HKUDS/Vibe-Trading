"""
Tests for research/pipeline/stage1_factors.py pure-logic helpers.

Covers:
  (a) verify_outputs() / check_manifest()
      - missing manifest detected
      - invalid (schema-violating) manifest detected
      - valid manifest passes
      - multiple symbols: all pass / partial fail
  (b) compute_exit_code()
      - returns 0 on full success
      - returns non-zero on any failure
  (c) print_summary()
      - smoke test: does not raise

These tests are network-free. main() and _run_stage1_work() are NOT tested here
(they require live network APIs via factor_extended / factor_regime).

Pytest is run from research/ as:
    cd research && python -m pytest tests/
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Bootstrap: research/ and dashboard/server/ must be on sys.path.
# (stage1_factors.py does this too, but we replicate it here so the test file
# is self-contained and does not depend on a module-level side effect.)
_RESEARCH_DIR = Path(__file__).resolve().parents[1]  # research/
_REPO_ROOT = _RESEARCH_DIR.parent
_DASHBOARD_SCHEMAS = _REPO_ROOT / "dashboard" / "server"

for _p in (_RESEARCH_DIR, _DASHBOARD_SCHEMAS):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

from pipeline.stage1_factors import (
    ManifestCheckResult,
    check_manifest,
    compute_exit_code,
    print_summary,
    verify_outputs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_manifest_json(symbol: str = "BTC") -> str:
    """Return a minimal valid FactorManifest JSON string for the given symbol."""
    return json.dumps(
        {
            "schema_version": 1,
            "symbol": symbol.upper(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "period_days": 730,
            "horizons_h": [8, 24],
            "factors": [
                {
                    "name": "funding_rate",
                    "ic_by_horizon": {"8": 0.12, "24": 0.07},
                    "ir": 0.5,
                    "sample_size": 5000,
                    "cross_regime_ic": None,
                    "stability": None,
                    "verdict": "single_use",
                }
            ],
        }
    )


def _invalid_manifest_json() -> str:
    """Return JSON that is valid JSON but NOT a valid FactorManifest."""
    # Missing required 'factors' key -> Pydantic will reject it.
    return json.dumps(
        {
            "schema_version": 1,
            "symbol": "BTC",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "period_days": 730,
            "horizons_h": [8, 24],
            # 'factors' is missing on purpose
        }
    )


# ---------------------------------------------------------------------------
# (a) check_manifest / verify_outputs
# ---------------------------------------------------------------------------


class TestCheckManifest:
    """check_manifest(manifests_dir, symbol) -> ManifestCheckResult"""

    def test_missing_manifest_detected(self, tmp_path: Path):
        """When no file exists, exists=False and ok=False."""
        result = check_manifest(tmp_path, "btc")
        assert not result.exists
        assert not result.valid
        assert not result.ok
        assert result.error is not None

    def test_invalid_manifest_detected(self, tmp_path: Path):
        """When the file exists but fails FactorManifest validation, valid=False and ok=False."""
        path = tmp_path / "factor_btc.json"
        path.write_text(_invalid_manifest_json(), encoding="utf-8")
        result = check_manifest(tmp_path, "btc")
        assert result.exists
        assert not result.valid
        assert not result.ok
        assert result.error is not None

    def test_valid_manifest_passes(self, tmp_path: Path):
        """When the file exists and validates, ok=True."""
        path = tmp_path / "factor_btc.json"
        path.write_text(_valid_manifest_json("BTC"), encoding="utf-8")
        result = check_manifest(tmp_path, "btc")
        assert result.exists
        assert result.valid
        assert result.ok
        assert result.error is None

    def test_symbol_stored_on_result(self, tmp_path: Path):
        """The result carries the symbol name exactly as passed in."""
        result = check_manifest(tmp_path, "eth")
        assert result.symbol == "eth"

    def test_corrupt_json_detected(self, tmp_path: Path):
        """A file with malformed JSON is caught and reported as invalid."""
        path = tmp_path / "factor_btc.json"
        path.write_text("{ this is not json }", encoding="utf-8")
        result = check_manifest(tmp_path, "btc")
        assert result.exists
        assert not result.valid
        assert not result.ok

    def test_verdict_violation_detected(self, tmp_path: Path):
        """A manifest with an unknown verdict value fails schema validation."""
        data = json.loads(_valid_manifest_json("BTC"))
        data["factors"][0]["verdict"] = "super_good"  # not a valid FactorVerdict
        path = tmp_path / "factor_btc.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        result = check_manifest(tmp_path, "btc")
        assert result.exists
        assert not result.valid

    def test_extra_field_forbidden(self, tmp_path: Path):
        """The FactorManifest schema has extra='forbid', so unknown keys fail."""
        data = json.loads(_valid_manifest_json("BTC"))
        data["unknown_field"] = "surprise"
        path = tmp_path / "factor_btc.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        result = check_manifest(tmp_path, "btc")
        assert result.exists
        assert not result.valid


class TestVerifyOutputs:
    """verify_outputs(manifests_dir, symbols) -> list[ManifestCheckResult]"""

    def test_all_symbols_present_and_valid(self, tmp_path: Path):
        """All manifests present and valid -> every result is ok."""
        for sym in ["btc", "eth"]:
            (tmp_path / f"factor_{sym}.json").write_text(
                _valid_manifest_json(sym.upper()), encoding="utf-8"
            )
        results = verify_outputs(tmp_path, ["btc", "eth"])
        assert len(results) == 2
        assert all(r.ok for r in results)

    def test_missing_manifest_detected_in_verify(self, tmp_path: Path):
        """If one symbol's manifest is absent, that result is not ok."""
        # Write btc but not eth
        (tmp_path / "factor_btc.json").write_text(
            _valid_manifest_json("BTC"), encoding="utf-8"
        )
        results = verify_outputs(tmp_path, ["btc", "eth"])
        btc_result = next(r for r in results if r.symbol == "btc")
        eth_result = next(r for r in results if r.symbol == "eth")
        assert btc_result.ok
        assert not eth_result.ok

    def test_invalid_manifest_detected_in_verify(self, tmp_path: Path):
        """If one symbol's manifest fails validation, that result is not ok."""
        (tmp_path / "factor_btc.json").write_text(
            _valid_manifest_json("BTC"), encoding="utf-8"
        )
        (tmp_path / "factor_eth.json").write_text(
            _invalid_manifest_json(), encoding="utf-8"
        )
        results = verify_outputs(tmp_path, ["btc", "eth"])
        btc_result = next(r for r in results if r.symbol == "btc")
        eth_result = next(r for r in results if r.symbol == "eth")
        assert btc_result.ok
        assert not eth_result.ok

    def test_result_order_matches_symbols_order(self, tmp_path: Path):
        """Results are returned in the same order as the symbols list."""
        for sym in ["btc", "eth", "sol"]:
            (tmp_path / f"factor_{sym}.json").write_text(
                _valid_manifest_json(sym.upper()), encoding="utf-8"
            )
        symbols = ["btc", "eth", "sol"]
        results = verify_outputs(tmp_path, symbols)
        for i, sym in enumerate(symbols):
            assert results[i].symbol == sym

    def test_empty_symbols_list(self, tmp_path: Path):
        """Empty symbols list returns empty results without error."""
        results = verify_outputs(tmp_path, [])
        assert results == []


# ---------------------------------------------------------------------------
# (b) compute_exit_code
# ---------------------------------------------------------------------------


class TestComputeExitCode:
    """compute_exit_code(results) -> int"""

    def test_returns_zero_on_full_success(self):
        """All ok results -> exit code 0."""
        results = [
            ManifestCheckResult(symbol="btc", exists=True, valid=True),
            ManifestCheckResult(symbol="eth", exists=True, valid=True),
        ]
        assert compute_exit_code(results) == 0

    def test_returns_nonzero_on_missing_manifest(self):
        """A missing manifest -> non-zero exit code."""
        results = [
            ManifestCheckResult(symbol="btc", exists=True, valid=True),
            ManifestCheckResult(symbol="eth", exists=False, valid=False, error="file not found"),
        ]
        assert compute_exit_code(results) != 0

    def test_returns_nonzero_on_invalid_manifest(self):
        """An invalid manifest -> non-zero exit code."""
        results = [
            ManifestCheckResult(symbol="btc", exists=True, valid=False, error="schema error"),
        ]
        assert compute_exit_code(results) != 0

    def test_returns_nonzero_when_all_fail(self):
        """All results failing -> non-zero exit code."""
        results = [
            ManifestCheckResult(symbol="btc", exists=False, valid=False, error="missing"),
            ManifestCheckResult(symbol="eth", exists=False, valid=False, error="missing"),
        ]
        assert compute_exit_code(results) != 0

    def test_returns_zero_for_empty_list(self):
        """Empty list (no symbols configured) -> zero, as nothing failed."""
        assert compute_exit_code([]) == 0

    def test_exit_code_is_integer(self):
        """The return type is int."""
        assert isinstance(compute_exit_code([]), int)


# ---------------------------------------------------------------------------
# (c) print_summary — smoke test
# ---------------------------------------------------------------------------


class TestPrintSummary:
    """print_summary(results) — should not raise; output goes to stdout."""

    def test_all_pass_no_error(self, capsys: pytest.CaptureFixture):
        results = [
            ManifestCheckResult(symbol="btc", exists=True, valid=True),
            ManifestCheckResult(symbol="eth", exists=True, valid=True),
        ]
        print_summary(results)  # must not raise
        captured = capsys.readouterr()
        assert "OK" in captured.out
        assert "btc" in captured.out
        assert "eth" in captured.out

    def test_failure_shown_in_summary(self, capsys: pytest.CaptureFixture):
        results = [
            ManifestCheckResult(symbol="btc", exists=True, valid=True),
            ManifestCheckResult(symbol="eth", exists=False, valid=False, error="file not found"),
        ]
        print_summary(results)
        captured = capsys.readouterr()
        assert "FAIL" in captured.out
        assert "eth" in captured.out

    def test_empty_results_no_error(self, capsys: pytest.CaptureFixture):
        print_summary([])
        captured = capsys.readouterr()
        assert "0/0" in captured.out
