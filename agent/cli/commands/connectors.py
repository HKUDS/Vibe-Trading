"""CLI connectors commands and their helpers."""
from __future__ import annotations

from cli.commands import common
from cli.commands import execution
from cli.commands import live

def _profile_id(value: common.Optional[str]) -> common.Optional[str]:
    """Normalize an optional connector profile id."""
    if value is None:
        return None
    text = value.strip().lower()
    return text or None


def _selected_profile_or(value: common.Optional[str]):
    """Resolve the selected or explicit trading profile."""
    from src.trading.profiles import profile_by_id

    return profile_by_id(_profile_id(value))


def cmd_connector_list() -> int:
    """List selectable trading connector profiles.

    Returns:
        Success exit code after printing the profile table and current selection.
    """
    from src.trading.profiles import list_profiles, load_selected_profile_id

    selected = load_selected_profile_id()
    table = common.Table(title="Trading Connectors", box=common.box.SIMPLE_HEAVY, show_lines=False)
    table.add_column("Selected", justify="center", width=8)
    table.add_column("Profile")
    table.add_column("Connector")
    table.add_column("Env")
    table.add_column("Transport")
    table.add_column("Capabilities")
    for profile in list_profiles():
        table.add_row(
            "[green]*[/green]" if profile.id == selected else "",
            f"[cyan]{profile.id}[/cyan]\n[dim]{profile.label}[/dim]",
            profile.connector,
            profile.environment,
            profile.transport,
            ", ".join(profile.capabilities),
        )
    common.console.print(table)
    common.console.print("[dim]Use `vibe-trading connector use <profile>` to set the default profile.[/dim]")
    return common.EXIT_SUCCESS


def cmd_connector_init(connector_id: str, destination: str = ".") -> int:
    """Create a local-only read connector template.

    Args:
        connector_id: Lowercase connector ID used for the template directory.
        destination: Parent directory the template is created in.

    Returns:
        Success exit code after creation, or a usage error if the scaffold request is invalid.
    """
    from src.trading.plugin_scaffold import scaffold_connector

    try:
        path = scaffold_connector(connector_id, common.Path(destination))
    except ValueError as exc:
        common.console.print(f"[red]{exc}[/red]")
        return common.EXIT_USAGE_ERROR
    common.console.print(f"[green]Created local connector template[/green] {path}")
    common.console.print(
        "[dim]Implement adapter.py from the broker's official read-only API docs, "
        "then run connector validate and connector install.[/dim]"
    )
    return common.EXIT_SUCCESS


def cmd_connector_validate(directory: str) -> int:
    """Validate a local read-only connector manifest.

    Args:
        directory: Directory holding the connector manifest.

    Returns:
        Success exit code for a valid manifest, or a usage error on validation failure.
    """
    from src.trading.plugin_scaffold import validate_connector

    try:
        plugin = validate_connector(common.Path(directory))
    except ValueError as exc:
        common.console.print(f"[red]{exc}[/red]")
        return common.EXIT_USAGE_ERROR
    common.console.print(f"[green]Valid read-only connector[/green] {plugin.profile.id}")
    return common.EXIT_SUCCESS


def cmd_connector_install(directory: str) -> int:
    """Install a validated connector into the user's private connector directory.

    Args:
        directory: Directory holding the connector to validate and install.

    Returns:
        Success exit code after installation, or a usage error if validation or installation rejects
        the connector.
    """
    from src.trading.plugin_scaffold import install_connector

    try:
        path = install_connector(common.Path(directory))
    except ValueError as exc:
        common.console.print(f"[red]{exc}[/red]")
        return common.EXIT_USAGE_ERROR
    common.console.print(f"[green]Installed local connector[/green] {path}")
    return common.EXIT_SUCCESS


def cmd_connector_use(profile_id: str) -> int:
    """Select the default trading connector profile.

    Args:
        profile_id: ID of the profile to save as the default.

    Returns:
        Success exit code after saving the selection, or a usage error for an invalid profile.
    """
    from src.trading.profiles import profile_by_id, save_selected_profile_id

    try:
        profile = profile_by_id(profile_id)
        path = save_selected_profile_id(profile.id)
    except ValueError as exc:
        common.console.print(f"[red]{exc}[/red]")
        return common.EXIT_USAGE_ERROR
    common.console.print(f"[green]Selected trading connector[/green] {profile.id}")
    common.console.print(f"[dim]{profile.label} · {profile.environment} · {profile.transport}[/dim]")
    common.console.print(f"[dim]Config: {path}[/dim]")
    return common.EXIT_SUCCESS


def cmd_connector_configure(
    profile_id: str,
    *,
    host: str = "127.0.0.1",
    port: int | None = None,
    client_id: int = 77,
    account: str | None = None,
    yes: bool = False,
) -> int:
    """Configure a read-only local IBKR TWS or Gateway profile.

    Args:
        profile_id: ID of the local connector profile.
        host: Gateway host.
        port: Gateway port, using the profile port when omitted.
        client_id: IBKR client ID.
        account: Optional account code.
        yes: Whether to overwrite existing settings without prompting.

    Returns:
        Success after saving or declining an overwrite, or a usage error for an invalid profile or
        unavailable confirmation input.
    """
    from src.trading.connectors.ibkr.local import IBKRLocalConfig, config_path, save_config

    try:
        profile = _selected_profile_or(profile_id)
    except ValueError as exc:
        common.console.print(f"[red]{exc}[/red]")
        return common.EXIT_USAGE_ERROR
    if profile.transport != "local_tws" or profile.connector != "ibkr":
        common.console.print(f"[red]{profile.id} is not a local TWS/Gateway profile.[/red]")
        return common.EXIT_USAGE_ERROR

    path = config_path()
    if path.exists() and not yes:
        common.console.print(f"[yellow]Local connector config already exists:[/yellow] {path}")
        try:
            if not common.Confirm.ask("Overwrite it?", default=False):
                common.console.print("[dim]Aborted.[/dim]")
                return common.EXIT_SUCCESS
        except EOFError:
            common.console.print("[dim]No input available; use --yes for non-interactive setup.[/dim]")
            return common.EXIT_USAGE_ERROR

    cfg = IBKRLocalConfig.from_mapping(
        {
            **profile.config,
            "host": host,
            "port": port or profile.config.get("port"),
            "clientId": client_id,
            "account": account,
            "readonly": True,
        }
    )
    path = save_config(cfg)
    common.console.print(f"[green]Configured[/green] {profile.id} [dim]({path})[/dim]")
    common.console.print(f"[dim]Run `vibe-trading connector check {profile.id}` to verify it.[/dim]")
    return common.EXIT_SUCCESS


