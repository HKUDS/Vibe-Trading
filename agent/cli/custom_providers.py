"""CLI entry for the same tested custom profiles used by Settings."""
from __future__ import annotations

import asyncio
import getpass
import json


def configure_parser(parser) -> None:
    """Add list, add (test and save), and activate commands."""
    commands = parser.add_subparsers(dest="custom_command", required=True)
    commands.add_parser("list", help="List redacted custom provider metadata")
    add = commands.add_parser("add", help="Test and save a provider; prompts privately for its key")
    for name in ("id", "label", "base-url", "model"):
        add.add_argument(f"--{name}", required=True)
    activate = commands.add_parser("activate", help="Select a saved provider for new runs")
    activate.add_argument("id")


def run(args) -> int:
    """Run a custom provider operation without accepting a key on argv."""
    from src.providers.custom_profiles import CustomProviderStore

    store = CustomProviderStore()
    try:
        if args.custom_command == "list":
            result = store.list_public()
        elif args.custom_command == "add":
            from src.providers.custom_profiles import _perform_completion_test, _validate_custom_base_url

            base_url = _validate_custom_base_url(args.base_url)
            key = getpass.getpass("API key (hidden): ")
            asyncio.run(_perform_completion_test(base_url=base_url, model=args.model, api_key=key))
            result = store.save(profile_id=args.id, label=args.label, base_url=base_url, model=args.model, api_key=key)
        else:
            # Canonical settings writes use the same host paths as the API.
            from src.providers.custom_profiles import activate_custom_provider

            result = activate_custom_provider(args.id, store=store)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (RuntimeError, ValueError, OSError) as exc:
        print(str(exc))
        return 1
