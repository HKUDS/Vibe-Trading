"""CLI live commands and their helpers."""
from __future__ import annotations

from cli.commands import common
from cli.commands import connectors

def _authorize_timeout_seconds() -> float:
    """Resolve the OAuth authorize handshake deadline in seconds."""
    raw = common.get_env_config().agent_tuning.vibe_live_authorize_timeout_s
    return float(raw) if raw and raw > 0 else float(_LIVE_AUTHORIZE_INIT_TIMEOUT_SECONDS)


def _live_api_base() -> str:
    """Return the base URL of the running API server for runner-control calls."""
    return common.get_env_config().api.vibe_trading_api_url.rstrip("/")


def _api_auth_headers() -> common.Dict[str, str]:
    """Return Bearer auth headers for CLI-to-API control calls."""
    common.reset_env_config()  # ensure fresh read of auth credentials
    key = common.get_env_config().api.api_auth_key.strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _live_api_call(
    method: str, path: str, *, body: common.Optional[common.Dict[str, common.Any]] = None
) -> common.Dict[str, common.Any]:
    """Call an R6 live-runner endpoint and decode the JSON response."""
    import httpx

    url = f"{_live_api_base()}{path}"
    headers = _api_auth_headers()
    try:
        if method.upper() == "GET":
            response = httpx.get(url, headers=headers, timeout=30.0)
        else:
            response = httpx.post(url, json=body or {}, headers=headers, timeout=30.0)
        response.raise_for_status()
        return response.json()
    except Exception as exc:  # noqa: BLE001 — surface a clean error to the user
        return {"status": "error", "error": str(exc)}


def _live_server_config(broker: str):
    """Resolve the protected MCP server config for ``broker``."""
    from src.config.loader import load_agent_config

    agent_config = load_agent_config()
    servers = getattr(agent_config, "mcp_servers", {}) or {}
    return servers.get(broker.strip().lower())


def _raw_live_server_config_entry(broker: str) -> dict[str, common.Any] | None:
    """Best-effort raw lookup used only to explain invalid live config."""
    from src.config.loader import _read_config_file
    from src.config.paths import get_config_path
    from src.config.schema import live_broker_key_for_url

    try:
        path = get_config_path()
        if not path.exists():
            return None
        raw = _read_config_file(path)
    except Exception:  # noqa: BLE001 — diagnostics must not mask the real CLI error
        return None

    servers = raw.get("mcpServers")
    if not isinstance(servers, dict):
        servers = raw.get("mcp_servers")
    if not isinstance(servers, dict):
        return None

    key = broker.strip().lower()
    for server_key, server in servers.items():
        if isinstance(server, dict) and str(server_key).strip().lower() == key:
            return server

    if key != "robinhood":
        return None

    for server in servers.values():
        if isinstance(server, dict) and live_broker_key_for_url(str(server.get("url") or "")) == key:
            return server
    return None


def _raw_server_entry_uses_wildcard(entry: dict[str, common.Any] | None) -> bool:
    """Return whether a raw MCP server entry uses a wildcard enabledTools list."""
    if entry is None:
        return False
    enabled_tools = entry.get("enabledTools", entry.get("enabled_tools"))
    if not isinstance(enabled_tools, list):
        return False
    return "*" in {str(tool).strip() for tool in enabled_tools}


def _print_missing_live_channel_config(key: str) -> None:
    """Print actionable guidance when a live broker config cannot be loaded."""
    if key == "robinhood":
        from src.config.schema import format_robinhood_mcp_config_guidance

        reason = "wildcard" if _raw_server_entry_uses_wildcard(_raw_live_server_config_entry(key)) else "missing"
        common.console.print("[red]Robinhood live channel is not configured safely.[/red]")
        common.console.print(format_robinhood_mcp_config_guidance(reason=reason), markup=False, soft_wrap=True)
        return

    common.console.print(
        f"[red]No live channel configured for '{key}'.[/red] "
        "Add the broker's mcpServers entry to ~/.vibe-trading/agent.json first."
    )