def cmd_connector_check(
    profile_id: common.Optional[str] = None,
    *,
    connection_id: str | None = None,
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
    account: str | None = None,
) -> int:
    """Check selected or explicit trading connector profile.

    Args:
        profile_id: Profile to check, or None to use the selected profile.
        connection_id: Optional saved connection ID.
        host: Optional host override for a local gateway.
        port: Optional gateway port override.
        client_id: Optional broker client ID override.
        account: Optional account override.

    Returns:
        Success exit code when the profile is ready, or failure on an exception or non-ready report.
    """
    from src.trading.service import check_connection

    try:
        profile = _selected_profile_or(profile_id)
        options = {
            "host": host,
            "port": port,
            "client_id": client_id,
            "account": account,
        }
        if connection_id is not None:
            options["connection_id"] = connection_id
        report = check_connection(profile.id, **options)
    except Exception as exc:  # noqa: BLE001
        common.console.print(f"[red]Connector check failed:[/red] {exc}")
        return common.EXIT_RUN_FAILED

    title = f"Trading Connector: {profile.id}"
    if profile.transport == "local_tws":
        table = common.Table(title=title, box=common.box.SIMPLE_HEAVY, show_lines=False)
        table.add_column("Endpoint")
        table.add_column("Profile")
        table.add_column("Address")
        table.add_column("State")
        for row in report.get("ports", []):
            open_state = "[green]open[/green]" if row.get("open") else "[dim]closed[/dim]"
            table.add_row(
                str(row.get("label")),
                str(row.get("profile")),
                f"{row.get('host')}:{row.get('port')}",
                open_state,
            )
        common.console.print(table)
        target = report.get("target", {})
        target_state = "open" if target.get("open") else "closed"
        common.console.print(f"Target: [bold]{target.get('host')}:{target.get('port')}[/bold] ({target_state})")
        sdk = report.get("sdk", {})
        if not sdk.get("installed"):
            common.console.print("[yellow]Missing optional dependency:[/yellow] pip install 'ib_async>=2.0'")
        if report.get("account"):
            accounts = ", ".join(report["account"].get("accounts", [])) or "(none)"
            common.console.print(f"Accounts: [cyan]{common.rich_escape(accounts)}[/cyan]")
    else:
        table = common.Table(title=title, box=common.box.SIMPLE_HEAVY, show_lines=False)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        table.add_row("Connector", profile.connector)
        table.add_row("Environment", profile.environment)
        table.add_row("Transport", profile.transport)
        if profile.transport == "broker_sdk":
            if "configured" in report:
                table.add_row("Configured", "yes" if report.get("configured") else "[red]no[/red]")
            if report.get("connection_state"):
                table.add_row("Connection", str(report["connection_state"]))
            sdk = report.get("sdk")
            if isinstance(sdk, dict) and "installed" in sdk:
                package = str(sdk.get("package") or "SDK")
                state = "installed" if sdk.get("installed") else "[yellow]missing[/yellow]"
                table.add_row(package, state)
            if "tap" in report:
                table.add_row("TAP", "enabled" if report.get("tap") else "disabled")
            capabilities = report.get("capabilities")
            if capabilities:
                table.add_row("Capabilities", ", ".join(capabilities))
        else:
            table.add_row("Configured", "yes" if report.get("configured") else "[red]no[/red]")
            table.add_row("OAuth token", "present" if report.get("oauth_token_present") else "[yellow]missing[/yellow]")
            table.add_row("Capabilities", ", ".join(report.get("capabilities", [])))
        common.console.print(table)

    if report.get("status") not in {"ok"}:
        common.console.print(f"[red]{common.rich_escape(str(report.get('error') or report.get('status') or 'not ready'))}[/red]")
        return common.EXIT_RUN_FAILED
    common.console.print("[green]Connector profile is ready.[/green]")
    return common.EXIT_SUCCESS


