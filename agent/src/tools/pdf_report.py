"""Render Markdown reports to real PDFs without system rendering libraries."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape


def render_markdown_pdf(content: str, target: Path) -> None:
    """Render a paginated report atomically, retaining an old file on failure.

    Args:
        content: Markdown or plain text, never executable HTML.
        target: Already-authorized PDF output path.

    Raises:
        Exception: Rendering or writing failed; the target remains untouched.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from src.shadow_account.pdf_fallback import _ensure_font

    family = _ensure_font()
    pdfmetrics.registerFontFamily(family, normal=family, bold=family, italic=family, boldItalic=family)
    body = ParagraphStyle("report", fontName=family, fontSize=10, leading=15, wordWrap="CJK", spaceAfter=7)
    cell = ParagraphStyle("cell", parent=body, fontSize=8, leading=12, spaceAfter=0)
    code = ParagraphStyle("code", parent=body, backColor=colors.HexColor("#f3f1ed"), leftIndent=8)
    headings = {level: ParagraphStyle(f"h{level}", parent=body, fontSize=22 - level * 2,
                                     leading=27 - level * 2, spaceBefore=10, spaceAfter=8, keepWithNext=True)
                for level in range(1, 5)}
    width = A4[0] - 88
    story = []

    def inline(text: str) -> str:
        text = escape(text)
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
        return re.sub(r"`([^`]+)`", r"\1", text)

    lines = content.splitlines()
    position = 0
    in_code = False
    while position < len(lines):
        line = lines[position].strip()
        position += 1
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            story.append(Paragraph(escape(lines[position - 1]).replace(" ", "&#160;"), code))
            continue
        if not line:
            continue
        if line.startswith("|") and position < len(lines) and re.fullmatch(r"[| :\-]+", lines[position].strip()):
            rows = [[part.strip() for part in line.strip("|").split("|")]]
            position += 1
            while position < len(lines) and lines[position].strip().startswith("|"):
                rows.append([part.strip() for part in lines[position].strip().strip("|").split("|")])
                position += 1
            columns = max(map(len, rows))
            table = Table([[Paragraph(inline(value), cell) for value in row + [""] * (columns - len(row))]
                           for row in rows], colWidths=[width / columns] * columns, repeatRows=1,
                          splitInRow=1)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eee7da")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1c8b8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.extend([table, Spacer(1, 8)])
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)", line)
        if heading:
            story.append(Paragraph(inline(heading[2]), headings[len(heading[1])]))
        else:
            line = re.sub(r"^[-*+]\s+", "• ", line)
            line = re.sub(r"^>\s?", "", line)
            story.append(Paragraph(inline(line), body))
    if not story:
        story.append(Paragraph("&#160;", body))

    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".report-", suffix=".pdf", dir=target.parent)
    os.close(fd)
    try:
        document = SimpleDocTemplate(temporary, pagesize=A4, leftMargin=44, rightMargin=44,
                                     topMargin=42, bottomMargin=42, title=target.stem)
        document.build(story)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
