"""Portfolio command parser registration."""
from __future__ import annotations
import argparse

def register(subparsers: argparse._SubParsersAction) -> None:
    """Register portfolio snapshot, source, import, and rebalance commands.

    Args:
        subparsers: Parent subparser collection for the portfolio command.
    """
    portfolio_parser = subparsers.add_parser("portfolio", help="Read-only multi-broker portfolio (the Web UI /portfolio page, in the terminal)")
    portfolio_subparsers = portfolio_parser.add_subparsers(dest="portfolio_command")
    portfolio_show_parser = portfolio_subparsers.add_parser("show", help="Print a stored snapshot")
    portfolio_show_parser.add_argument("--snapshot-id", help="Read this exact immutable snapshot")
    portfolio_subparsers.add_parser("refresh", help="Read every enabled source now, store a new snapshot, and print it")
    import_parser = portfolio_subparsers.add_parser("import-extraetf", help="Import a local Investments CSV; never executes trades")
    import_parser.add_argument("file")
    import_parser.add_argument("--label", required=True)
    import_parser.add_argument("--expected-positions", required=True, type=int)
    import_parser.add_argument("--max-age-days", required=True, type=int)
    import_parser.add_argument("--select", action="store_true", help="Add this import to selected portfolio sources")
    rebalance_parser = portfolio_subparsers.add_parser("rebalance", help="Value-only proposal for a pinned snapshot")
    rebalance_parser.add_argument("--snapshot-id", required=True)
    rebalance_parser.add_argument("--targets", required=True, help="JSON file mapping canonical_id (or CASH) to target fraction")
    portfolio_subparsers.add_parser("sources", help="List local read-only connections and whether the portfolio uses them")
