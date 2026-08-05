"""Structural tests for the ``investor-lenses`` skill.

The skill is pure markdown: a router ``SKILL.md`` plus one file per lens under
``references/``. Nothing here executes a lens — these tests guard the properties
that silently rot as lenses are added or renamed:

* the router is loadable by :class:`SkillsLoader` and lands in a real category;
* every lens file parses as frontmatter and declares the same metadata keys;
* the router index and the files on disk agree **in both directions**, so a
  renamed file cannot leave a dead index row and a new file cannot stay orphaned;
* every router link carries the ``investor-lenses/`` prefix and resolves through
  ``read_file`` (bare ``references/...`` links are unreachable — the skills root
  has no top-level ``references/`` directory);
* each lens keeps the sections the output contract depends on, the
  not-investment-advice disclaimer, and framework-conditional phrasing;
* no lens hardcodes a registered tool name, which is what keeps the lenses
  decoupled from the data layer.

No network access: every assertion is a local file read.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

import pytest

from src.agent.frontmatter import parse_frontmatter
from src.agent.skills import SkillsLoader
from src.tools.read_file_tool import ReadFileTool

import json

_SKILL_NAME = "investor-lenses"
_SKILLS_ROOT = Path(__file__).resolve().parents[1] / "src" / "skills"
_SKILL_DIR = _SKILLS_ROOT / _SKILL_NAME
_REFS_DIR = _SKILL_DIR / "references"

# Router index rows link to "investor-lenses/references/<slug>.md".
_INDEX_LINK_RE = re.compile(r"\]\((?P<target>[^)]*references/[^)]+\.md)\)")

# Metadata every lens file must declare.
_REQUIRED_LENS_KEYS = ("name", "lens", "attributed_to", "style", "markets", "description")

# Section headings the skill-level output contract depends on.
_REQUIRED_SECTIONS = (
    "## What this lens optimizes for",
    "## Market-fit note",
    "## Priority signals",
    "## Disqualifiers",
    "## Typical misuse",
    "## Falsifiers",
    "## Output contract",
)

_DISCLAIMER = "**Framework, not investment advice.**"

# Categories SkillsLoader knows how to group (src/agent/skills.py:_CATEGORY_ORDER).
_KNOWN_CATEGORIES = {
    "data-source", "strategy", "analysis", "asset-class",
    "crypto", "flow", "tool", "other",
}


def _lens_paths() -> List[Path]:
    """Return every lens markdown file on disk, sorted by name."""
    return sorted(_REFS_DIR.glob("*.md"))


def _router_text() -> str:
    """Return the raw router SKILL.md text."""
    return (_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")


def _lens_ids() -> List[str]:
    """Return lens slugs for parametrization (filename stems)."""
    return [path.stem for path in _lens_paths()]


def _lens_text(slug: str) -> str:
    """Return the raw text of one lens file.

    Args:
        slug: Lens file stem, e.g. ``munger-inversion``.

    Returns:
        Raw markdown text.
    """
    return (_REFS_DIR / f"{slug}.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Directory structure
# ---------------------------------------------------------------------------


def test_skill_directory_structure() -> None:
    """Router and references directory both exist."""
    assert (_SKILL_DIR / "SKILL.md").is_file()
    assert _REFS_DIR.is_dir()


def test_lens_count_within_declared_range() -> None:
    """The skill ships a meaningful but bounded number of lenses."""
    assert 8 <= len(_lens_paths()) <= 12, f"found {len(_lens_paths())} lens files"


def test_router_loads_through_skills_loader() -> None:
    """SkillsLoader picks the skill up with a usable name/description/category."""
    loader = SkillsLoader(
        skills_dir=_SKILLS_ROOT,
        user_skills_dir=Path("/nonexistent-user-skills-dir"),
    )
    skill = next((s for s in loader.skills if s.name == _SKILL_NAME), None)
    assert skill is not None, "investor-lenses not discovered by SkillsLoader"
    assert skill.description.strip(), "router description is empty"
    assert skill.category in _KNOWN_CATEGORIES
    assert skill.body.strip(), "router body is empty"


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------


def test_router_frontmatter_is_parseable() -> None:
    """Router frontmatter parses and names the skill after its directory."""
    meta, body = parse_frontmatter(_router_text())
    assert meta.get("name") == _SKILL_NAME
    assert meta.get("category") in _KNOWN_CATEGORIES
    assert meta.get("description", "").strip()
    assert body.startswith("# "), "router body must open with a markdown H1"


@pytest.mark.parametrize("slug", _lens_ids())
def test_lens_frontmatter_is_complete(slug: str) -> None:
    """Every lens declares the full metadata key set, and name matches filename."""
    meta, body = parse_frontmatter(_lens_text(slug))
    assert meta, f"{slug}.md has no parseable frontmatter"
    for key in _REQUIRED_LENS_KEYS:
        assert str(meta.get(key, "")).strip(), f"{slug}.md is missing frontmatter key '{key}'"
    assert meta["name"] == slug, f"{slug}.md declares name={meta['name']!r}"
    assert body.strip(), f"{slug}.md has an empty body"


def test_lens_styles_cover_distinct_schools() -> None:
    """Lenses span multiple styles rather than restating one school."""
    styles = {parse_frontmatter(_lens_text(slug))[0]["style"] for slug in _lens_ids()}
    assert len(styles) >= 6, f"only {len(styles)} distinct styles: {sorted(styles)}"


def test_china_market_coverage_is_represented() -> None:
    """At least three lenses speak to A-share / HK market structure."""
    hits = [slug for slug in _lens_ids() if "A-share" in _lens_text(slug)]
    assert len(hits) >= 3, f"only {hits} mention A-share market structure"


# ---------------------------------------------------------------------------
# Index integrity (both directions)
# ---------------------------------------------------------------------------


def _router_link_targets() -> List[str]:
    """Return every reference link target written in the router."""
    return [m.group("target") for m in _INDEX_LINK_RE.finditer(_router_text())]


def test_router_index_and_disk_agree_both_ways() -> None:
    """Every indexed lens exists, and every lens on disk is indexed."""
    indexed = {Path(t).stem for t in _router_link_targets()}
    on_disk = set(_lens_ids())
    assert indexed - on_disk == set(), f"router links to missing lenses: {sorted(indexed - on_disk)}"
    assert on_disk - indexed == set(), f"lens files absent from the router index: {sorted(on_disk - indexed)}"


@pytest.mark.parametrize("target", _router_link_targets())
def test_router_links_carry_skill_prefix(target: str) -> None:
    """Links are prefixed with the skill name so they resolve from the skills root."""
    assert target.startswith(f"{_SKILL_NAME}/"), (
        f"link must start with '{_SKILL_NAME}/', got: {target}"
    )


@pytest.mark.parametrize("target", _router_link_targets())
def test_router_links_resolve_through_read_file(target: str) -> None:
    """Each router link is reachable via the read_file tool's skills root."""
    body = json.loads(ReadFileTool().execute(path=target))
    assert body["status"] == "ok", f"{target} did not resolve: {body}"
    assert body["content"].strip()


