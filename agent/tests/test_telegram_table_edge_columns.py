"""Telegram markdown tables must keep empty leading/trailing columns."""

from __future__ import annotations

import sys
import types


def _stub_telegram_deps() -> None:
    """Install minimal stubs so telegram.py imports without python-telegram-bot."""

    def _mod(name: str) -> types.ModuleType:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
        return mod

    tg = _mod("telegram")

    class _Accepting:
        def __init__(self, *args, **kwargs) -> None:
            pass

    for name in (
        "BotCommand",
        "InlineKeyboardButton",
        "InlineKeyboardMarkup",
        "ReactionTypeEmoji",
        "ReplyParameters",
        "Update",
    ):
        setattr(tg, name, _Accepting)

    err = _mod("telegram.error")
    for name in ("BadRequest", "NetworkError", "TimedOut"):
        setattr(err, name, type(name, (Exception,), {}))

    ext = _mod("telegram.ext")
    for name in (
        "Application",
        "CallbackQueryHandler",
        "ContextTypes",
        "MessageHandler",
        "filters",
    ):
        setattr(ext, name, _Accepting)

    _mod("telegram.request").HTTPXRequest = _Accepting


_stub_telegram_deps()

from src.channels.telegram import _render_table_box  # noqa: E402


def test_render_table_box_keeps_trailing_empty_column() -> None:
    box = _render_table_box(
        [
            "|Name|Qty||",
            "|---|---|---|",
            "|a|1||",
            "|b|2||",
        ]
    )
    rule = box.split("\n")[1]
    assert rule.count("  ") == 2


def test_render_table_box_keeps_leading_empty_header_with_row_labels() -> None:
    box = _render_table_box(
        [
            "||Name|Qty|",
            "|---|---|---|",
            "|row1|a|1|",
            "|row2|b|2|",
        ]
    )
    header, _rule, data_row = box.split("\n")[:3]
    assert data_row.startswith("row1")
    # Empty leading header must keep Name aligned over the second data cell.
    assert header.index("Name") == data_row.index("a")
    assert "1" in data_row
