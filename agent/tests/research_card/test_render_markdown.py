from __future__ import annotations

from pathlib import Path

from src.research_card.model import ResearchCard, StructuredFailure, StructuredWarning
from src.research_card.render_markdown import render_research_card_markdown


def test_markdown_snapshot_includes_warning_codes_and_hard_failures() -> None:
    card = ResearchCard(
        card_id="card_markdown",
        title="Markdown Study",
        hypothesis="Check a factor.",
        warnings=[StructuredWarning(code="QUANT_OOS_MISSING", message="OOS missing")],
        hard_failures=[StructuredFailure(code="PIT_FUTURE_DATA", message="future data")],
        conclusion_level="not_reliable",
    )

    markdown = render_research_card_markdown(card)
    snapshot = Path(__file__).parent / "snapshots" / "research_card_markdown.md"

    assert markdown == snapshot.read_text(encoding="utf-8")
    assert "QUANT_OOS_MISSING" in markdown
    assert "PIT_FUTURE_DATA" in markdown
