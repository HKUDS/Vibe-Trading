"""Read-only Research Card and governance API routes."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI, HTTPException, Query

from src.governance.discovery import discover_tool_manifest
from src.reliability.artifacts.store import ArtifactStore
from src.reliability.config import artifact_root
from src.reliability.redaction import redact_secrets
from src.research_card.model import ResearchCard
from src.tools import build_registry


RESEARCH_API_SCHEMA_VERSION = "1.0.0"
AuthDep = Callable[..., Awaitable[Any] | Any]


def register_research_card_routes(app: FastAPI, require_auth: AuthDep | None = None) -> None:
    """Mount read-only research card and governance inspection routes."""
    if require_auth is None:
        import sys as _sys

        host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        if host is None:  # pragma: no cover
            raise RuntimeError("register_research_card_routes requires require_auth when api_server is unavailable")
        require_auth = host.require_auth

    @app.get("/research/cards/{card_id}", dependencies=[Depends(require_auth)])
    async def get_research_card(card_id: str) -> dict[str, Any]:
        card = _find_research_card(card_id)
        if card is None:
            raise HTTPException(status_code=404, detail=f"research card {card_id} not found")
        return card.model_dump(mode="json")

    @app.get("/research/artifacts/{artifact_id}", dependencies=[Depends(require_auth)])
    async def get_research_artifact(artifact_id: str) -> dict[str, Any]:
        record = _artifact_record(artifact_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"artifact {artifact_id} not found")
        return {
            "schema_version": RESEARCH_API_SCHEMA_VERSION,
            "artifact": _public_record(record),
            "payload": _read_payload(record),
        }

    @app.get("/research/protocols/{protocol_id}", dependencies=[Depends(require_auth)])
    async def get_research_protocol(protocol_id: str) -> dict[str, Any]:
        for record in _artifact_records(artifact_type="research_protocol"):
            payload = _read_payload(record)
            if isinstance(payload, dict) and payload.get("protocol_id") == protocol_id:
                return payload
        raise HTTPException(status_code=404, detail=f"research protocol {protocol_id} not found")

    @app.get("/governance/tool-manifest", dependencies=[Depends(require_auth)])
    async def get_governance_tool_manifest() -> dict[str, Any]:
        registry = build_registry(include_shell_tools=True, interactive=False)
        tools = []
        for name in registry.tool_names:
            tool = registry.get(name)
            if tool is None:
                continue
            tools.append(discover_tool_manifest(tool).model_dump(mode="json"))
        return {"schema_version": RESEARCH_API_SCHEMA_VERSION, "tools": sorted(tools, key=lambda item: item["name"])}

    @app.get("/governance/policy-decisions", dependencies=[Depends(require_auth)])
    async def get_policy_decisions(run_id: str | None = Query(None)) -> dict[str, Any]:
        decisions = []
        for record in _artifact_records(artifact_type="policy_decision"):
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            payload = _read_payload(record)
            if run_id is not None and metadata.get("run_id") != run_id and not (
                isinstance(payload, dict) and payload.get("run_id") == run_id
            ):
                continue
            if isinstance(payload, dict):
                decisions.append(redact_secrets(payload))
        return {"schema_version": RESEARCH_API_SCHEMA_VERSION, "decisions": decisions}


def _find_research_card(card_id: str) -> ResearchCard | None:
    for record in _artifact_records(artifact_type="research_card"):
        payload = _read_payload(record)
        if isinstance(payload, dict) and payload.get("card_id") == card_id:
            return ResearchCard.model_validate(payload)
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        if metadata.get("card_id") == card_id and isinstance(payload, dict):
            return ResearchCard.model_validate(payload)
    return None


def _artifact_record(artifact_id: str) -> dict[str, Any] | None:
    for record in _artifact_records():
        if record.get("artifact_id") == artifact_id:
            return record
    return None


def _artifact_records(*, artifact_type: str | None = None) -> list[dict[str, Any]]:
    root = artifact_root()
    index_path = ArtifactStore(root=root).index_path
    if not index_path.exists():
        return []
    query = """
        SELECT artifact_id, artifact_type, schema_version, sha256, uri, path,
               inline_ref, parent_artifacts_json, created_at, generated_by, metadata_json
        FROM artifacts
    """
    params: tuple[Any, ...] = ()
    if artifact_type is not None:
        query += " WHERE artifact_type = ?"
        params = (artifact_type,)
    with sqlite3.connect(str(index_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
    return [_row_to_record(dict(row)) for row in rows]


def _row_to_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": row["artifact_id"],
        "artifact_type": row["artifact_type"],
        "schema_version": row["schema_version"],
        "sha256": row["sha256"],
        "uri": row["uri"],
        "path": row.get("path"),
        "inline_ref": row.get("inline_ref"),
        "parent_artifacts": json.loads(row.get("parent_artifacts_json") or "[]"),
        "created_at": row["created_at"],
        "generated_by": row["generated_by"],
        "metadata": redact_secrets(json.loads(row.get("metadata_json") or "{}")),
    }


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    public = dict(record)
    if public.get("path"):
        public["path"] = _safe_relative_payload_path(str(public["path"]))
    return redact_secrets(public)


def _read_payload(record: dict[str, Any]) -> Any:
    inline_ref = record.get("inline_ref")
    if inline_ref:
        return redact_secrets({"inline_ref": inline_ref})
    path_text = record.get("path")
    if not path_text:
        return None
    path = Path(path_text).resolve(strict=False)
    root = artifact_root().resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="artifact path escapes artifact root") from exc
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=404, detail="artifact payload missing") from exc
    try:
        return redact_secrets(json.loads(raw))
    except json.JSONDecodeError:
        return redact_secrets({"text": raw})


def _safe_relative_payload_path(path_text: str) -> str:
    path = Path(path_text).resolve(strict=False)
    root = artifact_root().resolve(strict=False)
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return ""
