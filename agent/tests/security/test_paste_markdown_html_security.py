from __future__ import annotations

from src.alpha_foundry.reports.builder import build_alpha_genesis_report
from src.alpha_foundry.reports.render_markdown import render_markdown


def test_alpha_genesis_markdown_escapes_html_and_dangerous_links() -> None:
    report = build_alpha_genesis_report(
        report_id="md",
        candidate_id="<img src=x onerror=alert(1)>",
        limitations=[
            "<script>alert(1)</script>",
            "[open](javascript:alert(1))",
            "![x](data:text/html;base64,PHNjcmlwdD4=)",
        ],
    )

    markdown = render_markdown(report)
    lowered = markdown.lower()

    assert "<script" not in lowered
    assert "<img" not in lowered
    assert "javascript:" not in lowered
    assert "data:text/html" not in lowered
    assert "&lt;script" in markdown
