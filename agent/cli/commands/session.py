"""``/history``, ``/search``, ``/export`` — session lifecycle commands."""

from __future__ import annotations

from src.config.accessor import get_env_config

from src.product.tool_policy import ToolPolicy

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from cli.theme import get_console


def _resolve_console() -> Console:
    """Return the shared CLI console."""
    return get_console()


def cmd_history(ctx: Any = None, *args: str) -> int:  # noqa: ARG001
    """List recent sessions using the session history handler.

    Args:
        ctx: Unused interactive context.
        *args: Unused slash-command arguments.

    Returns:
        Zero after listing sessions, or one if the history handler raises an exception.
    """
    console = _resolve_console()
    try:
        from cli.commands.sessions import cmd_sessions

        cmd_sessions()
        return 0
    except Exception as exc:  # noqa: BLE001
        console.print(Text(f"/history failed: {exc}", style="bold red"))
        return 1


def cmd_search(ctx: Any = None, *args: str) -> int:  # noqa: ARG001
    """Full-text search across recorded sessions.

    Args:
        ctx: Unused interactive context.
        *args: Search query words joined with spaces.

    Returns:
        Zero after displaying matches or reporting an empty result, or one for a missing query or a
        search error.
    """
    console = _resolve_console()
    if not args:
        console.print(Text("Usage: /search <query>", style="bold red"))
        return 1

    query = " ".join(args)
    try:
        from src.session.search import get_shared_index

        index = get_shared_index()
        matches = index.search(query)
    except Exception as exc:  # noqa: BLE001
        console.print(Text(f"/search failed: {exc}", style="bold red"))
        return 1

    if not matches:
        console.print(Text(f"No matches for '{query}'.", style="dim"))
        return 0

    for hit in matches:
        line = Text()
        line.append(str(hit.session_id), style="bold")
        line.append("  ")
        line.append(hit.title, style="dim")
        line.append("  ")
        line.append(hit.snippet or "", style="dim")
        console.print(line)
    return 0


def cmd_export(ctx: Any = None, *args: str) -> int:  # noqa: ARG001
    """Show where session export is available.

    Args:
        ctx: Unused interactive context.
        *args: Unused slash-command arguments.

    Returns:
        Zero after printing the web export instructions.
    """
    console = _resolve_console()
    body = Text()
    body.append("/export is not yet wired up to the interactive CLI.\n\n", style="dim")
    body.append("Until then: ", style="dim")
    body.append("the web UI exports md/json from the message footer.", style="bold")
    console.print(Panel(body, title="/export", border_style="dim", padding=(1, 2)))
    return 0


def cmd_fork(ctx: Any = None, *args: str) -> int:
    """Fork the active session at a specified turn and switch to the fork.

    Args:
        ctx: Interactive context holding the active session ID and optional transcript.
        *args: Source turn ID followed by optional title words.

    Returns:
        Zero on successful fork, or one for missing inputs or a failed fork.
    """
    console = _resolve_console()
    session_id = getattr(ctx, "session_id", None)
    if not session_id or not args:
        console.print(Text("Usage: /fork <turn-id> [title]", style="bold red"))
        return 1
    try:
        from cli.main import _session_store
        from src.config.paths import get_runs_dir
        from src.session.events import EventBus
        from src.session.service import SessionService

        turn_id, *title_parts = args
        session = SessionService(
            policy=ToolPolicy.from_config(get_env_config()),
            store=_session_store(), event_bus=EventBus(), runs_dir=get_runs_dir()
        ).fork_session(session_id, turn_id, title=" ".join(title_parts))
        ctx.session_id = session.session_id
        if hasattr(ctx, "transcript"):
            ctx.transcript = []
    except Exception as exc:  # noqa: BLE001 - preserve the REPL on refusal
        console.print(Text(f"/fork failed: {exc}", style="bold red"))
        return 1
    console.print(Text(f"Forked session {session.session_id} from turn {turn_id}.", style="bold"))
    return 0


_DISPATCH = {
    "history": cmd_history,
    "search": cmd_search,
    "export": cmd_export,
    "fork": cmd_fork,
}


def run(ctx: Any = None, command: str = "history", *args: str) -> int:
    """Dispatch a session slash command.

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
        console.print(Text(f"Unknown session command: /{command}", style="bold red"))
        return 1
    return handler(ctx, *args)


__all__ = ["run", "cmd_history", "cmd_search", "cmd_export", "cmd_fork"]
