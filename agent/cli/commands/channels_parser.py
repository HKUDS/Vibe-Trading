"""IM channel command parser registration."""
from __future__ import annotations
import argparse

def register(subparsers: argparse._SubParsersAction) -> None:
    channels_parser = subparsers.add_parser("channels", help="Manage IM channel adapters")
    channels_subparsers = channels_parser.add_subparsers(dest="channels_command")
    channels_status = channels_subparsers.add_parser("status", help="Show IM channel status")
    channels_status.add_argument("--json", dest="channels_json", action="store_true", help="Print JSON")
    channels_status.add_argument("--local", action="store_true", help="Inspect local config without contacting the API")
    channels_start = channels_subparsers.add_parser("start", help="Start configured IM channels through the API")
    channels_start.add_argument("--json", dest="channels_json", action="store_true", help="Print JSON")
    channels_stop = channels_subparsers.add_parser("stop", help="Stop configured IM channels through the API")
    channels_stop.add_argument("--json", dest="channels_json", action="store_true", help="Print JSON")
    channels_login = channels_subparsers.add_parser("login", help="Run a channel adapter login hook")
    channels_login.add_argument("channel_name", help="Channel name, e.g. weixin, feishu, whatsapp")
    channels_login.add_argument("--force", action="store_true", help="Ignore existing credentials where supported")
    channels_pairing = channels_subparsers.add_parser("pairing", help="Manage IM sender pairing")
    channels_pairing.add_argument("--channel", default="telegram", help="Channel context for list/revoke commands")
    channels_pairing.add_argument("pairing_command", nargs="?", default="list", choices=["list", "approve", "deny", "revoke"], help="Pairing command")
    channels_pairing.add_argument("pairing_args", nargs="*", help="Pairing command arguments")
