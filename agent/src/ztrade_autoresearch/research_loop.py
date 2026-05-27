"""Karpathy-style research-loop artifacts for ztrade autoresearch.

The fixed evaluator remains in ``runner.py``.  This module owns the research
workspace that a coding agent can drive for long-running loops:

* ``program.md`` is the instruction contract.
* ``mutable/v47_params.json`` is the first allowed mutation surface.
* Alpha Zoo metadata and swarm prompts feed the proposal step.
* ``results.tsv`` is the compact experiment ledger.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.ztrade_autoresearch.protocol import BASELINE_ID, DEFAULT_V47_PARAMS, STRATEGY_FAMILY


AUTORESEARCH_DIRNAME = "autoresearch"
MUTABLE_PARAMS_REL = f"{AUTORESEARCH_DIRNAME}/mutable/v47_params.json"
BEST_PARAMS_REL = f"{AUTORESEARCH_DIRNAME}/best/v47_params.json"
PROGRAM_REL = f"{AUTORESEARCH_DIRNAME}/program.md"
RESULTS_TSV_REL = f"{AUTORESEARCH_DIRNAME}/results.tsv"
ALPHA_CONTEXT_REL = f"{AUTORESEARCH_DIRNAME}/context/alpha_zoo_context.json"
SWARM_REQUEST_REL = f"{AUTORESEARCH_DIRNAME}/proposals/swarm_proposal_request.json"
LATEST_STATE_REL = f"{AUTORESEARCH_DIRNAME}/latest_state.json"
MUTABLE_CANDIDATE_ID = "candidate_mutable_v47"

RESULTS_COLUMNS = [
    "iteration",
    "candidate_id",
    "verdict",
    "score",
    "return_delta",
    "win_rate_avg",
    "max_drawdown_delta",
    "trade_retention",
    "candidate_trades",
    "failed_gates",
    "rationale",
]

SWARM_ROLES = [
    {
        "role": "factor_librarian",
        "purpose": "Use Alpha Zoo metadata to nominate explainable factor ideas; do not invent factors.",
    },
    {
        "role": "v47_researcher",
        "purpose": "Map each idea onto the current v47 parameter surface before requesting any expansion.",
    },
    {
        "role": "regime_analyst",
        "purpose": "Compare bull, bear, chop, and live-like windows using only evaluator artifacts.",
    },
    {
        "role": "overfit_skeptic",
        "purpose": "Reject ideas that depend on frozen-test peeking, evaluator edits, or one-window luck.",
    },
    {
        "role": "proposal_writer",
        "purpose": "Emit one structured experiment proposal that mutates only the allowed surface.",
    },
]

PARAM_BOUNDS: dict[str, tuple[float | None, float | None]] = {
    "s1_window": (3, 30),
    "s1_volume_ratio_min": (0.5, 3.0),
    "s1_max_age": (0, 10),
    "s1_stale_age_min": (0, 30),
    "s1_stale_volume_ratio_min": (0.5, 5.0),
    "early_failure_max_hold_days": (1, 15),
    "early_failure_loss_pct": (0.1, 10.0),
    "early_failure_market_ma_window": (5, 120),
    "early_failure_market_min_coverage": (1, 5000),
    "early_failure_market_below_ma_ratio_min": (0.0, 1.0),
    "early_failure_market_down_ratio_min": (0.0, 1.0),
    "early_failure_gap_guard_pct": (0.0, 20.0),
    "early_failure_gap_guard_capitulation_pct": (0.0, 30.0),
    "early_failure_gap_guard_capitulation_below_ma_ratio_max": (0.0, 1.0),
    "early_failure_gap_guard_capitulation_down_ratio_max": (0.0, 1.0),
    "early_failure_weak_breadth_below_ma_ratio_max": (0.0, 1.0),
    "early_failure_weak_breadth_down_ratio_max": (0.0, 1.0),
}

PROGRAM_MD = """# ztrade Karpathy-Style Autoresearch Program

