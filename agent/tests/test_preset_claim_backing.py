"""CI gate: a swarm preset may not order work its own grants cannot reach.

Swarm workers get a strict per-node tool whitelist. ``build_swarm_registry``
projects the full registry down to ``agent_spec.tools`` and merely *logs* a
warning for anything it had to drop (``src/tools/__init__.py::_filter_registry``),
so a preset whose prompt instructs the worker to "use the ``foo`` tool" while
``foo`` is absent from that node's ``tools:`` list fails silently at runtime —
the model is told to call something it was never handed, and the usual failure
mode is that it invents the output instead.

Two structural claims are checkable without judging prose, and both are checked
here:

1. **Every real tool named in a node's prompt is granted to that node.** The
   match set is deliberately narrowed twice. Only ``snake_case`` identifiers are
   considered, and of those only the ones that are *actually* registered tool
   names. Bare English words are what makes this scan otherwise worthless:
   ``sentiment``, ``pattern``, ``backtest`` and ``remember`` are all genuine tool
   names AND ordinary vocabulary, so a word-boundary search on the plain names
   produces almost nothing but false positives. Requiring an underscore removes
   that entire class, and intersecting with the live registry removes the rest.
2. **Every ``skills:`` entry resolves to a ``SKILL.md`` on disk.** ``load_skill``
   resolves a skill by directory name; a preset naming a skill that was renamed
   or removed hands the worker a dead reference.

The gate is a regression fence, not a discovery tool: it is expected to pass.
When it fails, the fix is to grant the tool, correct the skill name, or stop
naming the tool in the prompt — never to relax the assertion.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from src.swarm.presets import PRESETS_DIR
from src.tools import build_registry

#: Skill bodies live one directory per skill, each holding a ``SKILL.md``.
SKILLS_DIR = Path(__file__).resolve().parents[1] / "src" / "skills"

#: ``snake_case`` only — at least one underscore between lowercase/digit runs.
#: This is the single most important constraint in the file; see the module
#: docstring for why a looser pattern makes the scan meaningless.
_SNAKE_CASE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")

#: Prompt contexts that unambiguously present a name as a callable tool.
#: Kept narrow on purpose: a bare backtick is NOT a tool-reference context,
#: because presets legitimately backtick Python helpers such as
#: ``src.quantlib.risk.historical_var`` that are imported under ``bash`` rather
#: than dispatched through the tool registry.
_TOOL_REFERENCE_CONTEXTS = (
    re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\s+tool\b"),
    re.compile(r"\bthe\s+`?([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`?\s+tool\b"),
)


def _preset_paths() -> list[Path]:
    """Every bundled preset YAML, sorted for stable test ids.

    Returns:
        Sorted list of paths to the bundled ``*.yaml`` presets.
    """
    return sorted(PRESETS_DIR.glob("*.yaml"))


def _registered_tool_names() -> frozenset[str]:
    """Names of every tool a swarm worker could possibly be granted.

    Shell tools are included because a preset may legitimately whitelist
    ``bash``; whether the operator enabled them at runtime is a separate
    concern from whether the preset's prompt is self-consistent.

    Returns:
        Frozen set of registered tool names.
    """
    return frozenset(build_registry(include_shell_tools=True).tool_names)


def _agent_prompt_text(preset: dict, agent_id: str, agent: dict) -> str:
    """All prompt text a given agent will actually see.

    An agent's instructions arrive from two places: its own ``system_prompt``
    and the ``prompt_template`` of every task routed to it. A tool named in
    either one is a tool the worker is being told to call.

    Args:
        preset: The parsed preset mapping.
        agent_id: The agent's ``id``.
        agent: The agent's own spec mapping.

    Returns:
        The agent's system prompt concatenated with its task templates.
    """
    parts = [agent.get("system_prompt") or ""]
    parts.extend(
        task.get("prompt_template") or ""
        for task in preset.get("tasks") or []
        if task.get("agent_id") == agent_id
    )
    return "\n".join(parts)


def _load(path: Path) -> dict:
    """Parse one preset YAML.

    Args:
        path: Path to the preset file.

    Returns:
        The parsed mapping.
    """
    return yaml.safe_load(path.read_text(encoding="utf-8"))


PRESET_PATHS = _preset_paths()


def test_presets_are_discovered() -> None:
    """Guard the glob itself, so a path regression cannot vacuously pass.

    Every other test in this module is parametrised over ``PRESET_PATHS``; if
    that list were ever empty the whole gate would report success while
    checking nothing.
    """
    assert PRESET_PATHS, f"no presets found under {PRESETS_DIR}"


@pytest.mark.parametrize("path", PRESET_PATHS, ids=lambda p: p.stem)
def test_named_tools_are_granted_to_the_node_that_names_them(path: Path) -> None:
    """A prompt may not instruct a worker to use a tool the node lacks.

    Args:
        path: The preset under test.
    """
    registered = _registered_tool_names()
    preset = _load(path)
    violations: list[str] = []

    for agent in preset.get("agents") or []:
        agent_id = agent.get("id", "<unnamed>")
        granted = set(agent.get("tools") or [])
        text = _agent_prompt_text(preset, agent_id, agent)
        named_tools = {
            token for token in _SNAKE_CASE.findall(text) if token in registered
        }
        for missing in sorted(named_tools - granted):
            violations.append(
                f"{path.name}::{agent_id} prompt names the registered tool "
                f"{missing!r} but its tools list is {sorted(granted)}"
            )

    assert not violations, (
        "Preset prompts name tools the node was never granted; the worker "
        "cannot call them and will fabricate the output instead. Grant the "
        "tool or stop naming it:\n  " + "\n  ".join(violations)
    )


@pytest.mark.parametrize("path", PRESET_PATHS, ids=lambda p: p.stem)
def test_prompts_do_not_reference_nonexistent_tools(path: Path) -> None:
    """A prompt may not call something a "tool" when no such tool exists.

    Catches the inverse of the previous check: a name that reads as a tool
    reference but matches nothing in the registry, which is a demand the worker
    can only satisfy by inventing a result.

    Args:
        path: The preset under test.
    """
    registered = _registered_tool_names()
    preset = _load(path)
    violations: list[str] = []

    for agent in preset.get("agents") or []:
        agent_id = agent.get("id", "<unnamed>")
        text = _agent_prompt_text(preset, agent_id, agent)
        referenced: set[str] = set()
        for pattern in _TOOL_REFERENCE_CONTEXTS:
            referenced.update(pattern.findall(text))
        for phantom in sorted(referenced - registered):
            violations.append(
                f"{path.name}::{agent_id} refers to {phantom!r} as a tool, "
                "but no such tool is registered"
            )

    assert not violations, (
        "Preset prompts reference tools that do not exist:\n  "
        + "\n  ".join(violations)
    )


@pytest.mark.parametrize("path", PRESET_PATHS, ids=lambda p: p.stem)
def test_declared_skills_exist_on_disk(path: Path) -> None:
    """Every ``skills:`` entry must resolve to a real ``SKILL.md``.

    Args:
        path: The preset under test.
    """
    preset = _load(path)
    violations: list[str] = []

    for agent in preset.get("agents") or []:
        agent_id = agent.get("id", "<unnamed>")
        for skill in agent.get("skills") or []:
            if not (SKILLS_DIR / skill / "SKILL.md").is_file():
                violations.append(
                    f"{path.name}::{agent_id} declares skill {skill!r}, but "
                    f"{SKILLS_DIR / skill / 'SKILL.md'} does not exist"
                )

    assert not violations, (
        "Presets declare skills with no SKILL.md on disk:\n  "
        + "\n  ".join(violations)
    )


@pytest.mark.parametrize("path", PRESET_PATHS, ids=lambda p: p.stem)
def test_every_node_naming_a_skill_can_load_it(path: Path) -> None:
    """A node with ``skills:`` must also be granted ``load_skill``.

    Declaring a skill is inert on its own — the worker still has to call
    ``load_skill`` to pull the body into context. A node carrying skills it
    cannot load is being pointed at methodology it will never actually read.

    Args:
        path: The preset under test.
    """
    preset = _load(path)
    violations = [
        f"{path.name}::{agent.get('id', '<unnamed>')} declares skills "
        f"{agent.get('skills')} but was not granted 'load_skill'"
        for agent in preset.get("agents") or []
        if (agent.get("skills") or []) and "load_skill" not in (agent.get("tools") or [])
    ]

    assert not violations, (
        "Presets declare skills on nodes that cannot load them:\n  "
        + "\n  ".join(violations)
    )
