"""System and utility HTTP routes.

Mounted by ``agent/api_server.py`` via ``register_system_routes(app, ...)``.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Deque, Dict, Optional, Tuple

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Security,
    status,
)
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


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
# In-process per-client rate limiter
# ---------------------------------------------------------------------------


class _SlidingWindowRateLimiter:
    """Thread-safe fixed-capacity sliding-window limiter keyed by client.

    Deliberately in-process and dependency-free: the API has no shared cache
    or Redis, and a single endpoint doing bounded computation does not warrant
    a third-party limiter. A monotonic clock is used so wall-clock jumps never
    widen or collapse the window.
    """

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Record a hit for ``key`` and report whether it stays within budget."""
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self._max:
                return False
            bucket.append(now)
            return True

    def reset(self) -> None:
        """Clear all recorded hits (test/maintenance helper)."""
        with self._lock:
            self._hits.clear()


# 30 requests / minute / client IP: /correlation runs real cross-asset math on
# each hit, so a moderate ceiling is enough to blunt abuse without hurting UX.
_correlation_rate_limiter = _SlidingWindowRateLimiter(max_requests=30, window_seconds=60.0)


def _client_key(request: Request) -> str:
    """Return a stable per-client bucket key (client IP, or a fixed fallback)."""
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Readiness check (network-free)
# ---------------------------------------------------------------------------


