"""Tests for artifacts.py — filesystem scanning helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from artifacts import (
    get_factor_manifest,
    get_selection_manifest,
    get_strategy_manifest,
    get_testnet_status,
    list_factor_manifests,
    list_strategy_manifests,
    list_testnet_statuses,
)


# ---------------------------------------------------------------------------
# Minimal valid JSON payloads
# ---------------------------------------------------------------------------

STRATEGY_PAYLOAD = {
    "schema_version": 1,
    "strategy_id": "strat_btc_001",
    "symbol": "BTC",
    "generated_at": "2024-01-01T00:00:00Z",
    "pipeline_stage": 2,
    "spec": {
        "strategy_id": "strat_btc_001",
        "symbol": "BTC",
        "spec_yaml": "runs/strat_btc_001/config.yaml",
    },
}

FACTOR_PAYLOAD = {
    "schema_version": 1,
    "symbol": "BTC",
    "generated_at": "2024-01-01T00:00:00Z",
    "period_days": 365,
    "horizons_h": [4, 8, 24],
    "factors": [
        {
            "name": "funding_rate",
            "ic_by_horizon": {"4": 0.12, "8": 0.09, "24": 0.06},
            "ir": 0.8,
            "sample_size": 500,
            "verdict": "single_use",
        }
    ],
}

SELECTION_PAYLOAD = {
    "schema_version": 1,
    "generated_at": "2024-01-01T00:00:00Z",
    "method": "weighted_score",
    "ranking": [
        {
            "strategy_id": "strat_btc_001",
            "symbol": "BTC",
            "rank": 1,
            "score": 0.92,
            "selected": True,
        }
    ],
}

TESTNET_PAYLOAD = {
    "schema_version": 1,
    "testnet_id": "tn_001",
    "strategy_id": "strat_btc_001",
    "symbol": "BTC",
    "live": {
        "started_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T01:00:00Z",
        "status": "running",
    },
    "killswitch": {"triggered": False},
}


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# Strategy manifest
# ---------------------------------------------------------------------------

def test_list_strategy_manifests_empty(tmp_path):
    assert list_strategy_manifests(tmp_path) == []


def test_list_strategy_manifests(tmp_path):
    _write(tmp_path / "research/manifests/strat_btc_001/manifest.json", STRATEGY_PAYLOAD)
    result = list_strategy_manifests(tmp_path)
    assert len(result) == 1
    assert result[0].strategy_id == "strat_btc_001"


def test_get_strategy_manifest_found(tmp_path):
    _write(tmp_path / "research/manifests/strat_btc_001/manifest.json", STRATEGY_PAYLOAD)
    m = get_strategy_manifest(tmp_path, "strat_btc_001")
    assert m is not None
    assert m.symbol == "BTC"


def test_get_strategy_manifest_missing(tmp_path):
    assert get_strategy_manifest(tmp_path, "nonexistent") is None


def test_list_strategy_manifests_skips_invalid(tmp_path):
    _write(tmp_path / "research/manifests/strat_btc_001/manifest.json", STRATEGY_PAYLOAD)
    bad = tmp_path / "research/manifests/strat_bad/manifest.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("not json", encoding="utf-8")
    result = list_strategy_manifests(tmp_path)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Factor manifest
# ---------------------------------------------------------------------------

def test_list_factor_manifests_empty(tmp_path):
    assert list_factor_manifests(tmp_path) == []


def test_list_factor_manifests(tmp_path):
    _write(tmp_path / "research/manifests/factor_BTC.json", FACTOR_PAYLOAD)
    result = list_factor_manifests(tmp_path)
    assert len(result) == 1
    assert result[0].symbol == "BTC"


def test_get_factor_manifest_found(tmp_path):
    _write(tmp_path / "research/manifests/factor_BTC.json", FACTOR_PAYLOAD)
    m = get_factor_manifest(tmp_path, "BTC")
    assert m is not None
    assert len(m.factors) == 1


def test_get_factor_manifest_missing(tmp_path):
    assert get_factor_manifest(tmp_path, "ETH") is None


# ---------------------------------------------------------------------------
# Selection manifest
# ---------------------------------------------------------------------------

def test_get_selection_manifest_found(tmp_path):
    _write(tmp_path / "research/manifests/selection.json", SELECTION_PAYLOAD)
    m = get_selection_manifest(tmp_path)
    assert m is not None
    assert len(m.ranking) == 1


def test_get_selection_manifest_missing(tmp_path):
    assert get_selection_manifest(tmp_path) is None


# ---------------------------------------------------------------------------
# Testnet status
# ---------------------------------------------------------------------------

def test_list_testnet_statuses_empty(tmp_path):
    assert list_testnet_statuses(tmp_path) == []


def test_list_testnet_statuses(tmp_path):
    _write(tmp_path / "runs/testnet/tn_001/testnet_status.json", TESTNET_PAYLOAD)
    result = list_testnet_statuses(tmp_path)
    assert len(result) == 1
    assert result[0].testnet_id == "tn_001"


def test_get_testnet_status_found(tmp_path):
    _write(tmp_path / "runs/testnet/tn_001/testnet_status.json", TESTNET_PAYLOAD)
    s = get_testnet_status(tmp_path, "tn_001")
    assert s is not None
    assert s.strategy_id == "strat_btc_001"


def test_get_testnet_status_missing(tmp_path):
    assert get_testnet_status(tmp_path, "nonexistent") is None
