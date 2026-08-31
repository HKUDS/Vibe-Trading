"""NIFTY 50 bench universe: constituent provenance, sector tag, concurrency.

Mirrors the SP500 coverage in ``test_alpha_bench_universe_metadata.py`` /
``test_alpha_bench_sector_tag.py``. No network — the Wikipedia fetch and the
Yahoo loader are both stubbed.
"""

from __future__ import annotations

import pandas as pd
import pytest

import backtest.loaders.registry as registry
from src.tools import alpha_bench_tool as tool


def _fake_loader() -> object:
    dates = pd.date_range("2024-01-01", periods=6, freq="D")

    class _Loader:
        # _fetch_equity_panel_concurrent calls fetch([code], start, end, interval=...)
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


@pytest.mark.parametrize(
    ("wiki", "source", "source_date_is_none", "degraded"),
    [
        (
            (["RELIANCE", "TCS", "INFY"] * 15, {"RELIANCE": "Energy", "TCS": "IT", "INFY": "IT"}),
            "wikipedia",
            False,
            False,
        ),
        (([], {}), "hand-picked fallback", False, True),
    ],
)
def test_nifty50_constituent_provenance(
    monkeypatch: pytest.MonkeyPatch,
    wiki: tuple[list[str], dict[str, str]],
    source: str,
    source_date_is_none: bool,
    degraded: bool,
) -> None:
    monkeypatch.setattr(tool, "_fetch_nifty50_constituents", lambda: wiki)
    monkeypatch.setattr(registry, "resolve_loader", lambda _market: _fake_loader())

    panel = tool._load_nifty_panel("2024-01-01", "2024-01-31")

    assert panel["_meta"]["universe"] == "nifty50"
    assert panel["_meta"]["constituent_source"] == source
    assert (panel["_meta"]["constituent_source_date"] is None) is source_date_is_none
    assert panel["_meta"]["degraded"] is degraded
    assert panel["_meta"]["survivorship_bias"] is True
    # synthetic vwap always present for alpha101
    assert "vwap" in panel


def test_nifty50_carries_sector_tag_when_coverage_is_high(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full-coverage NSE sector labels → a ``sector`` frame the registry accepts."""
    codes = list(tool._NIFTY50_FALLBACK)
    sectors = dict(tool._NIFTY50_FALLBACK)
    monkeypatch.setattr(tool, "_fetch_nifty50_constituents", lambda: (codes, sectors))
    monkeypatch.setattr(registry, "resolve_loader", lambda _market: _fake_loader())

    panel = tool._load_nifty_panel("2024-01-01", "2024-01-31")

    assert "sector" in panel
    assert panel["_meta"]["sector_coverage"] == pytest.approx(1.0)
    # one column per fetched name, each tagged
    assert set(panel["sector"].iloc[0].unique()).issubset(set(sectors.values()))