You are driving a long-running quant research loop in the style of
Karpathy/autoresearch.

## Objective

Improve the ztrade v47 strategy family under a fixed, code-owned judge.
The first research surface is v47 parameter tuning only.

## Loop

1. Read this file, `results.tsv`, `latest_state.json`, and the current best
   parameters before changing anything.
2. Think with the local Alpha Zoo context and the swarm proposal request.
3. Mutate exactly one allowed candidate surface:
   `autoresearch/mutable/v47_params.json`.
4. Run the fixed ztrade autoresearch evaluator.
5. Append or refresh `results.tsv` from evaluator output.
6. Keep the candidate only when the evaluator returns KEEP and all required
   gates pass. Otherwise discard or revise in the next iteration.

## Immutable Judge

Do not modify data loaders, data windows, benchmark rows, evaluator gates,
backtest execution, cost/slippage/T+1 assumptions, run-card hashing, or frozen
test rules during a research run.

## Proposal Layer

Swarm agents and Alpha Zoo are inside the Think step:

- Swarm may analyze history, explain failure modes, challenge overfitting, and
  propose one next experiment.
- Alpha Zoo is the explainable idea library for factors and factor families.
- Neither swarm nor Alpha Zoo may decide KEEP/DISCARD.
- Neither may directly expand the official search space.

Search-space expansion is allowed only as a written proposal after repeated
plateau evidence under v47 parameter tuning. The proposal must be evaluated by
a separate human or code-review step before becoming mutable surface.

## Current Allowed Surface

