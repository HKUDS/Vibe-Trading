"""The five READMEs must agree with the code about how much of everything ships.

Every number these tests check is one a reader uses to decide whether the
project does what they need — how many MCP tools they get, how many skills,
how many backtest engines. They drift silently: a feature lands, the English
README is updated by hand, and the four translations keep yesterday's count
until somebody happens to look. Both counts these tests were written for had
already drifted this way (``analyze_options_payoff`` was missing from four
locale tool lists, and the ``investor-lenses`` skill from all five badges).

Locale independence is the whole difficulty. The numbers sit inside translated
prose, so nothing can be matched on wording. Instead each check anchors on
something that survives translation:

* the enumerated MCP tool list — the line carrying the most ``\\`name\\``
  literals, whose contents are code identifiers in every locale;
* the repository-tree line, anchored on ``mcp_server.py``;
* the MCP prose paragraph, anchored on ``stdio`` — dated news bullets are
  excluded, because an old entry mentions stdio too;
* the feature badges, anchored on ``<summary>…<sub>N …</sub></summary>``. The
  enclosing ``<summary>`` matters: a loose ``<sub>`` ("Plus 20+ specialist
  presets") sits among them, and it wraps onto its own line in English but not
  in the other four, so counting bare ``<sub>`` elements puts the locales out
  of step with one another.

A badge is asserted to *contain* its expected number rather than to start with
it, because the word order differs by language — "89 skills across 9
categories" against "9 个类别中的 89 个 skills". That still fails the moment the
code count moves, which is what this file is for.
"""

from __future__ import annotations

import asyncio
import importlib
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = Path(__file__).resolve().parents[1]

READMES = (
    "README.md",
    "README_zh.md",
    "README_ja.md",
    "README_ko.md",
    "README_ar.md",
)

# Feature badges in the order they appear in every README. Each entry is the
# badge's position among numeric <sub> badges and a callable returning the
# count the code actually ships.
BADGE_ORDER = ("skills", "brokers", "presets", "alphas", "engines")

# Brokers are a curated product claim (which venues we support), not something
# countable from a single directory — connectors, profiles and the read-only
# caps do not map one-to-one. It is pinned here so a reader-facing number still
# has one owner, and updating it is a deliberate edit.
EXPECTED_BROKERS = 12


def _read(name: str) -> str:
    """Return a README's text.

    Args:
        name: File name relative to the repository root.

    Returns:
        The file contents.
    """
    return (REPO_ROOT / name).read_text(encoding="utf-8")


def _mcp_tool_names() -> list[str]:
    """Return the MCP tool names in registration order.

    Returns:
        Tool names exactly as the MCP server exposes them.
    """
    if str(AGENT_DIR) not in sys.path:
        sys.path.insert(0, str(AGENT_DIR))
    mod = sys.modules.get("mcp_server") or importlib.import_module("mcp_server")
    return [tool.name for tool in asyncio.run(mod.mcp.list_tools())]


def _bundled_skill_count() -> int:
    """Count skills that ship inside the package.

    User-created skills live outside the checkout and must not be counted, so
    the loader is pointed at a directory that cannot exist.

    Returns:
        Number of bundled skills.
    """
    if str(AGENT_DIR) not in sys.path:
        sys.path.insert(0, str(AGENT_DIR))
    from src.agent.skills import SkillsLoader

    loader = SkillsLoader(user_skills_dir=AGENT_DIR / "__no_user_skills__")
    return len(loader.skills)


def _engine_count() -> int:
    """Count market backtest engines.

    ``options_portfolio`` is counted separately by the README ("9 engines +
    options portfolio"), and the shared bases are not engines.

    Returns:
        Number of market engines.
    """
    excluded = {"__init__", "base", "futures_base", "_market_hooks", "options_portfolio"}
    return len(
        [p for p in (AGENT_DIR / "backtest" / "engines").glob("*.py") if p.stem not in excluded]
    )


def _counts() -> dict[str, int]:
    """Return every code-derived count the READMEs state.

    Returns:
        Mapping of badge key to the count the code ships.
    """
    return {
        "skills": _bundled_skill_count(),
        "brokers": EXPECTED_BROKERS,
        "presets": len(list((AGENT_DIR / "src" / "swarm" / "presets").glob("*.yaml"))),
        "alphas": len([p for p in (AGENT_DIR / "src" / "factors" / "zoo").rglob("*.py")
                       if p.stem != "__init__"]),
        "engines": _engine_count(),
    }


