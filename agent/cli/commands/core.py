"""Core CLI parser registrations for prompt, run, setup, and inspection commands."""
from __future__ import annotations

import argparse
from pathlib import Path


def positive_int(value: str) -> int:
    """Parse a command-line count of at least one.

    Args:
        value: Command-line value to convert.

    Returns:
        Parsed positive integer.

    Raises:
        argparse.ArgumentTypeError: If the value is not an integer greater than zero.
    """
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {number}")
    return number


def register_global_arguments(parser: argparse.ArgumentParser) -> None:
    """Register top-level prompt, inspection, and execution flags.

    Args:
        parser: Top-level CLI argument parser to extend.
    """
    from cli._version import __version__

    parser.add_argument("--version", action="version", version="vibe-trading " + __version__)
    _register_prompt_arguments(parser)
    parser.add_argument("--chat", action="store_true", help="Interactive chat mode")
    parser.add_argument("--continue", dest="cont", nargs=2, metavar=("RUN_ID", "PROMPT"), help="Continue a run")
    parser.add_argument("--list", action="store_true", help="List runs")
    parser.add_argument("--show", metavar="RUN_ID", help="Show run details")
    parser.add_argument("--code", metavar="RUN_ID", help="Show generated code")
    parser.add_argument("--pine", metavar="RUN_ID", help="Show Pine Script for TradingView")
    parser.add_argument("--trace", metavar="RUN_ID", help="Replay a run trace")
    parser.add_argument("--skills", action="store_true", help="List skills")
    _register_max_iterations(parser, "max_iter")


def _register_prompt_arguments(parser: argparse.ArgumentParser, prefix: str = "") -> None:
    parser.add_argument("-p", "--prompt", dest=prefix + "prompt", type=str, help="Prompt text")
    parser.add_argument("-f", "--prompt-file", dest=prefix + "prompt_file", type=Path, help="Read prompt text from a file")
    parser.add_argument("--json", dest=prefix + "json", action="store_true", help="Print machine-readable JSON output")
    parser.add_argument("--no-rich", dest=prefix + "no_rich", action="store_true", help="Disable Rich formatting")


def _register_max_iterations(parser: argparse.ArgumentParser, dest: str) -> None:
    parser.add_argument("--max-iter", dest=dest, type=int, default=50, help="Maximum agent iterations")


def register_subcommands(subparsers: argparse._SubParsersAction) -> None:
    """Register the run, serve, and office commands.

    Args:
        subparsers: Parent subparser collection for the three commands.
    """
    run_parser = subparsers.add_parser("run", help="Run a prompt")
    _register_prompt_arguments(run_parser, "run_")
    _register_max_iterations(run_parser, "run_max_iter")
    serve_parser = subparsers.add_parser("serve", help="Start the API server")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    serve_parser.add_argument("--port", type=int, default=8000, help="Listen port")
    serve_parser.add_argument("--dev", action="store_true", help="Start the Vite dev server")
    office_parser = subparsers.add_parser("office", help="Manage the shared research task board")
    office_parser.add_argument("office_args", nargs=argparse.REMAINDER)


def register_inspection_subcommands(subparsers: argparse._SubParsersAction) -> None:
    """Register run inspection, interactive chat, setup, and development commands.

    Args:
        subparsers: Parent subparser collection to extend.
    """
    list_parser = subparsers.add_parser("list", help="List runs")
    list_parser.add_argument("--limit", dest="list_limit", type=positive_int, default=20, help="Maximum number of runs")
    show_parser = subparsers.add_parser("show", help="Show run details")
    show_parser.add_argument("run_id", help="Run identifier")
    chat_parser = subparsers.add_parser("chat", help="Interactive chat mode")
    _register_max_iterations(chat_parser, "chat_max_iter")
    subparsers.add_parser("update", help="Check for and install the latest vibe-trading-ai release from PyPI")
    subparsers.add_parser("init", help="Interactive setup: create ~/.vibe-trading/.env")
    from cli.commands import common
    setup_parser = subparsers.add_parser("setup", help="Install frontend dependencies and build the production bundle")
    setup_parser.add_argument("--frontend-dir", default=str(common.AGENT_DIR.parent / "frontend"), help="Path to the frontend directory (default: <repo>/frontend)")
    dev_parser = subparsers.add_parser("dev", help="Start backend + frontend dev servers in one process")
    dev_parser.add_argument("--port", type=int, default=8899, help="Backend port (default: 8899)")
    dev_parser.add_argument("--frontend-port", type=int, default=5899, help="Vite dev server port, must match vite.config.ts (default: 5899)")
    dev_parser.add_argument("--frontend-dir", default=str(common.AGENT_DIR.parent / "frontend"), help="Path to the frontend directory (default: <repo>/frontend)")
