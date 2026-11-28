"""Dispatch model selection and chat-flow slash commands."""

from __future__ import annotations

from src.config.accessor import get_env_config
from src.product.tool_policy import ToolPolicy

from typing import Any, Optional

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from cli.theme import get_console


def _resolve_console(console: Optional[Console] = None) -> Console:
    """Return the shared CLI console, or a caller-supplied override."""
    if console is not None:
        return console
    return get_console()


def _coming_soon(command: str, *, hint: str) -> int:
    """Render the placeholder panel for not-yet-wired commands."""
    console = _resolve_console()
    body = Text()
    body.append(f"/{command} is not yet wired up to the interactive CLI.\n\n", style="dim")
    body.append("Until then: ", style="dim")
    body.append(hint, style="bold")
    console.print(Panel(body, title=f"/{command}", border_style="dim", padding=(1, 2)))
    return 0


# /model


_MODEL_USAGE = "/model set <provider> <model> [reasoning_effort]  |  /model clear"


def _current_session(ctx: Any, *, create: bool) -> Any:
    """Return ``(store, session)`` for the REPL's session, creating one if asked."""
    from cli.main import _new_session, _session_store

    store = _session_store()
    session_id = getattr(ctx, "session_id", None)
    if session_id is None and create:
        session_id = _new_session("")
        if session_id is None:
            raise RuntimeError("could not create a session to hold the model selection")
        ctx.session_id = session_id
    return store, (store.get_session(session_id) if session_id else None)


def _change_session_model(ctx: Any, args: tuple[str, ...]) -> int:
    """Handle ``/model set ...`` and ``/model clear`` for the REPL's session."""
    from src.providers.selection import ModelSelection, ModelSelectionError, validate_model_selection
    from src.session.model_selection import set_model_selection

    console = _resolve_console()
    action, rest = args[0].lower(), args[1:]
    if not (action == "clear" and not rest) and not (action == "set" and len(rest) in (2, 3)):
        console.print(Text(f"Usage: {_MODEL_USAGE}", style="bold red"))
        return 1
    selection: ModelSelection | None = None
    if action == "set":
        raw = {"provider": rest[0], "model": rest[1], "reasoning_effort": rest[2] if len(rest) == 3 else ""}
        try:
            selection, _config = validate_model_selection(raw)
        except ModelSelectionError as exc:
            console.print(Text(f"Model not changed: {exc}", style="bold red"))
            return 1
    store, session = _current_session(ctx, create=selection is not None)
    if session is None:
        console.print(Text("This session has no model selection; it uses the configured model.", style="dim"))
        return 0
    set_model_selection(session, selection)
    store.update_session(session)
    if selection is None:
        console.print(Text("Session model cleared; the next turn uses the configured model.", style="bold"))
    else:
        effort = f" (effort {selection.reasoning_effort})" if selection.reasoning_effort else ""
        console.print(Text(
            f"Session model: {selection.provider} / {selection.model}{effort}; applies from the next turn.",
            style="bold",
        ))
    return 0


def cmd_model(ctx: Any = None, *args: str) -> int:
    """Show model configuration or change the current session's selection.

    Args:
        ctx: Optional interactive context from which to resolve the session.
        *args: Empty to show configuration, or tokens for set <provider> <model> [effort] or clear.

    Returns:
        Zero after displaying configuration, or the exit status of the requested session change.
    """
    if args:
        return _change_session_model(ctx, args)
    console = _resolve_console()
    try:
        from cli.commands.providers import _show_settings

        _show_settings()
    except Exception as exc:  # noqa: BLE001 — legacy may be absent on partial install
        from src.config.accessor import get_env_config

        cfg = get_env_config()
        provider = cfg.llm.langchain_provider or "(not set)"
        model = cfg.llm.langchain_model_name or "(not set)"
        console.print(Text(f"Provider: {provider}", style="bold"))
        console.print(Text(f"Model:    {model}", style="bold"))
        console.print(Text(f"(legacy _show_settings unavailable: {exc})", style="dim"))

    try:
        from src.session.model_selection import effective_model_selection

        _store, session = _current_session(ctx, create=False)
        effective = effective_model_selection(session) if session is not None else None
    except Exception as exc:  # noqa: BLE001 — showing the config must not fail on the store
        effective = {"source": "session", "error": str(exc)}
    if effective and effective["source"] == "session":
        console.print()
        detail = effective.get("error") or (
            f"{effective['provider']} / {effective['model']}"
            + (f" (effort {effective['reasoning_effort']})" if effective["reasoning_effort"] else "")
        )
        console.print(Text(f"This session: {detail}", style="bold"))

    console.print()
    console.print(
        Text(
            "Run `vibe-trading init` to switch provider, model, or credentials; "
            f"for this session only: {_MODEL_USAGE}",
            style="dim",
        )
    )
    return 0


