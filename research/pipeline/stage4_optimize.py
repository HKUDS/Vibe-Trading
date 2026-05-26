"""
research/pipeline/stage4_optimize.py
──────────────────────────────────────
Stage-4 runner: Optimization (deterministic grid sweep).

For each strategy that has diagnosis.json:
  1. Gate on diagnosis.json + strategy YAML + base run.
  2. Expand YAML ``parameter_search_ranges`` into discrete value lists.
  3. Sample N combos (seeded random, deterministic).
  4. For each combo: apply overrides to the spec, recompile signal_engine,
     scaffold ``runs/<strategy_id>_sweep_NNN/``, invoke backtest runner,
     parse metrics.csv.
  5. Rank combos by sharpe (with trade_count gate).
  6. Write ``research/manifests/<strategy_id>/optimization.json``
     (OptimizationBlock).

No LLM swarm — the swarm-driven variant in v1 returned empty swept_params
because the LLM cannot deterministically execute a parameter grid.

Usage
-----
    python -m research.pipeline.stage4_optimize
    python -m research.pipeline.stage4_optimize --max 30 --seed 7
    python -m research.pipeline.stage4_optimize --strategy eth_s1_multi_factor_consensus
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_FILE = Path(__file__).resolve()
_PIPELINE_DIR = _THIS_FILE.parent
_RESEARCH_DIR = _PIPELINE_DIR.parent

for _p in (_RESEARCH_DIR,):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

import argparse
import csv
import dataclasses
import json
import random
import re
import subprocess
import shutil
from itertools import product

import yaml as _yaml

from pipeline.config import _REPO_ROOT, ResearchConfig, load_config
from pipeline.strategy_runs import StrategyRunsEntry, StrategyRunsMap, load_strategy_runs
from pipeline.stage3_backtest import build_run_config, symbol_to_short

_DASHBOARD_SCHEMAS = _REPO_ROOT / "dashboard" / "server"
if str(_DASHBOARD_SCHEMAS) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_SCHEMAS))

from schemas import OptimizationBlock, StrategySpec  # noqa: E402

from lib.signal_compiler import compile_strategy  # noqa: E402


OPTIMIZATION_METHOD = "deterministic grid sweep (stage 4)"
DEFAULT_MAX_COMBOS = 60
DEFAULT_SEED = 42
MIN_TRADE_COUNT_GATE = 10
BACKTEST_TIMEOUT_S = 600


# ─── Data containers ──────────────────────────────────────────────────────────


@dataclasses.dataclass
class OptimizationCheckResult:
    strategy_id: str
    ok: bool
    error: str | None = None


@dataclasses.dataclass
class ComboResult:
    idx: int
    overrides: dict
    run_name: str
    metrics: dict | None
    error: str | None = None

    @property
    def sharpe(self) -> float:
        if not self.metrics:
            return float("-inf")
        try:
            return float(self.metrics.get("sharpe", "-inf"))
        except (TypeError, ValueError):
            return float("-inf")

    @property
    def trade_count(self) -> int:
        if not self.metrics:
            return 0
        try:
            return int(float(self.metrics.get("trade_count", 0)))
        except (TypeError, ValueError):
            return 0


# ─── Parameter grid helpers (pure) ────────────────────────────────────────────


def expand_param_ranges(psr: dict) -> dict[str, list]:
    """Expand [lo, hi, step] tuples into discrete value lists.

    Lists already discrete are passed through. Non-numeric or malformed
    entries are skipped silently.
    """
    out: dict[str, list] = {}
    for key, spec in psr.items():
        if not isinstance(spec, (list, tuple)) or len(spec) not in (1, 3):
            continue
        if len(spec) == 1:
            out[key] = [spec[0]]
            continue
        lo, hi, step = spec
        try:
            lo_f, hi_f, step_f = float(lo), float(hi), float(step)
        except (TypeError, ValueError):
            continue
        if step_f <= 0 or hi_f < lo_f:
            continue
        # Preserve int-ness if all three are integers
        is_int = all(float(x).is_integer() for x in (lo, hi, step))
        vals: list = []
        v = lo_f
        while v <= hi_f + 1e-9:
            vals.append(int(round(v)) if is_int else round(v, 6))
            v += step_f
        if vals:
            out[key] = vals
    return out


def sample_combos(expanded: dict[str, list], max_n: int, seed: int) -> list[dict]:
    """Cartesian product, then random-sample (seeded) down to max_n combos.

    If the full grid is smaller than max_n, returns the full grid in shuffled
    order. The first combo is always the centroid (median of each dim) for
    a sensible default-vs-tuned baseline.
    """
    if not expanded:
        return []
    keys = sorted(expanded.keys())
    all_combos = [dict(zip(keys, vals)) for vals in product(*[expanded[k] for k in keys])]
    if not all_combos:
        return []

    rng = random.Random(seed)
    rng.shuffle(all_combos)

    # Prepend centroid combo (median per dim) if not already at front
    centroid = {k: expanded[k][len(expanded[k]) // 2] for k in keys}
    if all_combos[0] != centroid:
        all_combos = [centroid] + [c for c in all_combos if c != centroid]

    return all_combos[: max_n]


# ─── Spec override helpers (pure, regex-driven) ───────────────────────────────


_PERCENTILE_COND_RE = re.compile(
    r"^([a-z][a-z0-9_]*)_percentile_(\d+)d\s+(<=|>=|<|>|==)\s+(-?\d+(?:\.\d+)?)"
    r"(?:\s+persist\s+(\d+)/(\d+))?\s*$"
)
_INVALIDATION_EXPR_RE = re.compile(
    r"^([a-z][a-z0-9_]*)_percentile_(\d+)d between (\d+(?:\.\d+)?),(\d+(?:\.\d+)?)$"
)


def _rewrite_percentile_condition(
    cond: str,
    new_value: float | None = None,
    new_lookback: int | None = None,
    new_persist_m: int | None = None,
    new_persist_n: int | None = None,
) -> str:
    """Apply field-wise overrides to a single percentile DSL condition.

    Untouched fields keep their original values. Raises ValueError if the
    condition does not match the percentile DSL.
    """
    m = _PERCENTILE_COND_RE.match(cond.strip())
    if not m:
        raise ValueError(f"Not a percentile DSL condition: {cond!r}")
    indicator, lookback, op, value, pm, pn = m.groups()
    lookback_out = new_lookback if new_lookback is not None else int(lookback)
    value_out = new_value if new_value is not None else float(value)
    persist_m_out = new_persist_m if new_persist_m is not None else (int(pm) if pm else None)
    persist_n_out = new_persist_n if new_persist_n is not None else (int(pn) if pn else None)

    # Format value: keep integer-looking values without trailing .0
    if float(value_out).is_integer():
        value_str = str(int(value_out))
    else:
        value_str = str(value_out)

    out = f"{indicator}_percentile_{lookback_out}d {op} {value_str}"
    if persist_m_out is not None and persist_n_out is not None:
        out += f" persist {persist_m_out}/{persist_n_out}"
    return out


def _rewrite_invalidation_lookback(expr: str, new_lookback: int) -> str:
    m = _INVALIDATION_EXPR_RE.match(expr.strip())
    if not m:
        raise ValueError(f"Not an invalidation expression: {expr!r}")
    indicator, _lookback, lo, hi = m.groups()
    return f"{indicator}_percentile_{new_lookback}d between {lo},{hi}"


def apply_overrides_to_spec(base_spec: dict, overrides: dict) -> dict:
    """Return a deep-ish copy of base_spec with sweep overrides applied.

    Override keys handled (subset of yaml parameter_search_ranges):
      - lookback_days       → rewrite all percentile_<n>d in entry/exit DSL
      - entry_low_pct       → entry_long condition value
      - entry_high_pct      → entry_short condition value
      - persistence_last_n  → persist X/N denominator (entry conditions)
      - persistence_min_hits→ persist M/X numerator (entry conditions)
      - hold_max_hours      → exit_rules[time_based].max_hold_hours
      - tp_pct              → exit_rules[take_profit_pct].value
      - sl_pct              → exit_rules[stop_loss_pct].value

    Unknown keys are ignored.
    """
    spec = json.loads(json.dumps(base_spec))  # cheap deep copy via json

    lookback = overrides.get("lookback_days")
    entry_low = overrides.get("entry_low_pct")
    entry_high = overrides.get("entry_high_pct")
    persist_n = overrides.get("persistence_last_n")
    persist_m = overrides.get("persistence_min_hits")

    def _rewrite_entry_block(block: dict | None, new_value: float | None) -> None:
        if not block or "conditions" not in block:
            return
        new_conds: list[str] = []
        for c in block["conditions"]:
            new_conds.append(
                _rewrite_percentile_condition(
                    c,
                    new_value=new_value,
                    new_lookback=lookback,
                    new_persist_m=persist_m,
                    new_persist_n=persist_n,
                )
            )
        block["conditions"] = new_conds

    _rewrite_entry_block(spec.get("entry_long"), float(entry_low) if entry_low is not None else None)
    _rewrite_entry_block(spec.get("entry_short"), float(entry_high) if entry_high is not None else None)

    # Exit rules
    hold = overrides.get("hold_max_hours")
    tp = overrides.get("tp_pct")
    sl = overrides.get("sl_pct")
    for rule in spec.get("exit_rules", []):
        cond = rule.get("condition")
        if cond == "time_based" and hold is not None:
            rule["max_hold_hours"] = int(hold)
        elif cond == "take_profit_pct" and tp is not None:
            rule["value"] = float(tp)
        elif cond == "stop_loss_pct" and sl is not None:
            rule["value"] = float(sl)
        elif cond == "signal_invalidation" and lookback is not None:
            rule["expression"] = _rewrite_invalidation_lookback(rule["expression"], int(lookback))

    return spec


# ─── Per-combo execution ──────────────────────────────────────────────────────


def _compile_signal_code(spec_dict: dict) -> str:
    """Validate spec dict against StrategySpec and compile to signal_engine source."""
    spec_model = StrategySpec.model_validate(spec_dict)
    return compile_strategy(spec_model)


def _scaffold_combo_run(
    run_dir: Path,
    base_config: dict,
    signal_code: str,
) -> None:
    """Create runs/<combo>/ with config.json + code/signal_engine.py."""
    code_dir = run_dir / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.json").write_text(
        json.dumps(base_config, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (code_dir / "signal_engine.py").write_text(signal_code, encoding="utf-8")


def _invoke_backtest(run_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "backtest.runner", str(run_dir)],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=BACKTEST_TIMEOUT_S,
    )


def _read_metrics(run_dir: Path) -> dict | None:
    path = run_dir / "artifacts" / "metrics.csv"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return rows[0] if rows else None


def _run_one_combo(
    idx: int,
    overrides: dict,
    base_spec: dict,
    base_config: dict,
    strategy_id: str,
    runs_root: Path,
) -> ComboResult:
    run_name = f"{strategy_id}_sweep_{idx:03d}"
    run_dir = runs_root / run_name

    try:
        spec_dict = apply_overrides_to_spec(base_spec, overrides)
        signal_code = _compile_signal_code(spec_dict)
    except Exception as exc:  # noqa: BLE001
        return ComboResult(idx=idx, overrides=overrides, run_name=run_name, metrics=None,
                           error=f"compile failed: {exc}")

    _scaffold_combo_run(run_dir, base_config, signal_code)

    try:
        proc = _invoke_backtest(run_dir)
    except subprocess.TimeoutExpired:
        return ComboResult(idx=idx, overrides=overrides, run_name=run_name, metrics=None,
                           error="backtest timeout")
    if proc.returncode != 0:
        return ComboResult(idx=idx, overrides=overrides, run_name=run_name, metrics=None,
                           error=f"backtest exit {proc.returncode}: {(proc.stderr or '')[:200]}")

    metrics = _read_metrics(run_dir)
    if metrics is None:
        return ComboResult(idx=idx, overrides=overrides, run_name=run_name, metrics=None,
                           error="no metrics.csv produced")
    return ComboResult(idx=idx, overrides=overrides, run_name=run_name, metrics=metrics)


# ─── Ranking / output ─────────────────────────────────────────────────────────


def rank_combos(combos: list[ComboResult], min_trades: int = MIN_TRADE_COUNT_GATE) -> list[ComboResult]:
    """Return combos sorted best→worst.

    Primary filter: trade_count >= min_trades. Among gated combos, sort by
    sharpe desc. If zero combos pass the gate, fall back to all combos
    ranked by sharpe desc (caller sees that the best has trade_count < gate).
    """
    valid = [c for c in combos if c.metrics is not None]
    gated = [c for c in valid if c.trade_count >= min_trades]
    pool = gated if gated else valid
    return sorted(pool, key=lambda c: c.sharpe, reverse=True)


def _summarise(combos: list[ComboResult], ranked: list[ComboResult], top_n: int = 5) -> str:
    n_total = len(combos)
    n_with_metrics = sum(1 for c in combos if c.metrics is not None)
    n_errors = n_total - n_with_metrics
    n_gated = sum(1 for c in ranked if c.trade_count >= MIN_TRADE_COUNT_GATE)

    lines = [
        f"# Stage 4 grid sweep summary",
        f"",
        f"- combos attempted: {n_total}",
        f"- combos with metrics: {n_with_metrics}",
        f"- combos with errors: {n_errors}",
        f"- combos passing trade_count >= {MIN_TRADE_COUNT_GATE}: {n_gated}",
        f"",
        f"## Top {min(top_n, len(ranked))} (by sharpe)",
        f"",
    ]
    for c in ranked[:top_n]:
        lines.append(
            f"- {c.run_name}: sharpe={c.sharpe:.3f}, trade_count={c.trade_count}, "
            f"overrides={c.overrides}"
        )
    return "\n".join(lines)


def build_optimization_block(
    swept_params: list[str],
    best: ComboResult | None,
    summary: str,
) -> dict:
    best_params: dict[str, float] = {}
    if best is not None:
        for k, v in best.overrides.items():
            try:
                best_params[k] = float(v)
            except (TypeError, ValueError):
                continue
    return {
        "source_run": best.run_name if best is not None else None,
        "method": OPTIMIZATION_METHOD,
        "swept_params": sorted(swept_params),
        "best_params": best_params,
        "improvement_summary": summary[:2000] if summary else None,
    }


def verify_optimization(optimization_path: Path) -> OptimizationCheckResult:
    strategy_id = optimization_path.parent.name
    if not optimization_path.exists():
        return OptimizationCheckResult(strategy_id=strategy_id, ok=False,
                                       error=f"optimization.json missing: {optimization_path}")
    try:
        data = json.loads(optimization_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return OptimizationCheckResult(strategy_id=strategy_id, ok=False,
                                       error=f"optimization.json invalid JSON: {exc}")
    try:
        OptimizationBlock.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        return OptimizationCheckResult(strategy_id=strategy_id, ok=False,
                                       error=f"schema validation failed: {exc}")
    return OptimizationCheckResult(strategy_id=strategy_id, ok=True)


def compute_exit_code(results: list[OptimizationCheckResult]) -> int:
    if not results:
        return 1
    return 0 if all(r.ok for r in results) else 1


def print_summary(results: list[OptimizationCheckResult]) -> None:
    print("\n" + "=" * 60)
    print("Stage-4 Optimization summary")
    print("=" * 60)
    for r in results:
        status = "OK" if r.ok else "FAIL"
        msg = "optimization.json present and valid" if r.ok else f"FAILED — {r.error}"
        print(f"  [{status}] {r.strategy_id}: {msg}")
    total = len(results)
    passed = sum(1 for r in results if r.ok)
    print(f"\n{passed}/{total} strategies optimized.")
    print("Stage 4 " + ("PASSED" if total and passed == total else "FAILED"))
    print("=" * 60)


# ─── Orchestration ────────────────────────────────────────────────────────────


def _optimize_strategy(
    strategy_id: str,
    entry: StrategyRunsEntry,
    cfg: ResearchConfig,
    runs_root: Path,
    strategies_dir: Path,
    manifests_dir: Path,
    max_combos: int,
    seed: int,
) -> OptimizationCheckResult:
    print(f"\n{'='*60}\n[stage4] Strategy: {strategy_id}\n{'='*60}")

    diagnosis_path = manifests_dir / strategy_id / "diagnosis.json"
    if not diagnosis_path.exists():
        msg = f"diagnosis.json not found at {diagnosis_path} — run stage 3 first"
        print(f"  [SKIP] {msg}")
        return OptimizationCheckResult(strategy_id=strategy_id, ok=False, error=msg)

    yaml_path = strategies_dir / f"strategy_{strategy_id}.yaml"
    if not yaml_path.exists():
        msg = f"strategy YAML missing: {yaml_path}"
        print(f"  [SKIP] {msg}")
        return OptimizationCheckResult(strategy_id=strategy_id, ok=False, error=msg)

    base_spec = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    psr = base_spec.get("parameter_search_ranges", {})
    expanded = expand_param_ranges(psr)
    if not expanded:
        msg = "no parameter_search_ranges to sweep"
        print(f"  [SKIP] {msg}")
        return OptimizationCheckResult(strategy_id=strategy_id, ok=False, error=msg)

    combos = sample_combos(expanded, max_n=max_combos, seed=seed)
    print(f"  Param dims: {list(expanded.keys())}")
    print(f"  Total grid: {sum(1 for _ in product(*[expanded[k] for k in expanded])):,}  "
          f"sampling: {len(combos)}  seed={seed}")

    base_config = build_run_config(symbol=entry.symbol, cfg=cfg)
    # If a regime/oos override is desired in future, route through here.

    results: list[ComboResult] = []
    for i, overrides in enumerate(combos):
        res = _run_one_combo(
            idx=i, overrides=overrides, base_spec=base_spec, base_config=base_config,
            strategy_id=strategy_id, runs_root=runs_root,
        )
        results.append(res)
        if res.error:
            print(f"  [combo {i:03d}] ERROR — {res.error}  overrides={overrides}")
        else:
            print(f"  [combo {i:03d}] sharpe={res.sharpe:+.3f}  trades={res.trade_count}  "
                  f"overrides={overrides}")

    ranked = rank_combos(results)
    best = ranked[0] if ranked else None
    summary = _summarise(results, ranked)
    print(f"\n{summary}\n")

    block = build_optimization_block(
        swept_params=list(expanded.keys()),
        best=best,
        summary=summary,
    )
    out_dir = manifests_dir / strategy_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "optimization.json"
    out_path.write_text(json.dumps(block, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [OK] wrote {out_path}")

    return verify_optimization(out_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", default=None, help="optimize only this strategy_id")
    parser.add_argument("--max", type=int, default=DEFAULT_MAX_COMBOS,
                        help=f"max combos per strategy (default {DEFAULT_MAX_COMBOS})")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help=f"RNG seed for combo sampling (default {DEFAULT_SEED})")
    args = parser.parse_args()

    cfg = load_config()
    runs_map = load_strategy_runs()

    runs_root = _REPO_ROOT / "runs"
    strategies_dir = _REPO_ROOT / "research" / "strategies"
    manifests_dir = _REPO_ROOT / "research" / "manifests"

    print("=" * 60)
    print(f"Stage 4 — Deterministic Grid Sweep")
    print("=" * 60)
    print(f"max_combos={args.max}  seed={args.seed}")

    targets = (
        [(args.strategy, runs_map.entries[args.strategy])]
        if args.strategy and args.strategy in runs_map.entries
        else list(runs_map.entries.items())
    )

    if not targets:
        print(f"[stage4] no matching strategies (--strategy={args.strategy!r}).")
        sys.exit(1)

    results: list[OptimizationCheckResult] = []
    for strategy_id, entry in targets:
        try:
            result = _optimize_strategy(
                strategy_id=strategy_id, entry=entry, cfg=cfg,
                runs_root=runs_root, strategies_dir=strategies_dir,
                manifests_dir=manifests_dir,
                max_combos=args.max, seed=args.seed,
            )
        except Exception as exc:  # noqa: BLE001
            result = OptimizationCheckResult(strategy_id=strategy_id, ok=False,
                                             error=f"unexpected error: {exc}")
            print(f"  [ERROR] {strategy_id}: {exc}")
        results.append(result)

    print_summary(results)
    sys.exit(compute_exit_code(results))


if __name__ == "__main__":
    main()
