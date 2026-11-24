"""Load skill summaries, full documents and individually addressable sections."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.product.resources.frontmatter import parse_frontmatter


@dataclass
class Skill:
    """Single skill definition."""

    name: str
    description: str = ""
    category: str = "other"
    body: str = ""
    dir_path: Optional[Path] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

def _load_skill_dir(dir_path: Path) -> Optional[Skill]:
    """Load a skill from a directory."""
    skill_file = dir_path / "SKILL.md"
    try:
        text = skill_file.read_text(encoding="utf-8")
    except Exception:
        return None

    meta, body = parse_frontmatter(text)
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
    """Load skills from the bundled and user skills directories.

    Args:
        skills_dir: Bundled skills directory to scan, if overriding the package default.
        user_skills_dir: User skills directory to scan, if overriding the runtime default.
    """

    def __init__(self, skills_dir: Optional[Path] = None,
                 user_skills_dir: Optional[Path] = None) -> None:
        """Initialize SkillsLoader."""
        self.skills_dir = skills_dir or Path(__file__).resolve().parents[2] / "skills"
        self._user_skills_dir = user_skills_dir or USER_SKILLS_DIR
        self.skills: List[Skill] = []
        self._load()

    def _load(self) -> None:
        """Load user skills first so they override bundled skills of the same name."""
        seen_names: set[str] = set()
        for directory in (self._user_skills_dir, self.skills_dir):
            if not directory or not directory.exists():
                continue
            for path in sorted(directory.iterdir()):
                skill = _load_skill_dir(path) if path.is_dir() else None
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
            Grouped skill list with category headers, or a marker when no skills are loaded.
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
        """Return the full documentation for a skill used by the load_skill tool.

        Falls back to disk lookup for user skills created mid-session.

        Args:
            name: Skill name to look up.

        Returns:
            XML-wrapped full skill document, or an error message listing available skills.
        """
        for skill in self.skills:
            if skill.name == name:
                return f'<skill name="{name}">\n{skill.body}\n</skill>'

        if self._user_skills_dir:
            skill = _load_skill_dir(self._user_skills_dir / name)
            if skill:
                if not any(existing.name == skill.name for existing in self.skills):
                    self.skills.append(skill)
                return f'<skill name="{name}">\n{skill.body}\n</skill>'

        available = ", ".join(s.name for s in self.skills)
        return f"Error: Unknown skill '{name}'. Available: {available}"


_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(\S.*?)[ \t]*#*[ \t]*$")

# Ignore apparent headings inside code fences.
_FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")

_SUMMARY_CHARS = 110


@dataclass(frozen=True)
class SkillSection:
    """One heading-delimited span of a skill document."""

    level: int
    title: str
    start: int
    end: int
    summary: str = ""

    @property
    def chars(self) -> int:
        """Measure the section including every nested subsection.

        Returns:
            Number of characters between the section's start and end offsets.
        """
        return self.end - self.start


def split_sections(document: str) -> List[SkillSection]:
    """Map a markdown document to its heading structure.

    A section runs from its heading to the next heading of the same or shallower
    level, so it includes the entire subtree.

    Args:
        document: Full markdown text.

    Returns:
        Sections in document order, or an empty list when no headings appear
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
                # A parent that only introduces its child keeps an empty summary.
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


PATH_SEPARATOR = ">"


def ancestor_titles(sections: List[SkillSection], index: int) -> List[str]:
    """Return the enclosing heading titles of sections[index], outermost first.

    Args:
        sections: Sections in the document order produced by split_sections.
        index: Position of the section whose ancestors are wanted.

    Returns:
        Titles from the outermost enclosing heading inwards, or an empty list at top level.
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
    """Render the full "Parent > Child" address of one section.

    Args:
        sections: Sections in the document order produced by split_sections.
        index: Position of the section to address.

    Returns:
        The heading title preceded by its enclosing headings, if any.
    """
    parts = ancestor_titles(sections, index) + [sections[index].title]
    return f" {PATH_SEPARATOR} ".join(parts)


def find_sections(sections: List[SkillSection], wanted: str) -> List[SkillSection]:
    """Locate every section matching a heading address.

    Args:
        sections: Sections in the document order produced by split_sections.
        wanted: A title or an ordered chain of ancestor titles separated by `>`.

    Returns:
        All matches in document order at the first successful tier of
        case-exact, case-folded, or prefix search. Multiple results indicate ambiguity.
    """
    parts = [part.strip() for part in wanted.split(PATH_SEPARATOR)]
    parts = [part for part in parts if part]
    if not parts:
        return []
    leaf_exact = " ".join(parts[-1].replace("#", " ").split())
    key = leaf_exact.casefold()
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
        # A case-exact qualified address must disambiguate headings that differ only by case.
        lambda title: " ".join(title.replace("#", " ").split()) == leaf_exact,
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

    Args:
        sections: Sections in the document order produced by split_sections.
        wanted: Section address as the caller typed it.

    Returns:
        The first matching section, or None if there are no matches.
    """
    matches = find_sections(sections, wanted)
    return matches[0] if matches else None
