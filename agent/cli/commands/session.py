"""``/history``, ``/search``, ``/export`` — session lifecycle commands.

* ``/history`` lists recent sessions (legacy ``cmd_sessions``).
* ``/search <query>`` runs FTS5 across the session store via
  :class:`src.session.search.SessionSearchIndex`.
* ``/export`` is a placeholder — the rich export lives in the Web bubble.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from cli.theme import get_console


def _resolve_console() -> Console:
    """Return the shared CLI console."""
    return get_console()


def cmd_history(ctx: Any = None, *args: str) -> int:  # noqa: ARG001
    """List recent sessions via legacy ``cmd_sessions``."""
    console = _resolve_console()
    try:
        from cli.commands.sessions import cmd_sessions

        cmd_sessions()
        return 0
    except Exception as exc:  # noqa: BLE001
        console.print(Text(f"/history failed: {exc}", style="bold red"))
        return 1


def cmd_search(ctx: Any = None, *args: str) -> int:  # noqa: ARG001
    """Full-text search across recorded sessions."""
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
    """Placeholder until the rich export lands."""
    console = _resolve_console()
    body = Text()
    body.append("/export is not yet wired up to the interactive CLI.\n\n", style="dim")
    body.append("Until then: ", style="dim")
    body.append("the web UI exports md/json from the message footer.", style="bold")
    console.print(Panel(body, title="/export", border_style="dim", padding=(1, 2)))
    return 0


def cmd_fork(ctx: Any = None, *args: str) -> int:
    """Fork the active session at ``/fork <turn-id> [title]``."""
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
    """Dispatch ``run("history")`` / ``run("search", ...)`` / ``run("export")``."""
    handler = _DISPATCH.get(command)
    if handler is None:
        console = _resolve_console()
        console.print(Text(f"Unknown session command: /{command}", style="bold red"))
        return 1
    return handler(ctx, *args)


__all__ = ["run", "cmd_history", "cmd_search", "cmd_export", "cmd_fork"]
