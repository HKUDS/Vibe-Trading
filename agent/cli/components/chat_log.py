"""Minimal chat-log renderer — stub for the demo."""

from __future__ import annotations

from typing import Iterable, Mapping, Optional

from rich.console import Console
from rich.text import Text


def _resolve_console(console: Optional[Console]) -> Console:
    """Return ``console`` if given, else the shared CLI console."""
    if console is not None:
        return console
    from cli.theme import get_console

    return get_console()


def _render_turn(turn: Mapping[str, object]) -> Text:
    """Compose the meta header line for one turn."""
    role = str(turn.get("role", "user"))
    timestamp = turn.get("timestamp")
    meta = turn.get("meta")
    header = Text()
    if role == "assistant":
        # "Vibe" is the brand wordmark for assistant turns — primary color
        header.append("Vibe", style="bold #d97706")
    else:
        header.append("you", style="bold")
    if timestamp:
        header.append(f"  {timestamp}", style="dim")
    if meta:
        header.append(f"  ·  {meta}", style="dim")
    return header


def render_history(
    turns: Iterable[Mapping[str, object]],
    *,
    console: Optional[Console] = None,
) -> None:
    """Print past turns to the CLI console.

    Args:
        turns: Iterable of turn mappings with display metadata and optional message content.
        console: Console override. Defaults to the shared CLI console.
    """
    cons = _resolve_console(console)
    for turn in turns:
        cons.print(_render_turn(turn))
        content = str(turn.get("content", ""))
        if content:
            # Keep the terminal transcript monospaced for diff-friendly replay.
            cons.print(content)
        cons.print()  # blank line between turns


__all__ = ["render_history"]
