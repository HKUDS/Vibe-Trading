"""Escaped HTML renderer for Research Cards."""

from __future__ import annotations

from html import escape

from src.research_card.model import ResearchCard


def render_research_card_html(card: ResearchCard) -> str:
    """Render escaped, self-contained HTML without accepting raw HTML."""
    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{escape(card.title)}</title>",
        "</head>",
        "<body>",
        f"<h1>Research Card: {escape(card.title)}</h1>",
        "<dl>",
        f"<dt>Card ID</dt><dd><code>{escape(card.card_id)}</code></dd>",
        f"<dt>Schema Version</dt><dd><code>{escape(card.schema_version)}</code></dd>",
        f"<dt>Conclusion</dt><dd><code>{escape(card.conclusion_level)}</code></dd>",
        "</dl>",
        "<h2>Hypothesis</h2>",
        f"<p>{escape(card.hypothesis or 'Not recorded.')}</p>",
    ]
    if card.warnings:
        parts.extend(["<h2>Warnings</h2>", "<ul>"])
        for warning in card.warnings:
            parts.append(
                f"<li><code>{escape(warning.code)}</code> "
                f"({escape(warning.severity)}): {escape(warning.message)}</li>"
            )
        parts.append("</ul>")
    if card.hard_failures:
        parts.extend(["<h2>Hard Failures</h2>", "<ul>"])
        for failure in card.hard_failures:
            parts.append(
                f"<li><code>{escape(failure.code)}</code> "
                f"({escape(failure.severity)}): {escape(failure.message)}</li>"
            )
        parts.append("</ul>")
    parts.extend(["</body>", "</html>"])
    return "\n".join(parts) + "\n"
