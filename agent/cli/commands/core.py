"""Core CLI parser registrations for prompt, run, setup, and inspection commands."""
from __future__ import annotations

import argparse
from pathlib import Path


def positive_int(value: str) -> int:
    """argparse type for counts that must be at least one."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {number}")
    return number


def register_global_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--version", action="version", version="vibe-trading " + _version())
    parser.add_argument("-p", "--prompt", type=str, help="Prompt text")
    parser.add_argument("-f", "--prompt-file", type=Path, help="Read prompt text from a file")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    parser.add_argument("--no-rich", action="store_true", help="Disable Rich formatting")
    parser.add_argument("--chat", action="store_true", help="Interactive chat mode")
    parser.add_argument("--continue", dest="cont", nargs=2, metavar=("RUN_ID", "PROMPT"), help="Continue a run")
    parser.add_argument("--list", action="store_true", help="List runs")
    parser.add_argument("--show", metavar="RUN_ID", help="Show run details")
    parser.add_argument("--code", metavar="RUN_ID", help="Show generated code")
    parser.add_argument("--pine", metavar="RUN_ID", help="Show Pine Script for TradingView")
    parser.add_argument("--trace", metavar="RUN_ID", help="Replay a run trace")
    parser.add_argument("--skills", action="store_true", help="List skills")
    parser.add_argument("--max-iter", type=int, default=50, help="Maximum agent iterations")


def register_subcommands(subparsers: argparse._SubParsersAction) -> None:
    run_parser = subparsers.add_parser("run", help="Run a prompt")
    run_parser.add_argument("-p", "--prompt", dest="run_prompt", type=str, help="Prompt text")
    run_parser.add_argument("-f", "--prompt-file", dest="run_prompt_file", type=Path, help="Read prompt text from a file")
    run_parser.add_argument("--json", dest="run_json", action="store_true", help="Print machine-readable JSON output")
    run_parser.add_argument("--no-rich", dest="run_no_rich", action="store_true", help="Disable Rich formatting")
    run_parser.add_argument("--max-iter", dest="run_max_iter", type=int, default=50, help="Maximum agent iterations")
    serve_parser = subparsers.add_parser("serve", help="Start the API server")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    serve_parser.add_argument("--port", type=int, default=8000, help="Listen port")
    serve_parser.add_argument("--dev", action="store_true", help="Start the Vite dev server")
    office_parser = subparsers.add_parser("office", help="Manage the shared research task board")
    office_parser.add_argument("office_args", nargs=argparse.REMAINDER)


def register_inspection_subcommands(subparsers: argparse._SubParsersAction) -> None:
    list_parser = subparsers.add_parser("list", help="List runs")
    list_parser.add_argument("--limit", dest="list_limit", type=positive_int, default=20, help="Maximum number of runs")
    show_parser = subparsers.add_parser("show", help="Show run details")
    show_parser.add_argument("run_id", help="Run identifier")
    chat_parser = subparsers.add_parser("chat", help="Interactive chat mode")
    chat_parser.add_argument("--max-iter", dest="chat_max_iter", type=int, default=50, help="Maximum agent iterations")
    subparsers.add_parser("update", help="Check for and install the latest vibe-trading-ai release from PyPI")
    subparsers.add_parser("init", help="Interactive setup: create ~/.vibe-trading/.env")
    from cli.commands import common
    setup_parser = subparsers.add_parser("setup", help="Install frontend dependencies and build the production bundle")
    setup_parser.add_argument("--frontend-dir", default=str(common.AGENT_DIR.parent / "frontend"), help="Path to the frontend directory (default: <repo>/frontend)")
    dev_parser = subparsers.add_parser("dev", help="Start backend + frontend dev servers in one process")
    dev_parser.add_argument("--port", type=int, default=8899, help="Backend port (default: 8899)")
    dev_parser.add_argument("--frontend-port", type=int, default=5899, help="Vite dev server port, must match vite.config.ts (default: 5899)")
    dev_parser.add_argument("--frontend-dir", default=str(common.AGENT_DIR.parent / "frontend"), help="Path to the frontend directory (default: <repo>/frontend)")


def _version() -> str:
    from cli._version import __version__
    return __version__