def cmd_connector_setup(
    profile_id: str,
    *,
    connection_id: str | None = None,
    label: str | None = None,
    skip_check: bool = False,
    account: str | None = None,
    host: str | None = None,
    port: int | None = None,
) -> int:
    """Create a local read-only connection and collect its credentials interactively.

    Args:
        profile_id: Read-only portfolio profile to connect through.
        connection_id: Local ID, defaulting to <connector>-<environment>.
        label: Display name, defaulting to the profile label.
        skip_check: Skip the connectivity check and any account selection that requires it.
        account: Account reference for an account-scoped connection. Otherwise prompt if a selection
            is needed.
        host: Optional connection-specific gateway host. Requires port.
        port: Optional connection-specific gateway port. Requires host.

    Returns:
        Success after setup, a usage error for rejected configuration, failure if verification
        fails, or the status of account selection when invoked.

    Raises:
        EOFError: If input ends during an interactive credential or account prompt.
    """
    from dataclasses import replace

    from src.trading.connections import (
        ConnectionStore,
        credential_field_catalog,
        is_readonly_connection_profile,
        requires_account_selection,
    )
    from src.trading.profiles import profile_by_id
    from src.trading.service import check_connection

    try:
        profile = profile_by_id(profile_id)
        if not is_readonly_connection_profile(profile):
            raise ValueError(f"{profile.id} is not a read-only connection profile")
        if (host is None) != (port is None):
            raise ValueError("gateway endpoint requires both --host and --port")
        local_id = str(connection_id or f"{profile.connector}-{profile.environment}").strip().lower()
        store = ConnectionStore()
        connection = store.ensure(local_id, profile.id, label or profile.label)
        if host is not None:
            connection = store.save(replace(connection, endpoint={"host": host, "port": port}))
        fields = credential_field_catalog(profile.id)
        names = [str(field["name"]) for field in fields]
        status = store.credentials.status(connection.id, names) if names else {}
        values: dict[str, str] = {}
        for field in fields:
            name = str(field["name"])
            required = bool(field.get("required", True))
            while True:
                saved = bool(status.get(name))
                suffix = " [already saved; Enter keeps it]" if saved else ""
                value = common.Prompt.ask(
                    f"{field.get('label') or name}{suffix}",
                    password=bool(field.get("secret", True)),
                    default="",
                    show_default=False,
                )
                if value:
                    values[name] = value
                    break
                if saved or not required:
                    break
                common.console.print(f"[yellow]{field.get('label') or name} is required.[/yellow]")
        if values:
            store.credentials.save(connection.id, values)
    except (RuntimeError, ValueError) as exc:
        common.console.print(f"[red]Connector setup failed:[/red] {common.rich_escape(str(exc))}")
        return common.EXIT_USAGE_ERROR

    common.console.print(
        f"[green]Local read-only connection ready[/green] "
        f"{connection.id} [dim]({connection.profile_id})[/dim]"
    )
    needs_account = requires_account_selection(profile)
    if skip_check:
        if needs_account and not connection.account_ref:
            common.console.print(
                f"[yellow]Select the account this connection reads:[/yellow] "
                f"vibe-trading connector select-account {connection.id}"
            )
        return common.EXIT_SUCCESS
    try:
        report = check_connection(profile.id, connection_id=connection.id)
    except Exception as exc:  # noqa: BLE001 - return an actionable diagnostic
        common.console.print(f"[red]Connection test failed:[/red] {common.rich_escape(str(exc))}")
        return common.EXIT_RUN_FAILED
    if report.get("status") != "ok":
        common.console.print(
            f"[red]Connection test failed:[/red] "
            f"{common.rich_escape(str(report.get('error') or report.get('status')))}"
        )
        return common.EXIT_RUN_FAILED
    common.console.print("[green]Connection test passed.[/green]")
    if needs_account and (account is not None or not connection.account_ref):
        return cmd_connector_select_account(connection.id, account=account)
    return common.EXIT_SUCCESS


def cmd_connector_select_account(
    connection_id: str,
    *,
    account: str | None = None,
    clear: bool = False,
) -> int:
    """Scope an account-scoped connection to one account from the broker's list.

    Args:
        connection_id: Connection to update.
        account: Account reference to select. Prompts from active broker accounts when omitted.
        clear: Remove the existing selection instead.

    Returns:
        Success after saving or clearing the selection, failure if the account list is unavailable,
        or a usage error if the selection is rejected.

    Raises:
        EOFError: If input ends before the interactive account selection.
    """
    from src.trading.accounts import AccountListUnavailable, choose_account, connection_accounts
    from src.trading.connections import ConnectionStore

    store = ConnectionStore()
    try:
        connection = store.get(connection_id)
        if clear:
            store.select_account(connection.id, "")
            common.console.print(f"[green]Cleared the account selection of[/green] {connection.id}")
            return common.EXIT_SUCCESS
        choices = connection_accounts(connection)
        if account is None:
            usable = [row for row in choices if not row.get("deactivated")]
            if not usable:
                raise ValueError("this login reaches no active account")
            table = common.Table(title="Accounts", box=common.box.SIMPLE_HEAVY)
            table.add_column("#", justify="right")
            table.add_column("Account")
            table.add_column("Broker default", justify="center")
            table.add_column("Agentic trading", justify="center")
            for index, row in enumerate(usable, start=1):
                table.add_row(
                    str(index),
                    common.rich_escape(str(row.get("label") or "")),
                    "yes" if row.get("is_default") else "",
                    "allowed" if row.get("agentic_allowed") else "[dim]not allowed[/dim]",
                )
            common.console.print(table)
            pick = common.Prompt.ask("Account", choices=[str(index) for index in range(1, len(usable) + 1)])
            account = str(usable[int(pick) - 1]["account_ref"])
        chosen = choose_account(choices, account.strip())
        store.select_account(connection.id, str(chosen["account_ref"]))
    except AccountListUnavailable as exc:
        common.console.print(f"[red]Could not read the account list:[/red] {common.rich_escape(str(exc))}")
        return common.EXIT_RUN_FAILED
    except (RuntimeError, ValueError) as exc:
        common.console.print(f"[red]Account selection failed:[/red] {common.rich_escape(str(exc))}")
        return common.EXIT_USAGE_ERROR
    common.console.print(f"[green]{connection.id} now reads[/green] {common.rich_escape(str(chosen.get('label') or ''))}")
    return common.EXIT_SUCCESS


def _first_present(row: dict[str, common.Any], *keys: str) -> common.Any:
    """Return the first key whose value is not None (0/'' are kept), else None."""
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return None


