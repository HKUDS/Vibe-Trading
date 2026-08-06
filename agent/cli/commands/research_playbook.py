"""User-facing entry points for the scheduled-research playbook catalogue.

The catalogue itself lives in :mod:`src.scheduled_research.playbooks` (markdown
templates with a YAML frontmatter header). Until this module existed the only
way to reach it was a Python import, so a shipped template was effectively
invisible. This module is the single place both non-interactive and interactive
users enter through:

* ``vibe-trading playbook list | show <slug> | create <slug>`` — the argparse
  subcommand, wired in :mod:`cli._legacy` next to ``alpha`` / ``hypothesis``.
* ``/playbook`` — the REPL slash command, registered in
  :mod:`cli.commands.slash_router`, dispatched through ``run(ctx, *args)``.

Two properties this layer is built to preserve:

* **The body is never rewritten.** A template states the data it needs in plain
  language and deliberately names no tool; routing is the agent's job. Both
  ``/playbook run`` and ``playbook create`` hand over
  ``ResearchPlaybook.render()`` output verbatim, so the text executed
  interactively is byte-identical to the ``prompt`` the scheduler later
  replays. Nothing here appends tool names, hints, or a preamble.
* **The schedule is validated by the scheduler's own rules.**
  ``ResearchPlaybook.to_job`` calls
  :func:`src.scheduled_research.models.validate_schedule` and
  ``validate_timezone``; this module only catches the resulting ``ValueError``
  and prints it. There is no second, drifting copy of the grammar here.

``playbook create`` writes straight to
:class:`src.scheduled_research.store.ScheduledResearchJobStore` — the same file
the API server and the executor read. It deliberately does not go through HTTP:
the store is a file under the user's own runtime root, so a local CLI writing it
carries exactly the trust of the shell that launched it, and requiring a running
server to schedule a job would be a worse experience with no security gain. The
HTTP surface for the same operation stays behind ``require_auth``.

Not to be confused with :mod:`cli.commands.institutional.playbooks`, which holds
the one-shot ``/comps`` / ``/dcf`` workflow cards. These are recurring research
templates for the scheduler.
"""

from __future__ import annotations

import argparse
import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

_HELP_TOKENS = frozenset({"help", "-h", "--help", "?"})
_LIST_TOKENS = frozenset({"list", "ls", "all"})
_VAR_TOKEN_RE = re.compile(r"^([A-Za-z0-9_]+)=(.*)$")

# Defensive ceilings. ``ResearchPlaybook.render`` already caps a single
# substituted value at 4000 chars; these bound the *number* of tokens and the
# raw argument string so a paste accident cannot make the CLI do silly work
# before that cap is reached.
_MAX_VARIABLES = 32
_MAX_ARG_CHARS = 20000

# "Caller did not override the timezone", distinct from an explicit ``None``
# (which means UTC and is a legitimate override of a template's suggestion).
_KEEP_TZ = object()


def _console() -> Any:
    """Return the shared CLI console."""
    from cli.theme import get_console

    return get_console()


def _print(message: str) -> None:
    """Print one line through the shared console."""
    _console().print(message)


# ---------------------------------------------------------------------------
# Argument parsing helpers
# ---------------------------------------------------------------------------


def parse_variable_tokens(tokens: Sequence[str]) -> Tuple[Dict[str, str], Optional[str]]:
    """Parse ``key=value`` tokens, allowing unquoted multi-word values.

    A token that does not look like ``key=`` continues the value of the
    previous key, so ``home_market=US equities`` works without shell quoting in
    the REPL. The first token must open a key.

    Args:
        tokens: Raw whitespace-split arguments.

    Returns:
        A ``(variables, error)`` pair. ``error`` is ``None`` on success and a
        user-facing message otherwise; ``variables`` is empty when it is set.
    """
    variables: Dict[str, str] = {}
    order: List[str] = []
    current: Optional[str] = None
    for token in tokens:
        match = _VAR_TOKEN_RE.match(token)
        if match is not None:
            current = match.group(1)
            if current not in variables:
                order.append(current)
            variables[current] = match.group(2)
            continue
        if current is None:
            return {}, f"expected key=value, got {token!r}"
        variables[current] = f"{variables[current]} {token}".strip()
    if len(order) > _MAX_VARIABLES:
        return {}, f"too many variables ({len(order)}); the cap is {_MAX_VARIABLES}"
    return variables, None


