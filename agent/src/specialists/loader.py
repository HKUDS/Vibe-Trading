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
from types import MappingProxyType
from typing import Mapping

import yaml

from src.agent.skills import SkillsLoader
from src.config.paths import get_runtime_root
from src.specialists.models import SpecialistSpec

logger = logging.getLogger(__name__)

DEFINITIONS_DIR = Path(__file__).resolve().parent / "definitions"

_cache: "Mapping[str, SpecialistSpec] | None" = None
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
    if spec.skills and "load_skill" not in spec.tools:
        raise ValueError(
            f"{source.name}: declares skills but does not grant load_skill; "
            "the declared skills are unreachable. Add `load_skill` to the "
            "tools list so the specialist can load them, or drop the skills "
            "declaration."
        )
    if "load_skill" in spec.tools and not spec.skills:
        logger.warning(
            "Specialist %r (%s) grants load_skill with an empty skills list: "
            "no skill is loadable — the allowlist is empty and every load is "
            "refused. Declare an explicit skills list or drop load_skill from "
            "the tools list.",
            spec.name,
            source.name,
        )

    # The specialist runs inside a delegate_to_specialist tool call, which the
    # agent loop wraps with the global tool timeout
    # (``VIBE_TRADING_TOOL_TIMEOUT_SECONDS``, default 1800s). The specialist's
    # own budget must leave headroom under that wrapper: the 60s margin
    # exceeds delegate_tool's ``_CANCEL_GRACE_SECONDS`` (30s), so even a
    # cancelled child thread finishes unwinding before the wrapper fires and
    # the parent always observes a structured result instead of a bare
    # tool-timeout kill.
    #
    # Design consequence (intentional): this clamp lives in _validate, so a
    # *bundled* file in violation makes load_specialists() raise as a whole →
    # delegate_tool.check_available catches it, warns, and takes the ENTIRE
    # specialist feature offline — not just the one specialist. A bundled
    # violation is a release-grade bug, so failing loud is correct. An
    # operator setting VIBE_TRADING_TOOL_TIMEOUT_SECONDS below 1260 (bundled
    # max quant-agent 1200 + 60) turns the whole feature off.
    try:
        from src.config.accessor import get_env_config

        wrapper = get_env_config().agent_tuning.vibe_trading_tool_timeout_seconds
    except Exception:  # noqa: BLE001 — fail-safe, see below
        # If the env config cannot be read (e.g. a malformed env var), skip
        # the headroom check rather than take the whole roster down for a
        # config problem the specialist author cannot fix; the loop still
        # enforces its own wrapper timeout at runtime.
        wrapper = None
    # A non-positive wrapper disables the loop's tool timeout entirely
    # (``loop.py``: timeout = _tool_timeout if _tool_timeout > 0 else None),
    # so there is nothing to leave headroom under.
    if wrapper is not None and wrapper > 0 and spec.timeout_seconds + 60 > wrapper:
        raise ValueError(
            f"{source.name}: timeout_seconds {spec.timeout_seconds} leaves no "
            f"headroom under the loop tool timeout {wrapper}s (need +60s "
            "margin); lower timeout_seconds or raise "
            "VIBE_TRADING_TOOL_TIMEOUT_SECONDS."
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


def load_specialists() -> Mapping[str, SpecialistSpec]:
    """Return the merged roster, ordered by name (user dir overrides bundled).

    Returns:
        Read-only mapping of specialist name to its validated spec. The
        result is cached process-wide; the ``MappingProxyType`` wrapper makes
        the shared cache structurally immutable so no caller can mutate the
        roster other callers see.
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

        _cache = MappingProxyType(dict(sorted(merged.items())))
        return _cache


def reset_specialists_cache() -> None:
    """Drop the cached roster so the next load re-reads disk (tests)."""
    global _cache
    with _cache_lock:
        _cache = None
