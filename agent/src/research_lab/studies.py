"""Execution-cost experiments and train/select/freeze/test walk-forward runs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from backtest.metrics import period_returns
from src.research_lab.execution import constructor_defaults, digest, freeze_run, source_run, trial
from src.research_lab.models import CostRequest, WalkForwardRequest

Progress = Callable[[dict], None]


def cost_sensitivity(request: CostRequest, root: Path, progress: Progress) -> dict:
    """Re-execute the same strategy and price inputs under declared costs."""
    config, manifest, _, source_hash = freeze_run(source_run(request.run_dir), root)
    rows = []
    for index, scenario in enumerate(request.scenarios):
        progress(
            {"phase": "cost_sensitivity", "completed": index, "total": len(request.scenarios), "label": scenario.name}
        )
        settings = {
            **config,
            "execution_cost_multiplier": scenario.fee_multiplier,
            "extra_slippage_bps": scenario.extra_slippage_bps,
        }
        measured = trial(root, f"cost-{index}", settings, manifest)
        rows.append({**scenario.model_dump(), **measured["metrics"], "run_dir": measured["run_dir"]})
    brackets = []
    # These are measured sign-change brackets, never interpolated claims of
    # an exact break-even. Position sizes and fills can change with costs.
    for bps in sorted({row["extra_slippage_bps"] for row in rows}):
        ordered = sorted(
            (row for row in rows if row["extra_slippage_bps"] == bps), key=lambda row: row["fee_multiplier"]
        )
        for left, right in zip(ordered, ordered[1:]):
            if left["total_return"] * right["total_return"] <= 0 and left["total_return"] != right["total_return"]:
                brackets.append(
                    {
                        "extra_slippage_bps": bps,
                        "fee_multiplier_interval": [left["fee_multiplier"], right["fee_multiplier"]],
                    }
                )
    return {
        "kind": "cost_sensitivity",
        "rows": rows,
        "break_even_brackets": brackets,
        "break_even_method": "observed_sign_change_only",
        "strategy_sha256": source_hash,
        "input_manifest_sha256": digest(manifest),
        "cost_scope": "engine execution commissions and transaction taxes; funding and borrow charges unchanged",
        "slippage_scope": "additional adverse basis points before the engine's normal slippage and tick rounding",
        "ranking": [row["name"] for row in sorted(rows, key=lambda row: row["total_return"], reverse=True)],
    }


def walk_forward(request: WalkForwardRequest, root: Path, progress: Progress) -> dict:
    """Select parameters on training data only, then execute frozen OOS folds.

    Every trial uses the ordinary execution engine. Test folds start flat and
    liquidate at their end, so fold boundary costs are included. A reserved
    final holdout is never included in any training or validation fold.
    """
    config, manifest, calendar, code_hash = freeze_run(source_run(request.run_dir), root)
    if config.get("engine", "daily") != "daily":
        raise ValueError("walk-forward parameter selection currently requires a daily/bar execution engine")
    limit = len(calendar) - request.holdout_bars
    if limit < request.train_bars + request.test_bars:
        raise ValueError("snapshot has too few bars for training, testing and the reserved holdout")
    boundaries = list(range(request.train_bars, limit - request.test_bars + 1, request.test_bars))
    boundaries = boundaries[: request.max_folds]
    sealed = {
        "request": request.model_dump(),
        "strategy_sha256": code_hash,
        "input_manifest_sha256": digest(manifest),
        "fold_test_starts": [str(calendar[i]) for i in boundaries],
        "holdout_start": str(calendar[limit]) if request.holdout_bars else None,
    }
    seal = hashlib.sha256(json.dumps(sealed, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (root / "sealed_plan.json").write_text(json.dumps({**sealed, "sha256": seal}, indent=2))
    folds = []
    test_returns = []
    count = len(boundaries) * (len(request.candidates) + 1)
    if request.holdout_bars:
        count += len(request.candidates) + 1
    completed = 0
    defaults = constructor_defaults((manifest.parent / "signal_engine.py").read_text())
    baseline_parameters = {**defaults, **config.get("signal_parameters", {})}

    def fit_and_test(number: int, boundary: int, end: int, holdout: bool = False):
        nonlocal completed
        start = 0 if request.training == "expanding" else boundary - request.train_bars
        train_results = []
        for index, candidate in enumerate(request.candidates):
            parameters = {**baseline_parameters, **candidate.parameters}
            progress(
                {"phase": "training", "completed": completed, "total": count, "fold": number, "label": candidate.name}
            )
            settings = {
                **config,
                "start_date": calendar[0].isoformat(),
                "end_date": calendar[boundary - 1].isoformat(),
                "evaluation_start_date": calendar[start].isoformat(),
                "warmup_bars": 0,
            }
            measured = trial(
                root,
                f"{'holdout' if holdout else 'fold'}-{number}-train-{index}",
                settings,
                manifest,
                parameters=parameters,
            )
            score = measured["metrics"].get(request.objective)
            if score is None or not np.isfinite(score):
                raise ValueError(f"candidate {candidate.name} has no finite training {request.objective}")
            train_results.append(
                {
                    "name": candidate.name,
                    "parameters": parameters,
                    "score": score,
                    "metrics": measured["metrics"],
                    "run_dir": measured["run_dir"],
                }
            )
            completed += 1
        # Stable input order resolves equal training scores. Test performance
        # does not participate in selection, including the final holdout.
        chosen = max(train_results, key=lambda item: item["score"])
        selection = {
            "parameters": chosen["parameters"],
            "name": chosen["name"],
            "training_start": str(calendar[start]),
            "training_end": str(calendar[boundary - 1]),
            "test_start": str(calendar[boundary]),
            "test_end": str(calendar[end - 1]),
            "plan_sha256": seal,
        }
        selection_path = root / f"selection-{'holdout' if holdout else number}.json"
        selection_path.write_text(json.dumps(selection, sort_keys=True, indent=2))
        selection_hash = digest(selection_path)
        progress(
            {
                "phase": "holdout" if holdout else "testing",
                "completed": completed,
                "total": count,
                "fold": number,
                "label": chosen["name"],
            }
        )
        settings = {
            **config,
            "start_date": calendar[0].isoformat(),
            "end_date": calendar[end - 1].isoformat(),
            "evaluation_start_date": calendar[boundary].isoformat(),
            "warmup_bars": 0,
        }
        measured = trial(
            root,
            f"{'holdout' if holdout else 'fold'}-{number}-test",
            settings,
            manifest,
            parameters=chosen["parameters"],
        )
        if digest(selection_path) != selection_hash or digest(manifest.parent / "signal_engine.py") != code_hash:
            raise ValueError("selected parameters or strategy changed during the frozen test")
        returns = period_returns(measured["equity"]["equity"], float(config.get("initial_cash", 1_000_000)))
        if returns.isna().any() or not np.isfinite(returns).all():
            raise ValueError("OOS equity contains unobserved or non-finite returns")
        if len(returns) != end - boundary or not returns.index.equals(calendar[boundary:end]):
            raise ValueError("test engine did not evaluate exactly the sealed calendar window")
        completed += 1
        return {
            **selection,
            "fold": number,
            "training": train_results,
            "selection_sha256": selection_hash,
            "test": {"metrics": measured["metrics"], "run_dir": measured["run_dir"]},
        }, returns

    for number, boundary in enumerate(boundaries, 1):
        result, returns = fit_and_test(number, boundary, boundary + request.test_bars)
        folds.append(result)
        test_returns.append(returns)
    holdout_result = None
    if request.holdout_bars:
        holdout_result, holdout_returns = fit_and_test(len(folds) + 1, limit, len(calendar), True)
        holdout_result["total_return"] = float((1 + holdout_returns).prod() - 1)
    combined = pd.concat(test_returns)
    equity = float(config.get("initial_cash", 1_000_000)) * (1 + combined).cumprod()
    pd.DataFrame({"return": combined, "equity": equity}).to_csv(root / "oos_equity.csv")
    return {
        "kind": "walk_forward",
        "mode": "locked" if request.holdout_bars else "strict",
        "plan_sha256": seal,
        "strategy_sha256": code_hash,
        "input_manifest_sha256": digest(manifest),
        "folds": folds,
        "oos_total_return": float((1 + combined).prod() - 1),
        "oos_bars": len(combined),
        "holdout": holdout_result,
        "unused_validation_bars": limit - (boundaries[-1] + request.test_bars),
        "position_policy": "flat_at_each_fold_with_engine_liquidation_costs",
        "selection_policy": "training_score_only; input_order_breaks_ties",
        "candidate_count": len(request.candidates),
        "causality": "Parameter isolation is enforced; the strategy's own forecasting logic is not independently certified.",
    }
