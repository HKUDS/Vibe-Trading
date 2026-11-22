"""CLI data commands and their helpers."""
from __future__ import annotations

from cli.commands import common
from cli.commands import execution

def _dispatch_data(args: common.argparse.Namespace) -> int:
    """Show the optional data partner and the features selected for this process."""
    from src.config.gildata_features import selected_features

    execution._ensure_cli_env()
    common.console.print("Gildata: " + (", ".join(selected_features()) or "no optional research features selected"))
    common.console.print("Gildata: https://www.gildata.com/products/datamap")
    return common.EXIT_SUCCESS