def _print_connector_balances(result: dict[str, common.Any]) -> int:
    """Render the ``balances`` list returned by ``broker_sdk`` connectors."""
    cell = lambda v: "" if v is None else str(v)  # noqa: E731
    rows = result.get("balances", [])
    if any("asset" in row for row in rows):
        table = common.Table(
            title=f"Asset Balances · {result.get('profile_id')}",
            caption=f"{len(rows)} non-zero balances",
            box=common.box.SIMPLE_HEAVY,
            show_lines=False,
        )
        table.add_column("Asset")
        table.add_column("Free", justify="right")
        table.add_column("Locked", justify="right")
        table.add_column("Total", justify="right")
        for row in rows:
            table.add_row(cell(row.get("asset")), cell(row.get("free")), cell(row.get("used")), cell(row.get("total")))
        common.console.print(table)
        return common.EXIT_SUCCESS
    table = common.Table(title=f"Account Balances · {result.get('profile_id')}", box=common.box.SIMPLE_HEAVY, show_lines=False)
    table.add_column("Currency")
    table.add_column("Net Assets", justify="right")
    table.add_column("Total Cash", justify="right")
    table.add_column("Buy Power", justify="right")
    table.add_column("Init Margin", justify="right")
    table.add_column("Maint Margin", justify="right")
    for row in rows:
        table.add_row(
            cell(row.get("currency")),
            cell(row.get("net_assets")),
            cell(row.get("total_cash")),
            cell(row.get("buy_power")),
            cell(row.get("init_margin")),
            cell(row.get("maintenance_margin")),
        )
    common.console.print(table)
    _print_balance_details(rows)
    return common.EXIT_SUCCESS


def _print_balance_details(rows: list[dict[str, common.Any]]) -> None:
    """Print broker cash legs and financing in each reported currency."""
    cell = lambda value: "—" if value is None else common.rich_escape(str(value))  # noqa: E731
    for row in rows:
        if not row.get("cash_infos") and all(row.get(key) is None for key in (
            "max_finance_amount", "remaining_finance_amount"
        )):
            continue
        currency = cell(row.get("currency"))
        common.console.print(f"Cash and financing · {currency}")
        common.console.print(f"Financing limit: {cell(row.get('max_finance_amount'))} {currency}; "
                      f"Remaining financing: {cell(row.get('remaining_finance_amount'))} {currency}")
        table = common.Table(box=common.box.SIMPLE_HEAVY)
        for name in ("Currency", "Available", "Withdrawable", "Frozen", "Settling"):
            table.add_column(name)
        for cash in row.get("cash_infos") or []:
            table.add_row(*(cell(cash.get(key)) for key in (
                "currency", "available_cash", "withdraw_cash", "frozen_cash", "settling_cash"
            )))
        if table.row_count:
            common.console.print(table)


def _print_connector_assets(result: dict[str, common.Any]) -> int:
    """Render Futu's per-currency ``assets`` rows from ``accinfo_query``."""
    cell = lambda v: "" if v is None else str(v)  # noqa: E731
    table = common.Table(title=f"Account Assets · {result.get('profile_id')}", box=common.box.SIMPLE_HEAVY, show_lines=False)
    table.add_column("Currency")
    table.add_column("Total Assets", justify="right")
    table.add_column("Cash", justify="right")
    table.add_column("Market Value", justify="right")
    table.add_column("Available Funds", justify="right")
    table.add_column("Buying Power", justify="right")
    for row in result.get("assets", []):
        table.add_row(
            cell(row.get("currency")),
            cell(row.get("total_assets")),
            cell(row.get("cash")),
            cell(row.get("market_val")),
            cell(row.get("available_funds")),
            cell(row.get("power")),
        )
    common.console.print(table)
    return common.EXIT_SUCCESS


def _normalize_mcp_value(value: common.Any) -> common.Any:
    """Unwrap a value from a remote MCP call into plain JSON-safe data."""
    import dataclasses

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value


def _remote_payload(result: dict[str, common.Any]) -> tuple[common.Any, common.Any]:
    """Unwrap remote connector data and preserve its optional advisory."""
    data = _normalize_mcp_value(result.get("data"))
    guide = result.get("guide")
    if isinstance(data, dict) and "data" in data and "guide" in data:
        return _normalize_mcp_value(data.get("data")), data.get("guide") or guide
    return data, guide


def _flatten_account_fields(
    data: dict[str, common.Any],
    prefix: str = "",
    *,
    skip_zero: bool = True,
) -> list[tuple[str, str]]:
    """Flatten a remote-MCP account payload into (tag, value) rows."""
    rows: list[tuple[str, str]] = []
    for key, value in data.items():
        if key == "currency" or value is None:
            continue
        label = f"{prefix}{key}"
        normalized = _normalize_mcp_value(value)
        if isinstance(normalized, dict):
            rows.extend(
                _flatten_account_fields(
                    normalized,
                    prefix=f"{label}.",
                    skip_zero=skip_zero,
                )
            )
            continue
        text = str(normalized)
        if skip_zero:
            try:
                if float(text) == 0.0:
                    continue
            except (TypeError, ValueError):
                pass
        rows.append((label, text))
    return rows


def _print_connector_account_mapping(
    result: dict[str, common.Any],
    account_data: dict[str, common.Any],
) -> int:
    """Render the flat/nested ``account`` mapping used by direct SDK brokers."""
    account_label = (
        account_data.get("account_number")
        or result.get("account_number")
        or result.get("profile_id")
        or result.get("profile")
        or "unknown"
    )
    table = common.Table(
        title=f"Account Summary · {result.get('profile_id') or result.get('profile') or account_label}",
        box=common.box.SIMPLE_HEAVY,
        show_lines=False,
    )
    table.add_column("Field")
    table.add_column("Value", justify="right")
    currency = account_data.get("currency")
    if currency is not None:
        table.add_row("currency", str(currency))
    for tag, value in _flatten_account_fields(account_data, skip_zero=False):
        table.add_row(tag, value)
    common.console.print(f"Account: [cyan]{common.rich_escape(str(account_label))}[/cyan]")
    common.console.print(table)
    return common.EXIT_SUCCESS


def _enum_text(value: common.Any) -> str:
    """Render ``OrderSide.BUY``-style enum reprs as ``BUY``."""
    text = str(value or "")
    match = common.re.fullmatch(r"([A-Z][A-Za-z0-9_]*)\.([A-Z][A-Z0-9_]*)", text)
    if match and any(ch.islower() for ch in match.group(1)):
        return match.group(2)
    return text


