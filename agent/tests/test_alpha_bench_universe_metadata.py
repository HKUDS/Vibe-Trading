"""Universe loaders disclose constituent provenance and degradation."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from src.tools import alpha_bench_tool as tool


def _daily_frame() -> pd.DataFrame:
    """Return one deterministic Tushare-style daily row."""
    return pd.DataFrame(
        {
            "trade_date": ["20240102"],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "vol": [100.0],
            "amount": [105.0],
        }
    )


class _FakeTusharePro:
    """Minimal Tushare Pro surface used by the CSI300 loader."""

    def __init__(self, weights: pd.DataFrame | Exception) -> None:
        self.weights = weights

    def index_weight(self, **_kwargs) -> pd.DataFrame:
        """Return configured weights or simulate an upstream failure."""
        if isinstance(self.weights, Exception):
            raise self.weights
        return self.weights

    def daily(self, **_kwargs) -> pd.DataFrame:
        """Return deterministic OHLCV data for every requested code."""
        return _daily_frame()

    def adj_factor(self, **_kwargs) -> pd.DataFrame:
        """Return a flat adjustment factor — no corporate action in the window."""
        return pd.DataFrame({"trade_date": ["20240102"], "adj_factor": [1.0]})


def _install_fake_tushare(
    monkeypatch: pytest.MonkeyPatch,
    pro: _FakeTusharePro,
) -> None:
    """Install deterministic credentials and an in-memory Tushare module."""
    monkeypatch.setattr(
        tool,
        "get_env_config",
        lambda: SimpleNamespace(data=SimpleNamespace(tushare_token="test-token")),
    )
    monkeypatch.setitem(
        sys.modules,
        "tushare",
        SimpleNamespace(pro_api=lambda _token: pro),
    )


def test_csi300_reports_point_in_time_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A healthy CSI300 load carries every name that was ever a member."""
    weights = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240131", "20240131"],
            "con_code": ["600000.SH", "000001.SZ", "000002.SZ"],
        }
    )
    _install_fake_tushare(monkeypatch, _FakeTusharePro(weights))

    panel = tool._load_csi300_panel("2024-01-01", "2024-01-31")

    assert panel["_meta"] == {
        "universe": "csi300",
        # Membership is per date, so a name is no longer present merely because
        # it survived to the end of the window.
        "survivorship_bias": False,
        "pit_membership": True,
        "degraded": False,
        "constituent_source": "tushare index_weight",
        "constituent_source_date": "20240131",
        # The union of both snapshots, not the terminal roster.
        "constituent_count": 3,
        "price_adjustment": "qfq",
        "dropped_unadjustable": 0,
    }


def test_csi300_masks_a_name_outside_its_membership_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A name that left the index must be absent from later cross-sections."""
    weights = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240102", "20240131"],
            # 600000.SH is a member on the first snapshot only.
            "con_code": ["600000.SH", "000001.SZ", "000001.SZ"],
        }
    )
    _install_fake_tushare(monkeypatch, _FakeTusharePro(weights))

    panel = tool._load_csi300_panel("2024-01-01", "2024-01-31")

    close = panel["close"]
    assert set(close.columns) == {"600000.SH", "000001.SZ"}
    # The fake loader returns a single bar dated 2024-01-02, when both were in.
    assert close.loc["2024-01-02", "600000.SH"] == 10.5
    assert close.loc["2024-01-02", "000001.SZ"] == 10.5


def test_csi300_reports_hand_picked_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed index lookup discloses the smaller survivor-selected roster."""
    monkeypatch.setattr(
        tool,
        "_CSI300_FALLBACK_CODES",
        ["600519.SH", "000001.SZ"],
    )
    _install_fake_tushare(monkeypatch, _FakeTusharePro(RuntimeError("offline")))

    panel = tool._load_csi300_panel("2024-01-01", "2024-01-31")

    assert panel["_meta"] == {
        "universe": "csi300",
        # The fallback is a static survivor-selected roster with no membership
        # history, so the bias disclosure stays on.
        "survivorship_bias": True,
        "pit_membership": False,
        "degraded": True,
        "constituent_source": "hand-picked fallback",
        "constituent_source_date": None,
        "constituent_count": 2,
        "price_adjustment": "qfq",
        "dropped_unadjustable": 0,
    }


@pytest.mark.parametrize(
    ("codes", "source", "source_date", "degraded"),
    [
        (["AAPL"], "wikipedia", tool._SP500_CONSTITUENT_SOURCE_DATE, False),
        ([], "hand-picked fallback", None, True),
    ],
)
def test_sp500_source_date_matches_the_roster(
    monkeypatch: pytest.MonkeyPatch,
    codes: list[str],
    source: str,
    source_date: str | None,
    degraded: bool,
) -> None:
    """SP500 metadata never assigns Wikipedia's date to a fallback list."""

    class _Loader:
        def fetch(self, *_args, **_kwargs) -> dict:
            return {}

    import backtest.loaders.registry as registry

    monkeypatch.setattr(tool, "_fetch_sp500_constituents", lambda: codes)
    monkeypatch.setattr(registry, "resolve_loader", lambda _market: _Loader())

    panel = tool._load_sp500_panel("2024-01-01", "2024-01-31")

    assert panel["_meta"]["constituent_source"] == source
    assert panel["_meta"]["constituent_source_date"] == source_date
    assert panel["_meta"]["degraded"] is degraded
