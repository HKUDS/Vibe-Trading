"""Asset-class Brinson must not read an unpriced class member as a 0% return."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.api.attribution_core import _attribution_brinson_asset_class_mode


def _write_ohlcv(run_dir: Path, symbol: str, first: float, last: float) -> None:
    path = run_dir / "artifacts" / f"ohlcv_{symbol}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "trade_date,open,high,low,close,volume\n"
        f"2024-01-02,{first},{first},{first},{first},1000\n"
        f"2024-01-03,{last},{last},{last},{last},1000\n",
        encoding="utf-8",
    )


def _run(run_dir: Path, notes: list[str]):
    return _attribution_brinson_asset_class_mode(
        run_dir, "SPY.US", {"AAPL.US": 0.5, "MSFT.US": 0.5}, [0.0, 0.0], "ok", [100.0, 101.0], notes
    )


def test_a_class_with_an_unpriced_member_degrades_to_invested_cash(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path, "AAPL.US", 100.0, 110.0)
    notes: list[str] = []
    result = _run(tmp_path, notes)
    assert result is not None
    assert result["mode"] == "invested_cash"


def test_a_fully_priced_class_keeps_asset_class_mode(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path, "AAPL.US", 100.0, 110.0)
    _write_ohlcv(tmp_path, "MSFT.US", 100.0, 120.0)
    result = _run(tmp_path, [])
    assert result is not None
    assert result["mode"] == "asset_class"
    sectors = {sector["sector"]: sector for sector in result["sectors"]}
    assert sectors["us_equity"]["portfolio_return"] == pytest.approx(0.15)
