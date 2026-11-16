"""Agent tool for validated, versioned structured financial research."""

from __future__ import annotations

from typing import Any

from src.agent.tools import BaseTool
from src.research_artifacts.financial_facts import encode_financial_facts
from src.research_artifacts.store import ResearchArtifactStore
from src.tools.research_artifact_tool import _error, _ok


class SaveFinancialResearchArtifactTool(BaseTool):
    """Validate a financial facts object before creating an immutable revision."""

    name = "save_financial_research_artifact"
    description = (
        "Save issuer financial statement facts in the opt-in financial-facts/v1 format "
        "as an immutable versioned research artifact. Pass document as a JSON object "
        "with schema_version, subject, sources, and facts; do not pass a JSON string. "
        "Facts must identify period (duration start/end or instant as-of), metric, "
        "accounting scope/definition, numeric value or null, currency, units, source "
        "ID/section, and per-fact verification status. Include documented formulas and "
        "operands for derived values when available. Use partial or unavailable when "
        "evidence is insufficient. A verified label asserts cited evidence; it is NOT "
        "independent audit or source verification. On a correction, provide artifact_id "
        "to append a linked revision. Narrative research uses save_research_artifact."
    )
    is_readonly = False
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "document": {
                "type": "object",
                "description": "Financial facts envelope. Represent requested missing metrics with unavailable/null rather than silently omitting them.",
                "properties": {
                    "schema_version": {
                        "type": "string",
                        "enum": ["financial-facts/v1"],
                    },
                    "subject": {"type": "string"},
                    "sources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "url": {"type": "string"},
                            },
                            "required": ["id", "url"],
                        },
                    },
                    "facts": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "metric": {"type": "string"},
                                "period_kind": {
                                    "type": "string",
                                    "enum": ["duration", "instant"],
                                },
                                "period_start": {
                                    "type": ["string", "null"],
                                    "format": "date",
                                    "description": "ISO YYYY-MM-DD for duration facts; otherwise omit or null",
                                },
                                "period_end": {
                                    "type": ["string", "null"],
                                    "format": "date",
                                    "description": "ISO YYYY-MM-DD for duration facts; otherwise omit or null",
                                },
                                "as_of_date": {
                                    "type": ["string", "null"],
                                    "format": "date",
                                    "description": "ISO YYYY-MM-DD for instant facts; otherwise omit or null",
                                },
                                "scope": {"type": "string"},
                                "definition": {
                                    "type": "string",
                                    "description": "Reported definition or derived formula and operands",
                                },
                                "value": {"type": ["number", "null"]},
                                "currency": {"type": ["string", "null"]},
                                "unit": {"type": ["string", "null"]},
                                "source_id": {"type": ["string", "null"]},
                                "source_section": {"type": ["string", "null"]},
                                "source_page": {"type": ["string", "integer", "null"]},
                                "verification_status": {
                                    "type": "string",
                                    "enum": ["verified", "partial", "unavailable"],
                                },
                            },
                            "required": [
                                "metric",
                                "period_kind",
                                "scope",
                                "definition",
                                "value",
                                "currency",
                                "unit",
                                "source_id",
                                "source_section",
                                "verification_status",
                            ],
                            "allOf": [
                                {
                                    "if": {
                                        "properties": {
                                            "period_kind": {"const": "duration"}
                                        },
                                        "required": ["period_kind"],
                                    },
                                    "then": {
                                        "required": ["period_start", "period_end"],
                                        "properties": {
                                            "period_start": {
                                                "type": "string",
                                                "format": "date",
                                            },
                                            "period_end": {
                                                "type": "string",
                                                "format": "date",
                                            },
                                            "as_of_date": {"type": "null"},
                                        },
                                    },
                                },
                                {
                                    "if": {
                                        "properties": {
                                            "period_kind": {"const": "instant"}
                                        },
                                        "required": ["period_kind"],
                                    },
                                    "then": {
                                        "required": ["as_of_date"],
                                        "properties": {
                                            "as_of_date": {
                                                "type": "string",
                                                "format": "date",
                                            },
                                            "period_start": {"type": "null"},
                                            "period_end": {"type": "null"},
                                        },
                                    },
                                },
                            ],
                        },
                    },
                },
                "required": ["schema_version", "subject", "sources", "facts"],
            },
            "data_as_of": {
                "type": "string",
                "description": "Date or timestamp of the researched data",
            },
            "artifact_id": {
                "type": "string",
                "description": "Existing artifact series to revise",
            },
            "universe": {
                "type": "string",
                "description": "Optional market or asset universe",
            },
            "evidence": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Optional additional references; fact sources are linked automatically",
            },
            "verification_status": {
                "type": "string",
                "description": "Artifact revision status; independent of fact-level statuses, defaults to unverified",
            },
            "completeness": {
                "type": "string",
                "description": "Revision completeness state",
            },
            "hypothesis_id": {"type": "string"},
            "goal_id": {"type": "string"},
            "session_id": {"type": "string"},
            "run_id": {"type": "string"},
        },
        "required": ["document", "data_as_of"],
        "additionalProperties": False,
    }

    def execute(self, **kwargs: Any) -> str:
        try:
            document = kwargs["document"]
            content = encode_financial_facts(document)
            subject = document["subject"].strip()  # Normalized by the encoder
            # Link validated fact sources to revision-level evidence.
            # References do not independently verify the cited documents.
            supplied_evidence = kwargs.get("evidence")
            if supplied_evidence is not None and (
                not isinstance(supplied_evidence, list)
                or any(not isinstance(item, dict) for item in supplied_evidence)
            ):
                raise ValueError("evidence must be a list of objects")
            evidence = [
                {"source_id": source["id"], "url": source["url"]}
                for source in document["sources"]
            ]
            for item in supplied_evidence or []:
                if item not in evidence:
                    evidence.append(item)
            store = ResearchArtifactStore()
            try:
                result = store.save(
                    artifact_id=kwargs.get("artifact_id"),
                    subject=subject,
                    universe=kwargs.get("universe"),
                    content=content,
                    data_as_of=kwargs["data_as_of"],
                    evidence=evidence,
                    verification_status=kwargs.get("verification_status"),
                    completeness=kwargs.get("completeness"),
                    hypothesis_id=kwargs.get("hypothesis_id"),
                    goal_id=kwargs.get("goal_id"),
                    session_id=kwargs.get("session_id"),
                    run_id=kwargs.get("run_id"),
                )
                return _ok(result.to_dict())
            finally:
                store.close()
        except Exception as exc:
            return _error(exc)