Only `autoresearch/mutable/v47_params.json` may be edited by the loop.
All keys must be existing v47 parameter keys and must stay within the
machine-checked bounds in the project code.
"""


def initialize_karpathy_workspace(
    root: str | Path,
    *,
    mode: str,
    data_dir: str | Path | None = None,
    max_symbols: int | None = None,
) -> dict[str, Any]:
    """Create or refresh the agent-facing research workspace.

    Existing mutable/best parameter files are intentionally not overwritten.
    That lets a coding agent edit ``mutable/v47_params.json`` between evaluator
    runs without the runner erasing its candidate.
    """
    root_path = Path(root)
    research_dir = root_path / AUTORESEARCH_DIRNAME
    for rel in ("mutable", "best", "context", "proposals", "archive"):
        (research_dir / rel).mkdir(parents=True, exist_ok=True)

    _write_text(root_path / PROGRAM_REL, PROGRAM_MD)
    _write_json_if_missing(root_path / MUTABLE_PARAMS_REL, _params_payload(DEFAULT_V47_PARAMS))
    _write_json_if_missing(root_path / BEST_PARAMS_REL, _params_payload(DEFAULT_V47_PARAMS))
    _write_text_if_missing(root_path / RESULTS_TSV_REL, "\t".join(RESULTS_COLUMNS) + "\n")
    _write_json(
        root_path / ALPHA_CONTEXT_REL,
        build_alpha_zoo_context(limit_per_bucket=4),
    )
    _write_json(
        root_path / SWARM_REQUEST_REL,
        build_swarm_proposal_request(mode=mode, data_dir=data_dir, max_symbols=max_symbols),
    )
    return {
        "root": str(research_dir),
        "program": str(root_path / PROGRAM_REL),
        "mutable_params": str(root_path / MUTABLE_PARAMS_REL),
        "best_params": str(root_path / BEST_PARAMS_REL),
        "results_tsv": str(root_path / RESULTS_TSV_REL),
        "alpha_zoo_context": str(root_path / ALPHA_CONTEXT_REL),
        "swarm_proposal_request": str(root_path / SWARM_REQUEST_REL),
        "mutable_candidate_id": MUTABLE_CANDIDATE_ID,
    }


def load_mutable_v47_params(root: str | Path) -> dict[str, Any]:
    """Load and validate the current mutable v47 parameter candidate."""
    path = Path(root) / MUTABLE_PARAMS_REL
    payload = json.loads(path.read_text(encoding="utf-8"))
    params = payload.get("params", payload)
    if not isinstance(params, dict):
        raise ValueError(f"{MUTABLE_PARAMS_REL} must contain a JSON object or a params object")
    return validate_v47_params(params)


def mutable_candidate_definition(root: str | Path) -> dict[str, Any]:
    """Return the single Karpathy-style candidate for the current workspace."""
    return {
        "id": MUTABLE_CANDIDATE_ID,
        "role": "candidate",
        "params": load_mutable_v47_params(root),
        "rationale": "Mutable v47 parameter candidate from autoresearch/mutable/v47_params.json.",
    }


def write_results_tsv(root: str | Path, records: list[dict[str, Any]]) -> str:
    """Write the compact Karpathy-style ledger from evaluator records."""
    lines = ["\t".join(RESULTS_COLUMNS)]
    for idx, record in enumerate(records, start=1):
        diagnostics = record.get("diagnostics") or {}
        failed = ",".join(record.get("reasons") or [])
        lines.append(
            "\t".join(
                [
                    str(idx),
                    _tsv(record.get("candidate_id", "")),
                    _tsv(record.get("verdict", "")),
                    _tsv(record.get("score", "")),
                    _tsv(diagnostics.get("return_delta", "")),
                    _tsv(_avg_candidate_win_rate(record)),
                    _tsv(diagnostics.get("average_max_drawdown_delta", "")),
                    _tsv(diagnostics.get("trade_retention", "")),
                    _tsv(diagnostics.get("candidate_trades", "")),
                    _tsv(failed),
                    _tsv(record.get("rationale", "")),
                ]
            )
        )
    path = Path(root) / RESULTS_TSV_REL
    _write_text(path, "\n".join(lines) + "\n")
    return str(path)


def write_latest_state(root: str | Path, summary: dict[str, Any]) -> str:
    """Write a compact state snapshot for the next coding-agent iteration."""
    rows = summary.get("rows") or []
    payload = {
        "mode": summary.get("mode"),
        "baseline_id": summary.get("baseline_id", BASELINE_ID),
        "best_candidate": summary.get("best_candidate"),
        "iterations": summary.get("iterations", []),
        "row_count": len(rows),
        "candidate_count": len({row.get("candidate_id") for row in rows if isinstance(row, dict)}),
        "strategy_family": STRATEGY_FAMILY,
        "next_allowed_mutation": MUTABLE_PARAMS_REL,
    }
    path = Path(root) / LATEST_STATE_REL
    _write_json(path, payload)
    return str(path)


def build_swarm_proposal_request(
    *,
    mode: str,
    data_dir: str | Path | None,
    max_symbols: int | None,
) -> dict[str, Any]:
    """Structured prompt payload for a read-only swarm proposal step."""
    return {
        "status": "proposal_request",
        "mode": mode,
        "data_dir": str(data_dir) if data_dir is not None else None,
        "max_symbols": max_symbols,
        "roles": SWARM_ROLES,
        "inputs": [
            PROGRAM_REL,
            RESULTS_TSV_REL,
            LATEST_STATE_REL,
            ALPHA_CONTEXT_REL,
            MUTABLE_PARAMS_REL,
        ],
        "required_output": {
            "proposal_id": "short stable id",
            "hypothesis": "one falsifiable hypothesis",
            "mutation_surface": MUTABLE_PARAMS_REL,
            "param_changes": {"parameter_name": "new value"},
            "alpha_zoo_references": ["optional alpha ids used as idea support"],
            "overfit_objections": ["specific risks"],
            "expected_evaluator_effect": "return/win-rate/drawdown/trade-count expectation",
        },
        "hard_limits": [
            "read-only analysis only",
            "do not edit evaluator, protocol, data windows, or backtest engine",
            "do not decide KEEP or DISCARD",
            "emit one proposal only",
        ],
    }


def build_alpha_zoo_context(*, limit_per_bucket: int = 4) -> dict[str, Any]:
    """Return small, metadata-only Alpha Zoo context for proposal generation."""
    try:
        from src.factors.registry import Registry

        registry = Registry()
        health = registry.health()
        buckets: dict[str, list[dict[str, Any]]] = {}
        for zoo in ("qlib158", "alpha101", "gtja191", "academic"):
            for theme in ("momentum", "reversal", "volume", "volatility", "liquidity", "microstructure"):
                ids = registry.list(zoo=zoo, theme=theme, universe="equity_cn")
                if not ids:
                    continue
                bucket_key = f"{zoo}:{theme}"
                buckets[bucket_key] = [_alpha_meta(registry, alpha_id) for alpha_id in ids[:limit_per_bucket]]
        return {
            "status": "ok",
            "policy": "metadata only; use as proposal context, not as evaluator or automatic search space",
            "health": health,
            "buckets": buckets,
        }
    except Exception as exc:  # noqa: BLE001 - context generation must not block evaluator runs
        return {
            "status": "unavailable",
            "policy": "Alpha Zoo context failed open; evaluator remains fixed",
            "error": str(exc),
            "buckets": {},
        }


def validate_v47_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate a mutable candidate against the v47 parameter surface."""
    unknown = sorted(set(params) - set(DEFAULT_V47_PARAMS))
    if unknown:
        raise ValueError(f"unknown v47 params: {', '.join(unknown)}")

    validated = dict(DEFAULT_V47_PARAMS)
    for key, value in params.items():
        default = DEFAULT_V47_PARAMS[key]
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be bool")
        elif value is None:
            pass
        elif isinstance(default, int) and not isinstance(default, bool):
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{key} must be int or null")
        elif isinstance(default, float) or default is None:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"{key} must be numeric or null")
        else:
            raise ValueError(f"{key} has unsupported default type {type(default).__name__}")

        if value is not None and key in PARAM_BOUNDS:
            low, high = PARAM_BOUNDS[key]
            numeric = float(value)
            if low is not None and numeric < low:
                raise ValueError(f"{key}={value!r} below lower bound {low}")
            if high is not None and numeric > high:
                raise ValueError(f"{key}={value!r} above upper bound {high}")
        validated[key] = value
    return validated


