"""Connector history should print the bars the user asked for."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

import cli._legacy as legacy


def _bars(n: int) -> list[dict[str, object]]:
    return [
        {"date": f"2026-01-{i:02d}", "open": i, "high": i, "low": i, "close": i, "volume": i}
        for i in range(1, n + 1)
    ]


def _run(monkeypatch, rows: list[dict[str, object]], limit: int) -> str:
    monkeypatch.setattr(
        "src.trading.service.get_history",
        lambda *args, **kwargs: {
            "status": "ok",
            "symbol": "AAPL",
            "profile_id": "paper",
            "bars": rows,
        },
    )
    buf = StringIO()
    monkeypatch.setattr(
        legacy,
        "console",
        Console(file=buf, force_terminal=False, width=200, no_color=True),
    )
    assert legacy.cmd_connector_history("AAPL", limit=limit) == 0
    return buf.getvalue()


def test_history_prints_every_bar_inside_the_requested_limit(monkeypatch) -> None:
    text = _run(monkeypatch, _bars(40), 40)
    assert "2026-01-01" in text
    assert "2026-01-40" in text


def test_history_does_not_print_bars_outside_the_limit(monkeypatch) -> None:
    text = _run(monkeypatch, _bars(40), 5)
    assert "2026-01-36" in text
    assert "2026-01-40" in text
    assert "2026-01-01" not in text
