"""Agent-tool integration for versioned research artifacts."""

from __future__ import annotations

import json

from src.tools.research_artifact_tool import (
    GetResearchArtifactTool,
    SaveResearchArtifactTool,
    SearchResearchArtifactsTool,
)


def _payload(**overrides):
    payload = {
        "subject": "NVDA fundamental review",
        "universe": "NVDA",
        "content": "Evidence-backed conclusion.",
        "data_as_of": "2026-10-20",
        "evidence": [{"source_uri": "https://example.com/filing"}],
        "verification_status": "verified",
        "goal_id": "goal-a",
    }
    payload.update(overrides)
    return payload


def test_agent_tools_save_search_revise_and_read_history(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_RESEARCH_ARTIFACT_DB_PATH", str(tmp_path / "research.db"))
    save = SaveResearchArtifactTool()
    first = json.loads(save.execute(**_payload()))
    repeated = json.loads(save.execute(**_payload()))

    assert first["created"] is True
    assert repeated["created"] is False
    assert repeated["revision"]["revision_id"] == first["revision"]["revision_id"]

    artifact_id = first["revision"]["artifact_id"]
    revised = json.loads(
        save.execute(
            **_payload(
                artifact_id=artifact_id,
                content="Updated conclusion.",
                data_as_of="2026-10-27",
            )
        )
    )
    assert revised["revision"]["previous_revision_id"] == first["revision"]["revision_id"]

    searched = json.loads(SearchResearchArtifactsTool().execute(query="Updated conclusion"))
    assert searched["count"] == 1
    assert searched["artifacts"][0]["revision_id"] == revised["revision"]["revision_id"]

    detail = json.loads(GetResearchArtifactTool().execute(artifact_id=artifact_id))
    assert detail["artifact"]["content"] == "Updated conclusion."
    assert len(detail["revisions"]) == 2
    assert detail["revisions"][-1]["content"] == "Evidence-backed conclusion."

    old = json.loads(GetResearchArtifactTool().execute(revision_id=first["revision"]["revision_id"]))
    assert old["revision"]["data_as_of"] == "2026-10-20"


def test_agent_tool_reports_validation_and_missing_records(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_RESEARCH_ARTIFACT_DB_PATH", str(tmp_path / "research.db"))

    invalid = json.loads(SaveResearchArtifactTool().execute(**_payload(content=" ")))
    missing = json.loads(GetResearchArtifactTool().execute(artifact_id="ra_missing"))
    ambiguous = json.loads(GetResearchArtifactTool().execute())

    assert invalid["status"] == "error"
    assert "content is required" in invalid["error"]
    assert missing["status"] == "error"
    assert "not found" in missing["error"]
    assert ambiguous["status"] == "error"


def test_agent_registry_discovers_research_artifact_tools():
    from src.tools import build_registry

    registry = build_registry()
    assert {
        "save_research_artifact",
        "search_research_artifacts",
        "get_research_artifact",
    } <= set(registry.tool_names)
