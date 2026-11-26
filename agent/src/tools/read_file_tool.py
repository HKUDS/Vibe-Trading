"""Read file tool: read file contents from the workspace."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.agent.tools import BaseTool, FileBoundTool
from src.config.limits import TOOL_RESULT_LIMIT
from src.tools.path_utils import safe_path as _safe_path
from src.tools.path_utils import safe_run_dir as _safe_run_dir
from src.tools.path_utils import session_workspace_for_run
from src.tools.path_utils import allowed_file_roots
from src.tools.redaction import RESULT_SINK, is_sensitive_arg, redact_internal_paths, redact_payload

_OUTPUT_LIMIT = 50_000
_STRUCTURE_SAMPLE_LIMIT = 400
_JSON_TYPES = {dict: "object", list: "array", str: "string", bool: "boolean",
               int: "number", float: "number", type(None): "null"}

# Subdirectories a SKILL.md links into. A link inside a skill document is
# written relative to that document — `references/foo.md` — because that is the
# form that resolves for a human reading the file on GitHub. This tool roots at
# the bundled skills/ directory, so the same string has to be resolved against
# the skill that owns it or the agent cannot open what the document points at.
# The list is deliberately narrow: only these two names are searched, so an
# arbitrary model-supplied relative path never starts reaching into skills/.
_SKILL_RELATIVE_PREFIXES = ("references/", "scripts/")

# How many entries a directory listing returns.
_LISTING_LIMIT = 200

# What the refusal says, whichever root the path missed. A risk-parity run once
# spent all eight of its no-progress rounds trying spellings of the engine's
# source path (``../../agent/src/backtest``, ``skills/../backtest/engine.py``)
# against one message that said neither where it may read nor what to do.
_READABLE = (
    "read_file opens files under the run directory (a relative path such as "
    "artifacts/metrics.csv or config.json) and the bundled skill documents "
    "(skills/<skill>/...). The engine's source code is not readable here; its "
    "contracts and options are documented in the skills: load_skill(name) lists "
    "a skill's sections, and load_skill(name, section=...) returns one."
)


def _line_window(original: str, offset: int, limit: int | None, char_offset: int) -> dict:
    """Build a bounded window of complete lines or a fragment of an oversized line."""
    if not (offset or char_offset or limit) and len(original) <= _OUTPUT_LIMIT:
        return {"content": original}

    lines = original.splitlines(keepends=True)
    total_lines = len(lines)
    if offset >= max(1, total_lines) or (char_offset and (
        not lines or char_offset >= len(lines[offset])
    )):
        return {
            "status": "error",
            "error_code": "invalid_offset",
            "error": "offset and char_offset must identify a character inside the selected text.",
        }
    end = min(total_lines, offset + limit) if limit and limit > 0 else total_lines
    remaining = _OUTPUT_LIMIT
    complete_lines = []
    for index in range(offset, end):
        line = lines[index]
        if index == offset:
            line = line[char_offset:]
        if len(line) > remaining:
            break
        complete_lines.append(line)
        remaining -= len(line)

    returned_lines = len(complete_lines)
    following = offset + returned_lines
    capped = following < end
    text = "".join(complete_lines)
    if capped and not complete_lines:
        # The next page must resume this line before advancing to a new one.
        text = lines[offset][char_offset:char_offset + _OUTPUT_LIMIT]
    page = {"content": text + "\n... (truncated)" if capped else text}
    if offset or char_offset or following < total_lines:
        page.update(
            truncated=True,
            offset=offset,
            returned_chars=len(text),
            total_chars=len(original),
            returned_lines=returned_lines,
            total_lines=total_lines,
            message="Partial preview: content holds only part of the original file, which is unchanged at path.",
        )
        if char_offset:
            page["char_offset"] = char_offset
        if following < total_lines:
            page["next_offset"] = following
            if not returned_lines:
                page["next_char_offset"] = char_offset + len(text)
    return page


def _source_structure(document: Any, path: str) -> dict:
    """Describe top-level source values and label array boundaries by exact pointer."""
    fields = []
    shape = {"path": path, "fields": fields, "truncated": False}
    items = document.items() if isinstance(document, dict) else ((None, document),)
    for key, value in items:
        pointer = "" if key is None else "/" + key.replace("~", "~0").replace("/", "~1")
        field = {"pointer": pointer, "type": _JSON_TYPES[type(value)]}
        if isinstance(value, (dict, list)):
            field["length"] = len(value)
        if isinstance(value, list) and value:
            if isinstance(value[0], dict):
                field["first_item_fields"] = list(value[0])
            field["boundary_samples"] = []
            sensitive = key is not None and is_sensitive_arg(key, sink=RESULT_SINK, value=value)
            for index in dict.fromkeys((0, len(value) - 1)):
                sample = {"pointer": f"{pointer}/{index}"}
                if not sensitive:
                    try:
                        if len(json.dumps(value[index], ensure_ascii=False)) <= _STRUCTURE_SAMPLE_LIMIT:
                            sample["value"] = redact_payload(value[index], sink=RESULT_SINK)
                    except RecursionError:
                        pass
                field["boundary_samples"].append(sample)
        fields.append(field)
        if len(json.dumps(shape, ensure_ascii=False)) > TOOL_RESULT_LIMIT // 4:
            fields.pop()
            shape["truncated"] = True
            break
    return shape


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


class ReadFileTool(FileBoundTool, BaseTool):
    """Read file contents or one selected JSON value, with optional paging."""

    name = "read_file"
    description = (
        "Read a file from the workspace. Returns file contents, or the JSON value an RFC 6901 "
        "pointer selects. Use offset and limit for line windows. Continue with next_offset "
        "and, when returned, next_char_offset as char_offset."
    )
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
            "pointer": {
                "type": "string",
                "description": (
                    "Optional RFC 6901 JSON pointer into a JSON file, e.g. /_provenance or /data/0. "
                    "Selects that value before paging applies; an empty string selects "
                    "the whole document. A pointer that names no value is an error."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max number of lines to return (default: all)",
            },
            "offset": {
                "type": "integer",
                "minimum": 0,
                "description": "Zero-based first line of the file or JSON selection (default: 0)",
            },
            "char_offset": {
                "type": "integer",
                "minimum": 0,
                "description": "Character position within the first line (default: 0). "
                               "Use next_char_offset when the first line is longer than a page.",
            },
        },
        "required": ["path"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        """Read a file.

        Args:
            **kwargs: Must include path. Optional pointer (RFC 6901 selection inside a JSON
                file), offset (first line), limit (lines), char_offset (offset within the
                first line), and run_dir.

        Returns:
            JSON string containing content or an error. A pointer read carries ``pointer``,
            ``source_chars`` (characters in the whole file) and ``source_truncated`` when the
            selected value or an ancestor declares sampled data; its content is the selected
            value as indented JSON. A partial read carries ``truncated``, ``returned_chars``,
            ``total_chars``, ``returned_lines`` (lines through their end), ``total_lines`` and its
            starting offset. If more text follows, continue with ``next_offset`` and the optional
            ``next_char_offset``. Invalid pointers and offsets return an error without content.
        """
        file_path = kwargs["path"]
        limit = kwargs.get("limit")
        run_dir = kwargs.get("run_dir")
        offset = kwargs.get("offset", 0)
        char_offset = kwargs.get("char_offset", 0)
        if type(offset) is not int or offset < 0 or type(char_offset) is not int or char_offset < 0:
            return json.dumps({
                "status": "error",
                "error_code": "invalid_offset",
                "error": "offset and char_offset must be non-negative integers.",
            })

        allowed_roots = []
        if run_dir:
            try:
                run_root = _safe_run_dir(str(run_dir), roots=self.roots)
                allowed_roots.append(run_root)
                workspace = session_workspace_for_run(run_root, roots=self.roots)
                if workspace is not None:
                    workspace.mkdir(parents=True, exist_ok=True)
                    allowed_roots.append(workspace)
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
        for extra_root in allowed_file_roots(roots=self.roots):
            if extra_root not in allowed_roots:
                allowed_roots.append(extra_root)

        resolved = None
        namespaced = False
        # Whether any root contains the path at all: a path inside a root that
        # does not exist is "not found", one outside every root is refused.
        contained = False

        # `skills/` is a namespace bound to the bundled read-only skills root.
        # Binding the prefix stops a same-named file in run_dir — which the agent
        # itself can write — from shadowing a bundled skill and being loaded as
        # trusted guidance.
        if file_path.startswith("skills/"):
            namespaced = True
            try:
                candidate = _safe_path(file_path[len("skills/") :], skills_dir)
                contained = True
            except ValueError:
                candidate = None
            if candidate is not None and candidate.exists():
                resolved = candidate

        # Unprefixed paths search every allowed root, run_dir first.
        if resolved is None and not namespaced:
            for root in allowed_roots:
                try:
                    candidate = _safe_path(file_path, root)
                    contained = True
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
            if contained:
                error_code = "not_found"
                reason = f"{file_path} was not found."
            else:
                error_code = "outside_readable_roots"
                reason = f"{file_path} is outside what read_file may open."
            return json.dumps(
                {
                    "status": "error",
                    "error_code": error_code,
                    "error": f"{reason} {_READABLE}",
                },
                ensure_ascii=False,
            )

        pointer = kwargs.get("pointer")
        try:
            if resolved.is_dir():
                if pointer is not None:
                    return json.dumps({
                        "status": "error", "error_code": "not_a_file",
                        "error": "A JSON pointer selects inside a JSON file, not a directory. Omit pointer to list it.",
                    }, ensure_ascii=False)
                if offset or char_offset:
                    return json.dumps({
                        "status": "error", "error_code": "not_a_file",
                        "error": "Line and character offsets apply to files. Omit them to list the directory.",
                    }, ensure_ascii=False)
                # A directory is a question about what is in it.
                entries = sorted(
                    child.name + ("/" if child.is_dir() else "")
                    for child in resolved.iterdir()
                    if not child.name.startswith(".")
                )
                return json.dumps(
                    {
                        "status": "ok",
                        "path": str(resolved),
                        "kind": "directory",
                        "entries": entries[:_LISTING_LIMIT],
                        "truncated": len(entries) > _LISTING_LIMIT,
                    },
                    ensure_ascii=False,
                )

            source_text = original = resolved.read_text(encoding="utf-8")
            body: dict = {"status": "ok", "path": str(resolved)}
            if pointer is not None:
                from src.tools.data_refs import resolve_json_pointer

                try:
                    document = json.loads(original)
                except json.JSONDecodeError:
                    return json.dumps({
                        "status": "error", "error_code": "invalid_json",
                        "error": "A JSON pointer needs a JSON file. Omit pointer to read this file as text.",
                    }, ensure_ascii=False)
                try:
                    value, sampled = resolve_json_pointer(document, pointer)
                except ValueError as exc:
                    return json.dumps({"status": "error", "error_code": "invalid_pointer", "error": str(exc)},
                                      ensure_ascii=False)
                body.update(pointer=pointer, source_chars=len(original))
                if sampled:
                    body["source_truncated"] = True
                # The selection is what the limits below apply to.
                original = json.dumps(value, ensure_ascii=False, indent=2)
            page = _line_window(original, offset, limit, char_offset)
            if page.get("status") == "error":
                return json.dumps(page, ensure_ascii=False)
            body.update(page)
            encoded = json.dumps(body, ensure_ascii=False)
            if len(encoded) <= TOOL_RESULT_LIMIT:
                return encoded
            if pointer is None:
                try:
                    document = json.loads(source_text)
                except (ValueError, RecursionError):
                    return encoded
            body["_structure"] = _source_structure(document, body["path"])
            return json.dumps(body, ensure_ascii=False)
        except Exception as exc:
            return json.dumps(
                {
                    "status": "error",
                    "error": redact_internal_paths(str(exc)),
                },
                ensure_ascii=False,
            )
