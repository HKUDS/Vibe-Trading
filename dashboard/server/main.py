from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import artifacts
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