def _tool_list_line(text: str) -> str:
    """Return the line enumerating every MCP tool.

    Args:
        text: Full README text.

    Returns:
        The line carrying the most backticked identifiers.
    """
    return max(text.splitlines(), key=lambda line: len(re.findall(r"`[a-z_]+`", line)))


SUMMARY_BADGE = re.compile(r"<summary>[^\n]*<sub>([^<]*\d[^<]*)</sub>[^\n]*</summary>")

NEWS_BULLET = re.compile(r"- \*\*\d{4}-")


def _badges(text: str) -> list[str]:
    """Return the feature badges in document order.

    Args:
        text: Full README text.

    Returns:
        The numeric ``<sub>`` badge texts that sit inside a ``<summary>``.
    """
    return SUMMARY_BADGE.findall(text)


def _numbers(line: str) -> set[str]:
    """Return every integer appearing in a line.

    Args:
        line: Text to scan.

    Returns:
        The integers found, as strings.
    """
    return set(re.findall(r"\d+", line))


@pytest.mark.parametrize("name", READMES)
def test_enumerated_mcp_tool_list_matches_the_server(name: str) -> None:
    """The spelled-out tool list must be the server's list, in its order."""
    listed = re.findall(r"`([a-z_]+)`", _tool_list_line(_read(name)))
    runtime = _mcp_tool_names()

    assert set(listed) == set(runtime), (
        f"{name}: missing {sorted(set(runtime) - set(listed))}, "
        f"stale {sorted(set(listed) - set(runtime))}"
    )
    assert len(listed) == len(runtime), f"{name}: a tool name is listed twice"


@pytest.mark.parametrize("name", READMES)
def test_enumerated_mcp_list_header_states_the_real_count(name: str) -> None:
    """The "(N)" heading on the tool list must be the real tool count."""
    line = _tool_list_line(_read(name))
    header = re.search(r"[（(](\d+)[）)]", line[:60])

    assert header is not None, f"{name}: tool list has no (N) header"
    assert int(header.group(1)) == len(_mcp_tool_names())


@pytest.mark.parametrize("name", READMES)
def test_mcp_prose_states_the_real_count(name: str) -> None:
    """The MCP section paragraph must state the real tool count."""
    prose = [
        line
        for line in _read(name).splitlines()
        if "stdio" in line and re.search(r"\d\d", line) and not NEWS_BULLET.match(line)
    ]

    assert len(prose) == 1, f"{name}: expected one MCP prose line, found {len(prose)}"
    assert str(len(_mcp_tool_names())) in _numbers(prose[0])


@pytest.mark.parametrize("name", READMES)
def test_repo_tree_states_the_real_mcp_count(name: str) -> None:
    """The repository-tree comment on mcp_server.py must state the real count."""
    tree = [line for line in _read(name).splitlines() if "mcp_server.py" in line and "#" in line]

    assert len(tree) == 1, f"{name}: expected one mcp_server.py tree line, found {len(tree)}"
    assert str(len(_mcp_tool_names())) in _numbers(tree[0])


@pytest.mark.parametrize("name", READMES)
def test_feature_badges_state_the_real_counts(name: str) -> None:
    """Each <sub> badge must carry the count the code ships."""
    badges = _badges(_read(name))
    counts = _counts()

    assert len(badges) == len(BADGE_ORDER), (
        f"{name}: expected {len(BADGE_ORDER)} numeric badges, found {len(badges)}: {badges}"
    )
    for badge, key in zip(badges, BADGE_ORDER):
        assert str(counts[key]) in _numbers(badge), (
            f"{name}: {key} badge says {badge!r}, code ships {counts[key]}"
        )


@pytest.mark.parametrize("name", READMES)
def test_the_slash_table_is_the_router(name: str) -> None:
    """The documented TUI commands must be exactly the ones the router resolves.

    This table had drifted furthest of anything in the file: it listed seven
    commands the router does not resolve at all (they survive only in the
    legacy REPL reached when prompt_toolkit fails to import) while omitting
    twenty-one real ones, including the ``/halt`` kill switch.
    """
    if str(AGENT_DIR) not in sys.path:
        sys.path.insert(0, str(AGENT_DIR))
    from cli.commands.slash_router import SLASH_COMMANDS

    # Scoped to the TUI table: the IM-channels section further down has its own
    # slash table (``/new``, ``/pairing list``) for a different command set.
    lines = _read(name).splitlines()
    first = next(i for i, l in enumerate(lines) if l.startswith("| `/help`"))
    last = next(i for i, l in enumerate(lines) if l.startswith("| `/quit`"))
    rows = [line.split("`")[1].lstrip("/") for line in lines[first:last + 1]]
    expected = [command.name for command in SLASH_COMMANDS]

    assert rows == expected, (
        f"{name}: documents {sorted(set(rows) - set(expected))}, "
        f"missing {sorted(set(expected) - set(rows))}"
    )


