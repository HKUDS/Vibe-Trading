"""
research/pipeline/strategy_runs.py
────────────────────────────────────
Loads and validates research/strategy_runs.json.

This module is the primary API for any stage runner (e.g. emit_manifest.py)
that needs to know which backtest run directories belong to a given strategy.

Usage
-----
    from pipeline.strategy_runs import load_strategy_runs

    runs_map = load_strategy_runs()
    entry = runs_map.entries["btc_s1_multifactor_contrarian"]
    base = entry.base_run          # e.g. "btc_s1_base"
    regimes = entry.regime_runs    # e.g. {"bull": "btc_s1_bull", ...}

Notes
-----
- This module validates STRUCTURE only (types, required keys, correct
  collection types for each field).
- Whether the run directories actually exist on disk is NOT checked here;
  that responsibility belongs to emit_manifest.py (Task 2.12), which reads
  run metrics and therefore can give a richer error if a directory is absent.
- Path resolution follows the same pattern as research/pipeline/config.py:
  the JSON file lives at <repo-root>/research/strategy_runs.json and the
  default path is resolved relative to this module's location so the code
  works on any OS and in any working directory (Linux-deploy safe).
"""

from __future__ import annotations

import dataclasses
import json
import types
from pathlib import Path
from typing import Mapping

# strategy_runs.json lives at  <repo-root>/research/strategy_runs.json.
# This module is at            <repo-root>/research/pipeline/strategy_runs.py.
# So repo root = two parents up.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_JSON_PATH = _REPO_ROOT / "research" / "strategy_runs.json"

# ─── Required keys per entry ─────────────────────────────────────────────────

_REQUIRED_ENTRY_KEYS = {
    "symbol",
    "spec_yaml",
    "base_run",
    "regime_runs",
    "stress_runs",
    "oos_runs",
    "sweep_run",
}


# ─── Dataclasses ─────────────────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class StrategyRunsEntry:
    """Per-strategy run mapping — all fields are structural; do NOT check disk."""

    symbol: str
    """Exchange ticker this strategy trades, e.g. 'BTC-USDT-SWAP'."""

    spec_yaml: str
    """Repo-relative path to the strategy YAML, e.g. 'research/strategies/strategy_S1.yaml'."""

    base_run: str | None
    """
    Name of the primary in-sample backtest run directory under runs/.
    Null means the run has not been generated yet (fill in as you backtest).
    """

    regime_runs: Mapping[str, str]
    """
    Per-market-regime run directories.
    Typical keys: 'bull', 'bear', 'neutral'.
    Example: {"bull": "btc_s1_bull", "bear": "btc_s1_bear", "neutral": "btc_s1_neutral"}
    """

    stress_runs: Mapping[str, str]
    """
    Cost-stress run directories keyed by a descriptive label.
    Example: {"3x_fees": "btc_s1_base_stress"}
    """

    oos_runs: tuple[str, ...]
    """
    Out-of-sample run directory names (ordered chronologically if multiple).
    Example: ("btc_s1_oos_2023", "btc_s1_oos_2024")
    """

    sweep_run: str | None
    """
    Parameter-sweep run directory name.
    Null means no sweep has been run yet.
    """

    walk_forward_runs: tuple[str, ...] = ()
    """
    Held-out walk-forward validation run directory names (optional).
    These are out-of-sample runs of the strategy's TUNED params on data the
    parameter sweep never saw (e.g. years after the train window). They feed the
    manifest's ``walk_forward`` block. Empty when no walk-forward test exists.
    """


@dataclasses.dataclass(frozen=True)
class StrategyRunsMap:
    """Top-level object returned by load_strategy_runs()."""

    entries: Mapping[str, StrategyRunsEntry]
    """
    Maps strategy_id -> StrategyRunsEntry.
    strategy_id follows the convention: <coin>_s<N>_<archetype>
    e.g. 'btc_s1_multifactor_contrarian'.
    """


# ─── Loader ──────────────────────────────────────────────────────────────────

