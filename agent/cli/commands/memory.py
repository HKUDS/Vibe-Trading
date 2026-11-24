"""``/memory`` — list / show persistent memory snippets."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.text import Text

from cli.theme import get_console


def _resolve_console() -> Console:
    """Return the shared CLI console."""
    return get_console()


def cmd_memory(ctx: Any = None, *args: str) -> int:  # noqa: ARG001
    """List, show, search, or forget persistent memories.

    Args:
        ctx: Unused interactive context.
        *args: Memory name, search query tokens, or forget command with a name. Empty arguments list
            entries.

    Returns:
        Exit status of the selected memory command, or one if dispatch raises an exception.
    """
    console = _resolve_console()

    if not args:
        try:
            from cli.commands.setup_memory import cmd_memory_list

            return cmd_memory_list()
        except Exception as exc:  # noqa: BLE001
            console.print(Text(f"/memory list failed: {exc}", style="bold red"))
            return 1

    sub = args[0]
    rest = args[1:]
    try:
        if sub == "search" and rest:
            from cli.commands.setup_memory import cmd_memory_search

            return cmd_memory_search(" ".join(rest))
        if sub == "forget" and rest:
            from cli.commands.setup_memory import cmd_memory_forget

            return cmd_memory_forget(rest[0], yes=False)
        from cli.commands.setup_memory import cmd_memory_show

        return cmd_memory_show(sub)
    except Exception as exc:  # noqa: BLE001
        console.print(Text(f"/memory failed: {exc}", style="bold red"))
        return 1


def run(ctx: Any = None, *args: str) -> int:
    """Dispatch the memory slash command.

    Args:
        ctx: Interactive context passed through to the memory handler.
        *args: Memory subcommand arguments or entry name.

    Returns:
        Exit status of the memory handler.
    """
    return cmd_memory(ctx, *args)


__all__ = ["run", "cmd_memory"]
