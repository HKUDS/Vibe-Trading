from __future__ import annotations

from src.research_card.model import ResearchCard, StructuredWarning
from src.research_card.render_html import render_research_card_html


def test_html_renderer_escapes_untrusted_text() -> None:
    card = ResearchCard(
        card_id="card_html",
        title="<script>alert('x')</script>",
        hypothesis="<b>not trusted</b>",
        warnings=[StructuredWarning(code="WARN", message="<img src=x onerror=alert(1)>")],
    )

    html = render_research_card_html(card)

    assert "<script>" not in html
    assert "<b>not trusted</b>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
