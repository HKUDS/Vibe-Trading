"""CLI portfolio commands and their helpers."""
from __future__ import annotations

from cli.commands import common
from cli.commands import connectors

def _portfolio_service(service: common.Any | None = None) -> common.Any:
    """Return the injected portfolio service, or build the default one.

    Args:
        service: Optional pre-built service (tests inject a stub).

    Returns:
        A ``PortfolioService`` instance.
    """
    if service is not None:
        return service
    from src.portfolio.service import PortfolioService

    return PortfolioService()


def _print_portfolio_snapshot(snapshot: dict[str, common.Any]) -> None:
    """Render one portfolio snapshot: totals, per-source accounts, holdings, warnings.

    Args:
        snapshot: A snapshot envelope as produced by ``PortfolioService``.
    """
    totals = snapshot.get("totals") or {}
    usd = float(totals.get("usd") or 0.0)
    cny = float(totals.get("cny") or 0.0)
    state = "[green]complete[/green]" if snapshot.get("complete") else "[yellow]INCOMPLETE[/yellow]"
    common.console.print(
        f"Snapshot [cyan]{common.rich_escape(str(snapshot.get('created_at') or '?'))}[/cyan] · {state} · "
        f"total [bold]{usd:,.2f} USD[/bold] / {cny:,.0f} CNY"
    )

    accounts = common.Table(title="Sources", box=common.box.SIMPLE_HEAVY, show_lines=False)
    accounts.add_column("Source")
    accounts.add_column("Connector")
    accounts.add_column("Status", justify="center")
    accounts.add_column("Total USD", justify="right")
    accounts.add_column("Last success")
    for row in snapshot.get("accounts") or []:
        ok = row.get("status") == "ok"
        total = row.get("total_usd")
        accounts.add_row(
            common.rich_escape(str(row.get("label") or row.get("source_id") or "?")),
            common.rich_escape(str(row.get("broker") or "")),
            "[green]ok[/green]" if ok else f"[red]{common.rich_escape(str(row.get('status')))}[/red]",
            f"{float(total):,.2f}" if total is not None else "[dim]excluded[/dim]",
            common.rich_escape(str(row.get("last_success_at") or "never")),
        )
    common.console.print(accounts)
    for row in snapshot.get("accounts", []):
        if row.get("status") == "ok" and row.get("balance_details"):
            common.console.print(common.rich_escape(str(row.get("label") or row.get("broker") or "")))
            connectors._print_balance_details(row["balance_details"])
        if row.get("import_metadata"):
            meta = row["import_metadata"]
            common.console.print(f"extraETF file mtime: {common.rich_escape(meta['source_mtime'])}; expires: {common.rich_escape(meta['expires_at'])}; holdings only, no cash")

    holdings = common.Table(title="Holdings (combined across sources)", box=common.box.SIMPLE_HEAVY, show_lines=False)
    holdings.add_column("Symbol")
    holdings.add_column("Type")
    holdings.add_column("Value USD", justify="right")
    holdings.add_column("Weight", justify="right")
    holdings.add_column("Unrealized P/L USD", justify="right")
    holdings.add_column("Sources")
    for row in (snapshot.get("combined_holdings") or [])[:common._PORTFOLIO_CLI_MAX_HOLDINGS]:
        value = float(row.get("market_value_usd") or 0.0)
        pnl = row.get("unrealized_pnl_usd")
        holdings.add_row(
            common.rich_escape(str(row.get("symbol") or "?")),
            common.rich_escape(str(row.get("asset_type") or "")),
            f"{value:,.2f}",
            f"{(value / usd * 100):.1f}%" if usd > 0 else "—",
            f"{float(pnl):,.2f}" if pnl is not None else "—",
            common.rich_escape(", ".join(str(item) for item in (row.get("sources") or row.get("brokers") or []))),
        )
    common.console.print(holdings)
    for warning in snapshot.get("warnings") or []:
        common.console.print(f"[yellow]![/yellow] {common.rich_escape(str(warning))}")


def cmd_portfolio_show(service: common.Any | None = None, snapshot_id: str | None = None) -> int:
    """Print the latest snapshot or one exact stored observation.

    Args:
        service: Optional ``PortfolioService`` (tests inject a stub).
        snapshot_id: Optional immutable snapshot id; never falls back to latest.

    Returns:
        The process exit code.
    """
    instance = _portfolio_service(service)
    snapshot = instance.latest() if snapshot_id is None else instance.snapshot_by_id(snapshot_id)
    if snapshot is None:
        if snapshot_id is not None:
            common.console.print("[red]The requested portfolio snapshot is unavailable.[/red]")
            return common.EXIT_RUN_FAILED
        common.console.print(
            "[dim]No portfolio snapshot yet. Select sources on the Web UI Portfolio page "
            "(or `vibe-trading portfolio sources`), then run `vibe-trading portfolio refresh`.[/dim]"
        )
        return common.EXIT_SUCCESS
    _print_portfolio_snapshot(snapshot)
    return common.EXIT_SUCCESS


