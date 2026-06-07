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
MUTABLE_PARAMS_REL = "mutable/v47_params.json"
BEST_PARAMS_REL = "best/v47_params.json"
PROGRAM_REL = "program.md"
RESULTS_TSV_REL = "results.tsv"
RESULTS_TEMPLATE_REL = "results.template.tsv"
EVALUATOR_CONTRACT_REL = "evaluator_contract.md"
ALPHA_CONTEXT_REL = "context/alpha_zoo_context.json"
SWARM_REQUEST_REL = "proposals/swarm_proposal_request.json"
LATEST_STATE_REL = "latest_state.json"
LATEST_STATE_TEMPLATE_REL = "latest_state.template.json"
LOOP_CONFIG_REL = "loop_config.json"
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
    "candidate_weighted_win_rate",
    "candidate_mean_annual_return_pct",
    "fixed_loss_window_ratio",
    "bear_return_delta",
    "bear_loss_window_ratio",
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
        "purpose": "Map each idea onto the current v47 parameter, indicator-composition, or regime-sizing surface before requesting any expansion.",
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

# Advisory reviewers — invoked ONLY when search-space expansion is triggered
# (current best strategy's parameter tuning enters plateau, default 50 consecutive
# no-KEEP iterations). Both reviewers must return `recommend` for the expansion
# to enter the mutable surface. Neither may compute or override KEEP/DISCARD.
#
# system_prompt paths are loaded from
# `agent/src/swarm/presets/factor_research_committee.yaml` on demand via
# `inspect_preset("factor_research_committee")`. See
# `autoresearch/program.md#search-space-expansion-review`.
ADVISORY_REVIEWERS: dict[str, dict[str, str]] = {
    "factor_validator": {
        "preset": "factor_research_committee",
        "agent_id": "factor_validator",
        "purpose": "IC/ICIR/五分位/robustness 复核 — Output: Effectiveness Rating (Effective/Marginal/Ineffective).",
        "trigger": "plateau_then_expansion",
    },
    "backtest_reviewer": {
        "preset": "factor_research_committee",
        "agent_id": "backtest_reviewer",
        "purpose": "overfit/look-ahead/survivorship/transaction cost/stress test 复核 — Output: Live Deployment Recommendation.",
        "trigger": "plateau_then_expansion",
    },
}

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
    "alpha_qlib_roc10_min": (-1.0, 10.0),
    "alpha_qlib_roc10_max": (-1.0, 10.0),
    "alpha_qlib_rsv10_min": (0.0, 1.0),
    "alpha_qlib_rsv10_max": (0.0, 1.0),
    "entry_day_gain_max_pct": (-10.0, 15.0),
    "regime_entry_day_gain_max_pct_bear": (-10.0, 15.0),
    "alpha_qlib_roc10_score_weight": (0.0, 1.0),
    "alpha_qlib_mom20_score_weight": (0.0, 1.0),
    "alpha_qlib_cntd5_score_weight": (0.0, 1.0),
    "alpha_qlib_cntd10_score_weight": (0.0, 1.0),
    "alpha_qlib_cntd20_score_weight": (0.0, 1.0),
    "alpha_qlib_vma10_score_weight": (0.0, 1.0),
    "alpha_qlib_rsv10_score_weight": (0.0, 1.0),
    "alpha_qlib_std10_score_weight": (0.0, 1.0),
    "alpha_qlib_kup_score_weight": (0.0, 1.0),
    "alpha_qlib_cord10_score_weight": (0.0, 1.0),
    "alpha_qlib_max_positions": (4, 16),
    "bull_continuation_roc10_min": (-1.0, 10.0),
    "bull_continuation_roc10_max": (-1.0, 10.0),
    "bull_continuation_mom20_min": (-1.0, 10.0),
    "bull_continuation_rsv10_min": (0.0, 1.0),
    "bull_continuation_rsv10_max": (0.0, 1.0),
    "bull_continuation_entry_gain_max_pct": (-10.0, 15.0),
    "bull_continuation_volume_ratio_min": (0.0, 10.0),
    "bull_continuation_market_min_coverage": (0, 5000),
    "bull_continuation_below_ma_ratio_max": (0.0, 1.0),
    "bull_continuation_down_ratio_max": (0.0, 1.0),
    "bull_continuation_max_hold_days": (0, 60),
    "bull_position_weight": (0.0, 30.0),
    "bear_position_weight": (0.0, 30.0),
}

