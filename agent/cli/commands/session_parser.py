"""Session-related global option registration."""
from __future__ import annotations
import argparse

def register(subparsers: argparse._SubParsersAction) -> None:
    """Register session maintenance commands.

    Args:
        subparsers: Parent subparser collection for the sessions command.
    """
    sessions = subparsers.add_parser("sessions", help="Manage chat sessions")
    sessions.add_subparsers(dest="sessions_command").add_parser(
        "migrate", help="Migrate pre-thread sessions"
    )
