"""Literal document integer quotations, never a pool of measured evidence.

An ungrouped integer has no unit: its size cannot distinguish a quantity from
an identifier. It may be repeated with its original label and an exact source
quotation, but cannot ground a renamed metric, a price or a derived operand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .figures import Declaration, Figure, _normalize


@dataclass(frozen=True)
class DocumentIntegerQuote:
    """One observed line eligible only for literal, source-scoped quotation."""

    call_id: str
    text: str
    digits: str
    sign: str
    label: str


def _label(text: str, start: int, end: int) -> str:
    """Keep the exact label on both sides of a number; ignore table spacing."""
    marked = text[:start] + "\x00" + text[end:]
    return "".join(c for c in _normalize(marked).text if not c.isspace() and c != "|")


def document_integer_quotes(
    text: str, figures: Sequence[Figure], call_id: str, limit: int
) -> list[DocumentIntegerQuote]:
    """Collect bounded single-number lines without asserting their numeric role.

    Args:
        text: The document text actually returned by the reader.
        figures: Its existing shape-only scan, including structural figures.
        call_id: Exact reader call that supplied the text.
        limit: Maximum number of quotations to retain.

    Returns:
        Literal bare-integer lines with a label, excluding scaled quantities,
        years, dates, recognized symbols, and ambiguous multi-number lines.
    """
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    by_line: dict[int, list[Figure]] = {}
    for figure in figures:
        by_line.setdefault(figure.line, []).append(figure)
    result = []
    for index, row in by_line.items():
        if len(result) >= limit:
            break
        if len(row) != 1 or index >= len(lines):
            continue
        figure = row[0]
        if figure.shape != "bare" or figure.scale != 1 or not figure.digits.isdigit():
            continue
        line = lines[index].rstrip("\r\n")
        label = _label(line, figure.start - offsets[index], figure.end - offsets[index])
        if sum(c.isalpha() for c in label) < 2:
            continue
        result.append(
            DocumentIntegerQuote(
                call_id, line.strip(), figure.digits, figure.sign, label
            )
        )
    return result


def matches_document_integer_quote(
    quotes: Sequence[DocumentIntegerQuote],
    figure: Figure,
    declaration: Declaration | None,
    line: str,
    line_offset: int,
) -> bool:
    """Accept only the same labelled integer, with an exact call and quote.

    Args:
        quotes: Literal lines from successful, permitted document reads.
        figure: The number in the answer.
        declaration: Its observed declaration; note must be ``quote: <line>``.
        line: The visible answer line, outside the hidden figures block.
        line_offset: The line's starting offset in the whole answer.

    Returns:
        Whether the source, written integer, and surrounding label all match.
        No currency, percent, magnitude, price-column or derived conversion is
        authorized by this path.
    """
    if (
        declaration is None
        or declaration.role != "observed"
        or figure.currency
        or figure.percent
        or figure.column
        or figure.scale != 1
        or not figure.digits.isdigit()
    ):
        return False
    label = _label(line, figure.start - line_offset, figure.end - line_offset)
    return any(
        declaration.ref == quote.call_id
        and declaration.note == f"quote: {quote.text}"
        and figure.digits == quote.digits
        and figure.sign == quote.sign
        and label == quote.label
        for quote in quotes
    )