def _print_connector_account(result: dict[str, common.Any]) -> int:
    if result.get("valuation_basis") == "margin_limits_not_net_liquidation":
        common.console.print_json(data=result)
        return common.EXIT_SUCCESS
    accounts = ", ".join(result.get("accounts", [])) or "(none)"
    rows = result.get("summary", [])
    # broker_sdk connectors (Longbridge, …) return a ``balances`` list instead of
    # IBKR-style ``summary`` tag/value rows; render that when present (#735).
    if not rows and result.get("balances"):
        label = accounts if accounts != "(none)" else result.get("profile_id", result.get("profile", "unknown"))
        common.console.print(f"Accounts: [cyan]{common.rich_escape(str(label))}[/cyan]")
        return _print_connector_balances(result)
    if not rows and result.get("assets"):
        return _print_connector_assets(result)
    account_data = _normalize_mcp_value(result.get("account"))
    if not rows and isinstance(account_data, dict) and account_data:
        return _print_connector_account_mapping(result, account_data)
    # Trading 212 returns its cash and account metadata as two separate mappings.
    split = {key: result[key] for key in ("cash", "metadata") if isinstance(result.get(key), dict) and result[key]}
    if not rows and split:
        return _print_connector_account_mapping(result, split)
    if not rows:
        raw_data, guide = _remote_payload(result)
        if isinstance(raw_data, dict):
            currency = raw_data.get("currency", "")
            account_label = result.get("account_number") or accounts
            table = common.Table(
                title=f"Account Summary · {result.get('profile_id')}", box=common.box.SIMPLE_HEAVY, show_lines=False
            )
            table.add_column("Field")
            table.add_column("Value", justify="right")
            for tag, value in _flatten_account_fields(raw_data):
                is_currency_code = tag.endswith("currency") or tag.endswith("_currency")
                display = value if is_currency_code else f"{value} {currency}".strip()
                table.add_row(tag, display)
            common.console.print(f"Account: [cyan]{common.rich_escape(str(account_label))}[/cyan]")
            common.console.print(table)
            if guide:
                common.console.print(f"[dim]{common.rich_escape(str(guide))}[/dim]")
            return common.EXIT_SUCCESS
        common.console.print(f"Accounts: [cyan]{common.rich_escape(accounts)}[/cyan]")
        common.console.print("[dim]No account summary returned.[/dim]")
        return common.EXIT_SUCCESS
    common.console.print(f"Accounts: [cyan]{common.rich_escape(accounts)}[/cyan]")
    table = common.Table(title=f"Account Summary · {result.get('profile_id')}", box=common.box.SIMPLE_HEAVY, show_lines=False)
    table.add_column("Account")
    table.add_column("Tag")
    table.add_column("Value", justify="right")
    table.add_column("Currency")
    for row in rows:
        table.add_row(
            str(row.get("account") or ""),
            str(row.get("tag") or ""),
            str(row.get("value") or ""),
            str(row.get("currency") or ""),
        )
    common.console.print(table)
    return common.EXIT_SUCCESS


def cmd_connector_account(
    profile_id: common.Optional[str] = None,
    *,
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
    account: str | None = None,
    connection_id: str | None = None,
) -> int:
    """Print account summary from a connector profile.

    Args:
        profile_id: Profile ID, or None to use the default.
        host: Optional local gateway host.
        port: Optional local gateway port.
        client_id: Optional broker client ID.
        account: Optional account override.
        connection_id: Optional saved connection ID.

    Returns:
        Result of rendering the account summary, or a failure exit code if the broker read fails.
    """
    from src.trading.service import get_account

    try:
        options = {"host": host, "port": port, "client_id": client_id, "account": account}
        if connection_id is not None:
            options["connection_id"] = connection_id
        result = get_account(_profile_id(profile_id), **options)
    except Exception as exc:  # noqa: BLE001
        common.console.print(f"[red]Connector account failed:[/red] {exc}")
        return common.EXIT_RUN_FAILED
    if result.get("status") == "error":
        common.console.print(f"[red]{common.rich_escape(str(result.get('error')))}[/red]")
        return common.EXIT_RUN_FAILED
    return _print_connector_account(result)


