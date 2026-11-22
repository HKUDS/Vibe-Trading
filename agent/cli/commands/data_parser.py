"""Research data command parser registration."""
from __future__ import annotations
import argparse

def register(subparsers: argparse._SubParsersAction) -> None:
    data_parser = subparsers.add_parser("data", help="Show research data partner settings")
    data_subparsers = data_parser.add_subparsers(dest="data_command", required=True)
    data_subparsers.add_parser("status", help="Show selected Gildata features")
    from src.data_gateway.__main__ import add_history_parser, add_scan_parser
    add_history_parser(data_subparsers)
    add_scan_parser(data_subparsers)
