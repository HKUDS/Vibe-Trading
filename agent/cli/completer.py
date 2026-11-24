"""FuzzyCompleter for slash commands."""

from __future__ import annotations

from typing import Iterable

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import FormattedText

from .commands.slash_router import SLASH_COMMANDS, Command, match_commands


def _primary_style() -> str:
    """Resolve the brand-orange ``style`` string for prompt_toolkit."""
    try:
        from cli.theme import Theme

        brand = getattr(Theme, "brand_hex", None)
        if isinstance(brand, str) and brand:
            return f"fg:{brand} bold"
    except Exception:  # noqa: BLE001 — never block typeahead on theme import
        pass
    # Fallback approximates brand orange in 256-color terminals.
    return "fg:#d97706 bold"


def _muted_style() -> str:
    """Resolve the muted ``style`` string for prompt_toolkit descriptions."""
    return "fg:#9ca3af"


class SlashCompleter(Completer):
    """prompt_toolkit completer that fuzzy-matches the slash registry."""

    def __init__(self, commands: Iterable[Command] = SLASH_COMMANDS) -> None:
        # Snapshot the registry; commands is a tuple of frozen dataclasses
        # so the snapshot itself is effectively immutable.
        self._commands = tuple(commands)

    # API
    def get_completions(
        self,
        document: Document,
        complete_event: CompleteEvent,
    ) -> Iterable[Completion]:
        text = document.text_before_cursor
        stripped = text.lstrip()

        if not stripped.startswith("/"):
            return
        # Find the slash position (the leading whitespace is irrelevant once
        # we have confirmed it leads with ``/``).
        slash_idx = text.index("/")
        token_zone = text[slash_idx + 1 :]
        if " " in token_zone or "\t" in token_zone:
            return

        matches = match_commands(stripped)
        if not matches:
            return

        # Compute the replacement window so the chosen completion overwrites
        # whatever the user typed after ``/``.
        start_position = -len(token_zone)

        # Right-pad each command name so the description column lines up.
        name_width = max((len(c.name) for c in matches), default=0) + 2

        primary = _primary_style()
        muted = _muted_style()

        for cmd in matches:
            padded_name = cmd.name.ljust(name_width)
            display: FormattedText = FormattedText(
                [
                    (primary, f"/{padded_name}"),
                    (muted, cmd.description),
                ]
            )
            # ``text`` is the value inserted on accept (no leading slash —
            # the slash is already in the buffer at ``slash_idx``).
            yield Completion(
                text=cmd.name,
                start_position=start_position,
                display=display,
                display_meta=cmd.description,
            )


__all__ = ["SlashCompleter"]
