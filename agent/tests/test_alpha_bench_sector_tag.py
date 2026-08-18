"""The SP500 panel carries a sector tag, so industry-neutralized alphas run.

Nineteen alpha101 alphas declare ``requires_sector`` and the registry refuses
them outright when the panel has no ``sector`` frame, so every SP500 bench run
reported those nineteen as skipped. The labels ride along in the Wikipedia
table the constituent list already comes from — the fix costs no request.
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

import src.tools.alpha_bench_tool as tool
from src.factors.registry import Registry, SkipAlpha


def _fake_loader(codes: list[str]) -> object:
    dates = pd.date_range("2024-01-01", periods=6, freq="D")

    class _Loader:
        def fetch(self, project_codes, *_args, **_kwargs) -> dict:
            return {
                code: pd.DataFrame(
                    {
                        "open": range(1, 7),
                        "high": range(2, 8),
                        "low": range(1, 7),
                        "close": range(1, 7),
                        "volume": [100] * 6,
                    },
                    index=dates,
                )
                for code in project_codes
            }

    return _Loader()


def _patch(monkeypatch: pytest.MonkeyPatch, codes: list[str], sectors: dict[str, str]) -> None:
    import backtest.loaders.registry as registry

    monkeypatch.setattr(tool, "_fetch_sp500_constituents", lambda: (codes, sectors))
    monkeypatch.setattr(registry, "resolve_loader", lambda _market: _fake_loader(codes))


def test_sector_frame_matches_the_close_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_ind_neutralize`` indexes sector positionally against the value frame."""
    codes = ["AAPL", "MSFT", "JPM"]
    sectors = {"AAPL": "Information Technology", "MSFT": "Information Technology", "JPM": "Financials"}
    _patch(monkeypatch, codes, sectors)

    panel = tool._load_sp500_panel("2024-01-01", "2024-01-06")

    assert "sector" in panel
    close = panel["close"]
    assert panel["sector"].shape == close.shape
    assert list(panel["sector"].columns) == list(close.columns)
    assert panel["sector"].index.equals(close.index)
    # Every row carries the same labels — sector membership is not a time series here.
    for _, row in panel["sector"].iterrows():
        assert dict(row) == {f"{code}.US": sectors[code] for code in codes}
    assert panel["_meta"]["sector_source"] == "wikipedia GICS"
    assert panel["_meta"]["sector_coverage"] == 1.0


def test_industry_neutralized_alphas_are_no_longer_pre_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registry gate is what skipped them, so assert against the gate."""
    codes = ["AAPL", "MSFT", "JPM"]
    sectors = {"AAPL": "Information Technology", "MSFT": "Information Technology", "JPM": "Financials"}
    _patch(monkeypatch, codes, sectors)
    panel = tool._load_sp500_panel("2024-01-01", "2024-01-06")

    registry = Registry()
    gated = [
        alpha_id
        for alpha_id in registry.list(zoo="alpha101")
        if registry.get(alpha_id).meta.get("requires_sector")
    ]
    assert len(gated) == 19, gated

    without_tag = {key: value for key, value in panel.items() if key != "sector"}
    for alpha_id in gated:
        with pytest.raises(SkipAlpha, match="missing sector tag"):
            registry.compute(alpha_id, without_tag)
        # The same alpha with the tag present gets past the gate; whether the
        # formula then produces a usable series is the formula's business.
        try:
            registry.compute(alpha_id, panel)
        except Exception as exc:  # noqa: BLE001
            assert "missing sector tag" not in str(exc), alpha_id


def test_a_mostly_unlabelled_panel_keeps_the_tag_off(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """One "unknown" bucket is the global fallback wearing a sector label."""
    codes = ["AAPL", "MSFT", "JPM", "XOM"]
    _patch(monkeypatch, codes, {"AAPL": "Information Technology"})

    with caplog.at_level(logging.WARNING, logger=tool.logger.name):
        panel = tool._load_sp500_panel("2024-01-01", "2024-01-06")

    assert "sector" not in panel
    assert panel["_meta"]["sector_source"] is None
    assert panel["_meta"]["sector_coverage"] == 0.25
    assert any("sector coverage" in message for message in caplog.messages)
