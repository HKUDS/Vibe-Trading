"""System and utility HTTP routes.

Mounted by ``agent/api_server.py`` via ``register_system_routes(app, ...)``.
"""

from __future__ import annotations

import os
import signal
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Pydantic models (defined locally -- NO shared modules, per maintainer rule)
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """Health check payload."""
    status: str = Field(..., description="Service status")
    service: str = Field(..., description="Service name")
    timestamp: str = Field(..., description="Server timestamp")


# ---------------------------------------------------------------------------
# Process termination
# ---------------------------------------------------------------------------


def _terminate_current_process() -> None:
    """Stop the current API process after the response has been sent."""
    time.sleep(0.25)
    os.kill(os.getpid(), signal.SIGTERM)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_system_routes(
    app: FastAPI,
    app_version: str | None = None,
) -> None:
    """Mount the system routes onto ``app``.

    Resolves ``_security``, ``_require_shutdown_authorization``, and
    ``APP_VERSION`` from the host ``api_server`` module via ``sys.modules``
    when not passed explicitly.
    """
    # Resolve host dependencies via sys.modules fallback
    import sys as _sys

    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")

    if host is None:
        raise RuntimeError(
            "register_system_routes: api_server module not in sys.modules; "
            "ensure api_server is imported before calling this function"
        )

    _security = host._security
    _require_shutdown_authorization = host._require_shutdown_authorization
    _app_version = app_version if app_version is not None else host.APP_VERSION
    route_host = host

    def _get_terminate_process():
        """Late-access _terminate_current_process for test monkeypatch compat."""
        fn = getattr(route_host, "_terminate_current_process", None)
        if fn is not None:
            return fn
        return _terminate_current_process

    # --- Routes ---

    @app.get("/health", response_model=HealthResponse)
    async def health_check():
        """Liveness probe."""
        return HealthResponse(
            status="healthy",
            service="Vibe-Trading API",
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    @app.get("/correlation")
    async def get_correlation_matrix(
        codes: str = Query(..., description="Comma-separated asset codes, e.g. BTC-USDT,ETH-USDT,SPY"),
        days: int = Query(90, description="Lookback window in days", ge=7, le=365),
        method: str = Query("pearson", description="Correlation method: pearson or spearman"),
    ):
        """Compute cross-asset correlation matrix from daily returns.

        Fetches price data for each code via available data loaders,
        computes pairwise correlation of daily returns over the lookback window.
        """
        from backtest.correlation import compute_correlation_matrix

        code_list = [c.strip() for c in codes.split(",") if c.strip()]
        if len(code_list) < 2:
            raise HTTPException(status_code=400, detail="At least 2 asset codes required")
        if len(code_list) > 20:
            raise HTTPException(status_code=400, detail="Maximum 20 assets per request")
        if method not in ("pearson", "spearman"):
            raise HTTPException(status_code=400, detail="method must be 'pearson' or 'spearman'")

        try:
            result = compute_correlation_matrix(codes=code_list, days=days, method=method)
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Correlation computation failed: {exc}")

    @app.post("/system/shutdown")
    async def shutdown_local_api(
        background_tasks: BackgroundTasks,
        request: Request,
        cred: Optional[HTTPAuthorizationCredentials] = Security(_security),
    ):
        """Shut down the local API server after explicit local authorization."""
        _require_shutdown_authorization(request=request, cred=cred)
        client_host = request.client.host if request.client else ""
        if client_host not in {"127.0.0.1", "::1", "localhost"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Local access only")

        background_tasks.add_task(_get_terminate_process())
        return {
            "status": "shutting-down",
            "service": "Vibe-Trading API",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/skills")
    async def list_skills():
        """List registered skills (name and description)."""
        from src.agent.skills import SkillsLoader

        loader = SkillsLoader()
        return [
            {
                "name": s.name,
                "description": s.description,
            }
            for s in loader.skills
        ]

    @app.get("/api")
    async def api_info():
        """Service metadata."""
        return {
            "service": "Vibe-Trading API",
            "version": _app_version,
            "docs": "/docs",
            "health": "/health",
        }
