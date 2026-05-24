"""
Tests for research/pipeline/stage0_discovery.py pure-logic helpers.

Covers:
  (a)-(e) parse_candidates_json()
  (f)-(i) filter_invalid_candidates()
  (j)-(m) cache_hit()
  (n)-(p) compute_exit_code()

All tests are network-free; main() and _process_symbol() are NOT tested here.

Pytest is run from research/ as:
    cd research && python -m pytest tests/
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Bootstrap: research/ and dashboard/server/ must be on sys.path.
_RESEARCH_DIR = Path(__file__).resolve().parents[1]  # research/
_REPO_ROOT = _RESEARCH_DIR.parent
_DASHBOARD_SCHEMAS = _REPO_ROOT / "dashboard" / "server"

for _p in (_RESEARCH_DIR, _DASHBOARD_SCHEMAS):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

from pipeline.stage0_discovery import (
    CandidatesCheckResult,
    cache_hit,
    compute_exit_code,
    filter_invalid_candidates,
    parse_candidates_json,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candidates_manifest_json(
    sym: str = "eth",
    generated_at: datetime | None = None,
    n_candidates: int = 1,
) -> str:
    """Return a minimal valid CandidatesManifest JSON string."""
    if generated_at is None:
        generated_at = datetime.now(timezone.utc)
    candidates = []
    for i in range(n_candidates):
        candidates.append(
            {
                "name": f"funding_z_30d_{i}",
                "formula": "z-score of 30d rolling funding rate",
                "data_source": "okx_funding",
                "transform": "z_30d",
                "expected_ic_sign": "+",
                "economic_logic": "High funding -> crowded longs -> mean-revert",
                "horizons_h": [8, 24],
                "category": "funding",
            }
        )
    return json.dumps(
        {
            "schema_version": 1,
            "symbol": sym,
            "generated_at": generated_at.isoformat(),
            "source_swarm_run": None,
            "candidates": candidates,
        }
    )


# ---------------------------------------------------------------------------
# parse_candidates_json
# ---------------------------------------------------------------------------


class TestParseCandidatesJson:
    """parse_candidates_json(stdout) -> list[dict]"""

    # (a) Valid stdout with a single ```json ... ``` block containing a list
    def test_valid_single_json_block_returns_list(self):
        stdout = '```json\n[{"name": "foo", "transform": "raw"}]\n```'
        result = parse_candidates_json(stdout)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["name"] == "foo"

    # (b) stdout with no fenced block → raises ValueError
    def test_no_fenced_block_raises_value_error(self):
        stdout = 'Here is the answer: [{"name": "foo"}]'
        with pytest.raises(ValueError, match="No JSON fenced code block"):
            parse_candidates_json(stdout)

    # (c) stdout with whitespace before/after JSON content → still parses
    def test_whitespace_inside_fence_still_parses(self):
        stdout = '```json\n  \n  [{"name": "bar"}]\n  \n```'
        result = parse_candidates_json(stdout)
        assert isinstance(result, list)
        assert result[0]["name"] == "bar"

    # (d) stdout with a reasoning fenced block (not a list) BEFORE the real JSON list block
    def test_reasoning_block_before_list_block_returns_list(self):
        reasoning = '```json\n{"reasoning": "I think we should use z-score"}\n```'
        candidates = '```json\n[{"name": "funding_z_30d"}]\n```'
        stdout = f"Some reasoning:\n{reasoning}\n\nActual candidates:\n{candidates}"
        result = parse_candidates_json(stdout)
        assert isinstance(result, list)
        assert result[0]["name"] == "funding_z_30d"

    # (e) stdout with malformed JSON in the fence → raises ValueError
    def test_malformed_json_in_fence_raises_value_error(self):
        stdout = "```json\n[{name: 'foo', unclosed\n```"
        with pytest.raises(ValueError):
            parse_candidates_json(stdout)

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError, match="No JSON fenced code block"):
            parse_candidates_json("")

    def test_returns_multiple_items_from_list(self):
        items = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        stdout = f"```json\n{json.dumps(items)}\n```"
        result = parse_candidates_json(stdout)
        assert len(result) == 3

    def test_fence_without_json_tag_also_works(self):
        """Plain ``` fence (not ```json) should also be matched."""
        stdout = '```\n[{"name": "plain_fence"}]\n```'
        result = parse_candidates_json(stdout)
        assert result[0]["name"] == "plain_fence"

    def test_all_blocks_are_objects_raises_value_error(self):
        """If all fenced blocks are JSON objects (not arrays), raises ValueError."""
        stdout = '```json\n{"key": "val"}\n```\n```json\n{"key2": "val2"}\n```'
        with pytest.raises(ValueError, match="No valid JSON array"):
            parse_candidates_json(stdout)


# ---------------------------------------------------------------------------
# filter_invalid_candidates
# ---------------------------------------------------------------------------


_AVAIL_SOURCES = ["okx_funding", "okx_candles", "bybit_oi"]
_AVAIL_TRANSFORMS = ["raw", "z_30d", "z_90d", "pct_change_24h", "ma_diff_7d_30d"]


class TestFilterInvalidCandidates:
    """filter_invalid_candidates(raw, sources, transforms) -> (valid, warnings)"""

    def _make_cand(self, name="c1", src="okx_funding", tfm="raw"):
        return {"name": name, "data_source": src, "transform": tfm}

    # (f) Candidate with unknown data_source → filtered out, warning returned
    def test_unknown_data_source_filtered_with_warning(self):
        cand = self._make_cand(src="unknown_exchange")
        valid, warnings = filter_invalid_candidates([cand], _AVAIL_SOURCES, _AVAIL_TRANSFORMS)
        assert valid == []
        assert len(warnings) == 1
        assert "data_source" in warnings[0]
        assert "unknown_exchange" in warnings[0]

    # (g) Candidate with unknown transform → filtered out, warning returned
    def test_unknown_transform_filtered_with_warning(self):
        cand = self._make_cand(tfm="exotic_transform")
        valid, warnings = filter_invalid_candidates([cand], _AVAIL_SOURCES, _AVAIL_TRANSFORMS)
        assert valid == []
        assert len(warnings) == 1
        assert "transform" in warnings[0]
        assert "exotic_transform" in warnings[0]

    # (h) Candidate with both valid source and transform → kept
    def test_valid_candidate_kept(self):
        cand = self._make_cand(src="okx_funding", tfm="z_30d")
        valid, warnings = filter_invalid_candidates([cand], _AVAIL_SOURCES, _AVAIL_TRANSFORMS)
        assert len(valid) == 1
        assert warnings == []

    # (i) Mix of valid and invalid → returns only valid ones with warnings for invalid
    def test_mixed_returns_only_valid_with_warnings(self):
        good1 = self._make_cand("good1", "okx_funding", "raw")
        good2 = self._make_cand("good2", "bybit_oi", "z_30d")
        bad1 = self._make_cand("bad1", "unknown_src", "raw")
        bad2 = self._make_cand("bad2", "okx_funding", "bad_transform")

        valid, warnings = filter_invalid_candidates(
            [good1, bad1, good2, bad2], _AVAIL_SOURCES, _AVAIL_TRANSFORMS
        )
        assert len(valid) == 2
        assert all(v["name"].startswith("good") for v in valid)
        assert len(warnings) == 2

    def test_empty_list_returns_empty(self):
        valid, warnings = filter_invalid_candidates([], _AVAIL_SOURCES, _AVAIL_TRANSFORMS)
        assert valid == []
        assert warnings == []

    def test_candidate_missing_name_uses_index_in_warning(self):
        """If 'name' key is absent, warning references the index."""
        cand = {"data_source": "bad_src", "transform": "raw"}
        valid, warnings = filter_invalid_candidates([cand], _AVAIL_SOURCES, _AVAIL_TRANSFORMS)
        assert valid == []
        assert len(warnings) == 1

    def test_warning_message_identifies_candidate_name(self):
        cand = self._make_cand("my_factor", "bad_source", "raw")
        _, warnings = filter_invalid_candidates([cand], _AVAIL_SOURCES, _AVAIL_TRANSFORMS)
        assert "my_factor" in warnings[0]


# ---------------------------------------------------------------------------
# cache_hit
# ---------------------------------------------------------------------------


class TestCacheHit:
    """cache_hit(manifests_dir, sym, cache_days) -> bool"""

    def _write_manifest(self, dir_: Path, sym: str, generated_at: datetime) -> Path:
        """Write a minimal CandidatesManifest JSON to disk and return its path."""
        path = dir_ / f"candidates_{sym}.json"
        path.write_text(
            _make_candidates_manifest_json(sym=sym, generated_at=generated_at),
            encoding="utf-8",
        )
        return path

    # (j) file exists with generated_at 3 days ago, cache_days=7 → True
    def test_within_ttl_returns_true(self, tmp_path: Path):
        generated_at = datetime.now(timezone.utc) - timedelta(days=3)
        self._write_manifest(tmp_path, "eth", generated_at)
        assert cache_hit(tmp_path, "eth", cache_days=7) is True

    # (k) file exists with generated_at 8 days ago, cache_days=7 → False
    def test_expired_ttl_returns_false(self, tmp_path: Path):
        generated_at = datetime.now(timezone.utc) - timedelta(days=8)
        self._write_manifest(tmp_path, "eth", generated_at)
        assert cache_hit(tmp_path, "eth", cache_days=7) is False

    # (l) cache_days=0 → always False
    def test_cache_days_zero_always_false(self, tmp_path: Path):
        generated_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        self._write_manifest(tmp_path, "eth", generated_at)
        assert cache_hit(tmp_path, "eth", cache_days=0) is False

    # (m) file doesn't exist → False
    def test_missing_file_returns_false(self, tmp_path: Path):
        assert cache_hit(tmp_path, "eth", cache_days=7) is False

    def test_exactly_at_boundary_returns_false(self, tmp_path: Path):
        """Age equal to cache_days (not strictly less) should be False."""
        generated_at = datetime.now(timezone.utc) - timedelta(days=7)
        self._write_manifest(tmp_path, "eth", generated_at)
        # 7 days old, cache_days=7: age_days >= cache_days → False
        assert cache_hit(tmp_path, "eth", cache_days=7) is False

    def test_corrupt_file_returns_false(self, tmp_path: Path):
        """A corrupt JSON file should not raise; returns False."""
        path = tmp_path / "candidates_eth.json"
        path.write_text("{bad json}", encoding="utf-8")
        assert cache_hit(tmp_path, "eth", cache_days=7) is False

    def test_sym_name_used_in_filename(self, tmp_path: Path):
        """cache_hit for 'btc' should look at candidates_btc.json, not candidates_eth.json."""
        generated_at = datetime.now(timezone.utc) - timedelta(days=1)
        self._write_manifest(tmp_path, "eth", generated_at)
        # Only eth file exists; btc query should be False
        assert cache_hit(tmp_path, "btc", cache_days=7) is False
        assert cache_hit(tmp_path, "eth", cache_days=7) is True


# ---------------------------------------------------------------------------
# compute_exit_code
# ---------------------------------------------------------------------------


class TestComputeExitCode:
    """compute_exit_code(results) -> int"""

    # (n) All results ok → 0
    def test_all_ok_returns_zero(self):
        results = [
            CandidatesCheckResult(symbol="eth", exists=True, valid=True, n_candidates=3),
            CandidatesCheckResult(symbol="btc", exists=True, valid=True, n_candidates=5),
        ]
        assert compute_exit_code(results) == 0

    # (o) One result not ok → 1
    def test_one_failure_returns_one(self):
        results = [
            CandidatesCheckResult(symbol="eth", exists=True, valid=True, n_candidates=3),
            CandidatesCheckResult(symbol="btc", exists=False, valid=False, error="missing"),
        ]
        assert compute_exit_code(results) == 1

    # (p) Empty list → 0
    def test_empty_list_returns_zero(self):
        assert compute_exit_code([]) == 0

    def test_all_failed_returns_one(self):
        results = [
            CandidatesCheckResult(symbol="eth", exists=False, valid=False, error="missing"),
            CandidatesCheckResult(symbol="btc", exists=False, valid=False, error="missing"),
        ]
        assert compute_exit_code(results) == 1

    def test_invalid_but_exists_returns_one(self):
        """exists=True but valid=False → ok is False → exit code 1."""
        results = [
            CandidatesCheckResult(symbol="eth", exists=True, valid=False, error="corrupt"),
        ]
        assert compute_exit_code(results) == 1

    def test_return_type_is_int(self):
        assert isinstance(compute_exit_code([]), int)