PROGRAM_MD_FALLBACK = """# ztrade Karpathy-Style Autoresearch Program

This fallback exists only for isolated tests or packaged executions where the
repo-level autoresearch/program.md file is unavailable. In a normal checkout,
initialize_karpathy_workspace copies autoresearch/program.md as the single
agent-facing loop contract.
"""

EVALUATOR_CONTRACT_MD = """# ztrade Autoresearch Evaluator Contract

This file is the agent-readable contract for the fixed judge. The executable
source of truth remains the Python code listed below.

## Authoritative Code

- Protocol, windows, baseline, and gates:
  `agent/src/ztrade_autoresearch/protocol.py`
- KEEP/DISCARD decision logic:
  `agent/src/ztrade_autoresearch/evaluator.py`
- Backtest execution and artifact writing:
  `agent/src/ztrade_autoresearch/runner.py`

(There is no `agent/src/tools/ztrade_autoresearch_tool.py` wrapper in the
current checkout. The loop calls the evaluator directly via
`python -m src.ztrade_autoresearch.runner run_ztrade_csv_research`.)

## Current Judge

The evaluator compares one candidate against `ztrade_v47_baseline` on paired
windows. It computes return delta, drawdown delta, loss-window count, trade
retention, positive-return concentration, and minimum trade count. A candidate
is KEEP only if every gate passes.

CSV evaluation windows are the frozen bull/bear windows generated in
`agent/src/ztrade_autoresearch/protocol.py` from the user-defined bull intervals
between `2023-12-28` and `2026-05-27`; all non-bull dates in that span are bear
windows. Do not edit these windows during autoresearch.

Alternate scoring paths are forbidden. Do not compute your own KEEP/DISCARD
outside `agent/src/ztrade_autoresearch/evaluator.py`.

Advisory reviewers (`factor_validator` and `backtest_reviewer`, defined in
`agent/src/swarm/presets/factor_research_committee.yaml`) may not compute or
override verdicts; their outputs are proposal-time only and are loaded from
`autoresearch/proposals/advisory_verdicts/` when present.

## Required Mutable Input

The only editable candidate input for the active run is:

`autoresearch/mutable/v47_params.json`

It must contain strategy parameter keys declared by
`agent/src/ztrade_autoresearch/protocol.py`, including current v47 parameters,
candidate-only Alpha Zoo indicator controls, and regime-aware position sizing
controls. Bounds are enforced by `agent/src/ztrade_autoresearch/research_loop.py`.

## Required Proposal Input

Read this file before proposing the next experiment:

`autoresearch/proposals/swarm_proposal_request.json`

Swarm and Alpha Zoo can propose hypotheses. They cannot decide KEEP/DISCARD,
edit evaluator code, or expand the official mutable surface directly.

Search-space expansion proposals must include the verdicts of both
`factor_validator` and `backtest_reviewer` under
`autoresearch/proposals/advisory_verdicts/`. Both reviewers must return
`recommend` for the expansion to enter the mutable surface; if either returns
`improve` or `reject`, the proposal is archived and the loop returns to
current best strategy parameter tuning. See
`autoresearch/program.md#search-space-expansion-review` for the trigger
condition.

## Required Output

Each evaluator run writes normal run artifacts under `agent/runs/...` and
updates project-level runtime state:

- `autoresearch/results.tsv` is append-only experiment history.
- `autoresearch/latest_state.json` is refreshed to the latest evaluator state.
- `autoresearch/reports/iteration_<N>_<candidate_id>.md` records each
  iteration's swarm analysis, strategy diff, per-window historical returns,
  aggregate return, verdict diagnostics, and next-iteration plan.

Loop completion may be claimed only when a human asks to stop/pause/summarize,
or when the current candidate's evaluator diagnostics show both
`candidate_trade_weighted_win_rate > 0.50` and
`candidate_mean_annual_return_pct > 30.0`.

Leverage is forbidden for future mutable candidates. `allow_leverage` must stay
`false`; any leveraged result is archive-only evidence and cannot satisfy the
active stop contract.

Runbook-derived promotion/veto diagnostics are also part of the fixed judge:
paired-window coverage, fixed-window loss ratio, bear-window return delta,
bear-window loss ratio, bear-window drawdown delta, trade retention, and
improvement concentration. Incomplete `run_status.json` or stale reused
artifacts cannot support KEEP, stop-target, or promotion claims.

These files are runtime outputs and should not be committed. The tracked
templates are:

- `autoresearch/results.template.tsv`
- `autoresearch/latest_state.template.json`

Do not hand-edit evaluator results.
"""


