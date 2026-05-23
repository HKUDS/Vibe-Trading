"""Promotion state management — reads/writes dashboard/data/state.json.

This is the only file the dashboard writes. Research artifacts are read-only.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


_STATE_FILE = "data/state.json"
_EXPORTS_DIR = "data/exports"


def _state_path(dashboard_dir: Path) -> Path:
    return dashboard_dir / _STATE_FILE


def _exports_dir(dashboard_dir: Path) -> Path:
    return dashboard_dir / _EXPORTS_DIR


def load_state(dashboard_dir: Path) -> dict[str, Any]:
    path = _state_path(dashboard_dir)
    if not path.exists():
        return {"promoted": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"promoted": {}}


def _save_state(dashboard_dir: Path, state: dict) -> None:
    path = _state_path(dashboard_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def is_promoted(dashboard_dir: Path, strategy_id: str) -> bool:
    return strategy_id in load_state(dashboard_dir).get("promoted", {})


def promote(
    dashboard_dir: Path,
    repo_root: Path,
    strategy_id: str,
    spec_yaml_path: str,
    override_reason: Optional[str] = None,
) -> dict[str, Any]:
    """Mark strategy as promoted.

    Copies the strategy YAML to exports/ and records in state.json.
    Returns the promotion record.
    """
    state = load_state(dashboard_dir)
    record: dict[str, Any] = {
        "promoted_at": datetime.now(tz=timezone.utc).isoformat(),
        "override": {"reason": override_reason} if override_reason else None,
    }
    state.setdefault("promoted", {})[strategy_id] = record

    # Export strategy YAML — source path is relative to repo_root
    src = (repo_root / spec_yaml_path).resolve()
    if src.exists() and src.is_relative_to(repo_root.resolve()):
        exports = _exports_dir(dashboard_dir)
        exports.mkdir(parents=True, exist_ok=True)
        dest = exports / src.name
        shutil.copy2(src, dest)
        record["exported_config"] = str(dest.relative_to(dashboard_dir))

    _save_state(dashboard_dir, state)
    return record


def demote(dashboard_dir: Path, strategy_id: str) -> bool:
    """Remove strategy from promoted set. Returns True if it was promoted."""
    state = load_state(dashboard_dir)
    promoted = state.get("promoted", {})
    if strategy_id not in promoted:
        return False
    del promoted[strategy_id]
    _save_state(dashboard_dir, state)
    return True
