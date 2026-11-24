"""prompt_toolkit input editor + ``SafeFileHistory``."""

from __future__ import annotations

import sys
import shutil
import time
from pathlib import Path
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.styles import Style


# Reuse EOFError for prompt_toolkit while distinguishing Ctrl+C from actual EOF.
_EXIT_HINT_GAP_SEC = 2.0


# history


class SafeFileHistory(FileHistory):
    """:class:`FileHistory` that strips invalid surrogate code points."""

    def store_string(self, string: str) -> None:  # type: ignore[override]
        """Store a history entry after stripping surrogate characters.

        Args:
            string: Input line to save in the history file.
        """
        super().store_string(_strip_surrogates(string))


def _strip_surrogates(text: str) -> str:
    """Drop unpaired surrogate code points from ``text``."""
    try:
        round_tripped = text.encode("utf-16-le", "surrogatepass").decode(
            "utf-16-le", "replace"
        )
    except UnicodeError:
        return "".join(ch for ch in text if not 0xD800 <= ord(ch) <= 0xDFFF)
    cleaned = round_tripped.encode("utf-8", "ignore").decode("utf-8", "ignore")
    return cleaned.replace("�", "")


# session


class _VibePromptSession(PromptSession):
    """PromptSession with a prompt-height that hugs the edited text."""

    def _create_layout(self):  # type: ignore[no-untyped-def]
        layout = super()._create_layout()
        # prompt_toolkit's bottom_toolbar is a screen-bottom status bar. Insert
        # our divider directly after the input container so it hugs the prompt.
        layout.container.children.insert(1, _prompt_divider_window())
        return layout

    def _get_default_buffer_control_height(self) -> Dimension:  # type: ignore[override]
        line_count = self.default_buffer.document.line_count
        return Dimension.exact(max(1, line_count))


def _prompt_divider_window() -> Window:
    return Window(
        FormattedTextControl(
            lambda: FormattedText([("class:prompt-border", _prompt_rule())])
        ),
        height=1,
        style="class:prompt-border",
        dont_extend_height=True,
    )


