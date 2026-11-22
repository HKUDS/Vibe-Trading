"""Session-related global option registration."""
from __future__ import annotations
import argparse

def register_global_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sessions", action="store_true", help="List sessions")
    parser.add_argument("--session-chat", metavar="SESSION_ID", help="Continue a session chat")
    parser.add_argument("--upload", metavar="FILE_PATH", help="Upload a file")


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register session maintenance commands."""
    sessions = subparsers.add_parser("sessions", help="Manage chat sessions")
    sessions.add_subparsers(dest="sessions_command").add_parser(
        "migrate", help="Migrate pre-thread sessions"
    )
