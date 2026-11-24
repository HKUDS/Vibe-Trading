"""Provider command parser registration."""
from __future__ import annotations
import argparse

def register(subparsers: argparse._SubParsersAction) -> None:
    """Register provider login, diagnostics, catalog, and custom endpoint commands.

    Args:
        subparsers: Parent subparser collection for the provider command.
    """
    provider_parser = subparsers.add_parser("provider", help="Manage LLM providers")
    provider_subparsers = provider_parser.add_subparsers(dest="provider_command")
    login_parser = provider_subparsers.add_parser("login", help="Authenticate with an OAuth provider")
    login_parser.add_argument("provider", help="OAuth provider name, e.g. openai-codex")
    provider_subparsers.add_parser("doctor", help="Print redacted provider diagnostics")
    provider_subparsers.add_parser("list", help="List the shared provider catalog as JSON")
    from cli.custom_providers import configure_parser
    configure_parser(provider_subparsers.add_parser("custom", help="Manage tested custom model endpoints"))
