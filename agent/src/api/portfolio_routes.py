"""Authenticated Web API for the local read-only portfolio dashboard."""

from __future__ import annotations

import subprocess
import sys
import threading
from copy import deepcopy
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, Field

from src.api.security import require_auth, require_settings_write_auth
from src.portfolio.service import PortfolioService

_REFRESH_LOCK = threading.Lock()
_REFRESH_OPERATION_LOCK = threading.Lock()
_RECONNECT_OPERATION_LOCK = threading.Lock()
_RECONNECT_STATE_LOCK = threading.Lock()
_RECONNECT_TIMEOUT_SECONDS = 330
_RECONNECT_STATE = {
    "running": False,
    "source_id": None,
    "status": "idle",
    "error": None,
    "started_at": None,
    "finished_at": None,
}
_REFRESH_STATE = {
    "running": False,
    "current": None,
    "sources": {},
}


class PortfolioSourceRequest(BaseModel):
    connection_id: str
    label: str
    enabled: bool = True
    order: int = 0
    include_cash: bool = True


class PortfolioSettingsRequest(BaseModel):
    display_currency: str = Field(default="USD", pattern="^[A-Z]{3}$")
    sources: list[PortfolioSourceRequest] = Field(default_factory=list, max_length=50)


def _set_refresh_progress(source_id: str, status: str, error: str | None) -> None:
    """Record one source's live refresh state for the polling endpoint.

    Args:
        source_id: The configured source being refreshed.
        status: ``pending``, ``refreshing``, ``ok`` or ``error``.
        error: Short failure text, or ``None``.
    """
    with _REFRESH_LOCK:
        _REFRESH_STATE["current"] = source_id if status == "refreshing" else None
        _REFRESH_STATE["sources"][source_id] = {"status": status, "error": error}


def _reconnect_snapshot() -> dict:
    with _RECONNECT_STATE_LOCK:
        return deepcopy(_RECONNECT_STATE)


def _set_reconnect_state(**updates) -> None:
    with _RECONNECT_STATE_LOCK:
        _RECONNECT_STATE.update(updates)


