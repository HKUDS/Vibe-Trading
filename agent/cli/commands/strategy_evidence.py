"""CLI surface for the strategy-discovery evidence cache."""

from __future__ import annotations

from src.tools.path_utils import FileRoots

from src.config.accessor import get_env_config

import argparse
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_STRATEGY_EVIDENCE_PARSER: Optional[argparse.ArgumentParser] = None


def _console() -> Any:
    """Return the shared CLI console."""
    from cli.theme import get_console

    return get_console()


def _print(message: str) -> None:
    """Print one line through the shared console."""
    _console().print(message)


def _render_summary(envelope: dict) -> None:
    """Human-readable refresh summary: rows written, strategies, skipped table."""
    from rich.table import Table

    console = _console()
    console.print(
        f"Refreshed strategy evidence: [bold]{envelope.get('rows', 0)}[/bold] "
        f"row(s) across [bold]{envelope.get('strategies', 0)}[/bold] "
        f"strateg(y/ies) from {envelope.get('runs', 0)} run spec(s)."
    )
    skipped = envelope.get("skipped") or []
    if not skipped:
        return
    table = Table(title="Skipped runs", title_style="bold", box=None, pad_edge=False)
    table.add_column("run_dir", style="cyan", overflow="fold")
    table.add_column("reason", overflow="fold")
    for entry in skipped:
        table.add_row(str(entry.get("run_dir")), str(entry.get("reason")))
    console.print(table)


def _cmd_refresh(args: argparse.Namespace) -> int:
    """Handle ``vibe-trading strategy-evidence refresh``."""
    from src.tools.strategy_discovery_tool import refresh_strategy_evidence_core

    manifest = getattr(args, "strategy_evidence_manifest", None)
    try:
        envelope = refresh_strategy_evidence_core(
            manifest_path=manifest, scope=getattr(args, "scope", "all"),
            roots=FileRoots.from_config(get_env_config().api),
        )
    except ValueError as exc:
        message = str(exc)
        if getattr(args, "strategy_evidence_json", False):
            print(json.dumps({"status": "error", "error": message}, ensure_ascii=False))
        else:
            _print(f"[bold red]{message}[/bold red]")
        return 2
    except Exception:  # noqa: BLE001 — one line for the operator, never a traceback
        # Keep raw exception details out of operator output because they may contain internal paths.
        logger.exception("strategy-evidence refresh failed")
        message = "evidence refresh failed internally; see logs for detail"
        if getattr(args, "strategy_evidence_json", False):
            print(json.dumps({"status": "error", "error": message}, ensure_ascii=False))
        else:
            _print(f"[bold red]{message}[/bold red]")
        return 1

    if getattr(args, "strategy_evidence_json", False):
        print(json.dumps(envelope, ensure_ascii=False, indent=2))
    else:
        _render_summary(envelope)
    return 0


def _cmd_adapt(args: argparse.Namespace) -> int:
    """Prepare an adaptation; generation and backtesting use the returned plan."""
    from pathlib import Path
    from src.strategy_discovery.adaptation_workflow import prepare_adaptation

    try:
        result = prepare_adaptation(strategy_id=args.strategy_id, name=args.name,
                                    universe=args.universe,
                                    config=json.loads(Path(args.config).read_text()),
                                    position_sizing=args.position_sizing)
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


_DISPATCH = {
    "adapt": _cmd_adapt,
    "refresh": _cmd_refresh,
}


def add_subparser(subparsers: Any) -> argparse.ArgumentParser:
    """Register the strategy-evidence command and its refresh and adapt subcommands.

    Args:
        subparsers: The object returned by ArgumentParser.add_subparsers.

    Returns:
        The registered strategy-evidence parser.
    """
    global _STRATEGY_EVIDENCE_PARSER

    parser = subparsers.add_parser(
        "strategy-evidence",
        help="Strategy-evidence cache: refresh from backtest run artifacts",
        description=(
            "Prepare strategy adaptations and refresh their evidence. "
            "Querying evidence stays with the agent tools "
            "(list_strategies / query_strategies / get_strategy_evidence)."
        ),
    )
    sub = parser.add_subparsers(dest="strategy_evidence_command")

    p_refresh = sub.add_parser(
        "refresh",
        help="Rebuild the evidence cache from a JSON manifest of run specs",
        description=(
            "Rebuild the disposable strategy-evidence cache from real "
            "backtest run artifacts. The manifest is a JSON object with a "
            "'runs' array or a bare JSON array of "
            "{strategy_id, run_dir, position_size?} entries. Runs failing "
            "the ingestion gates are skipped with reasons; the rest still "
            "process."
        ),
    )
    p_refresh.add_argument(
        "--manifest",
        dest="strategy_evidence_manifest",
        required=True,
        help="Path to the JSON manifest of run specs",
    )
    p_refresh.add_argument(
        "--json",
        dest="strategy_evidence_json",
        action="store_true",
        help="Emit the machine-readable envelope instead of a summary",
    )

    p_refresh.add_argument("--scope", choices=["all", "strategies"], default="all",
                           help="Replace all evidence, or only successful named strategies")
    p_adapt = sub.add_parser("adapt", help="Prepare a child strategy for generation and backtest")
    p_adapt.add_argument("--strategy-id", required=True)
    p_adapt.add_argument("--name", required=True)
    p_adapt.add_argument("--universe", required=True)
    p_adapt.add_argument("--config", required=True, help="JSON backtest config with codes and dates")
    p_adapt.add_argument("--position-sizing")

    _STRATEGY_EVIDENCE_PARSER = parser
    return parser


def dispatch(args: argparse.Namespace) -> int:
    """Dispatch a parsed strategy-evidence subcommand.

    Args:
        args: Parsed arguments including the selected strategy-evidence subcommand.

    Returns:
        Handler exit code, or two if no supported subcommand is selected.
    """
    sub = getattr(args, "strategy_evidence_command", None)
    handler = _DISPATCH.get(sub or "")
    if handler is None:
        if _STRATEGY_EVIDENCE_PARSER is not None:
            _STRATEGY_EVIDENCE_PARSER.print_help()
        else:
            _print(
                "[red]strategy-evidence requires a subcommand.[/red] "
                "Try: vibe-trading strategy-evidence refresh --manifest <path>"
            )
        return 2
    return int(handler(args))


__all__ = [
    "add_subparser",
    "dispatch",
]