def cmd_compact(ctx: Any = None, *args: str) -> int:
    """Compact the active session, optionally prioritising a focus topic.

    Args:
        ctx: Interactive context supplying the active session ID.
        *args: Optional focus words joined into a topic for compaction.

    Returns:
        Zero on success, or one if no session is active or compaction fails.
    """
    console = _resolve_console()
    session_id = getattr(ctx, "session_id", None)
    if not session_id:
        console.print(Text("Start or resume a session before using /compact.", style="bold red"))
        return 1
    try:
        import asyncio
        from src.session.events import EventBus
        from src.session.service import SessionService
        from src.config.paths import get_runs_dir
        from cli.main import _session_store

        store = _session_store()
        result = asyncio.run(
            SessionService(
                policy=ToolPolicy.from_config(get_env_config()),
                store=store, event_bus=EventBus(), runs_dir=get_runs_dir(),
            )
            .compact_session(session_id, " ".join(args))
        )
    except Exception as exc:  # noqa: BLE001 - keep the REPL alive on refusal
        console.print(Text(f"/compact failed: {exc}", style="bold red"))
        return 1
    console.print(Text("Session context compacted.", style="bold"))
    if result.get("summary"):
        console.print(Text(str(result["summary"]), style="dim"))
    return 0


# /clear, /journal, /shadow, /swarm, /debug, /quit


def cmd_clear(ctx: Any = None, *args: str) -> int:  # noqa: ARG001
    """Clear the screen and start a fresh conversation.

    Args:
        ctx: Optional interactive context whose transcript and session ID are cleared if available.
        *args: Unused slash-command arguments.

    Returns:
        Zero after the screen and session reset attempts.
    """
    console = _resolve_console()
    try:
        console.clear()
    except Exception:  # noqa: BLE001 — clear can fail on dumb terminals
        pass
    # Reuse startup stats so the redrawn banner shows the current counts.
    try:
        from cli.intro import print_banner
        from cli.main import _collect_banner_stats

        print_banner(console, **_collect_banner_stats())
    except Exception:  # noqa: BLE001
        console.print(Text("Conversation cleared.", style="dim"))
    # Start a fresh session so clearing the screen also clears model history.
    if ctx is not None:
        try:
            if hasattr(ctx, "transcript"):
                ctx.transcript.clear()
            if hasattr(ctx, "session_id"):
                ctx.session_id = None
        except Exception:  # noqa: BLE001
            pass
    return 0


def _queue_prompt(ctx: Any, prompt: str) -> bool:
    """Stash ``prompt`` on ``ctx.pending_prompt`` for the loop to consume."""
    if ctx is None or not hasattr(ctx, "pending_prompt"):
        return False
    try:
        ctx.pending_prompt = prompt
        return True
    except Exception:  # noqa: BLE001 — never crash the slash dispatch
        return False


def cmd_journal(ctx: Any = None, *args: str) -> int:
    """Queue an agent turn to analyze a trade journal.

    Args:
        ctx: Optional interactive context accepting a pending prompt.
        *args: Journal CSV path tokens, joined with spaces. Empty input prints usage.

    Returns:
        Zero after queuing a prompt or printing instructions.
    """
    console = _resolve_console()
    path = " ".join(args).strip()
    if not path:
        body = Text()
        body.append("Usage: ", style="dim")
        body.append("/journal <path-to-csv>\n", style="bold")
        body.append("Example: ", style="dim")
        body.append('/journal ~/Downloads/journal.csv\n\n', style="bold")
        body.append("Or type the prompt directly: ", style="dim")
        body.append('"analyze my trade journal at <path>"', style="bold")
        console.print(Panel(body, title="/journal", border_style="dim", padding=(1, 2)))
        return 0

    prompt = f"Analyze my trade journal at {path}"
    if _queue_prompt(ctx, prompt):
        console.print(Text(f"→ Running: {prompt}", style="dim"))
        return 0
    # Fallback when the context does not support queuing (legacy callers).
    console.print(Text(f'Type: "{prompt}"', style="bold"))
    return 0