def _stop_reconnect_process(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _run_reconnect(source_id: str) -> None:
    process = None
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "src.portfolio.oauth_worker", source_id],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return_code = process.wait(timeout=_RECONNECT_TIMEOUT_SECONDS)
        if return_code == 0:
            _set_reconnect_state(status="authorized", error=None)
        else:
            _set_reconnect_state(
                status="error",
                error="Authorization did not complete. Close the old broker authorization tab and reconnect.",
            )
    except subprocess.TimeoutExpired:
        if process is not None:
            _stop_reconnect_process(process)
        _set_reconnect_state(
            status="timeout",
            error="Authorization timed out. The callback server was closed and reconnect is safe to retry.",
        )
    except Exception:
        if process is not None and process.poll() is None:
            _stop_reconnect_process(process)
        _set_reconnect_state(
            status="error", error="Unable to start the local authorization process."
        )
    finally:
        _set_reconnect_state(
            running=False,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        _RECONNECT_OPERATION_LOCK.release()


def register_portfolio_routes(app: FastAPI) -> None:
    """Register the authenticated, read-only portfolio endpoints.

    Args:
        app: The FastAPI application to mount the routes on.
    """

    def service(*, progress: bool = False) -> PortfolioService:
        return PortfolioService(
            progress_callback=_set_refresh_progress if progress else None
        )

    @app.get("/api/portfolio", dependencies=[Depends(require_auth)])
    def latest_portfolio():
        snapshot = service().latest()
        if snapshot is None:
            return {"status": "empty", "snapshot": None}
        return {"status": "ok", "snapshot": snapshot}

    @app.post("/api/portfolio/refresh", dependencies=[Depends(require_auth)])
    def refresh_portfolio():
        if not _REFRESH_OPERATION_LOCK.acquire(blocking=False):
            raise HTTPException(
                status_code=409, detail="portfolio refresh already running"
            )
        try:
            selected = [
                item for item in service().settings()["sources"] if item["enabled"]
            ]
            with _REFRESH_LOCK:
                _REFRESH_STATE.update(
                    running=True,
                    current=None,
                    sources={
                        item["connection_id"]: {"status": "pending", "error": None}
                        for item in selected
                    },
                )
            return {"status": "ok", "snapshot": service(progress=True).refresh()}
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        finally:
            with _REFRESH_LOCK:
                _REFRESH_STATE["running"] = False
                _REFRESH_STATE["current"] = None
            _REFRESH_OPERATION_LOCK.release()

    @app.get("/api/portfolio/refresh-status", dependencies=[Depends(require_auth)])
    def portfolio_refresh_status():
        with _REFRESH_LOCK:
            refresh = deepcopy(_REFRESH_STATE)
            # ``brokers`` was the original dashboard field name. Keep it as a
            # compatibility alias so an already-open frontend can safely poll
            # a newer backend while its cached assets are being replaced.
            refresh["brokers"] = deepcopy(refresh["sources"])
            return {"status": "ok", "refresh": refresh}

    @app.post(
        "/api/portfolio/sources/{source_id}/reconnect",
        dependencies=[Depends(require_auth)],
        status_code=202,
    )
    def reconnect_portfolio_source(source_id: str):
        if not _RECONNECT_OPERATION_LOCK.acquire(blocking=False):
            raise HTTPException(
                status_code=409, detail="portfolio reconnect already running"
            )
        try:
            service().reconnect_target(source_id)
        except RuntimeError as exc:
            _RECONNECT_OPERATION_LOCK.release()
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            _RECONNECT_OPERATION_LOCK.release()
            raise HTTPException(
                status_code=503, detail="Unable to load the local OAuth configuration"
            ) from exc
        _set_reconnect_state(
            running=True,
            source_id=source_id,
            status="authorizing",
            error=None,
            started_at=datetime.now(timezone.utc).isoformat(),
            finished_at=None,
        )
        try:
            threading.Thread(
                target=_run_reconnect,
                args=(source_id,),
                daemon=True,
                name=f"portfolio-oauth-{source_id}",
            ).start()
        except Exception:
            _RECONNECT_OPERATION_LOCK.release()
            _set_reconnect_state(
                running=False,
                status="error",
                error="Unable to start the local authorization task.",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            raise HTTPException(
                status_code=503, detail="Unable to start the local authorization task"
            )
        return {"status": "started", "reconnect": _reconnect_snapshot()}

    @app.get("/api/portfolio/reconnect-status", dependencies=[Depends(require_auth)])
    def portfolio_reconnect_status():
        return {"status": "ok", "reconnect": _reconnect_snapshot()}

    @app.get("/api/portfolio/settings", dependencies=[Depends(require_auth)])
    def portfolio_settings():
        instance = service()
        return {
            "status": "ok",
            "settings": instance.settings(),
            "catalog": instance.sources(),
        }

    @app.put(
        "/api/portfolio/settings",
        dependencies=[Depends(require_settings_write_auth)],
    )
    def update_portfolio_settings(payload: PortfolioSettingsRequest):
        try:
            instance = service()
            settings = instance.save_settings(payload.model_dump())
            return {"status": "ok", "settings": settings, "catalog": instance.sources()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/portfolio/history", dependencies=[Depends(require_auth)])
    def portfolio_history(limit: int = Query(180, ge=1, le=2000)):
        return {"status": "ok", "history": service().history(limit)}

    @app.get("/api/portfolio/analysis-context", dependencies=[Depends(require_auth)])
    def portfolio_analysis_context():
        context = service().analysis_context()
        if context is None:
            raise HTTPException(status_code=404, detail="no portfolio snapshot exists")
        return {"status": "ok", "context": context}

    @app.get("/api/portfolio/export.csv", dependencies=[Depends(require_auth)])
    def export_portfolio_csv():
        content = service().export_csv()
        if not content:
            raise HTTPException(status_code=404, detail="no portfolio snapshot exists")
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=portfolio.csv"},
        )
