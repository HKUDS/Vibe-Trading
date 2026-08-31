"""Specialist definition loader: bundled roster plus user overrides.

Bundled definitions live in ``definitions/`` next to this module so wheels
and editable installs behave identically (the same packaging rule as swarm
presets, see ``test_swarm_presets_packaging.py``). User definitions live in
``<runtime root>/specialists/`` — searched first, so a user file overrides a
bundled specialist of the same name without touching site-packages.

Validation is fail-loud at load time, mirroring the production admission
gate's structural checks: every whitelisted tool must be a known local tool
(typo = load error, not a runtime surprise), structurally forbidden tools
(recursion, orchestration, shell, session-state, order-write) are rejected by
the model itself, and every named skill must exist. A broken *bundled* file
is a release bug and raises; a broken *user* file is skipped with a warning
so one bad local file cannot take down the agent.

The loaded roster is cached process-wide; dropping or editing a YAML takes
effect on the next process start.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import yaml

from src.agent.skills import SkillsLoader
from src.config.paths import get_runtime_root
from src.specialists.models import SpecialistSpec

logger = logging.getLogger(__name__)

DEFINITIONS_DIR = Path(__file__).resolve().parent / "definitions"

_cache: "dict[str, SpecialistSpec] | None" = None
_cache_lock = threading.Lock()


def _user_dir() -> Path:
    return get_runtime_root() / "specialists"


def _known_local_tool_names() -> frozenset[str]:
    from src.tools import known_local_tool_names

    return known_local_tool_names()


def _known_skill_names() -> frozenset[str]:
    return frozenset(skill.name for skill in SkillsLoader().skills)


def _validate(
    spec: SpecialistSpec,
    *,
    source: Path,
    known_tools: frozenset[str],
    known_skills: frozenset[str],
) -> None:
    """Raise ``ValueError`` on any authoring error in *spec*."""
    unknown_tools = [name for name in spec.tools if name not in known_tools]
    if unknown_tools:
        raise ValueError(
            f"{source.name}: whitelist references unknown local tool(s) "
            f"{unknown_tools} (MCP-served mcp_* tools are not supported in "
            "specialist whitelists)"
        )
    unknown_skills = [name for name in spec.skills if name not in known_skills]
    if unknown_skills:
        raise ValueError(f"{source.name}: unknown skill name(s) {unknown_skills}")
    if "load_skill" in spec.tools and not spec.skills:
        logger.warning(
            "Specialist %r (%s) grants load_skill with an empty skills list: "
            "every skill becomes loadable. Pin an explicit skills list to keep "
            "the specialist surface small.",
            spec.name,
            source.name,
        )


def _load_file(
    path: Path, *, known_tools: frozenset[str], known_skills: frozenset[str]
) -> SpecialistSpec:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: expected a mapping at the top level")
    spec = SpecialistSpec(**data)
    _validate(spec, source=path, known_tools=known_tools, known_skills=known_skills)
    return spec


def load_specialists() -> dict[str, SpecialistSpec]:
    """Return the merged roster, ordered by name (user dir overrides bundled).

    Returns:
        Mapping of specialist name to its validated spec. The result is
        cached process-wide.
    """
    global _cache
    with _cache_lock:
        if _cache is not None:
            return _cache

        known_tools = _known_local_tool_names()
        known_skills = _known_skill_names()
        merged: dict[str, SpecialistSpec] = {}

        for path in sorted(DEFINITIONS_DIR.glob("*.yaml")):
            spec = _load_file(path, known_tools=known_tools, known_skills=known_skills)
            merged[spec.name] = spec

        user_dir = _user_dir()
        if user_dir.is_dir():
            for path in sorted(user_dir.glob("*.yaml")):
                try:
                    spec = _load_file(
                        path, known_tools=known_tools, known_skills=known_skills
                    )
                except (
                    Exception
                ) as exc:  # noqa: BLE001 — one bad user file must not break the roster
                    logger.warning("Skipping user specialist %s: %s", path.name, exc)
                    continue
                merged[spec.name] = spec

        _cache = dict(sorted(merged.items()))
        return _cache


def reset_specialists_cache() -> None:
    """Drop the cached roster so the next load re-reads disk (tests)."""
    global _cache
    with _cache_lock:
        _cache = None
