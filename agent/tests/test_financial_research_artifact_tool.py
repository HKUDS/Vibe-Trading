"""Agent-facing structured financial research artifact tool regression tests."""

import json

from src.research_artifacts.financial_facts import decode_financial_facts
from src.research_artifacts.store import ResearchArtifactStore
from src.tools.financial_research_artifact_tool import SaveFinancialResearchArtifactTool
from src.tools.research_artifact_tool import SaveResearchArtifactTool


def _document(value=100):
    return {
        "schema_version": "financial-facts/v1",
        "subject": "Example Corporation",
        "sources": [{"id": "annual", "url": "https://example.org/annual"}],
        "facts": [
            {
                "metric": "revenue",
                "period_kind": "duration",
                "period_start": "2025-01-01",
                "period_end": "2025-12-31",
                "scope": "consolidated",
                "definition": "Reported consolidated revenue",
                "value": value,
                "currency": "USD",
                "unit": "millions",
                "source_id": "annual",
                "source_section": "Income statement",
                "verification_status": "partial",
            }
        ],
    }


def test_financial_tool_validates_before_opening_store(tmp_path, monkeypatch):
    from src.tools import financial_research_artifact_tool as tool_module

    def unexpected_store():
        raise AssertionError("must not open a database for invalid input")

    monkeypatch.setattr(tool_module, "ResearchArtifactStore", unexpected_store)
    tool = SaveFinancialResearchArtifactTool()
    document = _document()
    document["facts"][0]["value"] = float("nan")
    result = json.loads(tool.execute(document=document, data_as_of="2026-11-04"))
    assert result["status"] == "error"
    assert "finite numeric" in result["error"]


def test_financial_tool_round_trip_idempotence_and_revisions(tmp_path, monkeypatch):
    from src.tools import financial_research_artifact_tool as tool_module

    path = tmp_path / "isolated.sqlite"
    monkeypatch.setattr(
        tool_module,
        "ResearchArtifactStore",
        lambda: ResearchArtifactStore(db_path=path),
    )
    tool = SaveFinancialResearchArtifactTool()
    first = json.loads(tool.execute(document=_document(), data_as_of="2026-11-04"))
    assert first["status"] == "ok"
    assert first["created"] is True
    assert first["revision"]["evidence_missing"] is False
    assert first["revision"]["evidence"] == [
        {"source_id": "annual", "url": "https://example.org/annual"}
    ]
    revision = first["revision"]
    artifact_id = revision["artifact_id"]

    again = json.loads(
        tool.execute(
            document=_document(), data_as_of="2026-11-04", artifact_id=artifact_id
        )
    )
    assert again["status"] == "ok"
    assert again["created"] is False
    assert again["revision"]["revision_id"] == revision["revision_id"]

    revised = json.loads(
        tool.execute(
            document=_document(105), data_as_of="2026-11-04", artifact_id=artifact_id
        )
    )
    assert revised["status"] == "ok"
    assert revised["created"] is True
    assert revised["revision"]["revision_number"] == 2

    store = ResearchArtifactStore(db_path=path)
    try:
        old = store.get_revision(revision["revision_id"])
        new = store.get_revision(revised["revision"]["revision_id"])
        assert decode_financial_facts(old.content)["facts"][0]["value"] == 100
        assert decode_financial_facts(new.content)["facts"][0]["value"] == 105
        assert new.verification_status == "unverified"
    finally:
        store.close()


def test_narrative_research_tool_stays_unchanged(tmp_path, monkeypatch):
    from src.tools import research_artifact_tool as tool_module

    path = tmp_path / "narrative.sqlite"
    monkeypatch.setattr(
        tool_module,
        "ResearchArtifactStore",
        lambda: ResearchArtifactStore(db_path=path),
    )
    result = json.loads(
        SaveResearchArtifactTool().execute(
            subject="Example Corporation",
            content="Narrative findings.",
            data_as_of="2026-11-04",
        )
    )
    assert result["status"] == "ok"
    store = ResearchArtifactStore(db_path=path)
    try:
        revision = store.get_revision(result["revision"]["revision_id"])
        assert revision.content == "Narrative findings."
    finally:
        store.close()


def test_financial_tool_persists_verified_share_count_without_currency(
    tmp_path, monkeypatch
):
    from src.tools import financial_research_artifact_tool as tool_module

    path = tmp_path / "share-count.sqlite"
    monkeypatch.setattr(
        tool_module,
        "ResearchArtifactStore",
        lambda: ResearchArtifactStore(db_path=path),
    )
    doc = _document()
    doc["facts"][0].update(
        metric="shares_outstanding",
        period_kind="instant",
        value=393_000_000,
        currency=None,
        unit="shares",
        source_section="Equity notes",
        verification_status="verified",
    )
    doc["facts"][0].pop("period_start")
    doc["facts"][0].pop("period_end")
    doc["facts"][0]["as_of_date"] = "2025-12-31"
    response = json.loads(
        SaveFinancialResearchArtifactTool().execute(
            document=doc, data_as_of="2026-11-04"
        )
    )
    assert response["status"] == "ok"
    store = ResearchArtifactStore(db_path=path)
    try:
        revision = store.get_revision(response["revision"]["revision_id"])
        fact = decode_financial_facts(revision.content)["facts"][0]
        assert fact["currency"] is None
        assert fact["value"] == 393_000_000
    finally:
        store.close()