def cmd_live_authorize(broker: str) -> int:
    """Bootstrap the OAuth handshake for a live broker channel (desktop only)."""
    key = broker.strip().lower()
    server_config = _live_server_config(key)
    if server_config is None:
        _print_missing_live_channel_config(key)
        return common.EXIT_USAGE_ERROR
    if getattr(server_config, "auth", None) is None:
        common.console.print(
            f"[red]Live channel '{key}' has no OAuth auth configured[/red] — "
            "cannot authorize."
        )
        return common.EXIT_USAGE_ERROR

    common.console.print(f"[cyan]Opening browser to authorize {key}…[/cyan]")
    common.console.print(
        "[dim]Complete the sign-in in your browser; this terminal will continue "
        "once the broker redirects back.[/dim]"
    )
    try:
        from src.tools.mcp import build_mcp_tool_wrappers

        # The OAuth flow is driven lazily by the first request to the server —
        # the `list_tools` discovery handshake — which is bounded by the
        # per-call `tool_timeout` (default 30 s), NOT `init_timeout`. Raise both
        # to the authorize deadline so a multi-minute human sign-in (e.g.
        # Robinhood's face scan) does not trip the handshake. Raise-only: never
        # shrink an already-larger user-configured timeout.
        authorize_timeout = _authorize_timeout_seconds()
        if hasattr(server_config, "model_copy"):
            updates: dict[str, float] = {}
            configured_init_timeout = getattr(server_config, "init_timeout", None)
            if (
                configured_init_timeout is None
                or float(configured_init_timeout) < authorize_timeout
            ):
                updates["init_timeout"] = authorize_timeout
            configured_tool_timeout = getattr(server_config, "tool_timeout", None)
            if (
                configured_tool_timeout is None
                or float(configured_tool_timeout) < authorize_timeout
            ):
                updates["tool_timeout"] = authorize_timeout
            if updates:
                server_config = server_config.model_copy(update=updates)

        # Single attempt: a transient-retry would open a fresh client context
        # that starts a SECOND OAuth callback server on a new port, orphaning
        # the sign-in the user just completed against the first one (see #259).
        tools = build_mcp_tool_wrappers(
            key, server_config, max_list_tools_attempts=1
        )
    except Exception as exc:  # noqa: BLE001 — surface any handshake failure
        common.console.print(f"[red]Authorization failed:[/red] {exc}")
        return common.EXIT_RUN_FAILED

    common.console.print(
        f"[green]Authorized {key}[/green] "
        f"[dim]({len(tools)} read-only tool(s) available)[/dim]"
    )
    common.console.print(
        "[dim]The channel is read-only until you commit a mandate and enable "
        "order tools. Use `vibe-trading connector status` to check state.[/dim]"
    )
    return common.EXIT_SUCCESS


def _format_expiry_countdown(expires_at: str) -> str:
    """Return a human-readable countdown to ``expires_at`` (ISO-8601 UTC)."""
    from datetime import datetime, timezone

    try:
        parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return f"{expires_at} (unparseable)"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = parsed - datetime.now(timezone.utc)
    secs = int(delta.total_seconds())
    if secs <= 0:
        return f"{expires_at} (EXPIRED)"
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        human = f"{days}d {hours}h"
    elif hours:
        human = f"{hours}h {minutes}m"
    else:
        human = f"{minutes}m"
    return f"{expires_at} (in {human})"


def _runner_id_for(broker: str) -> str:
    """Return the persistent-runner identity key for ``broker`` (SPEC §7.5)."""
    return f"live-{broker}"


def _add_runner_liveness_rows(table: common.Table, broker: str) -> None:
    """Append persistent-runner liveness rows to a ``live status`` table."""
    runner_id = _runner_id_for(broker)
    try:
        from src.live.runtime.liveness import is_runner_alive, last_tick
    except Exception:  # noqa: BLE001 — liveness lands concurrently; degrade cleanly
        table.add_row("Runner", "[dim]unknown (runtime not available)[/dim]")
        return

    try:
        alive = is_runner_alive(runner_id)
    except Exception as exc:  # noqa: BLE001 — never let a status read raise
        table.add_row("Runner", f"[dim]unknown ({exc})[/dim]")
        return

    if alive:
        table.add_row("Runner", "[green]running[/green]")
    else:
        table.add_row("Runner", "[yellow]stopped[/yellow]")

    try:
        tick = last_tick(runner_id)
    except Exception:  # noqa: BLE001
        tick = None
    if tick is not None:
        table.add_row("  Last tick", _format_last_tick(tick))