def _params_payload(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "strategy_family": STRATEGY_FAMILY,
        "candidate_id": MUTABLE_CANDIDATE_ID,
        "params": params,
    }


def _alpha_meta(registry: Any, alpha_id: str) -> dict[str, Any]:
    alpha = registry.get(alpha_id)
    meta = alpha.meta or {}
    return {
        "id": alpha.id,
        "zoo": alpha.zoo,
        "nickname": meta.get("nickname"),
        "theme": meta.get("theme", []),
        "formula_latex": meta.get("formula_latex", ""),
        "columns_required": meta.get("columns_required", []),
        "decay_horizon": meta.get("decay_horizon"),
        "min_warmup_bars": meta.get("min_warmup_bars"),
        "notes": meta.get("notes", ""),
    }


def _avg_candidate_win_rate(record: dict[str, Any]) -> str:
    rows = record.get("rows")
    if not isinstance(rows, list):
        return ""
    win_rates = [float(row["win_rate"]) for row in rows if isinstance(row, dict) and "win_rate" in row]
    if not win_rates:
        return ""
    return f"{sum(win_rates) / len(win_rates):.6f}"


def _tsv(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\t", " ").replace("\n", " ").replace("\r", " ")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_json_if_missing(path: Path, payload: Any) -> None:
    if path.exists():
        return
    _write_json(path, payload)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_text_if_missing(path: Path, text: str) -> None:
    if path.exists():
        return
    _write_text(path, text)
