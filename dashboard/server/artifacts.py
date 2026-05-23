from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from schemas import (
    FactorManifest,
    SelectionManifest,
    StrategyManifest,
    TestnetStatus,
)


def _load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Strategy manifests — research/manifests/<strategy_id>/manifest.json
# ---------------------------------------------------------------------------

def list_strategy_manifests(repo_root: Path) -> list[StrategyManifest]:
    base = repo_root / "research" / "manifests"
    manifests: list[StrategyManifest] = []
    if not base.is_dir():
        return manifests
    for path in sorted(base.glob("*/manifest.json")):
        raw = _load_json(path)
        if raw is not None:
            try:
                manifests.append(StrategyManifest.model_validate(raw))
            except Exception:
                pass
    return manifests


def get_strategy_manifest(repo_root: Path, strategy_id: str) -> Optional[StrategyManifest]:
    path = repo_root / "research" / "manifests" / strategy_id / "manifest.json"
    raw = _load_json(path)
    if raw is None:
        return None
    try:
        return StrategyManifest.model_validate(raw)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Factor manifests — research/manifests/factor_<symbol>.json
# ---------------------------------------------------------------------------

def list_factor_manifests(repo_root: Path) -> list[FactorManifest]:
    base = repo_root / "research" / "manifests"
    manifests: list[FactorManifest] = []
    if not base.is_dir():
        return manifests
    for path in sorted(base.glob("factor_*.json")):
        raw = _load_json(path)
        if raw is not None:
            try:
                manifests.append(FactorManifest.model_validate(raw))
            except Exception:
                pass
    return manifests


def get_factor_manifest(repo_root: Path, symbol: str) -> Optional[FactorManifest]:
    path = repo_root / "research" / "manifests" / f"factor_{symbol}.json"
    raw = _load_json(path)
    if raw is None:
        return None
    try:
        return FactorManifest.model_validate(raw)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Selection manifest — research/manifests/selection.json
# ---------------------------------------------------------------------------

def get_selection_manifest(repo_root: Path) -> Optional[SelectionManifest]:
    path = repo_root / "research" / "manifests" / "selection.json"
    raw = _load_json(path)
    if raw is None:
        return None
    try:
        return SelectionManifest.model_validate(raw)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Regime manifest — research/manifests/regime_<symbol>.json (raw dict)
# ---------------------------------------------------------------------------

def get_regime_manifest(repo_root: Path, symbol: str) -> Optional[dict]:
    path = repo_root / "research" / "manifests" / f"regime_{symbol}.json"
    return _load_json(path)


# ---------------------------------------------------------------------------
# Testnet status — runs/testnet/<id>/testnet_status.json
# ---------------------------------------------------------------------------

def list_testnet_statuses(repo_root: Path) -> list[TestnetStatus]:
    base = repo_root / "runs" / "testnet"
    statuses: list[TestnetStatus] = []
    if not base.is_dir():
        return statuses
    for path in sorted(base.glob("*/testnet_status.json")):
        raw = _load_json(path)
        if raw is not None:
            try:
                statuses.append(TestnetStatus.model_validate(raw))
            except Exception:
                pass
    return statuses


def get_testnet_status(repo_root: Path, testnet_id: str) -> Optional[TestnetStatus]:
    path = repo_root / "runs" / "testnet" / testnet_id / "testnet_status.json"
    raw = _load_json(path)
    if raw is None:
        return None
    try:
        return TestnetStatus.model_validate(raw)
    except Exception:
        return None
