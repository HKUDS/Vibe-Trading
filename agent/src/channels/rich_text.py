"""Safe rich-text rendering for outbound email reports."""

from __future__ import annotations

import nh3
from mistune import create_markdown

_MARKDOWN = create_markdown(escape=True, plugins=["table", "strikethrough", "url"])

_ALLOWED_TAGS = {
    "p", "a", "strong", "em", "del", "code", "pre", "blockquote",
    "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "br", "table", "thead", "tbody", "tr", "th", "td",
}
_ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href"},
    "code": {"class"},
    "ol": {"start"},
}
_CLEANER = nh3.Cleaner(
    tags=_ALLOWED_TAGS,
    attributes=_ALLOWED_ATTRIBUTES,
    url_schemes={"https", "http", "mailto"},
    strip_comments=True,
    link_rel="noopener noreferrer",
)

_EMAIL_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
       color: #1f2937; line-height: 1.55; max-width: 860px; margin: 0 auto; padding: 24px; }
h1, h2, h3 { color: #111827; line-height: 1.25; }
h1 { font-size: 26px; } h2 { font-size: 21px; margin-top: 28px; }
h3 { font-size: 17px; margin-top: 22px; }
a { color: #2563eb; }
table { border-collapse: collapse; width: 100%; margin: 16px 0; }
th, td { border: 1px solid #d1d5db; padding: 8px 10px; text-align: left; }
th { background: #f3f4f6; }
blockquote { border-left: 4px solid #d1d5db; margin-left: 0; padding-left: 14px; color: #4b5563; }
code { background: #f3f4f6; padding: 2px 4px; border-radius: 4px; }
pre { background: #f3f4f6; padding: 12px; overflow-wrap: anywhere; white-space: pre-wrap; }
"""


def render_markdown_fragment(text: str) -> str:
    """Render Markdown to a conservative, sanitized HTML fragment."""
    return _CLEANER.clean(_MARKDOWN(text or "")).strip()


def render_email_html(text: str) -> str:
    """Render Markdown as a standalone HTML document suitable for email/PDF."""
    body = render_markdown_fragment(text)
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<style>{_EMAIL_CSS}</style></head><body>{body}</body></html>"
    )
