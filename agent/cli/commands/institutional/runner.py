"""Shared rendering and dispatch for the institutional workflow commands."""

from __future__ import annotations

from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.config.accessor import get_env_config

from .playbooks import GAP_POLICY, NOT_ADVICE, PLAYBOOKS_BY_SLUG, Playbook

# Bound free text before queuing it, with a config default that keeps malformed overrides from breaking REPL imports.
def _arg_max_chars() -> int:
    """Resolve the argument length cap, ignoring a malformed override."""
    return max(32, get_env_config().agent_tuning.vibe_trading_slash_arg_max)


_ARG_MAX_CHARS = _arg_max_chars()

_HELP_TOKENS = frozenset({"help", "-h", "--help", "?"})


def _console() -> Console:
    """Return the shared CLI console."""
    from cli.theme import get_console

    return get_console()


def _render_card(playbook: Playbook) -> None:
    """Print the full playbook card for ``playbook``."""
    header = Text()
    header.append(playbook.objective + "\n\n")
    header.append("Usage  ", style="dim")
    header.append(playbook.usage + "\n", style="bold")
    for example in playbook.examples:
        header.append("       ")
        header.append(example + "\n", style="cyan")
    header.append("\nExecution skeleton", style="bold")

    steps = Table.grid(padding=(0, 1))
    steps.add_column(style="dim", no_wrap=True, justify="right", width=9)
    steps.add_column(ratio=1, overflow="fold")
    for index, step in enumerate(playbook.steps, start=1):
        steps.add_row(f"{index}.", Text(step.title, style="bold"))
        steps.add_row("in", Text(step.inputs, style="dim"))
        steps.add_row("compute", Text(step.compute, style="dim"))
        steps.add_row("out", Text(step.output, style="dim"))
        steps.add_row("", "")

    example_block = Text()
    example_block.append("Worked example\n", style="bold")
    for line in playbook.worked_example:
        example_block.append(f"  {line}\n", style="dim")
    example_block.append("\nTools  ", style="dim")
    example_block.append(", ".join(playbook.tools) + "\n\n", style="cyan")
    example_block.append("Missing data\n", style="bold")
    for line in GAP_POLICY:
        example_block.append(f"  {line}\n", style="dim")
    example_block.append("\n")
    example_block.append(NOT_ADVICE + "\n\n", style="yellow")
    example_block.append(playbook.ask, style="bold")

    _console().print(
        Panel(
            Group(header, steps, example_block),
            title=f"/{playbook.slug}",
            border_style="cyan",
            padding=(1, 2),
        )
    )


def build_prompt(playbook: Playbook, subject: str) -> str:
    """Render ``playbook`` plus the user's arguments into an agent prompt."""
    lines = [
        f"Run the {playbook.slug.upper()} research playbook.",
        "",
        f"Request: {subject}",
        "",
        f"Deliverable: {playbook.objective}",
        "",
        "Work through these steps in order. Do not skip a step, do not reorder them,",
        "and show the intermediate artifact each step is required to produce.",
        "",
    ]
    for index, step in enumerate(playbook.steps, start=1):
        lines.append(f"Step {index} — {step.title}")
        lines.append(f"  Inputs:  {step.inputs}")
        lines.append(f"  Compute: {step.compute}")
        lines.append(f"  Output:  {step.output}")
        lines.append("")

    lines.append("Worked example — reproduce this level of arithmetic explicitness with")
    lines.append("the real retrieved data. The figures below are illustrative teaching")
    lines.append("numbers, not data about any real security, and must not be reused as facts.")
    lines.extend(f"  {line}" for line in playbook.worked_example)
    lines.append("")

    lines.append(f"Preferred tools: {', '.join(playbook.tools)}.")
    # Report key-gated tools as gaps when unavailable so the model does not substitute remembered figures.
    lines.append(
        "Any preferred tool that is not registered in this session is simply "
        "unavailable — skip it, record what it would have supplied as a gap under "
        "the missing-data policy below, and never fill that gap from memory."
    )
    lines.append("")
    lines.append("Missing data:")
    lines.extend(f"  {line}" for line in GAP_POLICY)
    lines.append("")
    lines.append(NOT_ADVICE)
    return "\n".join(lines)


def run_playbook(slug: str, ctx: Any = None, *args: str) -> int:
    """Render or dispatch the playbook registered under ``slug``."""
    playbook = PLAYBOOKS_BY_SLUG.get(slug)
    if playbook is None:
        _console().print(Text(f"Unknown research playbook: {slug}", style="bold red"))
        return 1

    if args and args[0].lower() in _HELP_TOKENS:
        _render_card(playbook)
        return 0

    subject = " ".join(args).strip()
    if not subject:
        _render_card(playbook)
        return 0
    if len(subject) > _ARG_MAX_CHARS:
        subject = subject[:_ARG_MAX_CHARS].rstrip() + " …(truncated)"

    prompt = build_prompt(playbook, subject)
    console = _console()
    if ctx is not None and hasattr(ctx, "pending_prompt"):
        try:
            ctx.pending_prompt = prompt
            console.print(
                Text(f"→ Running the /{playbook.slug} playbook on: {subject}", style="dim")
            )
            return 0
        except Exception:  # noqa: BLE001 — never let a slash handler kill the REPL
            pass

    console.print(Text(f"/{playbook.slug} — paste this prompt to run it:", style="bold"))
    console.print(Text(prompt, style="dim"))
    return 0


__all__ = ["build_prompt", "run_playbook"]