def cmd_connector_positions(
    profile_id: common.Optional[str] = None,
    *,
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
    account: str | None = None,
    connection_id: str | None = None,
) -> int:
    """Print positions from a connector profile.

    Args:
        profile_id: Profile ID, or None to use the default.
        host: Optional local gateway host.
        port: Optional local gateway port.
        client_id: Optional broker client ID.
        account: Optional account override.
        connection_id: Optional saved connection ID.

    Returns:
        Success exit code after reporting positions, including an empty result, or failure if the
        broker read fails.
    """
    from src.trading.service import get_positions

    try:
        options = {"host": host, "port": port, "client_id": client_id, "account": account}
        if connection_id is not None:
            options["connection_id"] = connection_id
        result = get_positions(_profile_id(profile_id), **options)
    except Exception as exc:  # noqa: BLE001
        common.console.print(f"[red]Connector positions failed:[/red] {exc}")
        return common.EXIT_RUN_FAILED
    if result.get("status") == "error":
        common.console.print(f"[red]{common.rich_escape(str(result.get('error')))}[/red]")
        return common.EXIT_RUN_FAILED
    if result.get("valuation_basis") == "broker_books_unaggregated":
        common.console.print_json(data=result)
        return common.EXIT_SUCCESS
    rows = result.get("positions", [])
    if not rows:
        inner, guide = _remote_payload(result)
        remote_positions = inner.get("positions") if isinstance(inner, dict) else None
        if remote_positions:
            account_label = result.get("account_number") or "(none)"
            table = common.Table(title=f"Positions · {result.get('profile_id')}", box=common.box.SIMPLE_HEAVY, show_lines=False)
            table.add_column("Symbol")
            table.add_column("Type")
            table.add_column("Qty", justify="right")
            table.add_column("Avail. Sell", justify="right")
            table.add_column("Avg Buy Price", justify="right")
            for pos in remote_positions:
                pos = _normalize_mcp_value(pos)
                table.add_row(
                    str(pos.get("symbol") or pos.get("local_symbol") or ""),
                    str(pos.get("type") or pos.get("sec_type") or ""),
                    str(pos.get("quantity") or pos.get("position") or ""),
                    str(pos.get("shares_available_for_sells") or ""),
                    str(pos.get("average_buy_price") or pos.get("avg_cost") or ""),
                )
            common.console.print(f"Account: [cyan]{common.rich_escape(str(account_label))}[/cyan]")
            common.console.print(table)
            if guide:
                common.console.print(f"[dim]{common.rich_escape(str(guide))}[/dim]")
            next_cursor = inner.get("next") if isinstance(inner, dict) else None
            if next_cursor:
                common.console.print(f"[dim]More results available (next={common.rich_escape(str(next_cursor))}).[/dim]")
            return common.EXIT_SUCCESS
        common.console.print("[dim]No positions returned.[/dim]")
        return common.EXIT_SUCCESS
    table = common.Table(title=f"Positions · {result.get('profile_id')}", box=common.box.SIMPLE_HEAVY, show_lines=False)
    table.add_column("Account")
    table.add_column("Symbol")
    table.add_column("Type")
    table.add_column("Qty", justify="right")
    table.add_column("Avg Cost", justify="right")
    table.add_column("Currency")
    for row in rows:
        # Tolerate both IBKR-style and broker_sdk (Longbridge, …) schemas (#735):
        # position→quantity, avg_cost→cost_price, sec_type→market.
        qty = _first_present(row, "position", "quantity")
        avg_cost = _first_present(row, "avg_cost", "cost_price")
        table.add_row(
            str(row.get("account") or ""),
            str(row.get("local_symbol") or row.get("symbol") or ""),
            str(row.get("sec_type") or row.get("market") or ""),
            "" if qty is None else str(qty),
            "" if avg_cost is None else str(avg_cost),
            str(row.get("currency") or ""),
        )
    common.console.print(table)
    return common.EXIT_SUCCESS


def cmd_connector_orders(
    profile_id: common.Optional[str] = None,
    *,
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
    account: str | None = None,
    include_executions: bool = False,
) -> int:
    """Print open orders from a connector profile.

    Args:
        profile_id: Profile ID, or None to use the default.
        host: Optional local gateway host.
        port: Optional local gateway port.
        client_id: Optional broker client ID.
        account: Optional account override.
        include_executions: Whether to request executions alongside open orders from the connector.

    Returns:
        Success exit code after printing open orders or an empty result, or failure if the broker
        read fails.
    """
    from src.trading.service import get_open_orders

    try:
        result = get_open_orders(
            _profile_id(profile_id),
            host=host,
            port=port,
            client_id=client_id,
            account=account,
            include_executions=include_executions,
        )
    except Exception as exc:  # noqa: BLE001
        common.console.print(f"[red]Connector orders failed:[/red] {exc}")
        return common.EXIT_RUN_FAILED
    if result.get("status") == "error":
        common.console.print(f"[red]{common.rich_escape(str(result.get('error')))}[/red]")
        return common.EXIT_RUN_FAILED
    orders = result.get("open_orders", [])
    if not orders:
        common.console.print("[dim]No open orders returned.[/dim]")
        return common.EXIT_SUCCESS
    table = common.Table(title=f"Open Orders · {result.get('profile_id')}", box=common.box.SIMPLE_HEAVY, show_lines=False)
    table.add_column("Account")
    table.add_column("Symbol")
    table.add_column("Action")
    table.add_column("Type")
    table.add_column("Qty", justify="right")
    table.add_column("Limit", justify="right")
    table.add_column("Status")
    for row in orders:
        contract = row.get("contract") or {}
        order = row.get("order") or row
        # IBKR nests status as ``{"status": {"status": ...}}``; broker_sdk
        # connectors (Alpaca, …) return it as a plain string on the flat row.
        raw_status = row.get("status")
        status_text = raw_status.get("status") if isinstance(raw_status, dict) else raw_status
        table.add_row(
            str(order.get("account") or ""),
            str(contract.get("local_symbol") or contract.get("symbol") or order.get("symbol") or ""),
            _enum_text(order.get("action") or order.get("side") or ""),
            _enum_text(order.get("order_type") or ""),
            str(order.get("total_quantity") or order.get("quantity") or ""),
            str(order.get("limit_price") or ""),
            _enum_text(status_text or ""),
        )
    common.console.print(table)
    return common.EXIT_SUCCESS


def cmd_connector_quote(
    symbol: str,
    profile_id: common.Optional[str] = None,
    *,
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
    account: str | None = None,
    exchange: str = "SMART",
    currency: str = "USD",
    sec_type: str = "STK",
) -> int:
    """Print a quote from a connector profile.

    Args:
        symbol: Broker symbol to look up.
        profile_id: Profile ID, or None to use the default.
        host: Optional local gateway host.
        port: Optional local gateway port.
        client_id: Optional broker client ID.
        account: Optional account override.
        exchange: Contract exchange or routing code.
        currency: Contract currency code.
        sec_type: Broker security type code.

    Returns:
        Success exit code after printing the quote, or failure if the broker read fails.
    """
    from src.trading.service import get_quote

    try:
        result = get_quote(
            symbol,
            _profile_id(profile_id),
            host=host,
            port=port,
            client_id=client_id,
            account=account,
            exchange=exchange,
            currency=currency,
            sec_type=sec_type,
        )
    except Exception as exc:  # noqa: BLE001
        common.console.print(f"[red]Connector quote failed:[/red] {exc}")
        return common.EXIT_RUN_FAILED
    if result.get("status") == "error":
        common.console.print(f"[red]{common.rich_escape(str(result.get('error')))}[/red]")
        return common.EXIT_RUN_FAILED
    quote = result.get("quote", {})
    table = common.Table(title=f"Quote {result.get('symbol', symbol)} · {result.get('profile_id')}", box=common.box.SIMPLE_HEAVY)
    table.add_column("Bid", justify="right")
    table.add_column("Ask", justify="right")
    table.add_column("Last", justify="right")
    table.add_column("Close", justify="right")
    table.add_column("Volume", justify="right")
    table.add_row(
        str(quote.get("bid") or ""),
        str(quote.get("ask") or ""),
        str(quote.get("last") or ""),
        str(quote.get("close") or ""),
        str(quote.get("volume") or ""),
    )
    common.console.print(table)
    return common.EXIT_SUCCESS