def _format_last_tick(tick: common.Any) -> str:
    """Render a runner's last-tick timestamp as an absolute + relative string."""
    from datetime import datetime, timezone

    if isinstance(tick, datetime):
        parsed = tick
    else:
        try:
            parsed = datetime.fromisoformat(str(tick).replace("Z", "+00:00"))
        except ValueError:
            return str(tick)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    ago = int((datetime.now(timezone.utc) - parsed).total_seconds())
    iso = parsed.isoformat()
    if ago < 0:
        return iso
    if ago < 60:
        return f"{iso} ({ago}s ago)"
    if ago < 3600:
        return f"{iso} ({ago // 60}m ago)"
    return f"{iso} ({ago // 3600}h ago)"


def cmd_live_status(broker: common.Optional[str] = None) -> int:
    """Show auth state, active mandate, and halt state for live channels."""
    from src.live.halt import halt_flag_set, read_halt
    from src.live.mandate.model import MANDATE_SCHEMA_VERSION
    from src.live.mandate.store import load_mandate

    key = (broker or _DEFAULT_LIVE_BROKER).strip().lower()

    table = common.Table(title=f"Live channel: {key}", box=common.box.SIMPLE)
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value")

    server_config = _live_server_config(key)
    authorized = server_config is not None and getattr(server_config, "auth", None) is not None
    table.add_row("Configured", "yes" if server_config is not None else "[red]no[/red]")
    table.add_row("OAuth auth", "yes" if authorized else "no")

    halted = halt_flag_set(key)
    if halted:
        meta = read_halt(key) or read_halt() or {}
        reason = meta.get("reason", "")
        by = meta.get("by", "")
        detail = f" [dim]({by}: {reason})[/dim]" if (by or reason) else ""
        table.add_row("Halt", f"[bold red]HALTED[/bold red]{detail}")
    else:
        table.add_row("Halt", "[green]clear[/green]")

    _add_runner_liveness_rows(table, key)

    mandate = load_mandate(key)
    if mandate is None:
        table.add_row("Mandate", "[yellow]none on file[/yellow] (read-only)")
    elif mandate.schema_version != MANDATE_SCHEMA_VERSION:
        table.add_row(
            "Mandate",
            f"[red]unknown schema v{mandate.schema_version}[/red] (gate fail-closed)",
        )
    else:
        caps = mandate.hard_caps
        table.add_row("Mandate", "[green]active[/green]")
        table.add_row("  Max order", f"${caps.max_order_notional_usd:,.0f}")
        table.add_row("  Max exposure", f"${caps.max_total_exposure_usd:,.0f}")
        table.add_row("  Max leverage", f"{caps.max_leverage:g}x")
        table.add_row("  Trades/day", str(caps.max_trades_per_day))
        table.add_row(
            "  Instruments",
            ", ".join(i.value for i in caps.allowed_instruments) or "[red]none[/red]",
        )
        table.add_row("  Expires", _format_expiry_countdown(mandate.consent.expires_at))

    common.console.print(table)
    return common.EXIT_SUCCESS


def cmd_live_mandate(broker: common.Optional[str] = None) -> int:
    """Print the committed mandate for a broker (read-only)."""
    from dataclasses import asdict

    from src.live.mandate.store import load_mandate

    key = (broker or _DEFAULT_LIVE_BROKER).strip().lower()
    mandate = load_mandate(key)
    if mandate is None:
        common.console.print(
            f"[yellow]No committed mandate for '{key}'.[/yellow] "
            "The channel is read-only until a mandate is committed via the consent flow."
        )
        return common.EXIT_RUN_FAILED

    payload = asdict(mandate)
    # asdict leaves enums as Enum members; render their string values.
    caps = payload["hard_caps"]
    caps["allowed_instruments"] = [i.value for i in mandate.hard_caps.allowed_instruments]
    payload["universe"]["asset_classes"] = [a.value for a in mandate.universe.asset_classes]
    common.console.print_json(data=payload)
    return common.EXIT_SUCCESS


