"""Agent tools for saving and reusing versioned research artifacts."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.research_artifacts import ResearchArtifactStore


def _ok(payload: dict[str, Any]) -> str:
    return json.dumps({"status": "ok", **payload}, ensure_ascii=False)


def _error(exc: Exception) -> str:
    return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)


class SaveResearchArtifactTool(BaseTool):
    """Save an immutable revision with content and provenance identity."""

    name = "save_research_artifact"
    description = (
        "Save research as an immutable, versioned artifact with evidence and data-as-of provenance. "
        "Pass an existing artifact_id to append a linked revision. Identical repeated saves are idempotent. "
        "Changed content or provenance defaults to unverified; storing a revision does not revalidate it."
    )
    is_readonly = False
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "artifact_id": {"type": "string", "description": "Existing series ID to revise; omit for a new series"},
            "subject": {"type": "string", "description": "Research subject; inherited on revision"},
            "universe": {"type": "string", "description": "Optional market or asset universe"},
            "content": {"type": "string", "description": "Complete research conclusions for this revision"},
            "data_as_of": {"type": "string", "description": "Date or timestamp the research data represents"},
            "evidence": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Source/evidence references, including URIs, IDs, and content hashes when available",
            },
            "verification_status": {"type": "string", "description": "Verification state, default unverified"},
            "completeness": {"type": "string", "description": "Completeness state, default complete"},
            "hypothesis_id": {"type": "string"},
            "goal_id": {"type": "string"},
            "session_id": {"type": "string"},
            "run_id": {"type": "string"},
        },
        "required": ["content", "data_as_of"],
        "additionalProperties": False,
    }

    def execute(self, **kwargs: Any) -> str:
        store = ResearchArtifactStore()
        try:
            result = store.save(
                artifact_id=kwargs.get("artifact_id"),
                subject=kwargs.get("subject"),
                universe=kwargs.get("universe"),
                content=kwargs.get("content", ""),
                data_as_of=kwargs.get("data_as_of", ""),
                evidence=kwargs.get("evidence"),
                verification_status=kwargs.get("verification_status"),
                completeness=kwargs.get("completeness"),
                hypothesis_id=kwargs.get("hypothesis_id"),
                goal_id=kwargs.get("goal_id"),
                session_id=kwargs.get("session_id"),
                run_id=kwargs.get("run_id"),
            )
            return _ok(result.to_dict())
        except Exception as exc:
            return _error(exc)
        finally:
            store.close()


class SearchResearchArtifactsTool(BaseTool):
    """Search the latest revision of each research-artifact series."""

    name = "search_research_artifacts"
    description = (
        "Search previous research by text, subject, universe, or linked hypothesis/goal/session/run IDs. "
        "Results are the latest revisions only and preserve evidence gaps and data-as-of dates."
    )
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "subject": {"type": "string"},
            "universe": {"type": "string"},
            "hypothesis_id": {"type": "string"},
            "goal_id": {"type": "string"},
            "session_id": {"type": "string"},
            "run_id": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
        },
        "required": [],
        "additionalProperties": False,
    }

    def execute(self, **kwargs: Any) -> str:
        store = ResearchArtifactStore()
        try:
            results = store.search(
                query=str(kwargs.get("query", "")),
                subject=str(kwargs.get("subject", "")),
                universe=str(kwargs.get("universe", "")),
                hypothesis_id=str(kwargs.get("hypothesis_id", "")),
                goal_id=str(kwargs.get("goal_id", "")),
                session_id=str(kwargs.get("session_id", "")),
                run_id=str(kwargs.get("run_id", "")),
                limit=int(kwargs.get("limit", 50)),
            )
            return _ok(
                {
                    "count": len(results),
                    "artifacts": [item.to_dict() for item in results],
                }
            )
        except Exception as exc:
            return _error(exc)
        finally:
            store.close()


class GetResearchArtifactTool(BaseTool):
    """Retrieve one series or one immutable revision."""

    name = "get_research_artifact"
    description = (
        "Retrieve a research-artifact series by artifact_id or one immutable revision by revision_id. "
        "Series retrieval can include every linked historical revision."
    )
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "artifact_id": {"type": "string"},
            "revision_id": {"type": "string"},
            "include_history": {"type": "boolean", "default": True},
        },
        "required": [],
        "additionalProperties": False,
    }

    def execute(self, **kwargs: Any) -> str:
        store = ResearchArtifactStore()
        try:
            revision_id = str(kwargs.get("revision_id", "")).strip()
            artifact_id = str(kwargs.get("artifact_id", "")).strip()
            if bool(revision_id) == bool(artifact_id):
                return _error(ValueError("provide exactly one of artifact_id or revision_id"))
            if revision_id:
                revision = store.get_revision(revision_id)
                if revision is None:
                    return _error(ValueError(f"research revision not found: {revision_id}"))
                return _ok({"revision": revision.to_dict()})
            latest = store.get_latest(artifact_id)
            if latest is None:
                return _error(ValueError(f"research artifact not found: {artifact_id}"))
            payload: dict[str, Any] = {"artifact": latest.to_dict()}
            if kwargs.get("include_history", True):
                payload["revisions"] = [item.to_dict() for item in store.list_revisions(artifact_id)]
            return _ok(payload)
        except Exception as exc:
            return _error(exc)
        finally:
            store.close()
