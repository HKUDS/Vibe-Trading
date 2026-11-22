"""CLI channels commands and their helpers."""
from __future__ import annotations

from cli.commands import common
from cli.commands import live

def _channels_api_call(method: str, path: str, *, body: common.Optional[common.Dict[str, common.Any]] = None) -> common.Dict[str, common.Any]:
    """Call an IM channel runtime endpoint on the local API server."""
    import httpx

    url = f"{live._live_api_base()}{path}"
    headers = live._api_auth_headers()
    try:
        if method.upper() == "GET":
            response = httpx.get(url, headers=headers, timeout=10.0)
        else:
            response = httpx.post(url, json=body or {}, headers=headers, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except Exception as exc:  # noqa: BLE001 - CLI should explain offline API cleanly
        return {"status": "error", "error": str(exc)}


def _channels_local_status() -> common.Dict[str, common.Any]:
    """Build local channel config/import status without starting adapters."""
    from src.channels.config import load_channels_config
    from src.channels.registry import inspect_channels

    config = load_channels_config()
    return {
        "running": False,
        "source": "local_config",
        "channels": inspect_channels(config),
    }


def _print_channels_status(payload: common.Dict[str, common.Any]) -> None:
    """Render IM channel status."""
    table = common.Table(title="IM Channels", box=common.box.SIMPLE)
    table.add_column("Channel")
    table.add_column("Configured")
    table.add_column("Enabled")
    table.add_column("Available")
    table.add_column("Loaded")
    table.add_column("Running")
    table.add_column("Recovery")
    channels = payload.get("channels") if isinstance(payload, dict) else {}
    if not isinstance(channels, dict):
        channels = {}
    for name, item in sorted(channels.items()):
        if not isinstance(item, dict):
            continue
        recovery = item.get("install_hint") or item.get("error") or ""
        table.add_row(
            str(name),
            "yes" if item.get("configured") else "no",
            "yes" if item.get("enabled") else "no",
            "yes" if item.get("available") else "no",
            "yes" if item.get("loaded") else "no",
            "yes" if item.get("running") else "no",
            str(recovery),
        )
    common.console.print(table)
    if payload.get("status") == "error":
        common.console.print(f"[yellow]API unavailable:[/yellow] {payload.get('error')}")
        common.console.print("[dim]Start the backend with `vibe-trading serve --port 8000`, or inspect local config with this status output.[/dim]")


def cmd_channels_status(*, json_mode: bool = False, local: bool = False) -> int:
    """Show IM channel status."""
    payload = _channels_local_status() if local else _channels_api_call("GET", "/channels/status")
    if payload.get("status") == "error":
        local_payload = _channels_local_status()
        local_payload["status"] = "error"
        local_payload["error"] = payload.get("error", "")
        payload = local_payload
    if json_mode:
        print(common.json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        _print_channels_status(payload)
    return common.EXIT_SUCCESS


def cmd_channels_start(*, json_mode: bool = False) -> int:
    """Start configured IM channels through the API runtime."""
    payload = _channels_api_call("POST", "/channels/start")
    failed = payload.get("status") == "error"
    if json_mode:
        print(common.json.dumps(payload, indent=2, ensure_ascii=False))
    elif failed:
        common.console.print(f"[red]Failed to start IM channels:[/red] {payload.get('error')}")
        common.console.print(
            "[dim]Run `vibe-trading serve --port 8000` first, or set VIBE_TRADING_API_URL.[/dim]"
        )
    else:
        common.console.print("[green]IM channels started.[/green]")
        _print_channels_status(payload)
    return common.EXIT_RUN_FAILED if failed else common.EXIT_SUCCESS


def cmd_channels_stop(*, json_mode: bool = False) -> int:
    """Stop configured IM channels through the API runtime."""
    payload = _channels_api_call("POST", "/channels/stop")
    failed = payload.get("status") == "error"
    if json_mode:
        print(common.json.dumps(payload, indent=2, ensure_ascii=False))
    elif failed:
        common.console.print(f"[red]Failed to stop IM channels:[/red] {payload.get('error')}")
        common.console.print(
            "[dim]Run `vibe-trading serve --port 8000` first, or set VIBE_TRADING_API_URL.[/dim]"
        )
    else:
        common.console.print("[green]IM channels stopped.[/green]")
        _print_channels_status(payload)
    return common.EXIT_RUN_FAILED if failed else common.EXIT_SUCCESS


def cmd_channels_pairing(channel: str, command: str) -> int:
    """Run a pairing command against the shared local pairing store."""
    from src.channels.pairing import handle_pairing_command

    common.console.print(handle_pairing_command(channel, command))
    return common.EXIT_SUCCESS


def cmd_channels_login(channel_name: str, *, force: bool = False) -> int:
    """Run a channel adapter's interactive login hook when available."""
    import asyncio

    from src.channels.config import load_channels_config
    from src.channels.manager import ChannelManager
    from src.channels.bus.queue import MessageBus

    config = load_channels_config()
    section = dict(config.get(channel_name, {})) if isinstance(config.get(channel_name), dict) else {}
    if channel_name == "websocket":
        common.console.print("[green]WebSocket channel does not require interactive login.[/green]")
        common.console.print("[dim]Configure channels.websocket in ~/.vibe-trading/agent.json, then run `vibe-trading channels start`.[/dim]")
        return common.EXIT_SUCCESS
    if not section:
        common.console.print(f"[red]No config found for channel '{channel_name}'.[/red]")
        common.console.print("[dim]Add it under channels.<name> in ~/.vibe-trading/agent.json, then retry.[/dim]")
        return common.EXIT_USAGE_ERROR
    section["enabled"] = True
    manager = ChannelManager({channel_name: section}, MessageBus())
    adapter = manager.get_channel(channel_name)
    if adapter is None:
        status = manager.get_status().get(channel_name, {})
        recovery = status.get("install_hint") or status.get("error") or "adapter unavailable"
        common.console.print(f"[red]Channel '{channel_name}' is unavailable.[/red] {recovery}")
        return common.EXIT_RUN_FAILED
    ok = asyncio.run(adapter.login(force=force))
    if ok:
        common.console.print(f"[green]Channel '{channel_name}' login completed.[/green]")
        return common.EXIT_SUCCESS
    common.console.print(f"[red]Channel '{channel_name}' login failed.[/red]")
    return common.EXIT_RUN_FAILED


def _dispatch_channels(args: common.argparse.Namespace) -> int:
    """Dispatch IM channel subcommands."""
    command = args.channels_command
    if command == "status":
        return cmd_channels_status(json_mode=args.channels_json, local=args.local)
    if command == "start":
        return cmd_channels_start(json_mode=args.channels_json)
    if command == "stop":
        return cmd_channels_stop(json_mode=args.channels_json)
    if command == "pairing":
        text = " ".join([args.pairing_command, *args.pairing_args]).strip()
        return cmd_channels_pairing(args.channel, text or "list")
    if command == "login":
        return cmd_channels_login(args.channel_name, force=args.force)
    common.console.print("[red]channels requires a subcommand.[/red] Try: vibe-trading channels status")
    return common.EXIT_USAGE_ERROR