def test_financial_tool_requires_document_object(tmp_path, monkeypatch):
    from src.tools import financial_research_artifact_tool as tool_module

    def unexpected_store():
        raise AssertionError("invalid document must never reach storage")

    monkeypatch.setattr(tool_module, "ResearchArtifactStore", unexpected_store)
    tool = SaveFinancialResearchArtifactTool()
    for bad in [None, '{"schema_version":"financial-facts/v1"}']:
        result = json.loads(tool.execute(document=bad, data_as_of="2026-11-04"))
        assert result["status"] == "error"


def test_agent_tool_is_discoverable_without_changing_narrative_tool():
    from src.tools import build_registry

    registry = build_registry(include_shell_tools=False)
    assert "save_financial_research_artifact" in registry.tool_names
    assert "save_research_artifact" in registry.tool_names
    schema = registry.get("save_financial_research_artifact").to_openai_schema()
    assert "document" in schema["function"]["parameters"]["required"]


def test_financial_tool_merges_extra_evidence_without_dropping_fact_sources(
    tmp_path, monkeypatch
):
    from src.tools import financial_research_artifact_tool as tool_module

    path = tmp_path / "evidence.sqlite"
    monkeypatch.setattr(
        tool_module,
        "ResearchArtifactStore",
        lambda: ResearchArtifactStore(db_path=path),
    )
    extra = {"kind": "retrieval", "sha256": "abc123"}
    result = json.loads(
        SaveFinancialResearchArtifactTool().execute(
            document=_document(), data_as_of="2026-11-04", evidence=[extra]
        )
    )
    assert result["status"] == "ok"
    assert result["revision"]["evidence_missing"] is False
    assert result["revision"]["evidence"] == [
        {"source_id": "annual", "url": "https://example.org/annual"},
        extra,
    ]


def test_invalid_extra_evidence_is_rejected_before_store(monkeypatch):
    from src.tools import financial_research_artifact_tool as tool_module

    def unexpected_store():
        raise AssertionError("invalid evidence must not reach storage")

    monkeypatch.setattr(tool_module, "ResearchArtifactStore", unexpected_store)
    result = json.loads(
        SaveFinancialResearchArtifactTool().execute(
            document=_document(), data_as_of="2026-11-04", evidence=["invalid"]
        )
    )
    assert result["status"] == "error"
    assert "evidence must be a list" in result["error"]


def test_financial_tool_schema_exposes_fact_fields_to_llm():
    schema = SaveFinancialResearchArtifactTool().to_openai_schema()
    doc = schema["function"]["parameters"]["properties"]["document"]
    assert set(doc["required"]) == {"schema_version", "subject", "sources", "facts"}
    fact = doc["properties"]["facts"]["items"]
    assert {"period_kind", "value", "source_id", "verification_status"} <= set(
        fact["required"]
    )
    assert fact["properties"]["period_kind"]["enum"] == ["duration", "instant"]
    assert fact["properties"]["verification_status"]["enum"] == [
        "verified",
        "partial",
        "unavailable",
    ]


def test_financial_tool_saves_explicit_unavailable_fact(tmp_path, monkeypatch):
    from src.tools import financial_research_artifact_tool as tool_module

    path = tmp_path / "unavailable.sqlite"
    monkeypatch.setattr(
        tool_module,
        "ResearchArtifactStore",
        lambda: ResearchArtifactStore(db_path=path),
    )
    doc = _document()
    missing = dict(doc["facts"][0])
    missing.update(
        metric="cash",
        period_kind="instant",
        as_of_date="2025-12-31",
        value=None,
        source_id=None,
        source_section=None,
        verification_status="unavailable",
        definition="No issuer balance-sheet source retrieved",
    )
    missing.pop("period_start")
    missing.pop("period_end")
    doc["facts"].append(missing)
    result = json.loads(
        SaveFinancialResearchArtifactTool().execute(
            document=doc, data_as_of="2026-11-04"
        )
    )
    assert result["status"] == "ok"
    store = ResearchArtifactStore(db_path=path)
    try:
        facts = decode_financial_facts(
            store.get_revision(result["revision"]["revision_id"]).content
        )["facts"]
        assert len(facts) == 2
        assert facts[1]["verification_status"] == "unavailable"
        assert facts[1]["value"] is None
    finally:
        store.close()


def test_agent_offered_schema_requires_dates_by_period_kind():
    """Inspect the actual tool schema, not a separately reconstructed schema."""
    schema = SaveFinancialResearchArtifactTool().to_openai_schema()
    fact = schema["function"]["parameters"]["properties"]["document"]["properties"][
        "facts"
    ]["items"]
    rules = fact["allOf"]
    duration, instant = rules
    assert duration["if"]["properties"]["period_kind"]["const"] == "duration"
    assert set(duration["then"]["required"]) == {"period_start", "period_end"}
    assert duration["then"]["properties"]["period_start"] == {
        "type": "string",
        "format": "date",
    }
    assert duration["then"]["properties"]["period_end"] == {
        "type": "string",
        "format": "date",
    }
    assert duration["then"]["properties"]["as_of_date"] == {"type": "null"}
    assert instant["if"]["properties"]["period_kind"]["const"] == "instant"
    assert instant["then"]["required"] == ["as_of_date"]
    assert instant["then"]["properties"]["as_of_date"] == {
        "type": "string",
        "format": "date",
    }
    assert instant["then"]["properties"]["period_start"] == {"type": "null"}
    assert instant["then"]["properties"]["period_end"] == {"type": "null"}
