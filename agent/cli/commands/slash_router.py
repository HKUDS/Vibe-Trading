"""Slash command registry + fuzzy matcher."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    """Register a slash command backed by a module exposing run(ctx, *args)."""

    name: str
    description: str
    handler_module: str


# Order here = order shown in bare ``/`` typeahead. Group by frequency so the
# most-used commands surface first (help/model/memory/history are top).
SLASH_COMMANDS: tuple[Command, ...] = (
    Command("help",    "Show keyboard shortcuts and command list",   "cli.commands.help"),
    Command("model",   "Switch LLM provider and model",              "cli.commands.chat"),
    Command("compact", "Summarize the current session context",       "cli.commands.chat"),
    Command("memory",  "Show / manage persistent memory",            "cli.commands.memory"),
    Command("history", "Browse and resume prior sessions",           "cli.commands.session"),
    Command("goal",    "Start / inspect a finance research goal",    "cli.commands.goal"),
    Command("search",  "Full-text search across all sessions",       "cli.commands.session"),
    Command("swarm",   "Multi-agent presets (committee / quant / risk)", "cli.commands.chat"),
    Command("skill",   "List / load / unload skills",                "cli.commands.show"),
    Command("show",    "Show prior run by id",                       "cli.commands.show"),
    Command("clear",   "Clear current conversation",                 "cli.commands.chat"),
    Command("pine",    "Export current strategy as Pine Script",     "cli.commands.show"),
    Command("journal", "Analyze trade journal CSV",                  "cli.commands.chat"),
    Command("shadow",  "Train / view shadow account",                "cli.commands.chat"),
    Command("export",  "Export current session (md / json)",         "cli.commands.session"),
    Command("fork",    "Fork the current session from a turn",        "cli.commands.session"),
    Command("debug",   "Toggle debug panel (token usage / latency)", "cli.commands.chat"),
    Command("quit",    "Exit (also: q, exit, :q)",                   "cli.commands.chat"),
)


# Aliases — same handler, different surface keyword. Keep separate from the
# main registry so typeahead does not duplicate rows.
_ALIASES: dict[str, str] = {
    "q":    "quit",
    "exit": "quit",
    ":q":   "quit",
    "?":    "help",
}


def _register_institutional_slash_commands() -> None:
    """Append the institutional research workflow commands to the registry."""
    from .institutional.playbooks import PLAYBOOKS

    global SLASH_COMMANDS, _ALIASES

    existing = {cmd.name for cmd in SLASH_COMMANDS}
    additions = tuple(
        Command(pb.slug, pb.summary, pb.handler_module)
        for pb in PLAYBOOKS
        if pb.slug not in existing
    )
    if additions:
        commands = list(SLASH_COMMANDS)
        # Sit just above ``quit`` so the exit row stays last.
        quit_idx = next(
            (i for i, c in enumerate(commands) if c.name == "quit"), len(commands)
        )
        commands[quit_idx:quit_idx] = list(additions)
        SLASH_COMMANDS = tuple(commands)

    # Preserve existing command and alias names when registering a new alias.
    registered = {cmd.name for cmd in SLASH_COMMANDS}
    new_aliases = {
        alias: pb.slug
        for pb in PLAYBOOKS
        for alias in pb.aliases
        if alias not in registered and alias not in _ALIASES
    }
    if new_aliases:
        _ALIASES = {**_ALIASES, **new_aliases}


_register_institutional_slash_commands()


def _register_research_playbook_slash_command() -> None:
    """Append ``/playbook`` — the scheduled-research template catalogue."""
    global SLASH_COMMANDS

    if any(cmd.name == "playbook" for cmd in SLASH_COMMANDS):
        return
    commands = list(SLASH_COMMANDS)
    quit_idx = next(
        (i for i, c in enumerate(commands) if c.name == "quit"), len(commands)
    )
    commands.insert(
        quit_idx,
        Command(
            "playbook",
            "Scheduled research templates (list / run / schedule)",
            "cli.commands.research_playbook",
        ),
    )
    SLASH_COMMANDS = tuple(commands)


_register_research_playbook_slash_command()


def _parse_token(input_text: str) -> str:
    """Strip the leading ``/`` and isolate the command token."""
    text = input_text.lstrip()
    if not text.startswith("/"):
        return ""
    # ``/foo bar`` → ``foo``. Use ``split(None, 1)`` to handle any whitespace.
    parts = text[1:].split(None, 1)
    return parts[0] if parts else ""


def _fuzzy_score(needle: str, name: str) -> int:
    """Return a heuristic score for ``needle`` matching ``name``."""
    if not needle:
        return 1  # bare ``/`` shows everything in registry order
    needle_l = needle.lower()
    name_l = name.lower()
    if name_l.startswith(needle_l):
        return 100 + len(needle_l)
    if needle_l in name_l:
        return 50 + len(needle_l)
    # subsequence match: every char of needle appears in order inside name
    j = 0
    for ch in name_l:
        if j < len(needle_l) and ch == needle_l[j]:
            j += 1
    if j == len(needle_l):
        return 10 + j
    return 0


def match_commands(input_text: str) -> list[Command]:
    """Find slash commands that fuzzy-match the input's command token.

    Args:
        input_text: Raw input line, possibly empty. Leading whitespace and trailing arguments are
            ignored.

    Returns:
        New list ordered by best match first with ties broken by registry order. Input without a
        leading slash after trimming has no matches.
    """
    token = _parse_token(input_text)
    if not input_text.lstrip().startswith("/"):
        return []

    # Resolve aliases up front so ``/q`` shows the ``quit`` row.
    if token in _ALIASES:
        token = _ALIASES[token]

    scored: list[tuple[int, int, Command]] = []
    for idx, cmd in enumerate(SLASH_COMMANDS):
        score = _fuzzy_score(token, cmd.name)
        if score > 0:
            # Negative idx so ties prefer earlier registry position when
            # sorted descending by score.
            scored.append((score, -idx, cmd))
    scored.sort(reverse=True)
    return [cmd for _score, _idx, cmd in scored]


def find_exact(name: str) -> Command | None:
    """Resolve an exact command name or alias.

    Args:
        name: Command name or alias, optionally with a leading slash.

    Returns:
        Matching registered command, or None if there is no exact match.
    """
    key = name.lstrip("/").strip()
    key = _ALIASES.get(key, key)
    for cmd in SLASH_COMMANDS:
        if cmd.name == key:
            return cmd
    return None