def cmd_live_halt(broker: common.Optional[str] = None) -> int:
    """Trip the kill switch — write the HALT sentinel (privileged)."""
    from src.live.halt import trip_halt

    target = broker.strip().lower() if broker else None
    path = trip_halt(by="cli", reason="cli live halt", broker=target)
    scope = target or "ALL brokers"
    common.console.print(f"[bold red]Live trading halted[/bold red] for {scope}.")
    common.console.print(f"[dim]Sentinel: {path}[/dim]")
    common.console.print("[dim]Run `vibe-trading connector resume` to re-enable.[/dim]")
    return common.EXIT_SUCCESS


def cmd_live_resume(broker: common.Optional[str] = None) -> int:
    """Clear a tripped kill switch (privileged, explicit re-enable)."""
    from src.live.halt import clear_halt

    target = broker.strip().lower() if broker else None
    cleared = clear_halt(broker=target)
    scope = target or "ALL brokers"
    if cleared:
        common.console.print(f"[green]Halt cleared[/green] for {scope}.")
    else:
        common.console.print(f"[dim]No active halt for {scope}.[/dim]")
    return common.EXIT_SUCCESS


def cmd_live_revoke(broker: str) -> int:
    """Revoke the OAuth token and delete the mandate — full channel off."""
    from src.live.paths import broker_dir

    key = broker.strip().lower()
    try:
        base = broker_dir(key)
    except ValueError as exc:
        common.console.print(f"[red]{exc}[/red]")
        return common.EXIT_USAGE_ERROR

    removed: list[str] = []

    # OAuth token cache. Prefer the configured cache_dir; fall back to the
    # canonical per-broker oauth/ subtree.
    server_config = _live_server_config(key)
    cache_dir: common.Optional[common.Path] = None
    auth = getattr(server_config, "auth", None) if server_config is not None else None
    if auth is not None and getattr(auth, "cache_dir", None):
        cache_dir = common.Path(auth.cache_dir).expanduser()
    if cache_dir is None or not cache_dir.exists():
        cache_dir = base / "oauth"
    if cache_dir.exists():
        common.shutil.rmtree(cache_dir, ignore_errors=True)
        removed.append(f"OAuth token cache ({cache_dir})")

    mandate_path = base / "mandate.json"
    if mandate_path.exists():
        try:
            mandate_path.unlink()
            removed.append(f"mandate ({mandate_path})")
        except OSError as exc:
            common.console.print(f"[red]Failed to delete mandate: {exc}[/red]")
            return common.EXIT_RUN_FAILED

    if removed:
        common.console.print(f"[green]Revoked live channel '{key}'.[/green]")
        for item in removed:
            common.console.print(f"  [dim]- removed {item}[/dim]")
    else:
        common.console.print(f"[dim]Nothing to revoke for '{key}' (no token or mandate on file).[/dim]")
    return common.EXIT_SUCCESS


def _preview_live_spending(broker: str) -> bool:
    """Show operator settings before either foreground or background start."""
    from urllib.parse import urlencode

    preview = _live_api_call("GET", "/live/runner/settings?" + urlencode({"broker": broker}))
    if preview.get("status") == "error":
        common.console.print("[red]Could not read runner model-spending settings; not starting.[/red]")
        return False
    common.console.print("[yellow]Model calls are billed independently of trade limits.[/yellow]")
    common.console.print_json(data=preview)
    return True


def cmd_live_start(broker: common.Optional[str] = None) -> int:
    """Start the persistent live runner in the background (SPEC §7.5)."""
    key = (broker or _DEFAULT_LIVE_BROKER).strip().lower()
    if not _preview_live_spending(key):
        return common.EXIT_RUN_FAILED
    result = _live_api_call(
        "POST", "/live/runner/start", body={"broker": key, "foreground": False}
    )
    if result.get("status") == "error":
        common.console.print(f"[red]Could not start the live runner:[/red] {result.get('error')}")
        common.console.print(
            "[dim]Is the API server running? Start it with `vibe-trading serve`.[/dim]"
        )
        return common.EXIT_RUN_FAILED

    runner_id = result.get("runner_id") or _runner_id_for(key)
    common.console.print(f"[green]Live runner started[/green] for {key} [dim]({runner_id})[/dim].")
    common.console.print("[dim]Check it with `vibe-trading connector status`.[/dim]")
    return common.EXIT_SUCCESS


