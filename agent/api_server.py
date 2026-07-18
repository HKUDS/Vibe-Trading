#!/usr/bin/env python3
"""Vibe-Trading API Server - RESTful API for finance research and backtesting.

Thin assembler: creates the FastAPI app, mounts middleware, registers route
modules, and re-exports symbols for test compatibility.  All shared
infrastructure lives in ``src.api.{security,models,helpers,state}``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request, status  # noqa: F401
from fastapi.responses import FileResponse  # noqa: F401
from fastapi.middleware.cors import CORSMiddleware
from rich.console import Console

from cli._version import __version__ as APP_VERSION
from src.ui_services import build_run_analysis, load_run_context  # noqa: F401

# UTF-8 on Windows
import sys as _sys
for _s in ("stdout", "stderr"):
    _r = getattr(getattr(_sys, _s, None), "reconfigure", None)
    if callable(_r):
        _r(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Extracted infrastructure — re-exported for route-module and test access
# ---------------------------------------------------------------------------

from src.api.security import (  # noqa: F401, E402
    _API_KEY,
    _CORS_ORIGINS,
    _DEFAULT_CORS_ORIGINS,
    _DEFAULT_LOOPBACK_HOSTS,
    _EXTRA_LOOPBACK_HOSTS,
    _SAFE_BROWSER_METHODS,
    _apply_security_headers,
    _auth_credential_from_header_or_query,
    _configured_api_key,
    _consume_sse_ticket,
    _default_gateway_ips,
    _env_shell_tools_enabled,
    _host_without_port,
    _is_allowed_loopback_host,
    _is_local_client,
    _is_loopback_bind_host,
    _is_loopback_origin,
    _mint_sse_ticket,
    _origin_matches_request_host,
    _parse_cors_origins,
    _parse_extra_loopback_hosts,
    _redact_query_secrets,
    _reject_cross_site_browser_request,
    _reject_untrusted_loopback_host,
    _require_shutdown_authorization,
    _security,
    _shell_tools_enabled_for_request,
    _trusted_docker_loopback_ip,
    _validate_api_auth,
    install_access_log_redaction_filter,
    require_auth,
    require_event_stream_auth,
    require_local_or_auth,
    require_settings_write_auth,
)

from src.api.models import (  # noqa: F401, E402
    Artifact,
    BacktestMetrics,
    RAGSelection,
    RunInfo,
    RunResponse,
)

from src.api.helpers import (  # noqa: F401, E402
    AGENT_DIR,
    ENV_EXAMPLE_PATH,
    ENV_PATH,
    LEGACY_ENV_PATH,
    RUNS_DIR,
    SESSIONS_DIR,
    UPLOADS_DIR,
    _coerce_float,
    _coerce_int,
    _ensure_agent_env_file,
    _format_env_value,
    _FRONTEND_DIST,
    _is_configured_secret,
    _is_spa_html_route,
    _project_relative_path,
    _read_env_values,
    _SAFE_PATH_PARAM_RE,
    _spa_html_deep_link_fallback,
    _strip_env_value,
    _validate_path_param,
    _write_env_values,
)

from src.api.state import (  # noqa: F401, E402
    _channel_bus,
    _channel_manager,
    _channel_runtime,
    _get_channel_runtime,
    _get_session_service,
    _session_service,
)

console = Console()
logger = logging.getLogger(__name__)

# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="Vibe-Trading API",
    description="Vibe-Trading API: natural-language finance research, backtesting, and swarm workflows",
    version=APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware functions are defined in src.api.security / src.api.helpers, so
# the @app.middleware("http") decorator cannot be used here — register them
# programmatically instead.
app.middleware("http")(_reject_untrusted_loopback_host)
app.middleware("http")(_spa_html_deep_link_fallback)
app.middleware("http")(_apply_security_headers)

# ============================================================================
# Lifecycle hooks
# ============================================================================

from src.api.channels_routes import (  # noqa: E402
    _start_channel_runtime,
    _stop_channel_runtime,
)
from src.api.scheduled_routes import (  # noqa: E402
    _start_scheduled_research_executor,
    _stop_scheduled_research_executor,
)


@app.on_event("startup")
async def _run_startup_preflight() -> None:
    """Run preflight checks on server startup."""
    from src.preflight import run_preflight

    run_preflight(console)
    _start_scheduled_research_executor()
    from src.config.accessor import get_env_config

    if get_env_config().agent_tuning.vibe_trading_channels_auto_start:
        await _start_channel_runtime()


@app.on_event("shutdown")
async def _stop_scheduled_research_on_shutdown() -> None:
    """Stop the scheduled research executor on server shutdown."""
    await _stop_channel_runtime()
    await _stop_scheduled_research_executor()


# ============================================================================
# Route registration + re-exports
# ============================================================================

# --- Runs ---
from src.api.runs_routes import register_runs_routes  # noqa: E402
register_runs_routes(app)

from src.api.runs_routes import (  # noqa: F401, E402
    _load_json_file,
    _load_csv_to_dict,
    _build_response_from_run_dir,
)

# --- Sessions ---
from src.api.sessions_routes import register_sessions_routes  # noqa: E402
register_sessions_routes(app)

from src.api.sessions_routes import (  # noqa: F401, E402
    _goal_store,
    _live_action_frame_from_tool_result,
    _mandate_proposal_frame_from_tool_result,
)

# --- System ---
from src.api.system_routes import register_system_routes  # noqa: E402
register_system_routes(app)

from src.api.system_routes import _terminate_current_process  # noqa: F401, E402

# --- Settings ---
from src.api.settings_routes import register_settings_routes  # noqa: E402
register_settings_routes(app)

from src.api.settings_routes import (  # noqa: F401, E402
    _baostock_supported,
    _baostock_installed,
    _load_llm_providers,
)

# --- Uploads ---
from src.api.uploads_routes import register_uploads_routes  # noqa: E402
register_uploads_routes(app)

from src.api.uploads_routes import (  # noqa: F401, E402
    MAX_UPLOAD_SIZE,
    _BLOCKED_UPLOAD_EXT,
    _BLOCKED_UPLOAD_NAMES,
    _SHADOW_ID_RE,
    _UPLOAD_CHUNK_SIZE,
)

# --- Channels ---
from src.api.channels_routes import register_channels_routes  # noqa: E402
register_channels_routes(app)
from src.api.qveris_routes import qveris_router  # noqa: E402  # QVERIS-INTEGRATION
app.include_router(qveris_router)  # QVERIS-INTEGRATION

from src.api.channels_routes import (  # noqa: F401, E402
    ChannelPairingCommandRequest,
)

# --- Swarm ---
from src.api.swarm_routes import register_swarm_routes  # noqa: E402
register_swarm_routes(app)

from src.api.swarm_routes import _get_swarm_runtime  # noqa: F401, E402

# --- Live trading ---
from src.api.live_routes import register_live_routes  # noqa: E402
register_live_routes(app)

from src.api.live_routes import (  # noqa: F401, E402
    CommitMandateRequest,
    LiveHaltRequest,
    LiveAuthorizeRequest,
    LiveRunnerControlRequest,
    BrokerAuthState,
    MandateLimits,
    ActiveMandateState,
    RunnerLivenessState,
    LiveBrokerStatus,
    LiveStatusResponse,
    LiveRunnerUnavailable,
    _runner_tasks,
    _runner_factory,
    _emit_live_event,
    _fetch_broker_ceilings,
    _known_live_brokers,
    _oauth_token_present,
    _active_mandate_state,
    _runner_liveness_state,
    _live_broker_adapter,
    _build_live_runner,
    _drive_runner,
    _connector_verify_cache,
    _check_connector_status,
)

# --- Alpha Zoo ---
from src.api.alpha_routes import register_alpha_routes  # noqa: E402
register_alpha_routes(app)

# --- Auth helpers (SSE tickets) ---
from src.api.auth_routes import register_auth_routes  # noqa: E402
register_auth_routes(app)


# ============================================================================
# Scheduled Research Routes - defined in src/api/scheduled_routes.py
# ============================================================================
#
# Lightweight CRUD endpoints backed by ScheduledResearchJobStore. The endpoint
# handlers only record and expose jobs; the optional executor lifecycle is
# guarded separately by VIBE_TRADING_ENABLE_SCHEDULER.

from src.api.scheduled_routes import register_scheduled_routes  # noqa: E402
register_scheduled_routes(app)

from src.api.scheduled_routes import (  # noqa: E402, F401
    CreateScheduledRunRequest,
    ScheduledRunResponse,
    _dispatch_scheduled_research_job,
    _get_scheduled_research_executor,
    _get_scheduled_research_store,
    _scheduled_research_scheduler_enabled,
)


# ============================================================================
# Main Entry Point
# ============================================================================

def serve_main(argv: list[str] | None = None) -> int:
    """Start the API server from CLI-style arguments."""
    import argparse
    import subprocess
    import uvicorn
    from fastapi.staticfiles import StaticFiles
    from starlette.exceptions import HTTPException as StarletteHTTPException

    class SPAStaticFiles(StaticFiles):
        """Serve index.html for browser refreshes on client-side routes."""

        async def get_response(self, path: str, scope: Dict[str, Any]):
            try:
                return await super().get_response(path, scope)
            except StarletteHTTPException as exc:
                if exc.status_code != status.HTTP_404_NOT_FOUND:
                    raise
                return await super().get_response("index.html", scope)

    parser = argparse.ArgumentParser(description="Vibe-Trading Server")
    parser.add_argument("--port", type=int, default=8000, help="Listen port (default 8000)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    parser.add_argument("--dev", action="store_true", help="Dev mode: spawn Vite on :5173")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    if not _is_loopback_bind_host(args.host) and not _configured_api_key():
        print(
            f"[warn] Binding to {args.host} without API_AUTH_KEY set. "
            f"Remote requests are rejected by the loopback peer-IP check, "
            f"but consider using --host 127.0.0.1 for local-only access."
        )

    frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    frontend_root = Path(__file__).resolve().parent.parent / "frontend"

    vite_proc = None
    if args.dev and frontend_root.exists():
        print("[dev] Starting Vite dev server on :5173 ...")
        vite_proc = subprocess.Popen(
            ["npx", "vite", "--host", "0.0.0.0"],
            cwd=str(frontend_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"[dev] Vite PID={vite_proc.pid}")
        print("[dev] Frontend: http://localhost:5173")
        print(f"[dev] API: http://localhost:{args.port}")
    elif frontend_dist.exists():
        if not any(getattr(route, "path", None) == "/" for route in app.routes):
            app.mount("/", SPAStaticFiles(directory=str(frontend_dist), html=True), name="frontend")
        print(f"[prod] Frontend served from {frontend_dist}")
    else:
        print(f"[warn] No frontend build found at {frontend_dist}")
        print("[warn] Run: cd frontend && npm run build")

    print("=" * 50)
    print("  Vibe-Trading Server")
    print(f"  http://127.0.0.1:{args.port}")
    print("=" * 50)

    # Redact api_key=/ticket= values from Uvicorn's access log (it logs the full
    # request line including the query string). Installed before run() so the
    # filter is attached when Uvicorn configures its loggers.
    install_access_log_redaction_filter()

    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    finally:
        if vite_proc:
            vite_proc.terminate()
            print("[dev] Vite stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(serve_main())