def _parse_var_options(raw: Sequence[str]) -> Tuple[Dict[str, str], Optional[str]]:
    """Parse repeated ``--var key=value`` options.

    Unlike :func:`parse_variable_tokens` each option carries one whole
    assignment, because the shell already did the quoting.
    """
    variables: Dict[str, str] = {}
    for item in raw:
        match = _VAR_TOKEN_RE.match(item)
        if match is None:
            return {}, f"--var expects key=value, got {item!r}"
        variables[match.group(1)] = match.group(2)
    if len(variables) > _MAX_VARIABLES:
        return {}, f"too many --var options ({len(variables)}); the cap is {_MAX_VARIABLES}"
    return variables, None


# ---------------------------------------------------------------------------
# Catalogue access
# ---------------------------------------------------------------------------


def _load_catalogue() -> Tuple[List[Any], Optional[str]]:
    """Load every playbook, converting a parse failure into a message.

    Returns:
        A ``(playbooks, error)`` pair. A malformed file is surfaced rather than
        skipped, matching ``list_playbooks``.
    """
    from src.scheduled_research.playbooks import PlaybookError, list_playbooks

    try:
        return list_playbooks(), None
    except (PlaybookError, OSError) as exc:
        return [], str(exc)


def _load_one(slug: str) -> Tuple[Optional[Any], Optional[str]]:
    """Load a single playbook by slug, converting failures into a message."""
    from src.scheduled_research.playbooks import PlaybookError, get_playbook

    try:
        return get_playbook(slug), None
    except (PlaybookError, OSError) as exc:
        return None, str(exc)


def build_job_from_playbook(
    slug: str,
    *,
    schedule: Optional[str] = None,
    timezone: Any = _KEEP_TZ,
    variables: Optional[Dict[str, str]] = None,
    job_id: Optional[str] = None,
) -> Tuple[Optional[Any], Optional[str]]:
    """Build (but do not persist) a scheduled job from a template.

    Every validation rule — schedule grammar, timezone resolution, declared
    variable names, the cron search window — belongs to
    ``ResearchPlaybook.to_job``; this only translates the exception into a
    printable message.

    Args:
        slug: Template slug.
        schedule: Schedule override, or ``None`` to keep the suggestion.
        timezone: Timezone override. Leave at the sentinel to keep the
            template's suggestion; pass ``None`` to force UTC.
        variables: Placeholder overrides.
        job_id: Explicit job id, or ``None`` for a generated one.

    Returns:
        A ``(job, error)`` pair; exactly one side is populated.
    """
    from src.scheduled_research.playbooks import build_job

    kwargs: Dict[str, Any] = {"variables": variables or {}}
    if schedule is not None:
        kwargs["schedule"] = schedule
    if timezone is not _KEEP_TZ:
        kwargs["timezone"] = timezone
    if job_id:
        kwargs["job_id"] = job_id
    try:
        return build_job(slug, **kwargs), None
    except (ValueError, OSError) as exc:
        # PlaybookError and PlaybookNotFoundError both subclass ValueError.
        return None, str(exc)


def _persist(job: Any) -> Optional[str]:
    """Upsert ``job`` into the shared store. Returns an error message or None."""
    from src.scheduled_research.store import ScheduledResearchJobStore

    try:
        ScheduledResearchJobStore().upsert(job)
    except Exception as exc:  # noqa: BLE001 — surfaced as one line, never a traceback
        return f"{type(exc).__name__}: {exc}"
    return None


def _scheduler_enabled() -> bool:
    """Return whether the background executor is switched on for this install."""
    try:
        from src.config.accessor import get_env_config

        return bool(get_env_config().agent_tuning.vibe_trading_enable_scheduler)
    except Exception:  # noqa: BLE001 — a config problem must not break the print
        return False