# ---------------------------------------------------------------------------
# Lens content contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slug", _lens_ids())
def test_lens_has_required_sections(slug: str) -> None:
    """Each lens keeps the sections that make it an operable procedure."""
    text = _lens_text(slug)
    for heading in _REQUIRED_SECTIONS:
        assert heading in text, f"{slug}.md is missing section '{heading}'"


@pytest.mark.parametrize("slug", _lens_ids())
def test_lens_carries_disclaimer(slug: str) -> None:
    """Each lens states it is a framework and not investment advice."""
    assert _DISCLAIMER in _lens_text(slug)


@pytest.mark.parametrize("slug", _lens_ids())
def test_lens_requires_framework_conditional_verdict(slug: str) -> None:
    """The output contract of each lens demands a framework-conditional verdict.

    Checked inside the ``## Output contract`` section rather than the whole file,
    so the boilerplate disclaimer at the top cannot satisfy it.
    """
    parts = _lens_text(slug).split("## Output contract", 1)
    assert len(parts) == 2, f"{slug}.md has no output-contract section"
    # Prose is hard-wrapped, so collapse whitespace before matching phrases.
    contract = " ".join(parts[1].split())
    assert re.search(r"under (?:this|an?) [\w\- ]{0,40}?framework", contract), (
        f"{slug}.md output contract never requires a framework-conditional verdict"
    )
    assert "not investment advice" in contract, (
        f"{slug}.md output contract omits the not-investment-advice line"
    )


@pytest.mark.parametrize("slug", _lens_ids())
def test_lens_is_not_a_stub(slug: str) -> None:
    """Guard against placeholder lens files sneaking into the index."""
    assert len(_lens_text(slug)) > 2_500, f"{slug}.md looks like a stub"


# ---------------------------------------------------------------------------
# Decoupling from the data layer
# ---------------------------------------------------------------------------


def _registered_multiword_tool_names() -> List[str]:
    """Return registered tool names containing an underscore.

    Single-word tool names (``bash``, ``pattern``, ``sentiment``) are ordinary
    English words and cannot be distinguished from prose, so only the snake_case
    names are checked.

    Returns:
        Sorted list of multi-word tool names.
    """
    from src.tools import _discover_subclasses

    return sorted({c.name for c in _discover_subclasses() if c.name and "_" in c.name})


@pytest.mark.parametrize("slug", _lens_ids())
def test_lens_does_not_hardcode_tool_names(slug: str) -> None:
    """Lenses describe reasoning only; naming a tool would couple them to the data layer."""
    text = _lens_text(slug)
    leaked = [name for name in _registered_multiword_tool_names() if name in text]
    assert not leaked, f"{slug}.md hardcodes tool name(s): {leaked}"


def test_router_does_not_hardcode_tool_names() -> None:
    """The router routes between lenses by markdown link, not by tool name."""
    text = _router_text()
    leaked = [name for name in _registered_multiword_tool_names() if name in text]
    assert not leaked, f"SKILL.md hardcodes tool name(s): {leaked}"
