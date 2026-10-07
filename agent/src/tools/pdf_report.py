"""Render Markdown reports to real PDFs without system rendering libraries."""

from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from functools import lru_cache
from itertools import groupby
from pathlib import Path
from xml.sax.saxutils import escape



@lru_cache(maxsize=1)
def _arabic_font() -> str:
    """Register the Arabic-capable font already shipped by Matplotlib."""
    import matplotlib
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    family = "VibeReportArabic"
    path = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
    pdfmetrics.registerFont(TTFont(family, str(path)))
    pdfmetrics.registerFontFamily(family, normal=family, bold=family, italic=family, boldItalic=family)
    return family


@lru_cache(maxsize=1)
def _reshaper():
    """Keep Arabic vowel marks when shaping for visual RTL order."""
    import arabic_reshaper

    return arabic_reshaper.ArabicReshaper(configuration={
        "delete_harakat": False, "shift_harakat_position": True,
    })


def _visual_line(text: str, direction: str) -> str:
    """Shape Arabic and apply the Unicode bidi algorithm to one logical line."""
    from bidi.algorithm import get_display

    return get_display(_reshaper().reshape(text), base_dir=direction)


def _font_runs(text: str, cjk: str, arabic: str) -> list[tuple[str, str]]:
    """Select embedded fonts by real glyph coverage; never emit missing boxes."""
    from reportlab.pdfbase import pdfmetrics

    coverage = {family: pdfmetrics.getFont(family).face.charToGlyph for family in (arabic, cjk)}

    def select(char: str) -> str:
        for family, cmap in coverage.items():
            if cmap.get(ord(char), 0):
                return family
        raise ValueError(f"PDF fonts do not cover U+{ord(char):04X}")

    return [(family, "".join(chars)) for family, chars in groupby(text, key=select)]


def _rtl_lines(text: str, width: float, size: float, cjk: str, arabic: str) -> tuple[list[tuple[str, str]], str]:
    """Wrap logical text before shaping/reordering each visual line.

    Reordering the whole paragraph before wrapping reverses its line order.
    Widths use the actual shaped glyphs and the font selected for each run.
    """
    from bidi.algorithm import get_base_level
    from reportlab.pdfbase.pdfmetrics import stringWidth

    direction = "R" if get_base_level(text) else "L"

    def fits(value: str) -> bool:
        visual = _visual_line(value, direction)
        return sum(stringWidth(run, family, size) for family, run in _font_runs(visual, cjk, arabic)) <= width

    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if fits(candidate):
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        if fits(word):
            current = word
            continue
        # A long URL or CJK run has no word separator. Split in logical order,
        # keeping combining marks attached to their base character.
        clusters: list[str] = []
        for char in word:
            if clusters and unicodedata.combining(char):
                clusters[-1] += char
            else:
                clusters.append(char)
        for cluster in clusters:
            if current and not fits(current + cluster):
                lines.append(current)
                current = ""
            if not fits(cluster):
                raise ValueError("A PDF glyph is wider than the report column")
            current += cluster
    if current:
        lines.append(current)
    return [(line, _visual_line(line, direction)) for line in lines], direction


def _paragraph(markup: str, style, cjk: str):
    """Keep the standard layout for LTR/CJK and reorder RTL after line breaks."""
    from reportlab.platypus import Flowable, Paragraph

    logical = Paragraph(markup, style)
    text = logical.getPlainText()
    if not any(unicodedata.bidirectional(char) in {"R", "AL"} for char in text):
        return logical

    class BidirectionalParagraph(Flowable):
        def __init__(self, prepared=None, direction=None):
            super().__init__()
            self.style = style
            self.lines = prepared
            self.direction = direction

        def wrap(self, availWidth, availHeight):
            if self.lines is None:
                self.lines, self.direction = _rtl_lines(
                    text, max(1, availWidth - style.leftIndent - style.rightIndent),
                    style.fontSize, cjk, _arabic_font(),
                )
            self.width = availWidth
            self.height = len(self.lines) * style.leading
            return self.width, self.height

        def split(self, availWidth, availHeight):
            self.wrap(availWidth, availHeight)
            count = int(availHeight // style.leading)
            if count <= 0:
                return []
            first = BidirectionalParagraph(self.lines[:count], self.direction)
            rest = BidirectionalParagraph(self.lines[count:], self.direction)
            first.spaceAfter = 0
            rest.spaceBefore = 0
            return [first, rest] if rest.lines else [first]

        def draw(self):
            from reportlab.pdfbase.pdfmetrics import stringWidth

            canvas = self.canv
            canvas.saveState()
            if style.backColor:
                canvas.setFillColor(style.backColor)
                canvas.rect(0, 0, self.width, self.height, stroke=0, fill=1)
            canvas.setFillColor(style.textColor)
            for index, (logical_line, visual) in enumerate(self.lines):
                runs = _font_runs(visual, cjk, _arabic_font())
                width = sum(stringWidth(run, family, style.fontSize) for family, run in runs)
                x = self.width - style.rightIndent - width if self.direction == "R" else style.leftIndent
                y = self.height - (index + 1) * style.leading + max(0, (style.leading - style.fontSize) / 2)
                # PDF ActualText supplies canonical logical text for copy/search;
                # glyph positions remain the shaped visual order. Hex UTF-16BE
                # keeps user text out of PDF operator syntax.
                actual = ("\ufeff" + logical_line).encode("utf-16-be").hex()
                canvas._code.append(f"/Span << /ActualText <{actual}> >> BDC")
                for family, run in runs:
                    canvas.setFont(family, style.fontSize)
                    canvas.drawString(x, y, run)
                    x += stringWidth(run, family, style.fontSize)
                canvas._code.append("EMC")
            canvas.restoreState()

    return BidirectionalParagraph()

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
            story.append(_paragraph(escape(lines[position - 1]).replace(" ", "&#160;"), code, family))
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
            table = Table([[_paragraph(inline(value), cell, family) for value in row + [""] * (columns - len(row))]
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
            story.append(_paragraph(inline(heading[2]), headings[len(heading[1])], family))
        else:
            line = re.sub(r"^[-*+]\s+", "• ", line)
            line = re.sub(r"^>\s?", "", line)
            story.append(_paragraph(inline(line), body, family))
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
