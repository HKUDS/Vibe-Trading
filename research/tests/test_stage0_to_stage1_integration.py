"""
Integration test: stage0 → stage1 handoff contract.

Tests the full handoff from stage-0's _process_symbol() writing a
candidates_<sym>.json to stage-1's _load_candidates() reading it back.

The swarm subprocess is mocked so no real network calls are made.

Pytest is run from research/ as:
    cd research && python -m pytest tests/
"""

from __future__ import annotations

import json
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Bootstrap: research/ and dashboard/server/ must be on sys.path.
_RESEARCH_DIR = Path(__file__).resolve().parents[1]  # research/
_REPO_ROOT = _RESEARCH_DIR.parent
_DASHBOARD_SCHEMAS = _REPO_ROOT / "dashboard" / "server"

for _p in (_RESEARCH_DIR, _DASHBOARD_SCHEMAS):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

from factor_extended import _load_candidates
from pipeline.stage0_discovery import _process_symbol
from schemas import CandidatesManifest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_research_config():
    """Return a minimal ResearchConfig with all required fields."""
    from pipeline.config import FeesConfig, ResearchConfig, SymbolConfig
    return ResearchConfig(
        symbols=(SymbolConfig(name="eth", okx_swap="ETH-USDT-SWAP", ccxt_bybit="ETHUSDT"),),
        period=30,
        interval="1H",
        data_source="okx",
        engine="daily",
        fees=FeesConfig(maker_rate=0.0002, taker_rate=0.0005, slippage=0.0001),
        horizons_h=(8, 24),
        discovery_cache_days=0,  # disable cache so _process_symbol always runs
    )


_FAKE_SWARM_STDOUT = """
The crypto_factor_lab swarm has analysed ETH-USDT-SWAP and identified the
following candidate factors:

```json
[
  {
    "name": "funding_z_30d",
    "formula": "rolling 30-day z-score of 8h funding rate",
    "data_source": "okx_funding",
    "transform": "z_30d",
    "expected_ic_sign": "+",
    "economic_logic": "Elevated funding signals crowded longs which tend to mean-revert.",
    "horizons_h": [8, 24],
    "category": "funding"
  },
  {
    "name": "oi_pct_change_24h",
    "formula": "24-hour percent change in open interest",
    "data_source": "bybit_oi",
    "transform": "pct_change_24h",
    "expected_ic_sign": "-",
    "economic_logic": "Rapid OI build-up precedes squeeze-driven reversals.",
    "horizons_h": [8, 24],
    "category": "oi"
  }
]
```
"""


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------


