"""Consolidate per-stage pipeline outputs into the dashboard's StrategyManifest.

The research pipeline writes *separate* per-stage files under
``research/manifests/<strategy_id>/`` (generation.json, diagnosis.json,
optimization.json) plus per-run ``runs/<run>/artifacts/metrics.csv``. The
dashboard backend (``dashboard/server/artifacts.py``) instead reads a single
unified ``research/manifests/<strategy_id>/manifest.json`` conforming to the
``StrategyManifest`` schema, so without a bridge the ``/api/strategies`` list
is empty.

This builder assembles that ``manifest.json`` from the per-stage outputs:

    spec          <- strategy_runs.json entry + spec_yaml
    generation    <- <id>/generation.json          (stage 2)
    backtest      <- runs/<base|oos|regime>/artifacts/metrics.csv  (stage 3)
    optimization  <- <id>/optimization.json         (stage 4)
    diagnosis     <- <id>/diagnosis.json            (stage 3-diag)

Usage (from repo root):

    python -m research.pipeline.build_dashboard_manifest
    python -m research.pipeline.build_dashboard_manifest --strategy btc_s2_stablecoin_trend
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Bootstrap research/ onto sys.path so ``pipeline.*`` imports resolve from any CWD.
_PIPELINE_DIR = Path(__file__).resolve().parent
_RESEARCH_DIR = _PIPELINE_DIR.parent
if str(_RESEARCH_DIR) not in sys.path:
    sys.path.insert(0, str(_RESEARCH_DIR))

from pipeline.config import _REPO_ROOT  # noqa: E402
from pipeline.strategy_runs import StrategyRunsEntry, load_strategy_runs  # noqa: E402
from pipeline.stage3_backtest import symbol_to_short  # noqa: E402

# Bootstrap dashboard/server onto sys.path for the StrategyManifest schema.
_DASHBOARD_SCHEMAS = _REPO_ROOT / "dashboard" / "server"
if str(_DASHBOARD_SCHEMAS) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_SCHEMAS))

from schemas import (  # noqa: E402
    BacktestBlock,
    BacktestMetrics,
    DiagnosisBlock,
    GenerationBlock,
    OptimizationBlock,
    RegimeMetrics,
    SpecBlock,
    StrategyManifest,
)

import csv  # noqa: E402


def _read_json(path: Path) -> dict | None:
    """Read a UTF-8 JSON file, returning None if missing/unreadable."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _read_metrics(run_dir: Path) -> dict | None:
    """Read the first row of runs/<run>/artifacts/metrics.csv as a dict."""
    path = run_dir / "artifacts" / "metrics.csv"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return rows[0] if rows else None


def _f(d: dict, key: str) -> float | None:
    """Parse a float metric, returning None on missing/blank/bad value."""
    v = d.get(key)
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _backtest_metrics(run_name: str | None, runs_root: Path) -> BacktestMetrics | None:
    """Build a BacktestMetrics from a run's metrics.csv, or None if absent."""
    if not run_name:
        return None
    m = _read_metrics(runs_root / run_name)
    if not m:
        return None
    dd = _f(m, "max_drawdown")
    trades = _f(m, "trade_count")
    # source_run is the repo-relative dir that directly contains the run's CSVs
    # (equity.csv / trades.csv / metrics.csv). The dashboard's equity/trades
    # endpoints resolve REPO_ROOT/<source_run>/<file>, and our backtest runner
    # writes them under runs/<name>/artifacts/, so point there (not the bare name).
    source_run = f"runs/{run_name}/artifacts"
    return BacktestMetrics(
        source_run=source_run,
        sharpe=_f(m, "sharpe"),
        # schema wants a positive fraction in [0, 1]; metrics.csv stores it negative.
        max_drawdown=min(abs(dd), 1.0) if dd is not None else None,
        trades=int(trades) if trades is not None else None,
        profit_factor=_f(m, "profit_factor"),
        total_return=_f(m, "total_return"),
        win_rate=_f(m, "win_rate"),
    )


