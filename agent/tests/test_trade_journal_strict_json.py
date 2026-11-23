"""The journal analysis must be strict JSON even when a ratio is unbounded."""

from __future__ import annotations

from src.tools.path_utils import FileRoots
from src.config.accessor import get_env_config


import json
from pathlib import Path

import pytest

from src.tools.trade_journal_tool import analyze_trade_journal


def _reject_constant(name: str) -> None:
    raise ValueError(f"non-standard JSON literal {name}")


def _analyze(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rows: str) -> dict:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    csv = tmp_path / "journal.csv"
    csv.write_text("datetime,symbol,side,quantity,price\n" + rows, encoding="utf-8")
    raw = analyze_trade_journal(str(csv), "full", roots=FileRoots.from_config(get_env_config().api))
    return json.loads(raw, parse_constant=_reject_constant)


def test_winners_only_journal_has_null_profit_loss_ratio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _analyze(
        tmp_path,
        monkeypatch,
        "2026-01-02 09:35:00,AAPL,buy,10,180\n"
        "2026-01-05 14:00:00,AAPL,sell,10,190\n",
    )
    assert out["status"] == "ok"
    assert out["profile"]["profit_loss_ratio"] is None


def test_zero_day_winner_has_null_disposition_ratio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _analyze(
        tmp_path,
        monkeypatch,
        "2026-01-02 09:35:00,AAPL,buy,10,100\n"
        "2026-01-02 09:35:00,AAPL,sell,10,110\n"
        "2026-01-02 09:35:00,MSFT,buy,10,100\n"
        "2026-01-05 09:35:00,MSFT,sell,10,90\n",
    )
    assert out["behavior"]["disposition_effect"]["ratio_loss_to_win_hold"] is None
    assert out["behavior"]["disposition_effect"]["severity"] == "high"
    assert "inf" not in out["behavior"]["disposition_effect"]["evidence"]


def test_zero_day_winners_and_losers_do_not_imply_disposition_bias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _analyze(
        tmp_path,
        monkeypatch,
        "2026-01-02 09:35:00,AAPL,buy,10,100\n"
        "2026-01-02 09:35:00,AAPL,sell,10,110\n"
        "2026-01-02 09:35:00,MSFT,buy,10,100\n"
        "2026-01-02 09:35:00,MSFT,sell,10,90\n",
    )
    effect = out["behavior"]["disposition_effect"]
    assert effect["ratio_loss_to_win_hold"] is None
    assert effect["severity"] == "low"
    assert "undefined" in effect["evidence"]
    assert "Classic disposition" not in effect["evidence"]
