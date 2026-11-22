"""Session-related global option registration."""
from __future__ import annotations
import argparse

def register_global_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sessions", action="store_true", help="List sessions")
    parser.add_argument("--session-chat", metavar="SESSION_ID", help="Continue a session chat")
    parser.add_argument("--upload", metavar="FILE_PATH", help="Upload a file")
