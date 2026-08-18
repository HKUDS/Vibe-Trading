"""Run attribution HTTP routes for the Web UI.

Mounted by ``agent/api_server.py`` via ``register_attribution_routes(app, ...)``.

Routes (auth via the caller-supplied ``require_auth`` dependency):

- ``GET /runs/{run_id}/attribution`` — factor attribution (portfolio vs
  benchmark OLS: beta / alpha / rolling / cumulative) plus a single-period
  Brinson-Fachler decomposition, computed exclusively from the run's persisted
  artifacts. No market data is re-fetched.

The computation lives in ``attribution_core.py`` so this module stays a thin
registration slice.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from src.api.attribution_core import _attribution_round_values, _build_attribution_payload

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

AuthDep = Callable[..., Awaitable[Any] | Any]


def register_attribution_routes(
    app: FastAPI,
    require_auth: AuthDep | None = None,
) -> None:
    """Mount the attribution route onto ``app``.

    Resolves ``require_auth`` from the host ``api_server`` module via
    ``sys.modules`` when not passed explicitly.

    Args:
        app: The host FastAPI app.
        require_auth: Header-auth dependency for the endpoint.

    Raises:
        RuntimeError: When the host module is absent from ``sys.modules`` and
            no explicit dependency was passed.
    """
    import sys as _sys

    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
    if host is None:
        raise RuntimeError(
            "register_attribution_routes: api_server module not in sys.modules; "
            "ensure api_server is imported before calling this function"
        )

    if require_auth is None:
        require_auth = host.require_auth

    # Late-access closures for shared host symbols (monkeypatch-safe)
    def _host_validate_path_param(value: str, kind: str) -> None:
        h = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        return h._validate_path_param(value, kind)

    def _host_RUNS_DIR() -> Path:
        h = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        return h.RUNS_DIR

    @app.get("/runs/{run_id}/attribution", dependencies=[Depends(require_auth)])
    async def get_run_attribution(run_id: str):
        """Return factor + Brinson attribution for one run.

        All inputs come from the run's persisted artifacts; nothing is
        re-fetched. Blocking file work runs in the FastAPI threadpool.

        Args:
            run_id: Run identifier.

        Returns:
            The attribution envelope ``{"exists", "benchmark", "factor",
            "brinson", "notes"}`` with floats rounded to six decimals.

        Raises:
            HTTPException: 400 on a traversal-shaped ``run_id``, 404 when the
                run directory does not exist.
        """
        _host_validate_path_param(run_id, "run_id")
        run_dir = _host_RUNS_DIR() / run_id
        if not run_dir.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run {run_id} not found",
            )
        payload = await run_in_threadpool(_build_attribution_payload, run_dir)
        return _attribution_round_values(payload)
