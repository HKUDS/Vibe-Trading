"""Persistent memory command parser registration."""
from __future__ import annotations
import argparse

def register(subparsers: argparse._SubParsersAction, positive_int) -> None:
    """Register commands for inspecting and removing persistent memories.

    Args:
        subparsers: Parent subparser collection for the memory command.
        positive_int: Argument converter that validates a positive search result limit.
    """
    from src.memory.persistent import MEMORY_TYPES
    memory_parser = subparsers.add_parser("memory", help="Inspect persistent memory")
    memory_subparsers = memory_parser.add_subparsers(dest="memory_command")
    memory_list_parser = memory_subparsers.add_parser("list", help="List memory entries")
    memory_list_parser.add_argument("--type", dest="memory_type", choices=MEMORY_TYPES, help="Filter by memory type")
    memory_show_parser = memory_subparsers.add_parser("show", help="Show a memory entry")
    memory_show_parser.add_argument("name", help="Memory title or filename stem")
    memory_search_parser = memory_subparsers.add_parser("search", help="Recall memories for a query")
    memory_search_parser.add_argument("query", help="Search text")
    memory_search_parser.add_argument("--limit", dest="memory_limit", type=positive_int, default=5, help="Maximum matches (default: 5)")
    memory_forget_parser = memory_subparsers.add_parser("forget", help="Remove a memory entry")
    memory_forget_parser.add_argument("name", help="Memory title or filename stem")
    memory_forget_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