def _schedule_note(job: Any) -> str:
    """Return the one-line caveat printed after a job is stored."""
    if _scheduler_enabled():
        return "The scheduler is enabled; the API server will fire this job."
    return (
        "The scheduler is OFF — set VIBE_TRADING_ENABLE_SCHEDULER=1 and run "
        "`vibe-trading serve` for stored jobs to fire."
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _describe_schedule(schedule: str, tz: Optional[str]) -> str:
    """Return a human-readable form of a stored schedule string."""
    if schedule.isdigit():
        seconds = int(schedule) / 1000
        if seconds >= 3600:
            return f"every {seconds / 3600:g}h"
        if seconds >= 60:
            return f"every {seconds / 60:g}m"
        return f"every {seconds:g}s"
    return f"cron {schedule} ({tz or 'UTC'})"


def _render_catalogue(playbooks: Sequence[Any]) -> None:
    """Print the template catalogue as a table."""
    from rich.table import Table

    console = _console()
    if not playbooks:
        console.print("[dim]No research playbooks found.[/dim]")
        return

    table = Table(title="Scheduled research playbooks", title_style="bold", box=None, pad_edge=False)
    table.add_column("slug", style="cyan", no_wrap=True)
    table.add_column("cadence", style="dim", no_wrap=True)
    table.add_column("markets", style="dim", no_wrap=True)
    table.add_column("what it produces", overflow="fold")
    for playbook in playbooks:
        table.add_row(
            playbook.slug,
            _describe_schedule(playbook.suggested_schedule, playbook.suggested_timezone),
            ",".join(playbook.markets),
            playbook.description,
        )
    console.print(table)


def _render_card(playbook: Any, variables: Optional[Dict[str, str]] = None) -> bool:
    """Print one template: metadata, declared variables and the full body.

    Returns:
        ``True`` when the card was printed, ``False`` when substitution failed
        (the error is printed instead). Callers must propagate the failure into
        their exit code rather than reporting success on an empty card.
    """
    from rich.panel import Panel
    from rich.text import Text

    console = _console()
    header = Text()
    header.append(playbook.description + "\n\n")
    header.append("Cadence  ", style="dim")
    header.append(
        _describe_schedule(playbook.suggested_schedule, playbook.suggested_timezone) + "\n"
    )
    header.append("Markets  ", style="dim")
    header.append(", ".join(playbook.markets) + "\n\n")
    header.append("Data it needs\n", style="bold")
    for capability in playbook.data_capabilities:
        header.append(f"  - {capability}\n", style="dim")
    if playbook.variables:
        header.append("\nVariables\n", style="bold")
        for key, default in sorted(playbook.variables.items()):
            header.append(f"  {key}", style="cyan")
            header.append(f" = {default}\n", style="dim")

    try:
        body = playbook.render(variables)
    except ValueError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        return False

    console.print(
        Panel(
            header,
            title=f"{playbook.slug} — {playbook.name}",
            border_style="cyan",
            padding=(1, 2),
        )
    )
    console.print(Text(body, style="dim"))
    return True


def _job_summary(job: Any, slug: str) -> str:
    """Return the confirmation line printed after a job is created."""
    import datetime as _dt

    when = _dt.datetime.fromtimestamp(job.next_run_at / 1000, _dt.timezone.utc)
    return (
        f"Scheduled [cyan]{slug}[/cyan] as [bold]{job.id}[/bold] — "
        f"{_describe_schedule(job.schedule, job.timezone)}, "
        f"first run {when.strftime('%Y-%m-%d %H:%M')}Z"
    )


# ---------------------------------------------------------------------------
# Slash command: /playbook
# ---------------------------------------------------------------------------


def _queue_prompt(ctx: Any, prompt: str) -> bool:
    """Stash ``prompt`` on ``ctx.pending_prompt`` for the REPL loop to run."""
    if ctx is None or not hasattr(ctx, "pending_prompt"):
        return False
    try:
        ctx.pending_prompt = prompt
        return True
    except Exception:  # noqa: BLE001 — a stub context must not kill the REPL
        return False


def _slash_usage() -> None:
    """Print the ``/playbook`` usage block.

    The ``\\[k=v ...]`` hints are backslash-escaped: rich treats a bare
    ``[k=v ...]`` as a markup tag and silently drops it, which would hide the
    variable syntax — the one thing this help text exists to teach.
    """
    console = _console()
    console.print("[bold]/playbook[/bold] — scheduled research templates")
    console.print("  [cyan]/playbook[/cyan]                            list the templates")
    console.print("  [cyan]/playbook <slug>[/cyan]                     show one in full")
    console.print("  [cyan]/playbook run <slug> \\[k=v ...][/cyan]       run it now in this session")
    console.print("  [cyan]/playbook schedule <slug> \\[k=v ...][/cyan]  store it on its suggested cadence")


def run(ctx: Any = None, *args: str) -> int:
    """Handle a ``/playbook`` slash command line.

    Args:
        ctx: Interactive context supplying ``pending_prompt``. When it cannot
            hold a queued prompt (a test stub, a non-interactive caller) the
            prompt is printed so it can be pasted.
        *args: Raw slash-command arguments.

    Returns:
        ``0`` on every user-facing path, including "unknown slug" — a mistyped
        template is answered with the catalogue, not an error exit code.
    """
    console = _console()
    tokens = [token for token in args if token]

    if tokens and tokens[0].lower() in _HELP_TOKENS:
        _slash_usage()
        return 0

    if not tokens or tokens[0].lower() in _LIST_TOKENS:
        playbooks, error = _load_catalogue()
        if error:
            console.print(f"[bold red]{error}[/bold red]")
            return 0
        _render_catalogue(playbooks)
        console.print(
            "[dim]/playbook run <slug> to run one now, "
            "/playbook schedule <slug> to put it on a cadence.[/dim]"
        )
        return 0

    action = tokens[0].lower()
    if action in {"run", "schedule", "show"}:
        slug, rest = (tokens[1] if len(tokens) > 1 else ""), tokens[2:]
    else:
        action, slug, rest = "show", tokens[0], tokens[1:]

    if not slug:
        console.print(f"[bold red]/playbook {action} needs a template slug.[/bold red]")
        _slash_usage()
        return 0

    if sum(len(token) + 1 for token in rest) > _MAX_ARG_CHARS:
        console.print(f"[bold red]Arguments exceed {_MAX_ARG_CHARS} characters.[/bold red]")
        return 0

    variables, var_error = parse_variable_tokens(rest)
    if var_error:
        console.print(f"[bold red]{var_error}[/bold red]")
        return 0

    playbook, load_error = _load_one(slug)
    if playbook is None:
        console.print(f"[bold red]{load_error}[/bold red]")
        return 0

    if action == "show":
        _render_card(playbook, variables)
        return 0

    if action == "run":
        try:
            prompt = playbook.render(variables)
        except ValueError as exc:
            console.print(f"[bold red]{exc}[/bold red]")
            return 0
        if _queue_prompt(ctx, prompt):
            console.print(f"[dim]→ Running the {playbook.slug} playbook now.[/dim]")
            return 0
        console.print(f"[bold]{playbook.slug} — paste this prompt to run it:[/bold]")
        console.print(prompt)
        return 0

    job, build_error = build_job_from_playbook(slug, variables=variables)
    if job is None:
        console.print(f"[bold red]{build_error}[/bold red]")
        return 0
    store_error = _persist(job)
    if store_error:
        console.print(f"[bold red]{store_error}[/bold red]")
        return 0
    console.print(_job_summary(job, slug))
    console.print(f"[dim]{_schedule_note(job)}[/dim]")
    return 0


# ---------------------------------------------------------------------------
# argparse subcommand: vibe-trading playbook ...
# ---------------------------------------------------------------------------

_PLAYBOOK_PARSER: Optional[argparse.ArgumentParser] = None


def add_subparser(subparsers: Any) -> argparse.ArgumentParser:
    """Register ``playbook`` and its sub-subcommands on the parent subparsers.

    Args:
        subparsers: The object returned by ``ArgumentParser.add_subparsers``.

    Returns:
        The ``playbook`` parser, for test introspection.
    """
    global _PLAYBOOK_PARSER

    parser = subparsers.add_parser(
        "playbook",
        help="Scheduled research templates: list / show / create",
    )
    sub = parser.add_subparsers(dest="playbook_command")

    p_list = sub.add_parser("list", help="List the available research templates")
    p_list.add_argument(
        "--json", dest="playbook_json", action="store_true", help="Emit JSON instead of a table"
    )

    p_show = sub.add_parser("show", help="Show one template, including its full body")
    p_show.add_argument("slug", help="Template slug, e.g. premarket-brief")
    p_show.add_argument(
        "--var",
        dest="playbook_vars",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Substitute a declared variable in the previewed body (repeatable)",
    )
    p_show.add_argument(
        "--json", dest="playbook_json", action="store_true", help="Emit JSON instead of a card"
    )

    p_create = sub.add_parser("create", help="Create a scheduled job from a template")
    p_create.add_argument("slug", help="Template slug, e.g. premarket-brief")
    p_create.add_argument(
        "--schedule",
        dest="playbook_schedule",
        default=None,
        help="Override the suggested cadence: interval milliseconds or a 5-field cron string",
    )
    p_create.add_argument(
        "--timezone",
        dest="playbook_timezone",
        default=None,
        help="Override the suggested IANA timezone the cron schedule is read in",
    )
    p_create.add_argument(
        "--utc",
        dest="playbook_utc",
        action="store_true",
        help="Force UTC, dropping the template's suggested timezone",
    )
    p_create.add_argument(
        "--var",
        dest="playbook_vars",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Set a declared template variable (repeatable)",
    )
    p_create.add_argument("--id", dest="playbook_id", default=None, help="Explicit job id")
    p_create.add_argument(
        "--dry-run",
        dest="playbook_dry_run",
        action="store_true",
        help="Print the job that would be stored without persisting it",
    )
    p_create.add_argument(
        "--json", dest="playbook_json", action="store_true", help="Emit JSON instead of a summary"
    )

    _PLAYBOOK_PARSER = parser
    return parser


def _cmd_list(args: argparse.Namespace) -> int:
    """Handle ``vibe-trading playbook list``."""
    playbooks, error = _load_catalogue()
    if error:
        _print(f"[bold red]{error}[/bold red]")
        return 1
    if getattr(args, "playbook_json", False):
        print(json.dumps([p.to_dict() for p in playbooks], indent=2, ensure_ascii=False))
        return 0
    _render_catalogue(playbooks)
    _print("[dim]vibe-trading playbook show <slug> for the full text.[/dim]")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    """Handle ``vibe-trading playbook show <slug>``."""
    variables, var_error = _parse_var_options(getattr(args, "playbook_vars", []) or [])
    if var_error:
        _print(f"[bold red]{var_error}[/bold red]")
        return 2
    playbook, load_error = _load_one(args.slug)
    if playbook is None:
        _print(f"[bold red]{load_error}[/bold red]")
        return 1
    if getattr(args, "playbook_json", False):
        try:
            body = playbook.render(variables)
        except ValueError as exc:
            _print(f"[bold red]{exc}[/bold red]")
            return 2
        payload = playbook.to_dict()
        payload["body"] = body
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    # Same failure, same exit code as the --json branch above: a bad --var is a
    # usage error whichever output format was asked for.
    return 0 if _render_card(playbook, variables) else 2


def _cmd_create(args: argparse.Namespace) -> int:
    """Handle ``vibe-trading playbook create <slug>``."""
    variables, var_error = _parse_var_options(getattr(args, "playbook_vars", []) or [])
    if var_error:
        _print(f"[bold red]{var_error}[/bold red]")
        return 2

    timezone: Any = _KEEP_TZ
    if getattr(args, "playbook_utc", False):
        if getattr(args, "playbook_timezone", None):
            _print("[bold red]--utc and --timezone are mutually exclusive.[/bold red]")
            return 2
        timezone = None
    elif getattr(args, "playbook_timezone", None):
        timezone = args.playbook_timezone

    job, build_error = build_job_from_playbook(
        args.slug,
        schedule=getattr(args, "playbook_schedule", None),
        timezone=timezone,
        variables=variables,
        job_id=getattr(args, "playbook_id", None),
    )
    if job is None:
        _print(f"[bold red]{build_error}[/bold red]")
        return 1

    dry_run = getattr(args, "playbook_dry_run", False)
    if not dry_run:
        store_error = _persist(job)
        if store_error:
            _print(f"[bold red]{store_error}[/bold red]")
            return 1

    if getattr(args, "playbook_json", False):
        payload = job.to_dict()
        payload["dry_run"] = dry_run
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if dry_run:
        _print(f"[dim]Dry run — nothing stored.[/dim] {_job_summary(job, args.slug)}")
        _print(f"[dim]{job.prompt}[/dim]")
        return 0
    _print(_job_summary(job, args.slug))
    _print(f"[dim]{_schedule_note(job)}[/dim]")
    return 0


_DISPATCH = {
    "list": _cmd_list,
    "show": _cmd_show,
    "create": _cmd_create,
}


def dispatch(args: argparse.Namespace) -> int:
    """Dispatch ``playbook <sub>`` to its handler.

    Returns:
        A process exit code: ``0`` on success, ``1`` on a failed operation,
        ``2`` on a usage error.
    """
    sub = getattr(args, "playbook_command", None)
    handler = _DISPATCH.get(sub or "")
    if handler is None:
        if _PLAYBOOK_PARSER is not None:
            _PLAYBOOK_PARSER.print_help()
        else:
            _print(
                "[red]playbook requires a subcommand.[/red] "
                "Try: vibe-trading playbook list"
            )
        return 2
    return int(handler(args))


__all__ = [
    "add_subparser",
    "build_job_from_playbook",
    "dispatch",
    "parse_variable_tokens",
    "run",
]
