"""Read file tool: read file contents from the workspace."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.agent.tools import BaseTool
from src.tools.path_utils import safe_path as _safe_path
from src.tools.path_utils import safe_run_dir as _safe_run_dir
from src.tools.path_utils import allowed_file_roots
from src.tools.redaction import redact_internal_paths

_OUTPUT_LIMIT = 50_000

# Subdirectories a SKILL.md links into. A link inside a skill document is
# written relative to that document — `references/foo.md` — because that is the
# form that resolves for a human reading the file on GitHub. This tool roots at
# the bundled skills/ directory, so the same string has to be resolved against
# the skill that owns it or the agent cannot open what the document points at.
# The list is deliberately narrow: only these two names are searched, so an
# arbitrary model-supplied relative path never starts reaching into skills/.
_SKILL_RELATIVE_PREFIXES = ("references/", "scripts/")


def _bundled_skills_dir() -> Path:
    """Return the bundled read-only skills root."""
    return Path(__file__).resolve().parents[1] / "skills"


def _skill_relative_matches(file_path: str, skills_dir: Path) -> list[tuple[str, Path]]:
    """Return the bundled skills that carry ``file_path`` inside their directory.

    Args:
        file_path: Skill-relative path as written in a SKILL.md link, e.g.
            ``references/sec_edgar_client.md``.
        skills_dir: Bundled read-only skills root.

    Returns:
        ``(skill_name, path)`` for each owning skill, in skill-name order. Empty
        when no bundled skill carries the path.
    """
    # A link written in a skill document never needs to climb, and `..` would
    # let a path that merely *starts* with an allowed prefix land somewhere
    # else — `references/../SKILL.md` matching all 90 skills, for one. Refusing
    # the segment outright keeps "starts with references/" and "stays under
    # references/" the same statement.
    if ".." in file_path.replace("\\", "/").split("/"):
        return []

    matches: list[tuple[str, Path]] = []
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        try:
            candidate = _safe_path(file_path, skill_dir)
        except ValueError:
            # Absolute paths and UNC shares, rejected by the same containment
            # check the skills/ root already applies, enforced one level down
            # so the fallback cannot widen the boundary.
            continue
        if candidate.is_file():
            matches.append((skill_dir.name, candidate))
    return matches


class ReadFileTool(BaseTool):
    """Read file contents with optional line limit."""

    name = "read_file"
    description = "Read a file from the workspace. Returns file contents with optional line limit."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "File path relative to run_dir or skills/. "
                    "The skills/ prefix always resolves to the bundled skills. "
                    "A references/ or scripts/ path copied out of a SKILL.md "
                    "resolves against the skill that owns it."
                ),
            },
            "limit": {"type": "integer", "description": "Max number of lines to return (default: all)"},
        },
        "required": ["path"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        """Read a file.

        Args:
            **kwargs: Must include path. Optional limit and run_dir.

        Returns:
            JSON string containing content or an error.
        """
        file_path = kwargs["path"]
        limit = kwargs.get("limit")
        run_dir = kwargs.get("run_dir")

        allowed_roots = []
        if run_dir:
            try:
                allowed_roots.append(_safe_run_dir(str(run_dir)))
            except ValueError as exc:
                return json.dumps(
                    {
                        "status": "error",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                )
        # Read-only access to skills/
        skills_dir = _bundled_skills_dir()
        if skills_dir.exists():
            allowed_roots.append(skills_dir.resolve())

        # Add configured extra file roots (VIBE_TRADING_ALLOWED_FILE_ROOTS)
        for extra_root in allowed_file_roots():
            if extra_root not in allowed_roots:
                allowed_roots.append(extra_root)

        resolved = None
        namespaced = False

        # `skills/` is a namespace bound to the bundled read-only skills root.
        # Binding the prefix stops a same-named file in run_dir — which the agent
        # itself can write — from shadowing a bundled skill and being loaded as
        # trusted guidance.
        if file_path.startswith("skills/"):
            namespaced = True
            try:
                candidate = _safe_path(file_path[len("skills/") :], skills_dir)
            except ValueError:
                candidate = None
            if candidate is not None and candidate.exists():
                resolved = candidate

        # Unprefixed paths search every allowed root, run_dir first.
        if resolved is None and not namespaced:
            for root in allowed_roots:
                try:
                    candidate = _safe_path(file_path, root)
                    if candidate.exists():
                        resolved = candidate
                        break
                except ValueError:
                    continue

        # Last resort: a skill-relative link. Tried only after every allowed
        # root has already missed, so nothing that resolves today changes, and
        # it reads out of the read-only skills tree, so run_dir cannot poison
        # it. An ambiguous path is reported rather than guessed — silently
        # picking one of two same-named references would hand the agent a
        # document from the wrong skill and read as a correct answer.
        if (
            resolved is None
            and not namespaced
            and skills_dir.exists()
            and file_path.startswith(_SKILL_RELATIVE_PREFIXES)
        ):
            matches = _skill_relative_matches(file_path, skills_dir)
            if len(matches) == 1:
                resolved = matches[0][1]
            elif len(matches) > 1:
                owners = ", ".join(name for name, _ in matches)
                return json.dumps(
                    {
                        "status": "error",
                        "error": (
                            f"Ambiguous skill-relative path: {file_path} exists in "
                            f"{len(matches)} skills ({owners}). Prefix it with the "
                            f"skill name, e.g. skills/<skill>/{file_path}."
                        ),
                    },
                    ensure_ascii=False,
                )

        if resolved is None:
            return json.dumps(
                {
                    "status": "error",
                    "error": f"File not found or path escapes workspace: {file_path}",
                },
                ensure_ascii=False,
            )

        try:
            text = resolved.read_text(encoding="utf-8")
            if limit and limit > 0:
                lines = text.splitlines(keepends=True)
                text = "".join(lines[:limit])
            if len(text) > _OUTPUT_LIMIT:
                text = text[:_OUTPUT_LIMIT] + "\n... (truncated)"
            return json.dumps(
                {
                    "status": "ok",
                    "path": str(resolved),
                    "content": text,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps(
                {
                    "status": "error",
                    "error": redact_internal_paths(str(exc)),
                },
                ensure_ascii=False,
            )