def _provider_readiness() -> Tuple[bool, str]:
    """Report whether the configured LLM provider looks usable, cheaply.

    Mirrors the config-validation portion of
    ``src.preflight._check_llm_provider`` (provider + model present, a
    credential derivable) but deliberately omits the outbound base-URL ping:
    a readiness probe is hit frequently and must never block on the network or
    incur LLM cost.

    Returns:
        ``(ready, reason)`` where ``reason`` is a non-sensitive explanation
        suitable for returning to a probe when not ready.
    """
    try:
        from src.config.accessor import get_env_config
        from src.providers.capabilities import provider_env_names
        from src.providers.llm import _sync_provider_env
    except Exception as exc:  # noqa: BLE001 — degrade to not-ready, never crash the probe
        logger.warning("readiness: provider config import failed: %r", exc)
        return False, "provider configuration unavailable"

    cfg = get_env_config()
    provider = cfg.llm.langchain_provider.strip()
    model = cfg.llm.langchain_model_name.strip()
    if not provider:
        return False, "LLM provider not configured"
    if not model:
        return False, "LLM model not configured"

    # OAuth-based providers carry no API key; a local login token stands in.
    if provider.lower() in {"openai-codex", "openai_codex"}:
        try:
            from src.providers.openai_codex import get_openai_codex_login_status

            if not get_openai_codex_login_status():
                return False, "provider OAuth login not found"
        except Exception as exc:  # noqa: BLE001 — treat unknown OAuth state as not-ready
            logger.warning("readiness: OAuth status check failed: %r", exc)
            return False, "provider OAuth status unavailable"
        return True, "ready"

    _sync_provider_env()
    key_env, _base_env = provider_env_names(provider, model)
    # key_env is None for keyless local providers (e.g. Ollama).
    if key_env is not None:
        has_key = bool(os.getenv(key_env, "") or os.getenv("OPENAI_API_KEY", ""))  # noqa: env-gate — readiness credential probe
        if not has_key:
            return False, "LLM provider credential not configured"
    return True, "ready"


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
    _configured_api_key = host._configured_api_key
    require_auth = host.require_auth
    _app_version = app_version if app_version is not None else host.APP_VERSION

    def _get_terminate_process():
        """Late-access _terminate_current_process for test monkeypatch compat."""
        h = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        if h is not None:
            fn = getattr(h, "_terminate_current_process", None)
            if fn is not None:
                return fn
        return _terminate_current_process

    # --- Routes ---

    def _health_payload() -> HealthResponse:
        return HealthResponse(
            status="healthy",
            service="Vibe-Trading API",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    @app.get("/live", response_model=HealthResponse)
    async def liveness_probe():
        """Liveness: the process is up and can serve HTTP.

        Intentionally unconditional — a liveness probe only answers "should the
        container be restarted?", and the answer is no as long as this handler
        runs at all. Deeper checks belong on ``/ready``.
        """
        return _health_payload()

    @app.get("/health", response_model=HealthResponse)
    async def health_check():
        """Backward-compatible alias for ``/live`` (legacy monitors)."""
        return _health_payload()

    @app.get("/ready")
    async def readiness_probe():
        """Readiness: the configured LLM provider looks usable.

        Returns 200 when ready and 503 (with a non-sensitive reason) when the
        provider/model/credential is not configured, so orchestrators can hold
        traffic until the agent can actually serve requests.
        """
        ready, reason = _provider_readiness()
        if not ready:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=reason)
        return {
            "status": "ready",
            "service": "Vibe-Trading API",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/correlation", dependencies=[Depends(require_auth)])
    async def get_correlation_matrix(
        request: Request,
        codes: str = Query(..., description="Comma-separated asset codes, e.g. BTC-USDT,ETH-USDT,SPY"),
        days: int = Query(90, description="Lookback window in days", ge=7, le=365),
        method: str = Query("pearson", description="Correlation method: pearson or spearman"),
    ):
        """Compute cross-asset correlation matrix from daily returns.

        Fetches price data for each code via available data loaders,
        computes pairwise correlation of daily returns over the lookback window.
        """
        from backtest.correlation import compute_correlation_matrix

        if not _correlation_rate_limiter.allow(_client_key(request)):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded, try again later",
            )

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
        except Exception:
            logger.exception("Correlation computation failed for codes=%s", code_list)
            raise HTTPException(status_code=500, detail="Correlation computation failed")

    @app.get("/correlation/regime", dependencies=[Depends(require_auth)])
    async def get_correlation_regime(
        request: Request,
        codes: str = Query(..., description="Comma-separated asset codes, e.g. BTC-USDT,ETH-USDT,SPY"),
        days: int = Query(90, description="Timeline length in daily bars", ge=30, le=365),
        corr_window: int = Query(60, description="Rolling correlation window in bars", ge=5, le=250),
        edge_threshold: float = Query(0.5, description="|corr| level at which a pair counts as an edge", gt=0.0, lt=1.0),
        smooth_window: int = Query(5, description="Trailing smoothing window in bars", ge=1, le=60),
        enter_threshold: float = Query(0.65, description="Smoothed density that opens a FUSED regime", gt=0.0, lt=1.0),
        exit_threshold: float = Query(0.45, description="Smoothed density that closes a FUSED regime (must be below enter_threshold)", gt=0.0, lt=1.0),
    ):
        """Correlation-regime timeline: edge density + hysteresis over time.

        Applies Mode 1 of the correlation-regime skill to the same price data
        /correlation uses: rolling pairwise correlations are reduced to an
        edge-density series, causally smoothed, and run through a two-threshold
        hysteresis state machine. Descriptive risk context, not a trading
        signal. Shares /correlation's rate-limit budget.
        """
        from backtest.regime import compute_regime_timeline

        if not _correlation_rate_limiter.allow(_client_key(request)):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded, try again later",
            )

        code_list = [c.strip() for c in codes.split(",") if c.strip()]
        if len(code_list) < 2:
            raise HTTPException(status_code=400, detail="At least 2 asset codes required")
        if len(code_list) > 20:
            raise HTTPException(status_code=400, detail="Maximum 20 assets per request")
        if exit_threshold >= enter_threshold:
            raise HTTPException(status_code=400, detail="exit_threshold must be below enter_threshold")

        try:
            return compute_regime_timeline(
                codes=code_list,
                days=days,
                corr_window=corr_window,
                edge_threshold=edge_threshold,
                smooth_window=smooth_window,
                enter_threshold=enter_threshold,
                exit_threshold=exit_threshold,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception:
            logger.exception("Regime timeline computation failed for codes=%s", code_list)
            raise HTTPException(status_code=500, detail="Regime timeline computation failed")

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

    @app.get("/skills", dependencies=[Depends(require_auth)])
    async def list_skills():
        """List registered skills (name and description).

        Authenticated: the skill inventory describes the agent's installed
        capabilities and is not appropriate pre-auth reconnaissance material.
        """
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

    # --- API documentation ---
    #
    # ``api_server`` constructs the app with ``docs_url``/``redoc_url``/
    # ``openapi_url`` set to ``None`` and delegates here so the schema and its
    # schema sits behind ``require_auth``. It enumerates every route -- including
    # the live-trading and mandate control plane -- so an unauthorized peer must
    # not be able to read it.
    #
    # A browser navigation cannot attach a Bearer header before Swagger's
    # ``Authorize`` control loads, and its initial schema fetch is unauthenticated
    # too. Interactive docs therefore remain available only in keyless loopback
    # dev mode. Keyed deployments return 404 for both viewers and expose the
    # schema only to programmatic callers that send the Bearer header.

    _openapi_url = "/openapi.json"

    @app.get(_openapi_url, include_in_schema=False, dependencies=[Depends(require_auth)])
    async def openapi_schema():
        """Serve the OpenAPI schema to authorized callers only."""
        return JSONResponse(app.openapi())

    # Favicons point at the SPA's self-hosted asset rather than FastAPI's
    # default remote one, so the docs CSP exception does not have to widen
    # ``img-src`` to a third-party host.
    _docs_favicon = "/favicon.svg"

    @app.get("/docs", include_in_schema=False)
    async def swagger_ui(
        request: Request,
        cred: Optional[HTTPAuthorizationCredentials] = Security(_security),
    ):
        """Serve Swagger UI only in keyless loopback development mode."""
        if _configured_api_key():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
        await require_auth(request, cred)
        return get_swagger_ui_html(
            openapi_url=_openapi_url,
            title=f"{app.title} - Swagger UI",
            swagger_favicon_url=_docs_favicon,
        )

    @app.get("/redoc", include_in_schema=False)
    async def redoc_ui(
        request: Request,
        cred: Optional[HTTPAuthorizationCredentials] = Security(_security),
    ):
        """Serve ReDoc only in keyless loopback development mode."""
        if _configured_api_key():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
        await require_auth(request, cred)
        # ``with_google_fonts=False`` drops ReDoc's fonts.googleapis.com
        # stylesheet, so the docs CSP exception stays limited to the bundle
        # host instead of also allowing a font CDN. ReDoc falls back to system
        # fonts and is otherwise unchanged.
        return get_redoc_html(
            openapi_url=_openapi_url,
            title=f"{app.title} - ReDoc",
            redoc_favicon_url=_docs_favicon,
            with_google_fonts=False,
        )