def cmd_shadow(ctx: Any = None, *args: str) -> int:
    """Queue a Shadow Account agent turn.

    Args:
        ctx: Optional interactive context accepting a pending prompt.
        *args: Optional trade-journal path tokens. With no path, the prompt requests the latest
            dashboard report.

    Returns:
        Zero after queuing or printing the prompt.
    """
    console = _resolve_console()
    path = " ".join(args).strip()
    if path:
        prompt = f"Train a shadow account from my trade journal at {path}"
    else:
        prompt = "Open the shadow account dashboard and show the latest report"

    if _queue_prompt(ctx, prompt):
        console.print(Text(f"→ Running: {prompt}", style="dim"))
        return 0
    console.print(Text(f'Type: "{prompt}"', style="bold"))
    return 0


def cmd_swarm(ctx: Any = None, *args: str) -> int:  # noqa: ARG001
    """Dispatch to the canonical swarm slash command module.

    Args:
        ctx: Unused interactive context.
        *args: Swarm subcommand and arguments joined into a command line.

    Returns:
        Swarm handler's exit status, or one if dispatch raises an exception.
    """
    try:
        from cli.commands.swarm import dispatch

        return dispatch(" ".join(args))
    except Exception as exc:  # noqa: BLE001
        console = _resolve_console()
        console.print(Text(f"/swarm failed: {exc}", style="bold red"))
        return 1


def cmd_debug(ctx: Any = None, *args: str) -> int:  # noqa: ARG001
    """Toggle the debug summary that prints after each agent turn.

    Args:
        ctx: Interactive context holding the debug flag, if supported.
        *args: Unused slash-command arguments.

    Returns:
        Zero after toggling or printing a configuration hint, or one if the toggle fails.
    """
    console = _resolve_console()
    if ctx is not None and hasattr(ctx, "debug"):
        try:
            ctx.debug = not bool(getattr(ctx, "debug", False))
            state = "ON" if ctx.debug else "OFF"
            console.print(Text(f"Debug summary: {state}", style="bold"))
            if ctx.debug:
                console.print(
                    Text(
                        "After each turn a one-line summary will print: "
                        "iterations, tool count, elapsed, token usage.",
                        style="dim",
                    )
                )
            return 0
        except Exception as exc:  # noqa: BLE001
            console.print(Text(f"/debug toggle failed: {exc}", style="bold red"))
            return 1
    return _coming_soon(
        "debug",
        hint="set `VIBE_TRADING_DEBUG=1` and restart for verbose logging.",
    )


def cmd_quit(ctx: Any = None, *args: str) -> int:  # noqa: ARG001
    """Signal exit by returning a distinct exit code.

    Args:
        ctx: Unused interactive context.
        *args: Unused slash-command arguments.

    Returns:
        Two, which tells the interactive caller to exit.
    """
    return 2


# Module-level dispatch table

_DISPATCH = {
    "model": cmd_model,
    "compact": cmd_compact,
    "clear": cmd_clear,
    "journal": cmd_journal,
    "shadow": cmd_shadow,
    "swarm": cmd_swarm,
    "debug": cmd_debug,
    "quit": cmd_quit,
}


def run(ctx: Any = None, command: str = "model", *args: str) -> int:
    """Dispatch a chat slash command.

    Args:
        ctx: Interactive context passed to the handler.
        command: Command name without the leading slash.
        *args: Arguments passed to the handler.

    Returns:
        Handler exit status, or one for an unknown command.
    """
    handler = _DISPATCH.get(command)
    if handler is None:
        console = _resolve_console()
        console.print(Text(f"Unknown chat command: /{command}", style="bold red"))
        return 1
    return handler(ctx, *args)


__all__ = [
    "run",
    "cmd_model",
    "cmd_compact",
    "cmd_clear",
    "cmd_journal",
    "cmd_shadow",
    "cmd_swarm",
    "cmd_debug",
    "cmd_quit",
]