def initialize_karpathy_workspace(
    workspace_root: str | Path | None = None,
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
    root_path = _workspace_root(workspace_root)
    research_dir = root_path
    for rel in ("mutable", "best", "context", "proposals", "archive"):
        (research_dir / rel).mkdir(parents=True, exist_ok=True)

    _write_text(root_path / PROGRAM_REL, _program_md())
    _write_text(root_path / EVALUATOR_CONTRACT_REL, EVALUATOR_CONTRACT_MD)
    _write_json_if_missing(root_path / MUTABLE_PARAMS_REL, _params_payload(DEFAULT_V47_PARAMS))
    _write_json_if_missing(root_path / BEST_PARAMS_REL, _params_payload(DEFAULT_V47_PARAMS))
    _write_text(root_path / RESULTS_TEMPLATE_REL, "\t".join(RESULTS_COLUMNS) + "\n")
    _write_text_if_missing(root_path / RESULTS_TSV_REL, "\t".join(RESULTS_COLUMNS) + "\n")
    _write_json(root_path / LOOP_CONFIG_REL, _default_loop_config())
    _write_json(
        root_path / ALPHA_CONTEXT_REL,
        build_alpha_zoo_context(limit_per_bucket=4),
    )
    _write_json(
        root_path / SWARM_REQUEST_REL,
        build_swarm_proposal_request(mode=mode, data_dir=data_dir, max_symbols=max_symbols),
    )
    initial_state = _initial_latest_state(mode)
    _write_json(root_path / LATEST_STATE_TEMPLATE_REL, initial_state)
    _write_json_if_missing(root_path / LATEST_STATE_REL, initial_state)
    return {
        "root": str(research_dir),
        "program": str(root_path / PROGRAM_REL),
        "mutable_params": str(root_path / MUTABLE_PARAMS_REL),
        "best_params": str(root_path / BEST_PARAMS_REL),
        "results_tsv": str(root_path / RESULTS_TSV_REL),
        "results_template": str(root_path / RESULTS_TEMPLATE_REL),
        "evaluator_contract": str(root_path / EVALUATOR_CONTRACT_REL),
        "alpha_zoo_context": str(root_path / ALPHA_CONTEXT_REL),
        "swarm_proposal_request": str(root_path / SWARM_REQUEST_REL),
        "latest_state": str(root_path / LATEST_STATE_REL),
        "latest_state_template": str(root_path / LATEST_STATE_TEMPLATE_REL),
        "loop_config": str(root_path / LOOP_CONFIG_REL),
        "mutable_candidate_id": MUTABLE_CANDIDATE_ID,
    }


def load_mutable_v47_params(root: str | Path) -> dict[str, Any]:
    """Load and validate the current mutable v47 parameter candidate."""
    path = _workspace_root(root) / MUTABLE_PARAMS_REL
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
    """Append evaluator records to the compact Karpathy-style ledger."""
    path = _workspace_root(root) / RESULTS_TSV_REL
    header = "\t".join(RESULTS_COLUMNS)
    existing = _existing_tsv_lines(path, header)
    next_iteration = len(existing)
    new_lines: list[str] = []
    for offset, record in enumerate(records, start=1):
        diagnostics = record.get("diagnostics") or {}
        failed = ",".join(record.get("reasons") or [])
        new_lines.append(
            "\t".join(
                [
                    str(next_iteration + offset),
                    _tsv(record.get("candidate_id", "")),
                    _tsv(record.get("verdict", "")),
                    _tsv(record.get("score", "")),
                    _tsv(diagnostics.get("return_delta", "")),
                    _tsv(_avg_candidate_win_rate(record)),
                    _tsv(diagnostics.get("average_max_drawdown_delta", "")),
                    _tsv(diagnostics.get("trade_retention", "")),
                    _tsv(diagnostics.get("candidate_trades", "")),
                    _tsv(diagnostics.get("candidate_trade_weighted_win_rate", "")),
                    _tsv(diagnostics.get("candidate_mean_annual_return_pct", "")),
                    _tsv(diagnostics.get("loss_window_ratio", "")),
                    _tsv(diagnostics.get("bear_return_delta", "")),
                    _tsv(diagnostics.get("bear_loss_window_ratio", "")),
                    _tsv(failed),
                    _tsv(record.get("rationale", "")),
                ]
            )
        )
    _write_text(path, "\n".join([header, *existing, *new_lines]) + "\n")
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
        "next_allowed_mutation": f"{AUTORESEARCH_DIRNAME}/{MUTABLE_PARAMS_REL}",
    }
    path = _workspace_root(root) / LATEST_STATE_REL
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
            f"{AUTORESEARCH_DIRNAME}/{PROGRAM_REL}",
            f"{AUTORESEARCH_DIRNAME}/{EVALUATOR_CONTRACT_REL}",
            f"{AUTORESEARCH_DIRNAME}/{RESULTS_TSV_REL}",
            f"{AUTORESEARCH_DIRNAME}/{RESULTS_TEMPLATE_REL}",
            f"{AUTORESEARCH_DIRNAME}/{LATEST_STATE_REL}",
            f"{AUTORESEARCH_DIRNAME}/{LATEST_STATE_TEMPLATE_REL}",
            f"{AUTORESEARCH_DIRNAME}/{ALPHA_CONTEXT_REL}",
            f"{AUTORESEARCH_DIRNAME}/{MUTABLE_PARAMS_REL}",
        ],
        "required_output": {
            "proposal_id": "short stable id",
            "hypothesis": "one falsifiable hypothesis",
            "mutation_surface": f"{AUTORESEARCH_DIRNAME}/{MUTABLE_PARAMS_REL}",
            "param_changes": {"parameter_name": "new value"},
            "alpha_zoo_references": ["optional alpha ids used as idea support"],
            "overfit_objections": ["specific risks"],
            "expected_evaluator_effect": "return/win-rate/drawdown/trade-count expectation",
            "advisory_review_required": False,
        },
        "advisory_reviewers": ADVISORY_REVIEWERS,
        "hard_limits": [
            "read-only analysis only",
            "do not edit evaluator, protocol, data windows, or backtest engine",
            "do not decide KEEP or DISCARD",
            f"do not edit {AUTORESEARCH_DIRNAME}/{MUTABLE_PARAMS_REL}; emit proposed changes only",
            "emit one proposal only",
            "factor_validator and backtest_reviewer are advisory only; no KEEP/DISCARD authority",
            "do not invoke advisory reviewers during routine current best strategy micro-tuning; only when plateau-then-expansion is triggered",
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
        if key == "allow_leverage" and value is True:
            raise ValueError("allow_leverage is disabled by the current autoresearch protocol")
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


def _initial_latest_state(mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "baseline_id": BASELINE_ID,
        "best_candidate": None,
        "iterations": [],
        "row_count": 0,
        "candidate_count": 0,
        "strategy_family": STRATEGY_FAMILY,
        "next_allowed_mutation": f"{AUTORESEARCH_DIRNAME}/{MUTABLE_PARAMS_REL}",
    }


def _program_md() -> str:
    program_path = default_karpathy_workspace_root() / PROGRAM_REL
    if program_path.exists():
        return program_path.read_text(encoding="utf-8")
    return PROGRAM_MD_FALLBACK


def _default_loop_config() -> dict[str, Any]:
    return {
        "context_memory": {
            "continuation_state_path": "autoresearch/context/continuation_state.md",
            "recent_report_count": 5,
            "require_pack_before_context_boundary": True,
        },
        "progress_report_every_iterations": 5,
        "search_space_expansion_plateau_threshold": 50,
        "stop_conditions": {
            "allow_human_stop_pause_or_summary": True,
            "candidate_mean_annual_return_pct_min": 30.0,
            "candidate_trade_weighted_win_rate_min": 0.5,
            "require_both_performance_thresholds": True,
        },
        "notes": [
            "Per-invocation evaluator count is defined by autoresearch/program.md",
            "Only human stop/pause/summary or both performance thresholds may stop the loop",
            "Tool, time, or context pressure must trigger context packaging and memory recovery, then continue",
            "Search-space expansion requires advisory review (factor_validator + backtest_reviewer both returning recommend); see program.md#search-space-expansion-review",
        ],
    }


def default_karpathy_workspace_root() -> Path:
    """Return the repo-level Karpathy-style autoresearch workspace path."""
    return Path(__file__).resolve().parents[3] / AUTORESEARCH_DIRNAME


def _workspace_root(root: str | Path | None) -> Path:
    if root is None:
        return default_karpathy_workspace_root()
    return Path(root)


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


def _existing_tsv_lines(path: Path, header: str) -> list[str]:
    if not path.exists():
        return []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return []
    if lines[0] != header:
        raise ValueError(f"{path} has an unexpected header")
    return lines[1:]


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