class TestStage0ToStage1Handoff:
    """Verify that stage-0 writes a manifest that stage-1 can load."""

    def _make_completed_process(self, stdout: str) -> MagicMock:
        """Build a mock CompletedProcess object."""
        cp = MagicMock(spec=subprocess.CompletedProcess)
        cp.returncode = 0
        cp.stdout = stdout
        cp.stderr = ""
        return cp

    def test_process_symbol_writes_valid_manifest(self, tmp_path: Path):
        """_process_symbol() with mocked swarm writes a valid CandidatesManifest."""
        cfg = _make_research_config()

        with patch("pipeline.stage0_discovery.subprocess.run") as mock_run:
            mock_run.return_value = self._make_completed_process(_FAKE_SWARM_STDOUT)

            result = _process_symbol(
                sym_name="eth",
                okx_swap="ETH-USDT-SWAP",
                cfg=cfg,
                manifests_dir=tmp_path,
            )

        assert result.ok, f"Expected ok=True but got: {result}"
        assert result.symbol == "eth"
        assert result.n_candidates == 2

        out_path = tmp_path / "candidates_eth.json"
        assert out_path.exists(), "candidates_eth.json should have been written"

    def test_written_manifest_is_valid_candidates_manifest(self, tmp_path: Path):
        """The JSON written by _process_symbol validates as CandidatesManifest."""
        cfg = _make_research_config()

        with patch("pipeline.stage0_discovery.subprocess.run") as mock_run:
            mock_run.return_value = self._make_completed_process(_FAKE_SWARM_STDOUT)
            _process_symbol(
                sym_name="eth",
                okx_swap="ETH-USDT-SWAP",
                cfg=cfg,
                manifests_dir=tmp_path,
            )

        out_path = tmp_path / "candidates_eth.json"
        raw = out_path.read_text(encoding="utf-8")
        manifest = CandidatesManifest.model_validate_json(raw)
        assert isinstance(manifest, CandidatesManifest)
        assert manifest.symbol == "eth"
        assert len(manifest.candidates) == 2

    def test_manifest_has_two_candidates_with_correct_fields(self, tmp_path: Path):
        """The two candidates in the manifest have correct names and data_sources."""
        cfg = _make_research_config()

        with patch("pipeline.stage0_discovery.subprocess.run") as mock_run:
            mock_run.return_value = self._make_completed_process(_FAKE_SWARM_STDOUT)
            _process_symbol(
                sym_name="eth",
                okx_swap="ETH-USDT-SWAP",
                cfg=cfg,
                manifests_dir=tmp_path,
            )

        out_path = tmp_path / "candidates_eth.json"
        manifest = CandidatesManifest.model_validate_json(out_path.read_text(encoding="utf-8"))

        names = {c.name for c in manifest.candidates}
        assert "funding_z_30d" in names
        assert "oi_pct_change_24h" in names

        sources = {c.data_source for c in manifest.candidates}
        assert "okx_funding" in sources
        assert "bybit_oi" in sources

    def test_stage1_load_candidates_reads_stage0_output(self, tmp_path: Path):
        """_load_candidates (stage-1) reads back the manifest written by stage-0."""
        cfg = _make_research_config()

        with patch("pipeline.stage0_discovery.subprocess.run") as mock_run:
            mock_run.return_value = self._make_completed_process(_FAKE_SWARM_STDOUT)
            _process_symbol(
                sym_name="eth",
                okx_swap="ETH-USDT-SWAP",
                cfg=cfg,
                manifests_dir=tmp_path,
            )

        # Now simulate stage-1 loading the manifest
        loaded = _load_candidates(tmp_path, "eth")
        assert loaded is not None
        assert isinstance(loaded, CandidatesManifest)
        assert len(loaded.candidates) == 2

    def test_stage1_gets_two_candidates(self, tmp_path: Path):
        """The two candidates loaded by stage-1 match what stage-0 produced."""
        cfg = _make_research_config()

        with patch("pipeline.stage0_discovery.subprocess.run") as mock_run:
            mock_run.return_value = self._make_completed_process(_FAKE_SWARM_STDOUT)
            _process_symbol(
                sym_name="eth",
                okx_swap="ETH-USDT-SWAP",
                cfg=cfg,
                manifests_dir=tmp_path,
            )

        loaded = _load_candidates(tmp_path, "eth")
        assert loaded is not None

        cand_map = {c.name: c for c in loaded.candidates}
        assert "funding_z_30d" in cand_map
        assert "oi_pct_change_24h" in cand_map

        funding_cand = cand_map["funding_z_30d"]
        assert funding_cand.data_source == "okx_funding"
        assert funding_cand.transform == "z_30d"
        assert funding_cand.category == "funding"

    def test_swarm_failure_writes_failed_json(self, tmp_path: Path):
        """If swarm subprocess raises CalledProcessError, a .failed.json is written."""
        cfg = _make_research_config()

        with patch("pipeline.stage0_discovery.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1, cmd=["cli.py"], output="", stderr="error"
            )

            result = _process_symbol(
                sym_name="eth",
                okx_swap="ETH-USDT-SWAP",
                cfg=cfg,
                manifests_dir=tmp_path,
            )

        assert not result.ok
        failed_path = tmp_path / "candidates_eth.failed.json"
        assert failed_path.exists(), "Should write a .failed.json marker on swarm failure"

    def test_no_valid_candidates_in_stdout_writes_failed_json(self, tmp_path: Path):
        """If stdout contains an empty array, _process_symbol writes .failed.json."""
        cfg = _make_research_config()

        empty_stdout = "```json\n[]\n```"

        with patch("pipeline.stage0_discovery.subprocess.run") as mock_run:
            mock_run.return_value = self._make_completed_process(empty_stdout)

            result = _process_symbol(
                sym_name="eth",
                okx_swap="ETH-USDT-SWAP",
                cfg=cfg,
                manifests_dir=tmp_path,
            )

        assert not result.ok
        failed_path = tmp_path / "candidates_eth.failed.json"
        assert failed_path.exists()
