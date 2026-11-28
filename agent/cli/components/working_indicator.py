"""Thinking spinner — picks a random verb on entry, hides on exit."""

from __future__ import annotations

import random
from types import TracebackType
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text


_FALLBACK_VERBS: tuple[str, ...] = (
    "Pondering…",
    "Analyzing…",
    "Reasoning…",
    "Thinking…",
    "Investigating…",
)


def _pick_verb() -> str:
    """Pick a thinking verb via the shared helper, with a local fallback."""
    try:
        from cli.utils.thinking_verbs import pick_thinking_verb

        verb = pick_thinking_verb()
        if isinstance(verb, str) and verb:
            return verb
    except Exception:  # noqa: BLE001 — never block the spinner on helper issues
        pass
    return random.choice(_FALLBACK_VERBS)


def _resolve_console() -> Console:
    """Return the shared CLI console."""
    from cli.theme import get_console

    return get_console()


class ThinkingSpinner:
    """Show a transient Rich spinner with a thinking verb.

    Args:
        verb: Initial status verb. Omit it to pick one automatically.
        console: Console override. Defaults to the shared CLI console.
        spinner_name: Name of the Rich spinner animation.
    """

    def __init__(
        self,
        verb: Optional[str] = None,
        *,
        console: Optional[Console] = None,
        spinner_name: str = "dots",
    ) -> None:
        self._verb = verb or _pick_verb()
        self._console = console or _resolve_console()
        self._spinner_name = spinner_name
        self._live: Optional[Live] = None

    # lifecycle
    def __enter__(self) -> "ThinkingSpinner":
        self._live = Live(
            self._renderable(),
            console=self._console,
            transient=True,
            refresh_per_second=12,
        )
        self._live.__enter__()
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        live, self._live = self._live, None
        if live is not None:
            live.__exit__(exc_type, exc, tb)

    # helpers
    def _renderable(self) -> Spinner:
        # ``Spinner.text`` accepts Rich Text for styling — keep the verb in
        # the dim style so the live region is unobtrusive.
        return Spinner(self._spinner_name, text=Text(self._verb, style="dim"))

    def pause(self) -> "_SpinnerPause":
        """Temporarily hide the spinner while other output is printed.

        Returns:
            Context manager that hides the spinner inside its block.
        """
        return _SpinnerPause(self)


class _SpinnerPause:
    """Inner context manager returned by :meth:`ThinkingSpinner.pause`."""

    def __init__(self, parent: ThinkingSpinner) -> None:
        self._parent = parent
        self._saved_live: Optional[Live] = None

    def __enter__(self) -> None:
        # Stash the live so __exit__ on the outer spinner does nothing
        # while we are paused; restart it on exit.
        if self._parent._live is not None:
            self._parent._live.__exit__(None, None, None)
            self._saved_live = self._parent._live
            self._parent._live = None

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        if self._saved_live is not None:
            self._parent._live = self._saved_live
            self._parent._live.__enter__()
            self._saved_live = None


__all__ = ["ThinkingSpinner"]
