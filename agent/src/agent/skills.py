"""SkillsLoader: loads scenario guides from the skills/ directory.

Uses progressive disclosure at two levels:
- System prompt only injects one-line summaries (get_descriptions).
- Full docs loaded on demand (get_content, called by the load_skill tool).
- Inside one document, :func:`split_sections` maps the heading structure so the
  load_skill tool can hand back a skeleton plus one section at a time instead of
  a blind character page. Measured on the bundled corpus: 35 of the 88 skills
  do not fit a single tool result, and ``tushare`` delivers 9.1% of its 102,890
  characters in the first page — sequential paging means the agent must read ten
  more pages to reach a section it could have named.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Skill:
    """Single skill definition.

    Attributes:
        name: Skill name.
        description: Skill description.
        category: Skill category for grouped display.
        body: SKILL.md body text.
        dir_path: Skill directory path (used for on-demand loading of supporting files).
        metadata: Parsed frontmatter metadata.
    """

    name: str
    description: str = ""
    category: str = "other"
    body: str = ""
    dir_path: Optional[Path] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def load_support_file(self, filename: str) -> Optional[str]:
        """Load a supporting file on demand.

        Args:
            filename: File name (e.g. examples.md).

        Returns:
            File content or None.
        """
        if not self.dir_path:
            return None
        path = self.dir_path / filename
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return None


from src.agent.frontmatter import parse_frontmatter as _parse_frontmatter  # shared util


def _load_skill_dir(dir_path: Path) -> Optional[Skill]:
    """Load a skill from a directory.

    Args:
        dir_path: Skill directory path (must contain SKILL.md).

    Returns:
        Skill instance or None.
    """
    skill_file = dir_path / "SKILL.md"
    if not skill_file.exists():
        return None
    try:
        text = skill_file.read_text(encoding="utf-8")
    except Exception:
        return None

    meta, body = _parse_frontmatter(text)
    name = meta.get("name", dir_path.name)
    if not name:
        return None

    return Skill(
        name=name,
        description=meta.get("description", ""),
        category=meta.get("category", "other"),
        body=body,
        dir_path=dir_path,
        metadata=meta,
    )


USER_SKILLS_DIR = Path.home() / ".vibe-trading" / "skills" / "user"


class SkillsLoader:
    """Load skills from bundled skills/ directory and user skills directory.

    Attributes:
        skills: Loaded skill list (bundled + user-created).
    """

    def __init__(self, skills_dir: Optional[Path] = None,
                 user_skills_dir: Optional[Path] = None) -> None:
        """Initialize SkillsLoader.

        Args:
            skills_dir: Bundled skills directory path; defaults to agent/skills/.
            user_skills_dir: User-created skills directory; defaults to ~/.vibe-trading/skills/user/.
        """
        self.skills_dir = skills_dir or Path(__file__).resolve().parents[1] / "skills"
        self._user_skills_dir = user_skills_dir or USER_SKILLS_DIR
        self.skills: List[Skill] = []
        self._load()

    def _load(self) -> None:
        """Load all skill subdirectories from user and bundled directories.

        User skills are loaded first so they override bundled skills with the same name
        (e.g. after patch_skill copies and modifies a bundled skill).
        """
        seen_names: set[str] = set()
        for directory in (self._user_skills_dir, self.skills_dir):
            if not directory or not directory.exists():
                continue
            for path in sorted(directory.iterdir()):
                if path.is_dir() and (path / "SKILL.md").exists():
                    skill = _load_skill_dir(path)
                    if skill and skill.name not in seen_names:
                        self.skills.append(skill)
                        seen_names.add(skill.name)

    # Display order for categories (unlisted categories appear at the end).
    _CATEGORY_ORDER = [
        "data-source", "strategy", "analysis", "asset-class",
        "crypto", "flow", "tool", "other",
    ]

    def get_descriptions(self) -> str:
        """Return skills grouped by category for the system prompt.

        Returns:
            Grouped skill list with category headers.
        """
        if not self.skills:
            return "(no skills)"

        groups: Dict[str, List[Skill]] = {}
        for skill in self.skills:
            groups.setdefault(skill.category, []).append(skill)

        ordered_cats = [c for c in self._CATEGORY_ORDER if c in groups]
        ordered_cats += [c for c in sorted(groups) if c not in ordered_cats]

        lines: List[str] = []
        for cat in ordered_cats:
            lines.append(f"\n### {cat}")
            for skill in groups[cat]:
                lines.append(f"  - {skill.name}: {skill.description}")
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        """Return the full documentation for a skill (used by the load_skill tool).

        Falls back to disk lookup for user skills created mid-session.

        Args:
            name: Skill name.

        Returns:
            XML-wrapped full skill document, or an error message.
        """
        for skill in self.skills:
            if skill.name == name:
                return f'<skill name="{name}">\n{skill.body}\n</skill>'

        # Fallback: check user skills directory on disk (mid-session created skills)
        if self._user_skills_dir:
            skill = _load_skill_dir(self._user_skills_dir / name)
            if skill:
                self.skills.append(skill)
                return f'<skill name="{name}">\n{skill.body}\n</skill>'

        available = ", ".join(s.name for s in self.skills)
        return f"Error: Unknown skill '{name}'. Available: {available}"


# Markdown ATX heading, e.g. "## Authentication". Setext headings are not used
# in the bundled corpus and are deliberately not recognised.
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(\S.*?)[ \t]*#*[ \t]*$")

# A fenced block opener/closer: ``` or ~~~, optionally indented. Headings inside
# a fence are code comments (`# fmt: off`, shell prompts), not document
# structure, so the scanner must skip them.
_FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")

# Longest summary line kept per section in the outline.
_SUMMARY_CHARS = 110


@dataclass(frozen=True)
class SkillSection:
    """One heading-delimited span of a skill document.

    Attributes:
        level: Heading depth, 1 for ``#`` through 6 for ``######``.
        title: Heading text with the ``#`` markers stripped.
        start: Character offset of the heading line within the document.
        end: Character offset one past the section, subsections included.
        summary: First prose line under the heading, truncated.
    """

    level: int
    title: str
    start: int
    end: int
    summary: str = ""

    @property
    def chars(self) -> int:
        """Length of the section including every nested subsection."""
        return self.end - self.start


def split_sections(document: str) -> List[SkillSection]:
    """Map a markdown document to its heading structure.

    A section runs from its heading to the next heading of the same or shallower
    level, so asking for a ``##`` section yields that whole subtree rather than
    the paragraph before its first ``###``.

    Args:
        document: Full markdown text.

    Returns:
        Sections in document order; empty when the document has no headings
        outside fenced code blocks.
    """
    raw: List[Tuple[int, str, int, str]] = []  # level, title, start, summary
    offset = 0
    fenced = False
    pending: List[int] = []  # indices in ``raw`` still waiting for a summary
    for line in document.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        if _FENCE_RE.match(stripped):
            fenced = not fenced
        elif not fenced:
            heading = _HEADING_RE.match(stripped)
            if heading:
                raw.append((len(heading.group(1)), heading.group(2), offset, ""))
                pending.append(len(raw) - 1)
            elif pending and stripped.strip():
                # The prose belongs to the deepest heading just opened; any
                # shallower heading above it only introduced that subtree, so it
                # keeps an empty summary rather than stealing a later paragraph.
                index = pending[-1]
                pending.clear()
                summary = stripped.strip().lstrip("-*>| ").strip("*`").strip()
                if len(summary) > _SUMMARY_CHARS:
                    summary = summary[: _SUMMARY_CHARS - 1].rstrip() + "…"
                level, title, start, _ = raw[index]
                raw[index] = (level, title, start, summary)
        offset += len(line)

    total = len(document)
    sections: List[SkillSection] = []
    for index, (level, title, start, summary) in enumerate(raw):
        end = total
        for deeper_level, _, later_start, _ in raw[index + 1 :]:
            if deeper_level <= level:
                end = later_start
                break
        sections.append(SkillSection(level, title, start, end, summary))
    return sections


def _normalize_title(title: str) -> str:
    """Fold a heading to a comparable key (case, markers, spacing)."""
    return " ".join(title.replace("#", " ").split()).strip().casefold()


#: Separator for a path-qualified section address, e.g. ``"Mode 3 > Workflow"``.
#: Two bundled skills repeat a heading title (``correlation-regime`` has two
#: ``Workflow`` sections, ``pine-script`` two ``Template`` and two ``Syntax
#: Rules``), so a bare title cannot address them. No bundled heading contains
#: ``>``, which is what makes it safe as a separator.
PATH_SEPARATOR = ">"


def ancestor_titles(sections: List[SkillSection], index: int) -> List[str]:
    """Return the enclosing heading titles of ``sections[index]``, outermost first.

    Ancestry is derived from heading depth: walking backwards, each heading
    shallower than the deepest ancestor found so far encloses the target.

    Args:
        sections: Output of :func:`split_sections`.
        index: Position of the section whose ancestors are wanted.

    Returns:
        Titles from the outermost enclosing heading inwards; empty at top level.
    """
    ancestors: List[str] = []
    level = sections[index].level
    for candidate in reversed(sections[:index]):
        if candidate.level < level:
            ancestors.append(candidate.title)
            level = candidate.level
    ancestors.reverse()
    return ancestors


def qualified_path(sections: List[SkillSection], index: int) -> str:
    """Render the full ``"Parent > Child"`` address of one section."""
    parts = ancestor_titles(sections, index) + [sections[index].title]
    return f" {PATH_SEPARATOR} ".join(parts)


def find_sections(sections: List[SkillSection], wanted: str) -> List[SkillSection]:
    """Locate every section matching a heading address.

    ``wanted`` may be a bare title (``"Workflow"``) or a path that names one or
    more enclosing headings (``"Mode 3 > Workflow"``); the ancestors need not be
    contiguous or complete, they only have to appear in order above the target.
    Matching ignores case, ``#`` markers and repeated whitespace. An exact title
    match wins over a prefix match, and a prefix match is only consulted when no
    title matches exactly — so a longer heading can never shadow the exact one.

    Args:
        sections: Output of :func:`split_sections`.
        wanted: Section address as the caller typed it.

    Returns:
        Every match in document order — more than one means the address is
        ambiguous and the caller must disambiguate rather than guess.
    """
    parts = [part.strip() for part in wanted.split(PATH_SEPARATOR)]
    parts = [part for part in parts if part]
    if not parts:
        return []
    key = _normalize_title(parts[-1])
    wanted_ancestors = [_normalize_title(part) for part in parts[:-1]]
    if not key:
        return []

    def ancestors_match(index: int) -> bool:
        remaining = list(wanted_ancestors)
        for title in ancestor_titles(sections, index):
            if remaining and _normalize_title(title).startswith(remaining[0]):
                remaining.pop(0)
        return not remaining

    for predicate in (
        lambda title: _normalize_title(title) == key,
        lambda title: _normalize_title(title).startswith(key),
    ):
        matches = [
            section
            for index, section in enumerate(sections)
            if predicate(section.title) and ancestors_match(index)
        ]
        if matches:
            return matches
    return []


def find_section(sections: List[SkillSection], wanted: str) -> Optional[SkillSection]:
    """Locate a single section by heading address.

    Convenience wrapper over :func:`find_sections` that takes the first match.
    Callers that must not silently resolve an ambiguous address — the load_skill
    tool is one — should use :func:`find_sections` and report the ambiguity.

    Args:
        sections: Output of :func:`split_sections`.
        wanted: Section address as the caller typed it.

    Returns:
        The first matching section, or None.
    """
    matches = find_sections(sections, wanted)
    return matches[0] if matches else None
