"""Tool screening for the claude-cli provider: the deny list and the bash policy.

Both are convenience filters, not a security boundary: ``python -c`` can still
run anything, and live orders stay bound by the mandate gate and kill switch.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Any, Optional

from src.config.accessor import get_env_config

_PYTHON_COMMANDS = frozenset({"python", "python3"})
_READONLY_COMMANDS = frozenset({"ls", "cat", "head", "tail", "wc", "pwd"})
_SHELL_PROCESS_TOOLS = frozenset({"background_run", "cancel_background"})
_SHELL_OPERATOR_CHARS = set("();<>|&")


def _deny_prefixes() -> tuple[str, ...]:
    """Tool-name prefixes never offered to the model; ``""`` disables the list."""
    raw = get_env_config().llm.claude_cli_deny_tool_prefixes
    return tuple(p.strip() for p in raw.split(",") if p.strip())


def bash_policy() -> str:
    """``python-only`` (default) or ``off``; anything else is a configuration error."""
    value = get_env_config().llm.claude_cli_bash_policy.strip().lower()
    if value not in {"python-only", "off"}:
        raise RuntimeError(
            f"CLAUDE_CLI_BASH_POLICY must be python-only or off, got {value!r}"
        )
    return value


def tool_name(definition: dict[str, Any]) -> str:
    return str((definition.get("function") or definition).get("name") or "")


def offered_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prefixes = _deny_prefixes()
    return (
        [t for t in tools if not tool_name(t).startswith(prefixes)]
        if prefixes
        else list(tools)
    )


def _relative_path(token: str) -> bool:
    return not token.startswith(("/", "~")) and ".." not in Path(token).parts


def _hidden_path(token: str) -> bool:
    # ``.env`` and ``.git`` hold credentials; a read would put them in the trace.
    return any(part.startswith(".") and part != "." for part in Path(token).parts)


def check_bash_command(command: str) -> tuple[Optional[str], Optional[str]]:
    """Apply the ``python-only`` policy to one shell command.

    Args:
        command: The command the model asked ``bash`` to run.

    Returns:
        ``(rewritten_command, None)`` when allowed, else ``(None, reason)``.
        An allowed ``python``/``python3`` call is rewritten to this process's
        interpreter so scripts can import Vibe-Trading's own packages.
    """
    if "\n" in command or "`" in command or "$(" in command:
        return None, "newlines, backticks and $( ) are not allowed"
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError as exc:
        return None, f"unparseable command: {exc}"
    if not tokens:
        return None, "empty command"
    if any(tok and set(tok) <= _SHELL_OPERATOR_CHARS for tok in tokens):
        return None, "shell operators (; && || | redirection) are not allowed"
    program, args = tokens[0], tokens[1:]
    if program in _PYTHON_COMMANDS:
        if args[:1] == ["-c"] and len(args) >= 2:
            return shlex.join([sys.executable, *args]), None
        if args and args[0].endswith(".py") and _relative_path(args[0]):
            return shlex.join([sys.executable, *args]), None
        return (
            None,
            "python may only run `python <relative script>.py` or `python -c <code>`",
        )
    if program in _READONLY_COMMANDS:
        paths = [a for a in args if not a.startswith("-")]
        if all(_relative_path(p) and not _hidden_path(p) for p in paths):
            return shlex.join(tokens), None
        return (
            None,
            f"{program} may only read non-hidden relative paths inside the working directory",
        )
    return None, f"program {program!r} is not allowed (python-only policy)"


def screen_calls(
    calls: list[dict[str, Any]], offered: set[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return calls the host may execute, plus one rejection note per refused call."""
    policy = bash_policy()
    accepted: list[dict[str, Any]] = []
    notes: list[str] = []
    for call in calls:
        name = str(call.get("name") or "")
        args = dict(call.get("arguments") or {})
        if name not in offered:
            notes.append(f"- {name}: not an available tool")
            continue
        if policy == "python-only" and name in _SHELL_PROCESS_TOOLS:
            notes.append(
                f"- {name}: background processes are not allowed (python-only policy)"
            )
            continue
        if policy == "python-only" and name == "bash":
            rewritten, reason = check_bash_command(str(args.get("command") or ""))
            if reason:
                notes.append(f"- bash `{args.get('command')}`: {reason}")
                continue
            args["command"] = rewritten
        accepted.append({"name": name, "arguments": args})
    return accepted, notes
