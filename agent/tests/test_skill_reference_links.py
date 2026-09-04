"""Regression tests: every ``references/`` link in data-source SKILL.md files
resolves for **both** readers — a browser on GitHub and the ``read_file`` tool.

Background:
    A SKILL.md link is followed by two consumers. GitHub resolves it relative
    to the containing directory; ``read_file`` roots reads at the bundled
    ``skills/`` directory. Those two only agree on the document-relative form
    (``references/...``), so that is what these files are written with and what
    these tests lock in. The skill-name-prefixed form these tables used to
    carry resolved for the agent but 404'd for every human who clicked it.
    ``read_file`` reaches the document-relative form by resolving it against
    the skill that owns it — see ``test_read_file_skill_relative.py`` for that
    path, and note that it reports an ambiguous path rather than guessing, so
    ``test_reference_links_resolve_through_read_file`` below fails loudly if
    two skills ever ship the same reference path.

No live API is touched: ``read_file`` performs local filesystem reads of the
bundled skill docs only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Tuple

import pytest

from src.tools.read_file_tool import _SKILL_RELATIVE_PREFIXES, ReadFileTool

# Bundled skills root (mirrors ReadFileTool's own allowed-root computation).
_SKILLS_DIR = Path(__file__).resolve().parents[1] / "src" / "skills"

# Markdown link whose target is a references/*.md or scripts/*.py path, e.g.
# "[label](references/foo/bar.md)" or "[ex](scripts/x.py)". Written wide enough
# to still catch a skill-name-prefixed target, so a link that regresses to that
# form is caught by the assertions rather than skipped by the scanner.
# The target itself may contain parentheses (some tushare filenames do, e.g.
# "社融增量(月度).md"), so anchor on the trailing ".md)"/".py)" rather than the
# first ")". It must not contain "]" or a newline, though: excluding only "("
# let a match start at one link's "](" and run through the prose to a later
# link's ".py)", capturing a paragraph as a single "target".
_MD_LINK_RE = re.compile(
    r"\]\((?P<target>[^\]\n]*?(?:references/|scripts/)[^\]\n]*?\.(?:md|py))\)"
)


def _skills_with_reference_links() -> Tuple[str, ...]:
    """Return every bundled skill whose SKILL.md links into its own tree.

    Discovered, never listed. A hand-written tuple named five skills and let the
    others drift out of coverage: ``chanlun`` and ``ashare-pre-st-filter``
    shipped 8 links nothing was looking at, precisely because nothing was
    looking at them.
    """
    return tuple(
        sorted(
            path.parent.name
            for path in _SKILLS_DIR.rglob("SKILL.md")
            if _MD_LINK_RE.search(path.read_text(encoding="utf-8"))
        )
    )


#: Skills whose SKILL.md links into a references/ and/or scripts/ tree.
_SKILLS_UNDER_TEST = _skills_with_reference_links()


def _extract_reference_links(skill: str) -> List[str]:
    """Return every markdown link target containing ``references/``.

    Args:
        skill: Skill directory name (e.g. ``tushare``).

    Returns:
        List of raw link targets as written in SKILL.md.
    """
    text = (_SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
    return [m.group("target") for m in _MD_LINK_RE.finditer(text)]


def _read(path: str) -> dict:
    """Resolve a path through the read_file tool and return the parsed body.

    Args:
        path: Path argument passed to read_file (no run_dir; skills/ root).

    Returns:
        Parsed JSON response from ReadFileTool.execute.
    """
    return json.loads(ReadFileTool().execute(path=path))


def _all_links() -> List[Tuple[str, str]]:
    """Collect (skill, link) pairs across all skills under test."""
    pairs: List[Tuple[str, str]] = []
    for skill in _SKILLS_UNDER_TEST:
        for link in _extract_reference_links(skill):
            pairs.append((skill, link))
    return pairs


def test_skills_have_reference_links() -> None:
    """Sanity: each skill under test exposes references/ links to validate."""
    for skill in _SKILLS_UNDER_TEST:
        assert _extract_reference_links(skill), f"{skill} has no references/ links"


def test_every_skill_with_reference_links_is_covered() -> None:
    """Discovery must find every such skill, not a subset someone typed out.

    The parametrised tests below are only as wide as this set. While it was a
    literal tuple, a skill could add links of any shape and stay green forever —
    which is exactly what two of them did.
    """
    linking = {
        path.parent.name
        for path in _SKILLS_DIR.rglob("SKILL.md")
        if _MD_LINK_RE.search(path.read_text(encoding="utf-8"))
    }
    assert set(_SKILLS_UNDER_TEST) == linking
    assert len(_all_links()) == sum(
        len(_extract_reference_links(skill)) for skill in linking
    )


@pytest.mark.parametrize("skill,link", _all_links())
def test_reference_links_are_document_relative(skill: str, link: str) -> None:
    """Every references/ or scripts/ link is written relative to its SKILL.md.

    The allowed prefixes are imported from the tool rather than restated, so
    the form these documents are written in and the form ``read_file`` knows
    how to resolve cannot drift apart.

    The skill-name-prefixed form (``tushare/references/...``) reads correctly
    but is not what GitHub follows: a browser resolves it against the file's
    own directory and lands on ``tushare/tushare/references/...``, which does
    not exist. The document-relative form is the only one both readers agree
    on.
    """
    assert link.startswith(_SKILL_RELATIVE_PREFIXES), (
        f"{skill}/SKILL.md link must be written relative to the document "
        f"(one of {_SKILL_RELATIVE_PREFIXES}), got: {link}"
    )


@pytest.mark.parametrize("skill,link", _all_links())
def test_reference_links_resolve_through_read_file(skill: str, link: str) -> None:
    """Every references/ link resolves to an existing file via read_file.

    Also the ambiguity guard: ``read_file`` refuses rather than guesses when
    two skills carry the same reference path, so this goes red the day one is
    introduced instead of silently handing the agent the wrong skill's doc.
    """
    body = _read(link)
    assert body["status"] == "ok", f"{link} did not resolve: {body}"
    assert body["content"], f"{link} resolved to empty content"


@pytest.mark.parametrize("skill,link", _all_links())
def test_reference_links_resolve_the_way_github_resolves_them(
    skill: str, link: str
) -> None:
    """Every link exists relative to its SKILL.md, and is the file read_file reads.

    Resolving against the containing directory is what a browser does, and it
    is the reader the prefixed tables never served: every one of those links
    404'd on GitHub. Nothing asserted it, so nothing caught it.
    """
    target = (_SKILLS_DIR / skill / link).resolve()
    assert target.is_file(), (
        f"{skill}/SKILL.md link does not exist relative to the document: "
        f"{link} -> {target}"
    )
    assert Path(_read(link)["path"]).resolve() == target, (
        f"{link} sends the two readers to different files"
    )


def test_skill_prefixed_link_still_resolves_through_read_file() -> None:
    """The old prefixed form is still readable, so nothing that wrote it breaks.

    ``read_file`` roots at ``skills/``, so ``<skill>/references/...`` continues
    to resolve directly. Links copied from an older revision of these tables —
    or reproduced from a model's memory of them — keep working.
    """
    skill, link = _all_links()[0]
    body = _read(f"{skill}/{link}")
    assert body["status"] == "ok", f"{skill}/{link} did not resolve: {body}"
    assert body["path"] == _read(link)["path"]
