"""Research Card models, builders, renderers, and read-only API routes."""

from __future__ import annotations

from src.research_card.builder import (
    ResearchCardEvidenceArtifacts,
    ResearchCardGraph,
    build_research_card,
    build_research_card_evidence_artifacts,
)
from src.research_card.model import EvidenceClosureSummary, ResearchCard, StructuredFailure, StructuredWarning
from src.research_card.render_markdown import render_research_card_markdown

__all__ = [
    "EvidenceClosureSummary",
    "ResearchCard",
    "ResearchCardEvidenceArtifacts",
    "ResearchCardGraph",
    "StructuredFailure",
    "StructuredWarning",
    "build_research_card",
    "build_research_card_evidence_artifacts",
    "render_research_card_markdown",
]
