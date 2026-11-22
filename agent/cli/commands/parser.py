"""Argparse registry assembled from command-family modules."""
from __future__ import annotations
import argparse

from cli.commands import channels_parser, connector_parser, core, data_parser, memory_parser
from cli.commands import portfolio_parser, provider_parser, research_parser, session_parser, swarm_parser


def build_parser() -> argparse.ArgumentParser:
    """Build the public parser through one registration function per family."""
    parser = argparse.ArgumentParser(description="Vibe-Trading CLI")
    core.register_global_arguments(parser)
    swarm_parser.register_global_arguments(parser)
    session_parser.register_global_arguments(parser)
    subparsers = parser.add_subparsers(dest="command")
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