def cmd_connector_history(
    symbol: str,
    profile_id: common.Optional[str] = None,
    *,
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
    account: str | None = None,
    exchange: str = "SMART",
    currency: str = "USD",
    sec_type: str = "STK",
    duration: str = "30 D",
    bar_size: str = "1 day",
    what_to_show: str = "TRADES",
    use_rth: bool = True,
    period: str = "1d",
    limit: int = 90,
) -> int:
    """Print historical bars from a connector profile.

    Args:
        symbol: Broker symbol to look up.
        profile_id: Profile ID, or None to use the default.
        host: Optional local gateway host.
        port: Optional local gateway port.
        client_id: Optional broker client ID.
        account: Optional account override.
        exchange: Contract exchange or routing code.
        currency: Contract currency code.
        sec_type: Broker security type code.
        duration: Gateway lookback duration, such as 30 D.
        bar_size: Gateway bar size, such as 1 day.
        what_to_show: Gateway data type, such as TRADES.
        use_rth: Whether to restrict gateway bars to regular trading hours.
        period: Bar interval for connectors using period-based history.
        limit: Maximum number of bars requested and shown.

    Returns:
        Success exit code after reporting bars or an empty result, or failure if the broker read
        fails.
    """
    from src.trading.service import get_history

    try:
        result = get_history(
            symbol,
            _profile_id(profile_id),
            host=host,
            port=port,
            client_id=client_id,
            account=account,
            exchange=exchange,
            currency=currency,
            sec_type=sec_type,
            duration=duration,
            bar_size=bar_size,
            what_to_show=what_to_show,
            use_rth=use_rth,
            period=period,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001
        common.console.print(f"[red]Connector history failed:[/red] {exc}")
        return common.EXIT_RUN_FAILED
    if result.get("status") == "error":
        common.console.print(f"[red]{common.rich_escape(str(result.get('error')))}[/red]")
        return common.EXIT_RUN_FAILED
    rows = result.get("bars", [])
    # The table used to keep only the last 20 bars, so --limit 40 still
    # printed 20. Honor the same limit that was sent to the connector.
    shown = rows[-limit:] if isinstance(limit, int) and limit >= 1 else []
    if not shown:
        common.console.print("[dim]No historical bars returned.[/dim]")
        return common.EXIT_SUCCESS
    table = common.Table(title=f"History {result.get('symbol', symbol)} · {result.get('profile_id')}", box=common.box.SIMPLE_HEAVY)
    table.add_column("Date")
    table.add_column("Open", justify="right")
    table.add_column("High", justify="right")
    table.add_column("Low", justify="right")
    table.add_column("Close", justify="right")
    table.add_column("Volume", justify="right")
    for row in shown:
        table.add_row(
            str(row.get("date") or ""),
            str(row.get("open") or ""),
            str(row.get("high") or ""),
            str(row.get("low") or ""),
            str(row.get("close") or ""),
            str(row.get("volume") or ""),
        )
    common.console.print(table)
    return common.EXIT_SUCCESS


def cmd_connector_authorize(profile_id: common.Optional[str]) -> int:
    """Authorize a remote MCP connector profile.

    Args:
        profile_id: Live connector profile ID, or None to use the selected profile.

    Returns:
        Profile resolution error or the exit status of live authorization.
    """
    code, broker = live._live_profile_connector(profile_id)
    if code != common.EXIT_SUCCESS or broker is None:
        return code
    return live.cmd_live_authorize(broker)


def cmd_connector_status(profile_id: common.Optional[str]) -> int:
    """Show connector status.

    Args:
        profile_id: Profile ID, or None to use the selected profile.

    Returns:
        Exit status of the readiness check or, for a ready live MCP connector, the live status
        command. Returns a usage error for invalid profile selection.
    """
    try:
        profile = _selected_profile_or(profile_id)
    except ValueError as exc:
        common.console.print(f"[red]{exc}[/red]")
        return common.EXIT_USAGE_ERROR
    if profile.environment == "live" and profile.transport == "remote_mcp":
        check_code = cmd_connector_check(profile.id)
        if check_code != common.EXIT_SUCCESS:
            return check_code
        return live.cmd_live_status(profile.connector)
    return cmd_connector_check(profile.id)


def cmd_connector_start(profile_id: common.Optional[str]) -> int:
    """Start a live remote MCP connector runner.

    Args:
        profile_id: Runner-enabled live connector profile ID, or None to use the selected profile.

    Returns:
        Profile resolution error or the exit status of the runner start request.
    """
    code, broker = live._live_profile_connector(profile_id, require_runner=True)
    if code != common.EXIT_SUCCESS or broker is None:
        return code
    return live.cmd_live_start(broker)


def cmd_connector_runner_settings(profile_id: common.Optional[str], settings_file: common.Optional[str] = None) -> int:
    """Show model budgets or save a JSON settings file for a stopped runner.

    Args:
        profile_id: Runner-enabled live connector profile ID, or None to use the selected profile.
        settings_file: Optional JSON file containing DecisionSettings fields. Omit to read current
            settings.

    Returns:
        Success exit code on API success, a usage error for invalid settings, failure on API error,
        or an error from profile resolution.
    """
    from urllib.parse import urlencode

    code, broker = live._live_profile_connector(profile_id, require_runner=True)
    if code != common.EXIT_SUCCESS or broker is None:
        return code
    path = "/live/runner/settings?" + urlencode({"broker": broker})
    body = None
    if settings_file:
        try:
            from src.live.runtime.decision_budget import DecisionSettings

            body = DecisionSettings.model_validate_json(common.Path(settings_file).read_text()).model_dump()
        except (OSError, ValueError) as exc:
            common.console.print(f"[red]Invalid runner settings:[/red] {exc}")
            return common.EXIT_USAGE_ERROR
    result = live._live_api_call("PUT" if body is not None else "GET", path, body=body)
    common.console.print_json(data=result)
    return common.EXIT_RUN_FAILED if result.get("status") == "error" else common.EXIT_SUCCESS


def cmd_connector_stop(profile_id: common.Optional[str]) -> int:
    """Stop a live remote MCP connector runner.

    Args:
        profile_id: Runner-enabled live connector profile ID, or None to use the selected profile.

    Returns:
        Profile resolution error or the exit status of the runner stop request.
    """
    code, broker = live._live_profile_connector(profile_id, require_runner=True)
    if code != common.EXIT_SUCCESS or broker is None:
        return code
    return live.cmd_live_stop(broker)


def cmd_connector_halt(profile_id: common.Optional[str]) -> int:
    """Trip the halt switch for a live remote MCP connector profile.

    Args:
        profile_id: Runner-enabled live connector profile ID, or None to use the selected profile.

    Returns:
        Profile resolution error or the exit status of the halt request.
    """
    code, broker = live._live_profile_connector(profile_id, require_runner=True)
    if code != common.EXIT_SUCCESS or broker is None:
        return code
    return live.cmd_live_halt(broker)


def cmd_connector_resume(profile_id: common.Optional[str]) -> int:
    """Clear the halt switch for a live remote MCP connector profile.

    Args:
        profile_id: Runner-enabled live connector profile ID, or None to use the selected profile.

    Returns:
        Profile resolution error or the exit status of clearing the halt switch.
    """
    code, broker = live._live_profile_connector(profile_id, require_runner=True)
    if code != common.EXIT_SUCCESS or broker is None:
        return code
    return live.cmd_live_resume(broker)


def cmd_connector_revoke(profile_id: common.Optional[str]) -> int:
    """Revoke a live remote MCP connector profile.

    Args:
        profile_id: Live connector profile ID, or None to use the selected profile.

    Returns:
        Profile resolution error or the exit status of revocation.
    """
    code, broker = live._live_profile_connector(profile_id)
    if code != common.EXIT_SUCCESS or broker is None:
        return code
    return live.cmd_live_revoke(broker)


def _dispatch_connector(args: common.argparse.Namespace) -> int:
    """Route parsed ``connector`` subcommands."""
    execution._ensure_cli_env()
    sub = getattr(args, "connector_command", None)
    if sub == "list":
        return cmd_connector_list()
    if sub == "init":
        return cmd_connector_init(args.connector_id, args.destination)
    if sub == "validate":
        return cmd_connector_validate(args.directory)
    if sub == "install":
        return cmd_connector_install(args.directory)
    if sub == "use":
        return cmd_connector_use(args.profile)
    if sub == "configure":
        return cmd_connector_configure(
            args.profile,
            host=args.host,
            port=args.port,
            client_id=args.client_id,
            account=args.account,
            yes=args.yes,
        )
    if sub == "setup":
        return cmd_connector_setup(
            args.profile,
            connection_id=args.connection_id,
            label=args.label,
            skip_check=args.skip_check,
            account=args.account,
            host=args.host,
            port=args.port,
        )
    if sub == "select-account":
        return cmd_connector_select_account(
            args.connection_id,
            account=args.account,
            clear=args.clear,
        )
    if sub in {"check", "account", "positions", "orders", "quote", "history"}:
        options = {
            "host": args.host,
            "port": args.port,
            "client_id": args.client_id,
            "account": args.account,
        }
        if sub == "check":
            if args.connection_id is not None:
                options["connection_id"] = args.connection_id
            return cmd_connector_check(args.profile, **options)
        if sub in {"account", "positions"}:
            if getattr(args, "connection_id", None):
                options["connection_id"] = args.connection_id
            handler = cmd_connector_account if sub == "account" else cmd_connector_positions
            return handler(args.profile, **options)
        if sub == "orders":
            return cmd_connector_orders(args.profile, include_executions=args.include_executions, **options)

        options.update(exchange=args.exchange, currency=args.currency, sec_type=args.sec_type)
        if sub == "quote":
            return cmd_connector_quote(args.symbol, args.profile, **options)
        return cmd_connector_history(
            args.symbol,
            args.profile,
            duration=args.duration,
            bar_size=args.bar_size,
            what_to_show=args.what_to_show,
            use_rth=not args.no_rth,
            period=args.period,
            limit=args.bar_limit,
            **options,
        )
    if sub == "authorize":
        return cmd_connector_authorize(args.profile)
    if sub == "status":
        return cmd_connector_status(args.profile)
    if sub == "start":
        return cmd_connector_start(args.profile)
    if sub == "runner-settings":
        return cmd_connector_runner_settings(args.profile, args.file)
    if sub == "stop":
        return cmd_connector_stop(args.profile)
    if sub == "halt":
        return cmd_connector_halt(args.profile)
    if sub == "resume":
        return cmd_connector_resume(args.profile)
    if sub == "revoke":
        return cmd_connector_revoke(args.profile)
    common.console.print("[red]connector requires a subcommand.[/red] Try: vibe-trading connector list")
    return common.EXIT_USAGE_ERROR