def load_strategy_runs(path: Path | str | None = None) -> StrategyRunsMap:
    """Load and validate strategy_runs.json, returning a StrategyRunsMap.

    Parameters
    ----------
    path:
        Path to the JSON file.  Defaults to
        ``<repo-root>/research/strategy_runs.json``.
        Pass an explicit path in tests or CI to load fixture JSON.

    Raises
    ------
    FileNotFoundError
        If the JSON file does not exist at the resolved path.
    TypeError
        If the JSON root is not a mapping, an entry is not a mapping, or a
        field has the wrong type.  The error message names the offending
        ``strategy_id`` and field.
    KeyError
        If a required entry key is absent.  The error message names the
        offending ``strategy_id`` and field.
    """
    resolved = Path(path) if path is not None else _DEFAULT_JSON_PATH

    if not resolved.exists():
        raise FileNotFoundError(
            f"strategy_runs.json not found at: {resolved}\n"
            "Create the file or pass an explicit path to load_strategy_runs()."
        )

    with resolved.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    # Guard: root must be a JSON object (dict)
    if not isinstance(raw, dict):
        raise TypeError(
            f"strategy_runs.json must be a JSON mapping at the top level, "
            f"got {type(raw).__name__}."
        )

    entries: dict[str, StrategyRunsEntry] = {}

    for strategy_id, entry_raw in raw.items():
        # Skip the top-level "_comment" key used for self-documentation.
        # Only the exact key "_comment" is skipped; other underscore-prefixed
        # strategy ids (e.g. "_archived_strategy") are loaded normally.
        if strategy_id == "_comment":
            continue

        # Each entry must be a JSON object
        if not isinstance(entry_raw, dict):
            raise TypeError(
                f"strategy_runs.json: entry for strategy_id '{strategy_id}' "
                f"must be a JSON mapping, got {type(entry_raw).__name__}."
            )

        # ── Required key presence ────────────────────────────────────────────
        missing = _REQUIRED_ENTRY_KEYS - entry_raw.keys()
        if missing:
            raise KeyError(
                f"strategy_runs.json: entry for strategy_id '{strategy_id}' "
                f"is missing required key(s): {sorted(missing)}"
            )

        # ── Type validation — each field ────────────────────────────────────

        symbol = entry_raw["symbol"]
        if not isinstance(symbol, str):
            raise TypeError(
                f"strategy_runs.json: entry for strategy_id '{strategy_id}': "
                f"'symbol' must be a string, got {type(symbol).__name__}."
            )

        spec_yaml = entry_raw["spec_yaml"]
        if not isinstance(spec_yaml, str):
            raise TypeError(
                f"strategy_runs.json: entry for strategy_id '{strategy_id}': "
                f"'spec_yaml' must be a string, got {type(spec_yaml).__name__}."
            )

        base_run = entry_raw["base_run"]
        if base_run is not None and not isinstance(base_run, str):
            raise TypeError(
                f"strategy_runs.json: entry for strategy_id '{strategy_id}': "
                f"'base_run' must be a string or null, got {type(base_run).__name__}."
            )

        regime_runs = entry_raw["regime_runs"]
        if not isinstance(regime_runs, dict):
            raise TypeError(
                f"strategy_runs.json: entry for strategy_id '{strategy_id}': "
                f"'regime_runs' must be a JSON object (dict), got {type(regime_runs).__name__}."
            )
        for k, v in regime_runs.items():
            if not isinstance(v, str):
                raise TypeError(
                    f"strategy_runs.json: entry for strategy_id '{strategy_id}': "
                    f"'regime_runs[{k!r}]' must be a string, got {type(v).__name__}."
                )

        stress_runs = entry_raw["stress_runs"]
        if not isinstance(stress_runs, dict):
            raise TypeError(
                f"strategy_runs.json: entry for strategy_id '{strategy_id}': "
                f"'stress_runs' must be a JSON object (dict), got {type(stress_runs).__name__}."
            )
        for k, v in stress_runs.items():
            if not isinstance(v, str):
                raise TypeError(
                    f"strategy_runs.json: entry for strategy_id '{strategy_id}': "
                    f"'stress_runs[{k!r}]' must be a string, got {type(v).__name__}."
                )

        oos_runs = entry_raw["oos_runs"]
        if not isinstance(oos_runs, list):
            raise TypeError(
                f"strategy_runs.json: entry for strategy_id '{strategy_id}': "
                f"'oos_runs' must be a JSON array (list), got {type(oos_runs).__name__}."
            )
        for i, v in enumerate(oos_runs):
            if not isinstance(v, str):
                raise TypeError(
                    f"strategy_runs.json: entry for strategy_id '{strategy_id}': "
                    f"'oos_runs[{i}]' must be a string, got {type(v).__name__}."
                )

        sweep_run = entry_raw["sweep_run"]
        if sweep_run is not None and not isinstance(sweep_run, str):
            raise TypeError(
                f"strategy_runs.json: entry for strategy_id '{strategy_id}': "
                f"'sweep_run' must be a string or null, got {type(sweep_run).__name__}."
            )

        # Optional: held-out walk-forward validation runs (backward-compatible).
        wf_runs = entry_raw.get("walk_forward_runs", [])
        if not isinstance(wf_runs, list):
            raise TypeError(
                f"strategy_runs.json: entry for strategy_id '{strategy_id}': "
                f"'walk_forward_runs' must be a JSON array (list), got {type(wf_runs).__name__}."
            )
        for i, v in enumerate(wf_runs):
            if not isinstance(v, str):
                raise TypeError(
                    f"strategy_runs.json: entry for strategy_id '{strategy_id}': "
                    f"'walk_forward_runs[{i}]' must be a string, got {type(v).__name__}."
                )

        entries[strategy_id] = StrategyRunsEntry(
            symbol=symbol,
            spec_yaml=spec_yaml,
            base_run=base_run,
            regime_runs=types.MappingProxyType(dict(regime_runs)),
            stress_runs=types.MappingProxyType(dict(stress_runs)),
            oos_runs=tuple(oos_runs),
            sweep_run=sweep_run,
            walk_forward_runs=tuple(wf_runs),
        )

    return StrategyRunsMap(entries=types.MappingProxyType(entries))


