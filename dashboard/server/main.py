from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import artifacts
import parsers
from schemas import StrategyManifest

# Repo root — override with REPO_ROOT env var for Docker / Linux deployment.
REPO_ROOT = Path(os.environ.get("REPO_ROOT", Path(__file__).parent.parent.parent))

app = FastAPI(title="Quant Strategy Dashboard API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "repo_root": str(REPO_ROOT)}


# ---------------------------------------------------------------------------
# 3.4 Strategy list & detail
# ---------------------------------------------------------------------------

@app.get("/api/strategies")
def list_strategies() -> list[dict]:
    manifests = artifacts.list_strategy_manifests(REPO_ROOT)
    return [
        {
            "strategy_id": m.strategy_id,
            "symbol": m.symbol,
            "pipeline_stage": m.pipeline_stage,
            "generated_at": m.generated_at.isoformat(),
            "gate_pass": m.gate.overall_pass if m.gate else None,
            "gate_fatal": m.gate.fatal_fail if m.gate else None,
            "sharpe": m.backtest.in_sample.sharpe if m.backtest else None,
            "max_drawdown": m.backtest.in_sample.max_drawdown if m.backtest else None,
            "red_flags": [f.value for f in m.gate.red_flags] if m.gate else [],
        }
        for m in manifests
    ]


@app.get("/api/strategies/{strategy_id}")
def get_strategy(strategy_id: str) -> StrategyManifest:
    manifest = artifacts.get_strategy_manifest(REPO_ROOT, strategy_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"Strategy '{strategy_id}' not found")
    return manifest


# ---------------------------------------------------------------------------
# 3.5 Equity curve & trades
# ---------------------------------------------------------------------------

def _resolve_run_csv(strategy_id: str, run: Optional[str], filename: str) -> Path:
    """Return path to <run>/<filename>; 404 if not found."""
    manifest = artifacts.get_strategy_manifest(REPO_ROOT, strategy_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"Strategy '{strategy_id}' not found")

    run_dir = run
    if run_dir is None and manifest.backtest and manifest.backtest.in_sample:
        run_dir = manifest.backtest.in_sample.source_run
    if run_dir is None:
        raise HTTPException(status_code=404, detail="No run specified and no default in manifest")

    path = (REPO_ROOT / run_dir / filename).resolve()
    # Safety: must stay within repo_root
    if not path.is_relative_to(REPO_ROOT.resolve()):
        raise HTTPException(status_code=403, detail="Path outside repo root")
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{filename} not found in run '{run_dir}'")
    return path


@app.get("/api/strategies/{strategy_id}/equity")
def get_equity(
    strategy_id: str,
    run: Optional[str] = Query(default=None, description="Run directory relative to repo root"),
) -> list[dict[str, Any]]:
    path = _resolve_run_csv(strategy_id, run, "equity.csv")
    return parsers.csv_to_records(path)


@app.get("/api/strategies/{strategy_id}/trades")
def get_trades(
    strategy_id: str,
    run: Optional[str] = Query(default=None, description="Run directory relative to repo root"),
) -> list[dict[str, Any]]:
    path = _resolve_run_csv(strategy_id, run, "trades.csv")
    return parsers.csv_to_records(path)


# ---------------------------------------------------------------------------
# 3.6 Factor analysis, regime, selection
# ---------------------------------------------------------------------------

from schemas import FactorManifest, SelectionManifest


@app.get("/api/factor-analysis")
def get_factor_analysis(
    symbol: str = Query(..., description="Trading symbol, e.g. 'BTC'"),
) -> FactorManifest:
    manifest = artifacts.get_factor_manifest(REPO_ROOT, symbol)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"Factor manifest for '{symbol}' not found")
    return manifest


@app.get("/api/regime")
def get_regime(
    symbol: str = Query(..., description="Trading symbol, e.g. 'BTC'"),
) -> dict[str, Any]:
    data = artifacts.get_regime_manifest(REPO_ROOT, symbol)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Regime manifest for '{symbol}' not found")
    return data


@app.get("/api/selection")
def get_selection() -> SelectionManifest:
    manifest = artifacts.get_selection_manifest(REPO_ROOT)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Selection manifest not found")
    return manifest


# ---------------------------------------------------------------------------
# 3.7 Markdown reports — allowlist: research/ only
# ---------------------------------------------------------------------------

_REPORT_ALLOWED_DIRS = ["research"]


# ---------------------------------------------------------------------------
# 3.8 Pipeline stage overview
# ---------------------------------------------------------------------------

@app.get("/api/pipeline")
def get_pipeline() -> list[dict]:
    manifests = artifacts.list_strategy_manifests(REPO_ROOT)
    return [
        {
            "strategy_id": m.strategy_id,
            "symbol": m.symbol,
            "pipeline_stage": m.pipeline_stage,
            "generated_at": m.generated_at.isoformat(),
        }
        for m in manifests
    ]


# ---------------------------------------------------------------------------
# 3.7 Markdown reports — allowlist: research/ only
# ---------------------------------------------------------------------------

@app.get("/api/reports")
def get_report(
    path: str = Query(..., description="Path to markdown file relative to repo root"),
) -> dict[str, str]:
    target = (REPO_ROOT / path)
    if not parsers.is_path_allowed(target, REPO_ROOT, _REPORT_ALLOWED_DIRS):
        raise HTTPException(status_code=403, detail="Path not in allowed directories")
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Report '{path}' not found")
    return {"path": path, "content": parsers.read_text(target)}
