"""``/show``, ``/skill``, ``/pine`` — read-only inspect commands."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.text import Text

from cli.theme import get_console


def _resolve_console() -> Console:
    """Return the shared CLI console."""
    return get_console()


def cmd_show(ctx: Any = None, *args: str) -> int:  # noqa: ARG001
    """Display a prior run through the inspection handler.

    Args:
        ctx: Unused interactive context.
        *args: Run ID as the first argument.

    Returns:
        Zero when the inspection handler returns, or one if the ID is omitted or inspection raises
        an exception.
    """
    console = _resolve_console()
    if not args:
        console.print(Text("Usage: /show <run_id>", style="bold red"))
        return 1
    try:
        from cli.commands.inspection import cmd_show as show_run

        show_run(args[0])
        return 0
    except Exception as exc:  # noqa: BLE001
        console.print(Text(f"/show failed: {exc}", style="bold red"))
        return 1


def cmd_skill(ctx: Any = None, *args: str) -> int:  # noqa: ARG001
    """List bundled and user skills.

    Args:
        ctx: Unused interactive context.
        *args: Unused slash-command arguments.

    Returns:
        Zero after listing skills, or one if the listing raises an exception.
    """
    console = _resolve_console()
    try:
        from cli.commands.inspection import cmd_skills

        cmd_skills()
        return 0
    except Exception as exc:  # noqa: BLE001
        console.print(Text(f"/skill failed: {exc}", style="bold red"))
        return 1


def cmd_pine(ctx: Any = None, *args: str) -> int:  # noqa: ARG001
    """Display a prior run's Pine Script artifact.

    Args:
        ctx: Unused interactive context.
        *args: Run ID as the first argument.

    Returns:
        Zero when the inspection handler returns, or one if the ID is omitted or inspection raises
        an exception.
    """
    console = _resolve_console()
    if not args:
        console.print(Text("Usage: /pine <run_id>", style="bold red"))
        return 1
    try:
        from cli.commands.inspection import cmd_pine as show_pine

        show_pine(args[0])
        return 0
    except Exception as exc:  # noqa: BLE001
        console.print(Text(f"/pine failed: {exc}", style="bold red"))
        return 1


_DISPATCH = {
    "show": cmd_show,
    "skill": cmd_skill,
    "pine": cmd_pine,
}


def run(ctx: Any = None, command: str = "show", *args: str) -> int:
    """Dispatch a run or skill inspection slash command.

    Args:
        ctx: Interactive context passed to the handler.
        command: Command name without the leading slash.
        *args: Arguments passed to the handler.

    Returns:
        Handler exit status, or one for an unknown command.
    """
    handler = _DISPATCH.get(command)
    if handler is None:
        console = _resolve_console()
        console.print(Text(f"Unknown show command: /{command}", style="bold red"))
        return 1
    return handler(ctx, *args)


__all__ = ["run", "cmd_show", "cmd_skill", "cmd_pine"]