# ─── Writer ──────────────────────────────────────────────────────────────────

def update_sweep_run(
    strategy_id: str,
    sweep_run: str | None,
    path: Path | str | None = None,
) -> None:
    """Update the ``sweep_run`` field for one strategy and write the file back.

    Intended to be called by stage 4 after a successful grid sweep so that
    downstream stages (stage 3 diagnosis, stage 5 selection) and dashboards
    can resolve the strategy's best-tuned run via strategy_runs.json without
    requiring every consumer to also parse optimization.json.

    The on-disk write preserves the order and indentation of the existing
    JSON (uses ``json.dumps(..., indent=2)``) and includes a trailing newline
    to keep diffs stable. ``_comment`` top-level entries are preserved.

    Parameters
    ----------
    strategy_id:
        The strategy whose ``sweep_run`` field should be updated.
    sweep_run:
        The new sweep-run name (e.g. ``"eth_s1_multi_factor_consensus_sweep_033"``)
        or ``None`` to clear the field.
    path:
        Optional override for the strategy_runs.json path. Defaults to
        ``<repo-root>/research/strategy_runs.json``.

    Raises
    ------
    FileNotFoundError
        If strategy_runs.json does not exist at the resolved path.
    KeyError
        If ``strategy_id`` is not present in the file.
    TypeError
        If ``sweep_run`` is not a string or None.
    """
    if sweep_run is not None and not isinstance(sweep_run, str):
        raise TypeError(
            f"update_sweep_run: sweep_run must be a string or None, "
            f"got {type(sweep_run).__name__}."
        )

    resolved = Path(path) if path is not None else _DEFAULT_JSON_PATH
    if not resolved.exists():
        raise FileNotFoundError(
            f"strategy_runs.json not found at: {resolved}"
        )

    with resolved.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    if not isinstance(raw, dict):
        raise TypeError(
            f"strategy_runs.json must be a JSON mapping at the top level, "
            f"got {type(raw).__name__}."
        )

    if strategy_id not in raw or strategy_id == "_comment":
        raise KeyError(
            f"strategy_runs.json: strategy_id '{strategy_id}' not present."
        )

    entry = raw[strategy_id]
    if not isinstance(entry, dict):
        raise TypeError(
            f"strategy_runs.json: entry for '{strategy_id}' is not a JSON object."
        )

    entry["sweep_run"] = sweep_run

    payload = json.dumps(raw, indent=2, ensure_ascii=False) + "\n"
    resolved.write_text(payload, encoding="utf-8")


def update_walk_forward_runs(
    strategy_id: str,
    walk_forward_runs: list[str],
    path: Path | str | None = None,
) -> None:
    """Set the ``walk_forward_runs`` list for one strategy and write the file back.

    Called by stage 4 after running the tuned best params on the held-out OOS
    window, so the dashboard manifest builder can surface the genuine
    out-of-sample result in the ``walk_forward`` block.

    Same file-preserving semantics as :func:`update_sweep_run`.
    """
    if not isinstance(walk_forward_runs, list) or not all(
        isinstance(r, str) for r in walk_forward_runs
    ):
        raise TypeError("update_walk_forward_runs: walk_forward_runs must be a list of strings.")

    resolved = Path(path) if path is not None else _DEFAULT_JSON_PATH
    if not resolved.exists():
        raise FileNotFoundError(f"strategy_runs.json not found at: {resolved}")

    with resolved.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    if not isinstance(raw, dict):
        raise TypeError("strategy_runs.json must be a JSON mapping at the top level.")
    if strategy_id not in raw or strategy_id == "_comment":
        raise KeyError(f"strategy_runs.json: strategy_id '{strategy_id}' not present.")

    raw[strategy_id]["walk_forward_runs"] = list(walk_forward_runs)
    payload = json.dumps(raw, indent=2, ensure_ascii=False) + "\n"
    resolved.write_text(payload, encoding="utf-8")