def cmd_portfolio_refresh(service: common.Any | None = None) -> int:
    """Read every enabled source now, store a new snapshot, and print it.

    A source that fails is reported and excluded from the totals; the command
    then exits non-zero so scripts notice the portfolio is incomplete.

    Args:
        service: Optional ``PortfolioService`` (tests inject a stub).

    Returns:
        ``EXIT_SUCCESS`` for a complete snapshot, ``EXIT_RUN_FAILED`` otherwise.
    """
    try:
        snapshot = _portfolio_service(service).refresh()
    except RuntimeError as exc:
        common.console.print(f"[red]{common.rich_escape(str(exc))}[/red]")
        return common.EXIT_RUN_FAILED
    _print_portfolio_snapshot(snapshot)
    return common.EXIT_SUCCESS if snapshot.get("complete") else common.EXIT_RUN_FAILED


def cmd_portfolio_sources(service: common.Any | None = None) -> int:
    """List the local read-only connections and whether the portfolio uses them.

    Args:
        service: Optional ``PortfolioService`` (tests inject a stub).

    Returns:
        The process exit code.
    """
    rows = _portfolio_service(service).sources()
    table = common.Table(title="Portfolio sources", box=common.box.SIMPLE_HEAVY, show_lines=False)
    table.add_column("Selected", justify="center", width=8)
    table.add_column("Connection")
    table.add_column("Connector")
    table.add_column("Env")
    table.add_column("Transport")
    table.add_column("Credentials", justify="center")
    for row in rows:
        connection_cell = (
            f"[cyan]{common.rich_escape(str(row.get('connection_id') or row.get('id')))}[/cyan]"
            f"\n[dim]{common.rich_escape(str(row.get('label') or ''))}[/dim]"
        )
        account_ref = str(row.get("account_ref") or "")
        if account_ref:
            connection_cell += f"\n[dim]account ····{common.rich_escape(account_ref[-4:])}[/dim]"
        elif row.get("account_selection_required"):
            connection_cell += "\n[yellow]no account selected[/yellow]"
        table.add_row(
            "[green]*[/green]" if row.get("selected") else "",
            connection_cell,
            common.rich_escape(str(row.get("connector") or "")),
            common.rich_escape(str(row.get("environment") or "")),
            common.rich_escape(str(row.get("transport") or "")),
            "[green]ok[/green]" if row.get("credentials_configured") else "[dim]-[/dim]",
        )
    common.console.print(table)
    if not rows:
        common.console.print("[dim]No local connections yet. Create one on the Web UI Portfolio page (Manage accounts → Connection center).[/dim]")
    return common.EXIT_SUCCESS


def _dispatch_portfolio(args: common.argparse.Namespace) -> int:
    """Route ``vibe-trading portfolio <subcommand>``; bare ``portfolio`` shows.

    Args:
        args: Parsed CLI arguments.

    Returns:
        The process exit code.
    """
    sub = getattr(args, "portfolio_command", None) or "show"
    if sub == "show":
        return cmd_portfolio_show(snapshot_id=getattr(args, "snapshot_id", None))
    if sub == "refresh":
        return cmd_portfolio_refresh()
    if sub == "sources":
        return cmd_portfolio_sources()
    if sub == "import-extraetf":
        from datetime import datetime, timezone
        from src.portfolio.imports import MAX_IMPORT_BYTES
        try:
            path = common.Path(args.file).expanduser()
            with path.open("rb") as handle:
                data = handle.read(MAX_IMPORT_BYTES + 1)
                modified = common.os.fstat(handle.fileno()).st_mtime
            if len(data) > MAX_IMPORT_BYTES:
                raise ValueError("extraETF export exceeds the 4 MiB import limit")
            instance = _portfolio_service()
            imported = instance.settings_store.import_store.create(
                csv_text=data.decode("utf-8-sig"), label=args.label,
                source_mtime=datetime.fromtimestamp(modified, timezone.utc).isoformat(),
                expected_positions=args.expected_positions, max_age_days=args.max_age_days,
            )
            if args.select:
                settings = instance.settings()
                settings["sources"].append({"connection_id": imported["id"], "source_kind": "extraetf",
                                            "label": imported["label"], "include_cash": False})
                instance.save_settings(settings)
            common.console.print_json(data=imported)
            return 0
        except (ValueError, OSError) as exc:
            common.console.print(f"[red]{common.rich_escape(str(exc))}[/red]")
            return 1
    if sub == "rebalance":
        try:
            target = common.json.loads(common.Path(args.targets).read_text())
            common.console.print_json(data=_portfolio_service().rebalance(args.snapshot_id, target))
            return 0
        except (ValueError, OSError) as exc:
            common.console.print(f"[red]{common.rich_escape(str(exc))}[/red]")
            return 1
    common.console.print(f"[red]Unknown portfolio subcommand: {sub}[/red]")
    return common.EXIT_USAGE_ERROR
