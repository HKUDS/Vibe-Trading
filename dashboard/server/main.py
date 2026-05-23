from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