def cmd_live_stop(broker: common.Optional[str] = None) -> int:
    """Stop the persistent live runner (SPEC §7.5)."""
    key = (broker or _DEFAULT_LIVE_BROKER).strip().lower()
    result = _live_api_call("POST", "/live/runner/stop", body={"broker": key})
    if result.get("status") == "error":
        common.console.print(f"[red]Could not stop the live runner:[/red] {result.get('error')}")
        common.console.print(
            "[dim]Is the API server running? Start it with `vibe-trading serve`.[/dim]"
        )
        return common.EXIT_RUN_FAILED

    common.console.print(f"[yellow]Live runner stopped[/yellow] for {key}.")
    return common.EXIT_SUCCESS


def cmd_live_run(broker: common.Optional[str] = None) -> int:
    """Run the persistent live runner in the foreground (SPEC §7.5)."""
    key = (broker or _DEFAULT_LIVE_BROKER).strip().lower()
    runner_id = _runner_id_for(key)

    if not _preview_live_spending(key):
        return common.EXIT_RUN_FAILED

    result = _live_api_call(
        "POST", "/live/runner/start", body={"broker": key, "foreground": True}
    )
    if result.get("status") == "error":
        common.console.print(f"[red]Could not start the live runner:[/red] {result.get('error')}")
        common.console.print(
            "[dim]Is the API server running? Start it with `vibe-trading serve`.[/dim]"
        )
        return common.EXIT_RUN_FAILED

    common.console.print(
        f"[green]Live runner running[/green] for {key} [dim]({runner_id})[/dim] — "
        "press Ctrl+C to stop."
    )

    try:
        from src.live.runtime.liveness import is_runner_alive, last_tick
    except Exception:  # noqa: BLE001 — runtime lands concurrently; fall back to a wait
        is_runner_alive = None  # type: ignore[assignment]
        last_tick = None  # type: ignore[assignment]

    def _panel() -> common.Panel:
        alive = bool(is_runner_alive(runner_id)) if is_runner_alive else True
        state = "[green]running[/green]" if alive else "[yellow]stopped[/yellow]"
        lines = [f"Runner: {state}", f"Broker: {key}"]
        if last_tick:
            try:
                tick = last_tick(runner_id)
            except Exception:  # noqa: BLE001
                tick = None
            if tick is not None:
                lines.append(f"Last tick: {_format_last_tick(tick)}")
        return common.Panel("\n".join(lines), title=f"live run · {key}", box=common.box.ROUNDED)

    try:
        with common.Live(_panel(), console=common.console, refresh_per_second=2, transient=False) as live:
            while True:
                common.time.sleep(1.0)
                live.update(_panel())
                if is_runner_alive and not is_runner_alive(runner_id):
                    break
    except KeyboardInterrupt:
        common.console.print("\n[dim]Stopping live runner…[/dim]")
    finally:
        stop = _live_api_call("POST", "/live/runner/stop", body={"broker": key})
        if stop.get("status") == "error":
            common.console.print(f"[red]Failed to stop the runner cleanly:[/red] {stop.get('error')}")
        else:
            common.console.print(f"[yellow]Live runner stopped[/yellow] for {key}.")
    return common.EXIT_SUCCESS


def _live_profile_connector(
    profile_id: common.Optional[str],
    *,
    require_runner: bool = False,
) -> tuple[int, common.Optional[str]]:
    """Resolve a profile to a live-capable connector key."""
    try:
        profile = connectors._selected_profile_or(profile_id)
    except ValueError as exc:
        common.console.print(f"[red]{exc}[/red]")
        return common.EXIT_USAGE_ERROR, None
    if profile.environment != "live" or profile.transport != "remote_mcp":
        common.console.print(f"[red]{profile.id} is not a live remote MCP connector profile.[/red]")
        return common.EXIT_USAGE_ERROR, None
    if require_runner:
        from src.trading.service import profile_supports_live_runner

        if not profile_supports_live_runner(profile):
            common.console.print(f"[red]{profile.id} does not support live runner management.[/red]")
            return common.EXIT_USAGE_ERROR, None
    return common.EXIT_SUCCESS, profile.connector

_DEFAULT_LIVE_BROKER = "robinhood"
_LIVE_AUTHORIZE_INIT_TIMEOUT_SECONDS = 300.0
_LIVE_AUTHORIZE_TIMEOUT_ENV = "VIBE_LIVE_AUTHORIZE_TIMEOUT_SECONDS"
