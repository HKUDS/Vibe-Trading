"""Provider-agnostic tool screening: the deny list and the bash policy."""

from __future__ import annotations

from dataclasses import dataclass

import shlex
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from src.config.env_schema import EnvConfig, LLMConfig
if TYPE_CHECKING:
    from src.tools.path_utils import FileRoots
    from src.tools.sandbox import SandboxSettings

_PYTHON_COMMANDS = frozenset({"python", "python3"})
_READONLY_COMMANDS = frozenset({"ls", "cat", "head", "tail", "wc", "pwd"})
_SHELL_PROCESS_TOOLS = frozenset({"background_run", "cancel_background"})
_SHELL_OPERATOR_CHARS = set("();<>|&")


def _policy_value(config: LLMConfig, generic: str, legacy: str, default: str, legacy_defaults: bool) -> tuple[str, str]:
    if (value := getattr(config, generic)) is not None:
        return value, type(config).model_fields[generic].alias
    if legacy_defaults or legacy in config.model_fields_set:
        return getattr(config, legacy), type(config).model_fields[legacy].alias
    return default, "default"


@dataclass(frozen=True)
class ToolPolicy:
    """Host-configured policy shared by the registry and the provider."""

    prefixes: tuple[str, ...]
    deny_source: str
    bash: str
    bash_source: str
    claude_prefixes: tuple[str, ...]
    claude_deny_source: str
    claude_bash: str
    claude_bash_source: str
    sandbox: SandboxSettings
    shell_tools_enabled: bool
    file_roots: FileRoots

    @classmethod
    def from_config(cls, config: EnvConfig) -> ToolPolicy:
        """Snapshot general and Claude CLI tool-policy settings.

        Args:
            config: Resolved LLM and API settings supplying policy and filesystem limits.

        Returns:
            Policy holding both sets of tool restrictions, sandbox settings, and file roots.
        """
        from src.tools.path_utils import FileRoots
        from src.tools.sandbox import SandboxSettings

        def settings(legacy: bool) -> tuple[tuple[str, ...], str, str, str]:
            deny, deny_source = _policy_value(
                config.llm, "vibe_trading_deny_tool_prefixes", "claude_cli_deny_tool_prefixes", "", legacy
            )
            bash, bash_source = _policy_value(
                config.llm, "vibe_trading_bash_policy", "claude_cli_bash_policy", "off", legacy
            )
            return tuple(p.strip() for p in deny.split(",") if p.strip()), deny_source, bash.strip().lower(), bash_source

        file_roots = FileRoots.from_config(config.api)
        return cls(
            *settings(False), *settings(True),
            SandboxSettings.from_config(config.api, runtime_root=file_roots.runtime_root),
            config.api.vibe_trading_enable_shell_tools,
            file_roots,
        )

    def denies(self, name: str, *, legacy_defaults: bool = False) -> bool:
        """Check the tool name against the applicable deny prefixes.

        Args:
            name: Tool name to check.
            legacy_defaults: Whether to select the Claude CLI policy.

        Returns:
            True if the name starts with a configured deny prefix.
        """
        return name.startswith(self.claude_prefixes if legacy_defaults else self.prefixes)

    def bash_policy(self, *, legacy_defaults: bool = False) -> str:
        """Validate the selected bash policy at the enforcement boundary.

        Args:
            legacy_defaults: Whether to select the Claude CLI policy.

        Returns:
            The validated policy value, either python-only or off.

        Raises:
            RuntimeError: The selected policy value is unsupported.
        """
        value, source = (self.claude_bash, self.claude_bash_source) if legacy_defaults else (self.bash, self.bash_source)
        if value not in {"python-only", "off"}:
            raise RuntimeError(f"{source} must be python-only or off, got {value!r}")
        return value

    def status(self, *, legacy_defaults: bool) -> dict[str, Any]:
        """Report the selected policy and its configuration sources.

        Args:
            legacy_defaults: Whether to select the Claude CLI policy.

        Returns:
            The active deny prefixes, bash policy, and source of each setting.

        Raises:
            RuntimeError: The selected bash policy value is unsupported.
        """
        return {
            "deny_tool_prefixes": list(self.claude_prefixes if legacy_defaults else self.prefixes),
            "deny_tool_prefixes_source": self.claude_deny_source if legacy_defaults else self.deny_source,
            "bash_policy": self.bash_policy(legacy_defaults=legacy_defaults),
            "bash_policy_source": self.claude_bash_source if legacy_defaults else self.bash_source,
        }

    def offered_tools(self, tools: list[dict[str, Any]], *, legacy_defaults: bool = False) -> list[dict[str, Any]]:
        """Keep tool definitions that the applicable policy allows.

        Args:
            tools: Tool definitions to screen in their existing order.
            legacy_defaults: Whether to select the Claude CLI policy.

        Returns:
            The definitions whose names do not match the selected deny prefixes.
        """
        return [tool for tool in tools if not self.denies(tool_name(tool), legacy_defaults=legacy_defaults)]

    def screen_calls(
        self, calls: list[dict[str, Any]], offered: set[str], *, legacy_defaults: bool = False
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Screen requested calls before handing them to the host.

        Args:
            calls: Requested calls with tool names and argument mappings.
            offered: Names available for this request.
            legacy_defaults: Whether to select the Claude CLI policy.

        Returns:
            Accepted calls with any policy-adjusted arguments and one note per refusal.

        Raises:
            RuntimeError: The selected bash policy value is unsupported.
        """
        policy = self.bash_policy(legacy_defaults=legacy_defaults)
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


    def __call__(self, name: str, params: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        """Preflight a call from the tool registry or a trusted invocation."""
        if self.denies(name):
            return False, f"{name} is disabled by the active tool policy", params
        if name in {"bash", "background_run", "cancel_background"}:
            accepted, notes = self.screen_calls([{"name": name, "arguments": params}], {name})
            if notes:
                return False, notes[0], params
            return True, "", accepted[0]["arguments"]
        return True, "", params


def tool_name(definition: dict[str, Any]) -> str:
    """Read a tool's name from a function definition.

    Args:
        definition: Tool schema with a nested function definition or a top-level name.

    Returns:
        The name as a string, or an empty string when absent.
    """
    return str((definition.get("function") or definition).get("name") or "")


def _relative_path(token: str) -> bool:
    return not token.startswith(("/", "~")) and ".." not in Path(token).parts


def _hidden_path(token: str) -> bool:
    # ``.env`` and ``.git`` hold credentials; a read would put them in the trace.
    return any(part.startswith(".") and part != "." for part in Path(token).parts)


def check_bash_command(command: str) -> tuple[Optional[str], Optional[str]]:
    """Apply the python-only policy to one shell command.

    Args:
        command: The command the model asked bash to run.

    Returns:
        The rewritten command and no reason when allowed, or None and a refusal
        reason otherwise. Allowed Python calls use this process's interpreter.
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
    join = subprocess.list2cmdline if os.name == "nt" else shlex.join
    if program in _PYTHON_COMMANDS or program == sys.executable:
        if args[:1] == ["-c"] and len(args) >= 2:
            return join([sys.executable, *args]), None
        if args and args[0].endswith(".py") and _relative_path(args[0]):
            return join([sys.executable, *args]), None
        return (
            None,
            "python may only run `python <relative script>.py` or `python -c <code>`",
        )
    if program in _READONLY_COMMANDS:
        paths = [a for a in args if not a.startswith("-")]
        if all(_relative_path(p) and not _hidden_path(p) for p in paths):
            return join(tokens), None
        return (
            None,
            f"{program} may only read non-hidden relative paths inside the working directory",
        )
    return None, f"program {program!r} is not allowed (python-only policy)"
