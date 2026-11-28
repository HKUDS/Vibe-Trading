"""Extract citable passages from a single EDGAR HTML primary document."""

from __future__ import annotations

import re
from collections.abc import Iterator
from html.parser import HTMLParser
from typing import Any

_ITEM_NUMBER = r"[0-9]{1,2}(?:\.[0-9]{2}|[a-z])?"
_ITEM_HEADING = re.compile(
    rf"^(?i:item\s+({_ITEM_NUMBER}))\b(?=\s*[.:–—-]|\s*$|\s+[A-Z])"
)
_ITEM_SELECTOR = re.compile(rf"(?:item\s+)?({_ITEM_NUMBER})\.?", re.IGNORECASE)
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCKS = _HEADINGS | {
    "p",
    "div",
    "li",
    "tr",
    "br",
    "section",
    "article",
    "table",
    "pre",
}
_HIDDEN = {"head", "script", "style", "template", "noscript", "ix:header", "ix:hidden"}
_VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_HIDDEN_STYLE = re.compile(
    r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\b", re.I
)
_MAX_HEADING = 160
_MAX_EXCERPTS = 4
_PASSAGE_CHARS = 700
_CONTROLS = str.maketrans({i: " " for i in range(32)})


def item_number(value: str) -> str:
    """Normalize an SEC item selector such as 'Item 1A' or '2.02'."""
    match = _ITEM_SELECTOR.fullmatch(value.strip()) if isinstance(value, str) else None
    if match is None:
        raise ValueError("item must be an SEC item number such as '1A' or '2.02'")
    return match.group(1).upper()


class _FilingHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, bool, bool]] = []
        self._parts: list[str] = []
        self._hidden_tag = ""
        self._hidden_depth = 0
        self._heading = False
        self._inside_link = False
        self._linked = False
        self._row_depth = 0

    def flush(self) -> None:
        text = " ".join("".join(self._parts).translate(_CONTROLS).split())
        if text:
            self.blocks.append((text, self._heading, self._linked))
        self._parts.clear()
        self._linked = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._hidden_depth:
            if tag == self._hidden_tag:
                self._hidden_depth += 1
            return
        attributes = dict(attrs)
        if tag not in _VOID and (
            tag in _HIDDEN
            or "hidden" in attributes
            or (attributes.get("aria-hidden") or "").lower() == "true"
            or _HIDDEN_STYLE.search(attributes.get("style") or "")
        ):
            self._hidden_tag = tag
            self._hidden_depth = 1
            return
        if tag == "tr":
            self.flush()
            self._row_depth += 1
        elif tag in _BLOCKS:
            if self._row_depth:
                self._parts.append(" ")
            else:
                self.flush()
        if tag in _HEADINGS:
            self._heading = True
        elif tag in {"td", "th"}:
            self._parts.append(" ")
        elif tag == "a":
            self._inside_link = (attributes.get("href") or "").startswith("#")

    def handle_endtag(self, tag: str) -> None:
        if self._hidden_depth:
            if tag == self._hidden_tag:
                self._hidden_depth -= 1
            return
        if tag == "tr":
            self.flush()
            self._row_depth = max(0, self._row_depth - 1)
        elif tag in _BLOCKS:
            if self._row_depth:
                self._parts.append(" ")
            else:
                self.flush()
        if tag in _HEADINGS:
            self._heading = False
        elif tag == "a":
            self._inside_link = False

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self._parts.append(data)
            if self._inside_link and data.strip():
                self._linked = True


def _blocks(html: str) -> Iterator[tuple[str, bool, bool]]:
    parser = _FilingHTML()
    chunk_size = 64 * 1024
    for start in range(0, len(html), chunk_size):
        parser.feed(html[start : start + chunk_size])
        yield from parser.blocks
        parser.blocks.clear()
    parser.close()
    parser.flush()
    yield from parser.blocks


def extract_excerpts(html: str, item: str | None = None) -> dict[str, Any]:
    """Return ordered, bounded passages for the document or its first matching item.

    Args:
        html: Decoded primary-document HTML.
        item: Normalized SEC item number, if a specific item was requested.

    Returns:
        Excerpts with the nearest heading and a truncation flag for the selection.

    Raises:
        ValueError: The requested item or its visible body text was unavailable.
    """
    selected = item is None
    heading = None
    excerpts = []
    truncated = False
    for text, heading_tag, linked in _blocks(html):
        match = _ITEM_HEADING.match(text) if len(text) <= _MAX_HEADING else None
        # EDGAR contents tables often repeat the exact heading as a fragment link.
        if match and (
            linked or re.search(r"\s(?:\.{2,}\s*)?[0-9]+$", text[match.end() :])
        ):
            continue
        if match:
            number = match.group(1).upper()
            if item and selected and number != item:
                break
            selected = item is None or number == item
            heading = text
        elif selected and heading_tag and len(text) <= _MAX_HEADING:
            heading = text
        elif selected:
            if len(excerpts) == _MAX_EXCERPTS:
                truncated = True
                break
            excerpts.append({"heading": heading, "text": text[:_PASSAGE_CHARS]})
            truncated |= len(text) > _PASSAGE_CHARS
    if not excerpts:
        if item and not selected:
            raise ValueError(f"Could not locate Item {item} in the primary document")
        raise ValueError("The selected filing or item contains no readable body text")
    return {"excerpts": excerpts, "truncated": truncated}
