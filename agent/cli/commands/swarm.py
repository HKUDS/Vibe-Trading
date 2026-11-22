"""Slash routing for the swarm command family.

The interactive loop owns input and lifecycle handling. This module only parses
the slash arguments and delegates the actual swarm operations to the existing
subcommand implementations.
"""

from __future__ import annotations

import cli.commands.swarm_runtime as _cmd_swarm_runtime

from cli.theme import get_console


def dispatch(argument_text: str) -> int:
    """Dispatch ``/swarm`` arguments and return a slash-handler status."""

    console = get_console()
    argument_text = argument_text.strip()
    if not argument_text:
        _cmd_swarm_runtime.cmd_swarm_presets()
        return 0

    parts = argument_text.split(maxsplit=1)
    command = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""

    if command == "run":
        run_parts = argument.split(maxsplit=1)
        if not run_parts:
            console.print("[red]Usage: /swarm run <preset> [vars_json][/red]")
            return 0
        _cmd_swarm_runtime.cmd_swarm_run_live(run_parts[0], run_parts[1] if len(run_parts) > 1 else None)
        return 0
    if command == "inspect":
        if argument:
            _cmd_swarm_runtime.cmd_swarm_inspect(argument)
        else:
            console.print("[red]Usage: /swarm inspect <preset>[/red]")
        return 0
    if command == "list":
        _cmd_swarm_runtime.cmd_swarm_list()
        return 0
    if command == "show":
        if argument:
            _cmd_swarm_runtime.cmd_swarm_show(argument)
        else:
            console.print("[red]Usage: /swarm show <run_id>[/red]")
        return 0
    if command == "cancel":
        if argument:
            _cmd_swarm_runtime.cmd_swarm_cancel(argument)
        else:
            console.print("[red]Usage: /swarm cancel <run_id>[/red]")
        return 0
    if command == "retry":
        retry_parts = argument.split()
        if len(retry_parts) == 1:
            _cmd_swarm_runtime.cmd_swarm_retry_live(retry_parts[0])
        elif len(retry_parts) == 2 and retry_parts[1] == "--resume":
            _cmd_swarm_runtime.cmd_swarm_retry_live(retry_parts[0], resume=True)
        else:
            console.print("[red]Usage: /swarm retry <run_id> [--resume][/red]")
        return 0

    console.print(f"[red]Unknown swarm command: {command}[/red]")
    return 0


__all__ = ["dispatch"]
