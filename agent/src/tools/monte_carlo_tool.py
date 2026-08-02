"""Monte Carlo path-simulation tool for agents and swarm workers.

Runs large-batch GBM / bootstrap / block-bootstrap simulations on a backtest
run directory (reads ``artifacts/equity.csv``) or on caller-supplied returns.
Writes ``artifacts/monte_carlo_paths.json`` when a run_dir is provided.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest.monte_carlo import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_N_PATHS,
    run_monte_carlo_paths,
)
from backtest.validation import write_validation_json
from src.agent.progress import emit_progress
from src.agent.tools import BaseTool
from src.tools.path_utils import safe_run_dir


def _load_equity(run_path: Path) -> pd.Series:
    path = run_path / "artifacts" / "equity.csv"
    if not path.exists():
        raise FileNotFoundError("artifacts/equity.csv not found")
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    for col in ("equity", "nav", "value"):
        if col in df.columns:
            return df[col]
    raise ValueError(
        f"equity.csv must contain equity/nav/value column; got {list(df.columns)}"
    )


def _progress_bridge(stage: str, current: Optional[int], total: Optional[int], message: str) -> None:
    emit_progress(stage, current=current, total=total, message=message)


def run_monte_carlo_tool(
    *,
    run_dir: Optional[str] = None,
    method: str = "bootstrap",
    n_paths: int = DEFAULT_N_PATHS,
    horizon: Optional[int] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    seed: int = 42,
    mu: Optional[float] = None,
    sigma: Optional[float] = None,
    block_size: int = 21,
    ruin_level: float = 0.5,
    es_alpha: float = 0.95,
    returns: Optional[List[float]] = None,
    initial_capital: float = 1_000_000.0,
) -> str:
    """Execute Monte Carlo path simulation and return JSON."""
    emit_progress("validate", message="preparing Monte Carlo inputs")
    equity: Optional[pd.Series] = None
    run_path: Optional[Path] = None
    capital = float(initial_capital)

    if run_dir:
        try:
            run_path = safe_run_dir(run_dir)
        except ValueError as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
        try:
            equity = _load_equity(run_path)
        except (OSError, ValueError, FileNotFoundError) as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
        cfg_path = run_path / "config.json"
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                capital = float(cfg.get("initial_cash", capital))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass

    if equity is None and not returns:
        return json.dumps(
            {
                "status": "error",
                "error": "Provide run_dir (with artifacts/equity.csv) or returns[]",
            },
            ensure_ascii=False,
        )

    result = run_monte_carlo_paths(
        method=method,
        equity_curve=equity,
        returns=returns,
        initial_capital=capital,
        n_paths=int(n_paths),
        horizon=horizon,
        batch_size=int(batch_size),
        seed=int(seed),
        mu=mu,
        sigma=sigma,
        block_size=int(block_size),
        ruin_level=float(ruin_level),
        es_alpha=float(es_alpha),
        progress=_progress_bridge,
    )

    if "error" in result:
        return json.dumps({"status": "error", **result}, ensure_ascii=False)

    artifact = None
    if run_path is not None:
        out = run_path / "artifacts" / "monte_carlo_paths.json"
        write_validation_json(out, result)
        artifact = str(out)

    payload: Dict[str, Any] = {
        "status": "ok",
        "result": result,
        "artifact": artifact,
        "run_dir": run_dir,
    }
    return json.dumps(payload, ensure_ascii=False)


class MonteCarloTool(BaseTool):
    """Large-batch Monte Carlo path simulation for strategy risk analysis."""

    name = "monte_carlo"
    description = (
        "Run large-batch Monte Carlo path simulations (GBM / bootstrap / "
        "block_bootstrap) on a backtest run_dir or raw returns. Returns "
        "distributional outcomes: percentiles, ruin probability, expected "
        "shortfall, max-drawdown bands. Default 10_000 paths; supports up to "
        "5_000_000 with batched vectorization."
    )
    parameters = {
        "type": "object",
        "properties": {
            "run_dir": {
                "type": "string",
                "description": "Backtest run directory containing artifacts/equity.csv",
            },
            "method": {
                "type": "string",
                "description": "gbm | bootstrap | block_bootstrap (default bootstrap)",
            },
            "n_paths": {
                "type": "integer",
                "description": f"Number of paths (default {DEFAULT_N_PATHS}, max 5_000_000)",
            },
            "horizon": {
                "type": "integer",
                "description": "Path length in bars (default: history length or 252)",
            },
            "batch_size": {
                "type": "integer",
                "description": f"Paths per vectorized batch (default {DEFAULT_BATCH_SIZE})",
            },
            "seed": {"type": "integer", "description": "RNG seed (default 42)"},
            "mu": {"type": "number", "description": "Optional GBM drift (per bar)"},
            "sigma": {"type": "number", "description": "Optional GBM volatility (per bar)"},
            "block_size": {
                "type": "integer",
                "description": "Block length for block_bootstrap (default 21)",
            },
            "ruin_level": {
                "type": "number",
                "description": "Fraction of capital that counts as ruin (default 0.5)",
            },
            "es_alpha": {
                "type": "number",
                "description": "Expected-shortfall confidence level (default 0.95)",
            },
            "returns": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Optional explicit return series when run_dir is omitted",
            },
            "initial_capital": {
                "type": "number",
                "description": "Starting capital when not read from config.json",
            },
        },
        "required": [],
    }
    repeatable = True
    is_readonly = False

    def execute(self, **kwargs) -> str:
        return run_monte_carlo_tool(
            run_dir=kwargs.get("run_dir"),
            method=kwargs.get("method", "bootstrap"),
            n_paths=kwargs.get("n_paths", DEFAULT_N_PATHS),
            horizon=kwargs.get("horizon"),
            batch_size=kwargs.get("batch_size", DEFAULT_BATCH_SIZE),
            seed=kwargs.get("seed", 42),
            mu=kwargs.get("mu"),
            sigma=kwargs.get("sigma"),
            block_size=kwargs.get("block_size", 21),
            ruin_level=kwargs.get("ruin_level", 0.5),
            es_alpha=kwargs.get("es_alpha", 0.95),
            returns=kwargs.get("returns"),
            initial_capital=kwargs.get("initial_capital", 1_000_000.0),
        )