def _force_utf8_stdout() -> None:
    """Reconfigure stdout to UTF-8 on Windows so brand glyphs render."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                # Best-effort — a redirected pipe may refuse encoding swaps.
                pass


def _has_unbalanced_brackets(text: str) -> bool:
    """Return True if ``text`` contains unbalanced ``()``/``[]``/``{}`` pairs."""
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    openers = set(pairs.values())
    in_str: Optional[str] = None
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if in_str is not None:
            if ch == in_str:
                in_str = None
            continue
        if ch in ("'", '"'):
            in_str = ch
            continue
        if ch in openers:
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack[-1] != pairs[ch]:
                return True
            stack.pop()
    return bool(stack) or in_str is not None


class _CtrlCState:
    """Track Ctrl+C presses so the outer loop can implement two-press exit."""

    __slots__ = ("previous_press_ts", "last_window_hit")

    def __init__(self) -> None:
        self.previous_press_ts: float = 0.0
        self.last_window_hit: bool = False

    def record_press_and_check_window(self, window_sec: float = _EXIT_HINT_GAP_SEC) -> bool:
        """Record the current press, return True iff inside the window."""
        now = time.monotonic()
        prev = self.previous_press_ts
        self.previous_press_ts = now
        if prev == 0.0:
            self.last_window_hit = False
            return False
        hit = (now - prev) < window_sec
        self.last_window_hit = hit
        return hit


def _build_keybindings(state: _CtrlCState) -> KeyBindings:
    """Wire Ctrl+C + multi-line submit semantics."""
    kb = KeyBindings()

    @kb.add("c-c")
    def _(event) -> None:  # noqa: ANN001 — prompt_toolkit event
        buf = event.app.current_buffer
        if buf.text:
            buf.reset()
            event.app.invalidate()
            return
        # Update press timing before the outer loop checks for double-press exit.
        state.record_press_and_check_window(_EXIT_HINT_GAP_SEC)
        event.app.exit(exception=EOFError())

    @kb.add("enter")
    def _(event) -> None:  # noqa: ANN001
        buf = event.app.current_buffer
        text = buf.text
        if _has_unbalanced_brackets(text):
            buf.insert_text("\n")
            return
        buf.validate_and_handle()

    # Alt+Enter / Esc-Enter — unconditional newline.
    @kb.add("escape", "enter")
    def _(event) -> None:  # noqa: ANN001
        event.app.current_buffer.insert_text("\n")

    return kb


def _default_history_path() -> Path:
    """Where ``~/.vibe-trading/history`` lives by default."""
    home = Path.home() / ".vibe-trading"
    return home / "history"


def make_session(history_path: Optional[Path] = None) -> PromptSession:
    """Construct a configured prompt_toolkit session.

    Args:
        history_path: Override for the persistent history file. None uses the default history path.

    Returns:
        Prompt session with slash completion, multiline editing, surrogate-safe history, and a
        vibe_ctrl_c_state for two-press exit.
    """
    _force_utf8_stdout()

    path = history_path or _default_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Touch the file so FileHistory's first read does not fail on a fresh
    # install.
    if not path.exists():
        path.touch(mode=0o600)

    # Lazy import so unit tests can import this module without instantiating
    # the slash registry side-effects.
    from cli.completer import SlashCompleter

    ctrl_c_state = _CtrlCState()
    session = _VibePromptSession(
        history=SafeFileHistory(str(path)),
        completer=SlashCompleter(),
        complete_while_typing=True,
        key_bindings=_build_keybindings(ctrl_c_state),
        enable_history_search=True,
        mouse_support=False,
        multiline=True,
        reserve_space_for_menu=0,
        style=Style.from_dict(
            {
                "prompt": "#258bff bold",
                "prompt-border": "#4b5563",
            }
        ),
    )
    # Expose the state so the outer loop can implement two-press exit.
    setattr(session, "vibe_ctrl_c_state", ctrl_c_state)
    return session


# helpers


def get_user_input(
    prompt_message: str = "❯ ",
    *,
    session: Optional[PromptSession] = None,
) -> str:
    """Prompt for input with a styled terminal border.

    Args:
        prompt_message: Text displayed beside the input cursor.
        session: Existing prompt session to reuse. Omit to create one.

    Returns:
        Submitted input text.

    Raises:
        EOFError: If the user sends EOF or the configured Ctrl+C binding exits from an empty input
            buffer.
    """
    sess = session or make_session()
    formatted = FormattedText(
        [
            ("class:prompt-border", _prompt_rule() + "\n"),
            ("class:prompt", prompt_message),
        ]
    )
    return sess.prompt(formatted)


def _prompt_rule() -> str:
    cols = shutil.get_terminal_size((88, 24)).columns
    return "─" * max(10, cols)


def ctrl_c_within_window(session: PromptSession, window_sec: float = _EXIT_HINT_GAP_SEC) -> bool:
    """Read the most recent two-press Ctrl+C exit decision.

    Args:
        session: Active prompt session supplying the Ctrl+C state.
        window_sec: Window length in seconds for the timestamp fallback. The key binding normally
            supplies a cached decision.

    Returns:
        True if the cached decision, or the fallback check against the prior press timestamp,
        signals exit.
    """
    state = getattr(session, "vibe_ctrl_c_state", None)
    if state is None:
        return False
    # Primary path — the keybinding cached the press-time decision.
    if hasattr(state, "last_window_hit"):
        return bool(state.last_window_hit)
    # Legacy fallback for test doubles that only set ``last_press_ts``.
    last_ts = getattr(state, "last_press_ts", 0.0)
    if last_ts <= 0.0:
        return False
    return (time.monotonic() - last_ts) < window_sec


__all__ = [
    "SafeFileHistory",
    "make_session",
    "get_user_input",
    "ctrl_c_within_window",
]