def build_manifest(
    strategy_id: str, entry: StrategyRunsEntry, runs_root: Path, manifests_dir: Path
) -> dict | None:
    """Assemble a StrategyManifest dict for one strategy, or None if it has no data."""
    out_dir = manifests_dir / strategy_id
    short = symbol_to_short(entry.symbol)
    symbol = short.upper()

    # ── spec (always present post-stage-2) ────────────────────────────────────
    description = None
    spec_doc: dict = {}
    spec_path = _REPO_ROOT / entry.spec_yaml
    if spec_path.exists():
        try:
            import yaml  # local import; pyyaml is a pipeline dep

            spec_doc = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
            h = spec_doc.get("hypothesis")
            if isinstance(h, str):
                description = " ".join(h.split())[:300]
        except Exception:  # noqa: BLE001 — description is best-effort
            spec_doc = {}

    spec = SpecBlock(
        source_run=None,
        strategy_id=strategy_id,
        symbol=symbol,
        spec_yaml=entry.spec_yaml,
        description=description,
    )

    stage = 2  # spec implies stage 2 complete

    # ── generation (stage 2) ──────────────────────────────────────────────────
    # Prefer the swarm-written generation.json. If absent (e.g. a strategy that
    # was authored deterministically / by hand rather than by the stage-2 swarm),
    # synthesise an honest provenance block from the spec YAML so the dashboard
    # shows "generated" rather than a misleading "incomplete".
    generation = None
    gen_raw = _read_json(out_dir / "generation.json")
    if gen_raw:
        try:
            generation = GenerationBlock.model_validate(gen_raw)
        except Exception:  # noqa: BLE001
            generation = None
    if generation is None and spec_doc:
        archetype = spec_doc.get("archetype") or "unknown"
        factors_used = sorted((spec_doc.get("indicators") or {}).keys())
        generation = GenerationBlock(
            source_run=None,
            method=f"deterministic ({archetype}; not LLM swarm)",
            model=None,
            rationale=description,
            factors_used=factors_used,
        )

    # ── backtest (stage 3) ────────────────────────────────────────────────────
    backtest = None
    in_sample = _backtest_metrics(entry.base_run, runs_root)
    if in_sample is not None:
        oos = None
        for oos_run in entry.oos_runs:
            oos = _backtest_metrics(oos_run, runs_root)
            if oos is not None:
                break
        by_regime: list[RegimeMetrics] = []
        for label, run_name in entry.regime_runs.items():
            rm = _backtest_metrics(run_name, runs_root)
            if rm is not None:
                by_regime.append(
                    RegimeMetrics(
                        regime=label,
                        source_run=f"runs/{run_name}/artifacts",
                        sharpe=rm.sharpe,
                        max_drawdown=rm.max_drawdown,
                        total_return=rm.total_return,
                        trades=rm.trades,
                    )
                )
        backtest = BacktestBlock(in_sample=in_sample, oos=oos, by_regime=by_regime)
        stage = max(stage, 3)

    # ── diagnosis (stage 3-diag) ──────────────────────────────────────────────
    diagnosis = None
    diag_raw = _read_json(out_dir / "diagnosis.json")
    if diag_raw:
        try:
            diagnosis = DiagnosisBlock.model_validate(diag_raw)
            stage = max(stage, 3)
        except Exception:  # noqa: BLE001
            diagnosis = None

    # ── optimization (stage 4) ────────────────────────────────────────────────
    optimization = None
    opt_raw = _read_json(out_dir / "optimization.json")
    if opt_raw:
        try:
            optimization = OptimizationBlock.model_validate(opt_raw)
            stage = max(stage, 4)
        except Exception:  # noqa: BLE001
            optimization = None

    manifest = StrategyManifest(
        strategy_id=strategy_id,
        symbol=symbol,
        generated_at=datetime.now(timezone.utc),
        pipeline_stage=stage,
        spec=spec,
        generation=generation,
        backtest=backtest,
        optimization=optimization,
        diagnosis=diagnosis,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "manifest.json"
    out_path.write_text(
        manifest.model_dump_json(indent=2, exclude_none=False), encoding="utf-8"
    )
    return {"strategy_id": strategy_id, "stage": stage, "path": str(out_path)}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build dashboard StrategyManifest (manifest.json) from per-stage outputs."
    )
    parser.add_argument("--strategy", default=None, help="only build this strategy_id")
    args = parser.parse_args()

    runs_root = _REPO_ROOT / "runs"
    manifests_dir = _REPO_ROOT / "research" / "manifests"
    runs_map = load_strategy_runs()

    targets = (
        [(args.strategy, runs_map.entries[args.strategy])]
        if args.strategy and args.strategy in runs_map.entries
        else list(runs_map.entries.items())
    )
    if not targets:
        print(f"[manifest] no matching strategies (--strategy={args.strategy!r}).")
        sys.exit(1)

    print("=" * 60)
    print("Build Dashboard Manifest — consolidate per-stage outputs")
    print("=" * 60)
    built = 0
    for strategy_id, entry in targets:
        # Skip entries with no base_run: these are not deployable strategies but
        # validation harnesses (e.g. a walk-forward test that only carries
        # held-out oos_runs). They should not appear in the dashboard strategy list.
        if entry.base_run is None:
            print(f"  [SKIP] {strategy_id:32s} no base_run (validation harness, not a strategy)")
            continue
        try:
            res = build_manifest(strategy_id, entry, runs_root, manifests_dir)
            print(f"  [OK] {res['strategy_id']:32s} stage={res['stage']}  -> {res['path']}")
            built += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  [FAIL] {strategy_id}: {exc}", file=sys.stderr)
    print(f"\n{built}/{len(targets)} manifests written.")


if __name__ == "__main__":
    main()
