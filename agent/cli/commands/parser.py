"""Argparse registry assembled from command-family modules."""
from __future__ import annotations
import argparse

from cli.commands import channels_parser, connector_parser, core, data_parser, memory_parser
from cli.commands import portfolio_parser, provider_parser, research_parser, session_parser


def build_parser() -> argparse.ArgumentParser:
    """Build the public command-line parser.

    Returns:
        Argument parser with top-level flags and all command families registered.
    """
    parser = argparse.ArgumentParser(description="Vibe-Trading CLI")
    core.register_global_arguments(parser)
    parser.add_argument("--swarm-presets", action="store_true", help="List swarm presets")
    parser.add_argument("--swarm-inspect", metavar="PRESET", help="Inspect a swarm preset without running it")
    parser.add_argument("--swarm-run", nargs="+", metavar=("PRESET", "VARS"), help="Run a swarm preset")
    parser.add_argument("--swarm-list", action="store_true", help="List swarm runs")
    parser.add_argument("--swarm-show", metavar="RUN_ID", help="Show a swarm run")
    parser.add_argument("--swarm-cancel", metavar="RUN_ID", help="Cancel a swarm run")
    parser.add_argument("--swarm-retry", metavar="RUN_ID", help="Retry a prior swarm run")
    parser.add_argument("--swarm-resume", action="store_true", help="Keep completed tasks when retrying a swarm run")
    parser.add_argument("--sessions", action="store_true", help="List sessions")
    parser.add_argument("--session-chat", metavar="SESSION_ID", help="Continue a session chat")
    parser.add_argument("--upload", metavar="FILE_PATH", help="Upload a file")
    subparsers = parser.add_subparsers(dest="command")
    session_parser.register(subparsers)
    core.register_subcommands(subparsers)
    provider_parser.register(subparsers)
    data_parser.register(subparsers)
    channels_parser.register(subparsers)
    core.register_inspection_subcommands(subparsers)
    memory_parser.register(subparsers, core.positive_int)
    portfolio_parser.register(subparsers)
    connector_parser.register(subparsers)
    research_parser.register(subparsers)
    return parser
