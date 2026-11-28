"""Trading connector and live-runner parser registration."""
from __future__ import annotations
import argparse

def register(subparsers: argparse._SubParsersAction) -> None:
    """Register trading connector profile subcommands.

    Args:
        subparsers: Parent subparser collection for the connector command.
    """
    connector_parser = subparsers.add_parser("connector", help="Manage trading connector profiles")
    connector_subparsers = connector_parser.add_subparsers(dest="connector_command")

    connector_subparsers.add_parser("list", help="List selectable connector profiles")

    connector_init = connector_subparsers.add_parser(
        "init", help="Create a local read-only connector template"
    )
    connector_init.add_argument("connector_id", help="Lowercase connector id")
    connector_init.add_argument(
        "--destination", default=".", help="Parent directory for the template"
    )

    connector_validate = connector_subparsers.add_parser(
        "validate", help="Validate a local connector directory"
    )
    connector_validate.add_argument("directory")

    connector_install = connector_subparsers.add_parser(
        "install", help="Install a validated connector locally"
    )
    connector_install.add_argument("directory")

    connector_use = connector_subparsers.add_parser("use", help="Select the default connector profile")
    connector_use.add_argument("profile", help="Profile id, e.g. ibkr-paper-local")

    def _add_connector_profile_arg(p: argparse.ArgumentParser, *, required: bool = False) -> None:
        if required:
            p.add_argument("profile", help="Connector profile id")
        else:
            p.add_argument("profile", nargs="?", default=None, help="Connector profile id (default: selected)")

    def _add_connector_local(p: argparse.ArgumentParser) -> None:
        p.add_argument("--host", default=None)
        p.add_argument("--port", type=int, default=None)
        p.add_argument("--client-id", dest="client_id", type=int, default=None)
        p.add_argument("--account", default=None, help="Optional account code")

    def _add_connector_contract(p: argparse.ArgumentParser) -> None:
        p.add_argument("--exchange", default="SMART")
        p.add_argument("--currency", default="USD")
        p.add_argument("--sec-type", dest="sec_type", default="STK")

    connector_configure = connector_subparsers.add_parser("configure", help="Configure a local connector profile")
    _add_connector_profile_arg(connector_configure, required=True)
    connector_configure.add_argument("--host", default="127.0.0.1")
    connector_configure.add_argument("--port", type=int, default=None)
    connector_configure.add_argument("--client-id", dest="client_id", type=int, default=77)
    connector_configure.add_argument("--account", default=None)
    connector_configure.add_argument("-y", "--yes", action="store_true", help="Overwrite without prompting")

    connector_setup = connector_subparsers.add_parser(
        "setup",
        help="Create a local read-only connection and securely collect its credentials",
    )
    _add_connector_profile_arg(connector_setup, required=True)
    connector_setup.add_argument("--connection-id", default=None)
    connector_setup.add_argument("--label", default=None)
    connector_setup.add_argument("--skip-check", action="store_true")
    connector_setup.add_argument(
        "--host", default=None, help="Connection-specific IBKR/Futu gateway host (requires --port)"
    )
    connector_setup.add_argument(
        "--port", type=int, default=None, help="Connection-specific gateway port (requires --host)"
    )
    connector_setup.add_argument(
        "--account",
        default=None,
        help="Account to scope an account-scoped connection (Robinhood) to; prompts when omitted",
    )

    connector_select_account = connector_subparsers.add_parser(
        "select-account",
        help="Choose the broker account an account-scoped connection reads",
    )
    connector_select_account.add_argument("connection_id", help="Local connection id")
    connector_select_account.add_argument("--account", default=None, help="Account reference; prompts when omitted")
    connector_select_account.add_argument("--clear", action="store_true", help="Remove the selection")

    connector_check = connector_subparsers.add_parser("check", help="Check selected connector readiness")
    _add_connector_profile_arg(connector_check)
    _add_connector_local(connector_check)
    connector_check.add_argument("--connection-id", default=None)

    connector_status = connector_subparsers.add_parser("status", help="Show selected connector status")
    _add_connector_profile_arg(connector_status)

    connector_authorize = connector_subparsers.add_parser("authorize", help="Authorize a remote MCP connector profile")
    _add_connector_profile_arg(connector_authorize)

    connector_account = connector_subparsers.add_parser("account", help="Read account summary")
    _add_connector_profile_arg(connector_account)
    _add_connector_local(connector_account)
    connector_account.add_argument("--connection-id", default=None)

    connector_positions = connector_subparsers.add_parser("positions", help="Read current positions")
    _add_connector_profile_arg(connector_positions)
    _add_connector_local(connector_positions)
    connector_positions.add_argument("--connection-id", default=None)

    connector_orders = connector_subparsers.add_parser("orders", help="Read open orders")
    _add_connector_profile_arg(connector_orders)
    _add_connector_local(connector_orders)
    connector_orders.add_argument("--include-executions", action="store_true")

    connector_quote = connector_subparsers.add_parser("quote", help="Read a quote snapshot")
    connector_quote.add_argument("symbol")
    _add_connector_profile_arg(connector_quote)
    _add_connector_local(connector_quote)
    _add_connector_contract(connector_quote)

    connector_history = connector_subparsers.add_parser("history", help="Read historical bars")
    connector_history.add_argument("symbol")
    _add_connector_profile_arg(connector_history)
    _add_connector_local(connector_history)
    _add_connector_contract(connector_history)
    connector_history.add_argument("--duration", default="30 D", help="IBKR (local_tws) duration string")
    connector_history.add_argument("--bar-size", dest="bar_size", default="1 day", help="IBKR (local_tws) bar size")
    connector_history.add_argument("--what-to-show", dest="what_to_show", default="TRADES")
    connector_history.add_argument("--no-rth", action="store_true", help="Include outside-regular-hours data when available")
    connector_history.add_argument("--period", default="1d", help="Bar interval for SDK connectors: 1m/5m/15m/30m/1h/4h/1d/1w/1M")
    connector_history.add_argument("--limit", dest="bar_limit", type=int, default=90, help="Number of bars for SDK connectors")

    for name, help_text in (
        ("start", "Start the selected live connector runner"),
        ("stop", "Stop the selected live connector runner"),
        ("halt", "Trip the selected live connector kill switch"),
        ("resume", "Clear the selected live connector kill switch"),
        ("revoke", "Revoke the selected live connector OAuth token and mandate"),
    ):
        p = connector_subparsers.add_parser(name, help=help_text)
        _add_connector_profile_arg(p)

    runner_settings = connector_subparsers.add_parser(
        "runner-settings", help="Preview model spending or save runner cadence/budgets from JSON"
    )
    _add_connector_profile_arg(runner_settings)
    runner_settings.add_argument("--file", help="Validated settings JSON; stop the runner before changing it")