@pytest.mark.parametrize("name", READMES)
def test_every_skill_count_in_the_prose_is_current(name: str) -> None:
    """No sentence may quote a stale skill count.

    The badge is only one of seven places the number appears — the others are
    a feature bullet, the ``/skill`` row, two OpenSpace paragraphs and two
    repository-tree comments, and every one of them was a version behind.
    Only prose is in scope. Dated news entries are frozen history, credit
    lines carry issue numbers next to the word "skill", and the MCP tool list
    contains ``list_skills`` beside its own count — none of those is a claim
    about how many skills ship. ``8899`` is the server port.
    """
    skill_words = ("skill", "Skill", "스킬", "مهارة", "المهارات")
    expected = str(_bundled_skill_count())

    stale = [
        line.strip()
        for line in _read(name).splitlines()
        if any(word in line for word in skill_words)
        and re.search(r"\d\d", line)
        and "8899" not in line
        and not line.startswith("- @")
        and len(re.findall(r"`[a-z_]+`", line)) < 5
        and not NEWS_BULLET.match(line)
        and expected not in line
    ]

    assert not stale, f"{name}: {len(stale)} line(s) quote a stale skill count: {stale}"


@pytest.mark.parametrize("name", READMES)
def test_brokers_without_paper_trading_are_named_as_exceptions(name: str) -> None:
    """A broker with no paper order placement must be called out by name.

    The Broker Connectors paragraph summarises what the connectors can do, and
    a reader plans against it: "most do paper" invites them to rehearse on a
    paper account first. Three connectors have no such account — IBKR, which
    is read-only, Robinhood, whose only profile is live, and Trading 212,
    which refuses order placement outright. Robinhood being missing from that
    list survived two review passes, and it is the one that matters most:
    it is the live execution channel, so a reader who believes it has a paper
    mode places a real order while trying to test.
    """
    if str(AGENT_DIR) not in sys.path:
        sys.path.insert(0, str(AGENT_DIR))
    from src.trading.service import list_profiles

    by_connector: dict[str, list] = {}
    for profile in list_profiles():
        by_connector.setdefault(profile.connector, []).append(profile)
    no_paper = {
        connector
        for connector, profiles in by_connector.items()
        if not any(p.environment == "paper" and not p.readonly for p in profiles)
    }
    assert no_paper, "expected at least one connector without paper order placement"

    badges = [i for i, line in enumerate(_read(name).splitlines()) if SUMMARY_BADGE.search(line)]
    # BADGE_ORDER[1] is the broker badge; its prose sits two lines below.
    paragraph = _read(name).splitlines()[badges[1] + 2]
    flattened = paragraph.replace(" ", "").lower()

    missing = [c for c in sorted(no_paper) if c.replace("_", "") not in flattened]
    assert not missing, (
        f"{name}: connectors with no paper account are unnamed in the broker "
        f"paragraph: {missing}"
    )


def test_the_skill_category_table_matches_the_frontmatter() -> None:
    """Each category row must carry the number of skills declaring it."""
    counts: dict[str, int] = {}
    for skill_md in sorted((AGENT_DIR / "src" / "skills").glob("*/SKILL.md")):
        declared = re.search(r"^category:\s*(.+)$", skill_md.read_text(encoding="utf-8"), re.M)
        key = declared.group(1).strip() if declared else "(none)"
        counts[key] = counts.get(key, 0) + 1

    # Table labels are Title Case with spaces; frontmatter is kebab-case.
    rows = re.findall(r"^\| ([A-Z][A-Za-z ]+) \| (\d+) \| `", _read("README.md"), re.M)
    assert rows, "README.md: skill category table not found"

    for label, stated in rows:
        key = label.strip().lower().replace(" ", "-")
        assert key in counts, f"unknown category row {label!r}"
        assert int(stated) == counts[key], f"{label}: table says {stated}, code has {counts[key]}"
    assert sum(int(n) for _, n in rows) == _bundled_skill_count()


def test_all_five_readmes_agree_with_each_other() -> None:
    """No locale may drift from the others, whatever the code count is."""
    per_file = {name: [_numbers(b) for b in _badges(_read(name))] for name in READMES}
    counts = _counts()

    for index, key in enumerate(BADGE_ORDER):
        stale = [name for name, badges in per_file.items() if str(counts[key]) not in badges[index]]
        assert not stale, f"{key}: {stale} disagree with the other locales"
