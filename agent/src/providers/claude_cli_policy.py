"""Compatibility re-exports for the provider-agnostic tool policy."""

from src.providers import tool_policy as _shared
from src.providers.tool_policy import (
    check_bash_command,
    tool_name,
)


def _deny_prefixes():
    return _shared._deny_prefixes(legacy_defaults=True)


def bash_policy():
    return _shared.bash_policy(legacy_defaults=True)


def offered_tools(tools):
    return _shared.offered_tools(tools, legacy_defaults=True)


def screen_calls(calls, offered):
    return _shared.screen_calls(calls, offered, legacy_defaults=True)

__all__ = [
    "_deny_prefixes",
    "bash_policy",
    "check_bash_command",
    "offered_tools",
    "screen_calls",
    "tool_name",
]
