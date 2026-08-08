"""Load skill tool: load a skill document as a skeleton, a section, or pages.

Skill documents *are* the implementation for a large part of this product — the
bond maths, the implied-vol solver, the impact models and the China market
structure all live in markdown the agent reads and executes. A tool result is
capped at :data:`src.config.limits.TOOL_RESULT_LIMIT` characters, and measured on
the bundled corpus 35 of the 88 skills do not fit one result: ``tushare``
delivers 9.1% of its 102,890 characters in a page, ``social-media-intelligence``
23.2%, ``options-payoff`` 32.0%.

Character paging alone makes those documents reachable but not usable — to see
one named section the agent has to walk every page before it. So an oversized
document is answered first with a *skeleton*: the heading tree, each section's
size and first line, plus the document's own opening text. The agent then names
the section it wants. Sequential ``offset`` paging is unchanged and remains the
escape hatch for documents with no headings, and for reading a giant section
whole.

Short skills — the 53 that fit — are returned complete in one call exactly as
before, and the trigger is the delivered envelope rather than a size guess, so a
document that fits by one character is never turned into a map.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from src.agent.skills import (
    SkillSection,
    SkillsLoader,
    find_sections,
    qualified_path,
    split_sections,
)
from src.agent.tools import BaseTool
from src.config.limits import TOOL_RESULT_LIMIT

# Characters of skill body per page. The cap applies to the whole serialized
# envelope, so this leaves room for the surrounding JSON keys and counters.
_PAGE_CHARS = TOOL_RESULT_LIMIT - 600

# Floor on the shrink loop so a pathologically escape-heavy document still makes
# forward progress rather than paging one character at a time.
_MIN_PAGE_CHARS = 1_000

# Ceiling on the rendered heading map, so the skeleton never crowds out the
# document text that ships alongside it.
_OUTLINE_CHARS = 4_500

# Section titles listed back when a requested section does not exist.
_SUGGEST_SECTIONS = 40


def _render_outline(name: str, sections: List[SkillSection], total: int) -> str:
    """Render the heading tree of a skill within :data:`_OUTLINE_CHARS`.

    Detail is dropped in tiers rather than cutting the tail, so the agent always
    sees the complete list of section names it is allowed to ask for.

    Args:
        name: Skill name, echoed into the usage hint.
        sections: Output of :func:`src.agent.skills.split_sections`.
        total: Length of the whole document.

    Returns:
        A markdown outline, truncated with a notice only as a last resort.
    """
    header = (
        f"{len(sections)} sections, {total:,} characters total. Only the opening "
        f"text is in `content`.\nCall load_skill(name={name!r}, "
        f'section="<copy a label below verbatim>") to pull one section in full, or '
        f"load_skill(name={name!r}, offset=<next_offset>) to keep reading "
        f"straight through.\nSizes include nested subsections."
    )
    # A title that occurs twice cannot be addressed by name, so those entries —
    # and only those — are listed by their full "Parent > Child" path. Without
    # this the agent copies a name out of the outline and silently receives the
    # other section of the same name.
    repeated = {
        title
        for title in (s.title for s in sections)
        if sum(1 for s in sections if s.title == title) > 1
    }
    labels = [
        qualified_path(sections, index) if section.title in repeated else section.title
        for index, section in enumerate(sections)
    ]

    text = ""
    for with_summary, max_level in ((True, 6), (False, 6), (False, 2)):
        lines = [header]
        for section, label in zip(sections, labels):
            if section.level > max_level:
                continue
            line = f"{'  ' * (section.level - 1)}- {label} ({section.chars:,} chars)"
            if with_summary and section.summary:
                line += f" — {section.summary}"
            lines.append(line)
        text = "\n".join(lines)
        if len(text) <= _OUTLINE_CHARS:
            return text
    return text[: _OUTLINE_CHARS - 40].rstrip() + "\n… outline truncated."


def _paged(base: Dict[str, Any], body: str, offset: int, budget: int) -> Tuple[str, bool]:
    """Serialize ``base`` plus the page of ``body`` at ``offset``.

    The cap applies to the serialized envelope and JSON escaping is
    content-dependent — a newline-dense page costs two characters per line
    break — so the page is sized by what it actually serializes to.

    Args:
        base: Envelope keys other than the page and its counters.
        body: Text being paged (a whole document, or one section of one).
        offset: Character offset into ``body``.
        budget: First guess at the page size.

    Returns:
        A JSON envelope of at most :data:`TOOL_RESULT_LIMIT` characters, and
        whether it carried ``body`` to its end.
    """
    size = max(budget, _MIN_PAGE_CHARS)
    while True:
        page = body[offset : offset + size]
        next_offset = offset + len(page)
        complete = next_offset >= len(body)
        envelope = json.dumps(
            {
                **base,
                "content": page,
                "offset": offset,
                "next_offset": None if complete else next_offset,
                "complete": complete,
            },
            ensure_ascii=False,
        )
        if len(envelope) <= TOOL_RESULT_LIMIT or size <= _MIN_PAGE_CHARS:
            return envelope, complete
        # Shrink proportionally to the overflow, then a little further so a
        # page dense in escapes still converges in a couple of rounds.
        size = max(_MIN_PAGE_CHARS, int(size * TOOL_RESULT_LIMIT / len(envelope)) - 64)


def _error(message: str) -> str:
    """Return the shared error envelope."""
    return json.dumps({"status": "error", "content": message}, ensure_ascii=False)


class LoadSkillTool(BaseTool):
    """Load the documentation for a named skill, whole or section by section."""

    name = "load_skill"
    description = (
        "Load documentation for a named skill. Use this to learn about "
        "unfamiliar strategy patterns or workflows before starting. A skill that "
        "fits comes back complete. A long one comes back as an outline of its "
        "sections plus its opening text: call again with section=\"<title from "
        "the outline>\" for that section in full, or with offset=next_offset to "
        "read straight through."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name (e.g. 'strategy-generate', 'momentum')"},
            "section": {
                "type": "string",
                "description": (
                    "Label of one section from a previous outline result, copied "
                    "verbatim. Returns that heading and everything under it. A "
                    "title the document uses twice must be given as the "
                    '"Parent > Child" path the outline shows for it.'
                ),
            },
            "offset": {
                "type": "integer",
                "description": (
                    "Character offset to read from; defaults to 0. Pass the "
                    "next_offset value from a previous call to continue. With "
                    "section set, the offset is relative to that section."
                ),
            },
        },
        "required": ["name"],
    }
    repeatable = True

    def __init__(self, skills_loader: SkillsLoader | None = None) -> None:
        """Initialize LoadSkillTool.

        Args:
            skills_loader: SkillsLoader instance; creates one automatically if omitted.
        """
        self._loader = skills_loader or SkillsLoader()

    def execute(self, **kwargs: Any) -> str:
        """Load a skill as a skeleton, a named section, or a character page.

        Args:
            **kwargs: Must include ``name``; may include ``section`` and
                ``offset``.

        Returns:
            A JSON envelope whose ``mode`` says which of the three it is. Every
            mode carries ``offset``, ``next_offset`` and ``complete`` so a
            partial read is never mistaken for the whole thing; in ``section``
            mode those counters describe the section, and ``document_chars``
            gives the size of the document it came from.

        Raises:
            KeyError: If ``name`` is missing.
        """
        name = kwargs["name"]
        content = self._loader.get_content(name)
        if content.startswith("Error:"):
            return json.dumps({"status": "error", "content": content}, ensure_ascii=False)

        raw_offset = kwargs.get("offset")
        try:
            offset = max(int(raw_offset or 0), 0)
        except (TypeError, ValueError):
            return _error("Error: offset must be an integer")

        total = len(content)
        section_name = (kwargs.get("section") or "").strip()

        if section_name:
            sections = split_sections(content)
            matches = find_sections(sections, section_name)
            if not matches:
                titles = ", ".join(repr(s.title) for s in sections[:_SUGGEST_SECTIONS])
                return _error(
                    f"Error: skill {name!r} has no section {section_name!r}. "
                    f"Sections: {titles or '(none — this document has no headings)'}"
                )
            if len(matches) > 1:
                # Returning the first would be a silent wrong answer: the caller
                # asked for a name that names two different spans.
                paths = ", ".join(
                    repr(qualified_path(sections, sections.index(match)))
                    for match in matches[:_SUGGEST_SECTIONS]
                )
                return _error(
                    f"Error: section {section_name!r} is ambiguous in skill {name!r} "
                    f"({len(matches)} sections match). Re-request one of: {paths}"
                )
            section = matches[0]
            body = content[section.start : section.end]
            if offset >= len(body):
                return _error(
                    f"Error: offset {offset} is past the end of section "
                    f"{section.title!r} ({len(body)} characters)"
                )
            envelope, _ = _paged(
                {
                    "status": "ok",
                    "mode": "section",
                    "section": section.title,
                    "section_start": section.start,
                    "total_chars": len(body),
                    "document_chars": total,
                },
                body,
                offset,
                _PAGE_CHARS,
            )
            return envelope

        if offset >= total and total:
            return _error(
                f"Error: offset {offset} is past the end of skill {name!r} "
                f"({total} characters)"
            )

        document, complete = _paged(
            {"status": "ok", "mode": "document", "total_chars": total},
            content,
            offset,
            _PAGE_CHARS,
        )

        # An opening read that could not carry the whole document answers with
        # the heading map plus the document's own opening text, so the next call
        # can name a section instead of walking every page to find it. The
        # trigger is the delivered envelope, not a size guess, so a document that
        # fits by one character is never mapped. An explicit offset means the
        # caller is already paging deliberately: leave it alone.
        if complete or raw_offset is not None:
            return document
        sections = split_sections(content)
        if not sections:
            return document
        outline = _render_outline(name, sections, total)
        mapped, _ = _paged(
            {
                "status": "ok",
                "mode": "outline",
                "total_chars": total,
                "section_count": len(sections),
                "outline": outline,
            },
            content,
            0,
            max(_PAGE_CHARS - len(outline), _MIN_PAGE_CHARS),
        )
        return mapped
