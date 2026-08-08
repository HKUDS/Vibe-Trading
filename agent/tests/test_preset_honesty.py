"""CI gate: a shipped preset must not promise what its node cannot reach.

Swarm workers get a strict tool whitelist and a skill list. Two failure modes
had shipped: ``value_investing_committee`` named three skills that were never
bundled (``load_skill`` returns a soft error envelope, so the worker proceeded
without its methodology and said nothing), and ``derivatives_strategy_desk``
ordered its vol analyst to report ATM IV by tenor, IV-vs-HV premium and 25-delta
risk reversals while granting ``get_options_chain`` to no agent at all.

This gate covers the two mechanizable halves: every ``skills:`` entry resolves,
and every tool *named* in a node's prompt is granted to that node. It cannot
cover the third and hardest half — a prompt that demands a deliverable in prose
that no granted tool can compute — which stays a review obligation.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from src.tools import build_registry, build_swarm_registry

_PRESET_DIR = Path(__file__).resolve().parents[1] / "src" / "swarm" / "presets"
_SKILL_DIR = Path(__file__).resolve().parents[1] / "src" / "skills"


@pytest.fixture(scope="module")
def presets() -> list[tuple[str, dict]]:
    loaded = []
    for path in sorted(_PRESET_DIR.glob("*.yaml")):
        loaded.append((path.name, yaml.safe_load(path.read_text(encoding="utf-8"))))
    assert loaded, "no presets found"
    return loaded


@pytest.fixture(scope="module")
def bundled_skills() -> set[str]:
    return {path.parent.name for path in _SKILL_DIR.glob("*/SKILL.md")}


@pytest.fixture(scope="module")
def tool_identifiers() -> list[str]:
    # Only snake_case names are unambiguous identifiers. Bare tool names that
    # are also ordinary English words — sentiment, pattern, backtest, remember —
    # appear throughout the prose and would make this gate pure noise.
    return sorted(name for name in build_registry().tool_names if "_" in name)


def _nodes(presets):
    for filename, doc in presets:
        for node in doc.get("agents") or []:
            yield filename, node.get("id", "?"), node


def test_every_referenced_skill_is_bundled(presets, bundled_skills):
    missing = [
        f"{filename}:{node_id} -> {skill}"
        for filename, node_id, node in _nodes(presets)
        for skill in (node.get("skills") or [])
        if skill not in bundled_skills
    ]

    assert missing == [], (
        "preset references a skill that is not bundled; load_skill returns a "
        "soft error so the worker would run without its methodology silently"
    )


def test_every_tool_named_in_a_prompt_is_granted_to_that_node(
    presets, tool_identifiers
):
    ungranted = []
    for filename, node_id, node in _nodes(presets):
        granted = set(node.get("tools") or [])
        prompt = node.get("system_prompt") or ""
        for tool in tool_identifiers:
            named = re.search(rf"(?<![\w-]){re.escape(tool)}(?![\w-])", prompt)
            if named and tool not in granted:
                ungranted.append(f"{filename}:{node_id} names {tool}")

    assert ungranted == [], (
        "preset prompt names a tool the node was not granted; the worker would "
        "be told to call something its whitelist blocks"
    )


def test_every_granted_tool_resolves(presets):
    # Resolve through the swarm's own builder: shell tools (bash, read_file,
    # write_file) are not in the default agent registry but are legitimate for a
    # worker, so checking against build_registry() alone reports 118 phantoms.
    unresolved = []
    for filename, node_id, node in _nodes(presets):
        requested = list(node.get("tools") or [])
        if not requested:
            continue
        resolved = set(
            build_swarm_registry(requested, include_shell_tools=True).tool_names
        )
        unresolved.extend(
            f"{filename}:{node_id} -> {tool}"
            for tool in requested
            if tool not in resolved
        )

    assert unresolved == [], (
        "preset grants a tool that does not resolve; the runtime drops it with "
        "a warning and the worker runs without it"
    )


def test_the_derivatives_desk_can_reach_an_options_chain(presets):
    # The audit's sharpest single case: three agents were ordered to report
    # market-implied volatility with no chain tool granted to any of them, so
    # every IV number in that report was necessarily invented.
    desk = next(doc for name, doc in presets if name == "derivatives_strategy_desk.yaml")
    granting = [
        node.get("id")
        for node in desk["agents"]
        if "get_options_chain" in (node.get("tools") or [])
    ]

    assert granting, "no agent on the derivatives desk can fetch an options chain"
