"""Read-only Alpha Genesis report routes."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI, HTTPException, Response

from src.research_ledger.hash_utils import json_safe, redact_secrets


AuthDep = Callable[..., Awaitable[Any] | Any]
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def _default_report_root() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "agent" / "reports" / "alpha_genesis"


def _report_root() -> Path:
    raw = os.getenv("VIBE_TRADING_ALPHA_GENESIS_REPORT_DIR")
    return Path(raw).resolve() if raw else _default_report_root()


def _validate_identifier(value: str, kind: str) -> None:
    if not _SAFE_ID_RE.fullmatch(value or ""):
        raise HTTPException(status_code=400, detail=f"invalid {kind}")


def _load_json_artifact(name: str, suffix: str, *, expected_schema: str) -> dict[str, Any]:
    _validate_identifier(name, "artifact id")
    path = (_report_root() / f"{name}{suffix}").resolve()
    root = _report_root().resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid artifact path")
    if not path.exists():
        raise HTTPException(status_code=404, detail="alpha genesis artifact not found")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="alpha genesis artifact is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="alpha genesis artifact must be a JSON object")
    if payload.get("schema_version") != expected_schema:
        raise HTTPException(status_code=404, detail="alpha genesis artifact not found")
    return redact_secrets(json_safe(payload))


def _set_read_only_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"


def register_alpha_genesis_routes(
    app: FastAPI,
    require_auth: AuthDep | None = None,
) -> None:
    if require_auth is None:
        import sys as _sys

        host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        if host is None:
            raise RuntimeError(
                "register_alpha_genesis_routes: pass require_auth explicitly when api_server is not loaded"
            )
        require_auth = host.require_auth

    @app.get("/api/alpha-genesis/reports/{report_id}", dependencies=[Depends(require_auth)])
    async def get_alpha_genesis_report(report_id: str, response: Response) -> dict[str, Any]:
        _set_read_only_headers(response)
        return _load_json_artifact(
            report_id,
            ".json",
            expected_schema="alpha_genesis_report.v1",
        )

    @app.get("/api/alpha-genesis/scorecards/{candidate_id}", dependencies=[Depends(require_auth)])
    async def get_alpha_genesis_scorecard(candidate_id: str, response: Response) -> dict[str, Any]:
        _set_read_only_headers(response)
        return _load_json_artifact(
            candidate_id,
            ".scorecard.json",
            expected_schema="alpha_quality_scorecard.v1",
        )

    @app.get("/api/alpha-genesis/quality-decisions/{candidate_id}", dependencies=[Depends(require_auth)])
    async def get_alpha_genesis_quality_decision(candidate_id: str, response: Response) -> dict[str, Any]:
        _set_read_only_headers(response)
        return _load_json_artifact(
            candidate_id,
            ".decision.json",
            expected_schema="alpha_quality_decision.v1",
        )
