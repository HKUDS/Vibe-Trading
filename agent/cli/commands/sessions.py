"""CLI sessions commands and their helpers."""
from __future__ import annotations

from cli.commands import common

def cmd_sessions() -> None:
    """List chat sessions."""
    from src.session.store import SessionStore

    store = SessionStore(base_dir=common.SESSIONS_DIR)
    sessions = store.list_sessions()

    if not sessions:
        common.console.print("[dim]No sessions yet[/dim]")
        return

    table = common.Table(title="Sessions", show_lines=False)
    table.add_column("Session ID", style="cyan", no_wrap=True)
    table.add_column("Title", max_width=30)
    table.add_column("Status", width=10)
    table.add_column("Messages", width=8, justify="right")
    table.add_column("Updated", width=20)

    for s in sessions:
        messages = store.get_messages(s.session_id)
        sc = "green" if s.status.value == "active" else "dim"
        table.add_row(
            s.session_id,
            s.title or "[dim]untitled[/dim]",
            f"[{sc}]{s.status.value}[/{sc}]",
            str(len(messages)),
            s.updated_at[:19],
        )

    common.console.print(table)


def cmd_session_chat(session_id: str, max_iter: int) -> None:
    """Continue a session through the canonical interactive loop.

    Args:
        session_id: ID of the session to resume.
        max_iter: Maximum agent iterations per turn in the interactive loop.
    """
    from src.session.store import SessionStore

    store = SessionStore(base_dir=common.SESSIONS_DIR)
    session = store.get_session(session_id)

    if session is None:
        common.console.print(f"[red]Session {session_id} not found[/red]")
        return

    messages = store.get_messages(session_id, limit=None)
    common.console.print(
        common.Panel(
            f"[bold cyan]Session: {session.title or session_id}[/bold cyan]\n"
            f"[dim]History: {len(messages)} messages | Type q or /quit to exit[/dim]",
            border_style="cyan",
        )
    )

    from cli.main import _interactive_loop

    _interactive_loop(max_iter, resume_session_id=session_id, session_store=store)


def cmd_upload(file_path: str) -> None:
    """Copy a local file into the server's uploads directory.

    Args:
        file_path: Path to the source file. Its extension is preserved in the generated upload name.
    """
    src = common.Path(file_path)
    if not src.exists():
        common.console.print(f"[red]File not found: {file_path}[/red]")
        return
    if not src.is_file():
        common.console.print(f"[red]Not a file: {file_path}[/red]")
        return

    common.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    ext = src.suffix
    dest_name = f"{common.uuid.uuid4().hex[:12]}{ext}"
    dest = common.UPLOADS_DIR / dest_name

    common.shutil.copy2(str(src), str(dest))
    common.console.print(f"[green]Uploaded:[/green] {dest}")


def cmd_migrate_sessions() -> int:
    """Convert every pre-thread session into the canonical thread log.

    Returns:
        Zero after running migration and printing the number of migrated sessions.
    """
    from src.session.migration import migrate_all

    results = migrate_all(common.SESSIONS_DIR)
    migrated = sum(result.migrated for result in results)
    common.console.print(f"Migrated {migrated} of {len(results)} sessions.")
    return 0
