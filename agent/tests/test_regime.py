"""Tests for backtest/regime.py and the /correlation/regime route.

The math tests pin the Mode 1 semantics of the correlation-regime skill:
edge density in [0, 1] with NaN warmup, hysteresis that suppresses dead-band
chatter, and strict causality (future bars never change past states). The
route tests mirror test_system_routes.py: auth, validation, shared rate
limiter, and error masking.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.regime import (
    _aligned_returns,
    _fused_episodes,
    compute_edge_density,
    compute_regime_timeline,
    detect_regimes,
)


def _returns_panel(blocks: list[np.ndarray]) -> pd.DataFrame:
    """Stack return blocks into a date-indexed multi-asset returns frame."""
    data = np.vstack(blocks)
    dates = pd.date_range("2024-01-01", periods=len(data), freq="D")
    cols = [f"A{k}" for k in range(data.shape[1])]
    return pd.DataFrame(data, index=dates, columns=cols)


def _calm_block(rng: np.random.Generator, n: int, n_assets: int) -> np.ndarray:
    """Independent idiosyncratic returns — pairwise correlations near zero."""
    return rng.standard_normal((n, n_assets)) * 0.01


def _fused_block(rng: np.random.Generator, n: int, n_assets: int) -> np.ndarray:
    """One common factor dominating — pairwise correlations near one."""
    factor = rng.standard_normal((n, 1)) * 0.02
    return factor + rng.standard_normal((n, n_assets)) * 0.002


class TestComputeEdgeDensity:
    def test_warmup_is_nan_then_values_start(self):
        rng = np.random.default_rng(3)
        returns = _returns_panel([_calm_block(rng, 60, 4)])
        density = compute_edge_density(returns, corr_window=20)
        assert density.iloc[: 20 - 1].isna().all()
        assert density.iloc[20 - 1 :].notna().all()

    def test_fused_panel_has_density_one(self):
        rng = np.random.default_rng(5)
        returns = _returns_panel([_fused_block(rng, 80, 4)])
        density = compute_edge_density(returns, corr_window=20)
        assert density.iloc[-1] == pytest.approx(1.0)

    def test_independent_panel_has_low_density(self):
        rng = np.random.default_rng(7)
        returns = _returns_panel([_calm_block(rng, 120, 4)])
        density = compute_edge_density(returns, corr_window=60)
        assert density.iloc[-1] <= 0.2

    def test_values_stay_in_unit_interval(self):
        rng = np.random.default_rng(11)
        returns = _returns_panel([_calm_block(rng, 50, 3), _fused_block(rng, 50, 3)])
        density = compute_edge_density(returns, corr_window=15)
        observed = density.dropna()
        assert ((observed >= 0.0) & (observed <= 1.0)).all()

    def test_single_asset_returns_nan_density(self):
        returns = pd.DataFrame({"AAPL": [0.01] * 70})
        density = compute_edge_density(returns, corr_window=60)
        assert density.isna().all()


class TestDetectRegimes:
    def _series(self, values: list[float]) -> pd.Series:
        dates = pd.date_range("2024-01-01", periods=len(values), freq="D")
        return pd.Series(values, index=dates)

    def test_exit_at_or_above_enter_raises(self):
        with pytest.raises(ValueError, match="exit_threshold"):
            detect_regimes(self._series([0.1]), enter_threshold=0.5, exit_threshold=0.5)

    def test_enters_and_exits_across_thresholds(self):
        density = self._series([0.1] * 10 + [0.9] * 10 + [0.1] * 10)
        result = detect_regimes(density, smooth_window=1)
        assert result["fused"].iloc[5] == 0
        assert result["fused"].iloc[15] == 1
        assert result["fused"].iloc[-1] == 0

    def test_dead_band_chatter_stays_fused(self):
        # After entry, density oscillating between the two thresholds
        # (0.45 < value < 0.65) must never close the regime.
        density = self._series([0.9] * 5 + [0.5, 0.6] * 10)
        result = detect_regimes(density, smooth_window=1)
        assert (result["fused"] == 1).all()

    def test_causality_tail_corruption_never_changes_past(self):
        rng = np.random.default_rng(13)
        returns = _returns_panel([_calm_block(rng, 60, 4), _fused_block(rng, 60, 4)])
        corrupted = returns.copy()
        corrupted.iloc[-10:] = 0.5  # absurd future bars

        def states(frame: pd.DataFrame) -> np.ndarray:
            density = compute_edge_density(frame, corr_window=20)
            return detect_regimes(density, smooth_window=3)["fused"].to_numpy()

        np.testing.assert_array_equal(states(returns)[:-10], states(corrupted)[:-10])


class TestFusedEpisodes:
    DATES = [f"2024-01-{d:02d}" for d in range(1, 7)]

    def test_closed_and_ongoing_episodes(self):
        episodes = _fused_episodes(self.DATES, [0, 1, 1, 0, 0, 1])
        assert episodes == [
            {"start": "2024-01-02", "end": "2024-01-03"},
            {"start": "2024-01-06", "end": None},
        ]

    def test_never_fused_is_empty(self):
        assert _fused_episodes(self.DATES, [0] * 6) == []

    def test_always_fused_is_one_open_episode(self):
        assert _fused_episodes(self.DATES, [1] * 6) == [
            {"start": "2024-01-01", "end": None}
        ]


class TestAlignedReturns:
    def test_does_not_forward_fill_missing_prices(self):
        # Under pandas>=2,<3 a bare pct_change() forward-fills NaN closes,
        # manufacturing 0% returns; fill_method=None must keep them NaN so
        # the inner join drops those dates instead.
        dates = pd.date_range("2024-01-01", periods=6, freq="D")
        with_gap = pd.DataFrame(
            {"close": [100.0, np.nan, 102.0, 103.0, 104.0, 105.0]},
            index=pd.Index(dates, name="trade_date"),
        )
        complete = pd.DataFrame(
            {"close": [50.0, 51.0, 52.0, 53.0, 54.0, 55.0]},
            index=pd.Index(dates, name="trade_date"),
        )
        aligned = _aligned_returns({"GAP": with_gap, "FULL": complete})
        # The gap day and the day after it (whose return needs the gap day's
        # close) must both be gone; no zero return may be fabricated.
        assert len(aligned) == 3
        assert not (aligned["GAP"] == 0.0).any()


class _ServesPanelLoader:
    """Fake loader serving a prebuilt panel, keyed by normalized symbol."""

    frames: dict[str, pd.DataFrame] = {}
    name = "fake_panel"
    markets = {"us_equity"}

    def is_available(self):
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {c: self.frames[c].copy() for c in codes if c in self.frames}


def _install_panel(monkeypatch: pytest.MonkeyPatch, closes: dict[str, np.ndarray]) -> None:
    from backtest.loaders import registry

    dates = pd.date_range("2024-01-01", periods=len(next(iter(closes.values()))), freq="D")
    _ServesPanelLoader.frames = {
        f"{code}.US": pd.DataFrame(
            {"close": values}, index=pd.Index(dates, name="trade_date")
        )
        for code, values in closes.items()
    }
    monkeypatch.setattr(registry, "_registered", True)
    monkeypatch.setattr(registry, "LOADER_REGISTRY", {"fake_panel": _ServesPanelLoader})
    monkeypatch.setattr(registry, "FALLBACK_CHAINS", {"us_equity": ["fake_panel"]})


class TestComputeRegimeTimeline:
    def test_two_phase_panel_ends_fused_with_open_episode(self, monkeypatch):
        rng = np.random.default_rng(17)
        rets = np.vstack(
            [_calm_block(rng, 140, 4), _fused_block(rng, 80, 4)]
        )
        prices = 100.0 * np.cumprod(1.0 + rets, axis=0)
        codes = ["AAA", "BBB", "CCC", "DDD"]
        _install_panel(
            monkeypatch, {c: prices[:, k] for k, c in enumerate(codes)}
        )

        result = compute_regime_timeline(
            codes=codes, days=150, corr_window=20, smooth_window=3
        )

        assert result["labels"] == codes
        n = len(result["dates"])
        assert n <= 150
        assert len(result["density"]) == n
        assert len(result["smoothed"]) == n
        assert len(result["fused"]) == n
        # The fetch buffer keeps warmup NaNs out of the returned window.
        assert all(v is not None for v in result["density"])
        assert all(0.0 <= v <= 1.0 for v in result["density"])
        # The common-factor phase must end the timeline FUSED, as one
        # still-open episode.
        assert result["fused"][-1] == 1
        assert result["episodes"]
        assert result["episodes"][-1]["end"] is None
        assert result["params"]["corr_window"] == 20

    def test_invalid_thresholds_fail_before_any_fetch(self):
        with pytest.raises(ValueError, match="exit_threshold"):
            compute_regime_timeline(
                codes=["AAA", "BBB"], enter_threshold=0.5, exit_threshold=0.6
            )

    def test_fewer_than_two_fetched_assets_raises(self, monkeypatch):
        from backtest.loaders import registry

        monkeypatch.setattr(registry, "_registered", True)
        monkeypatch.setattr(registry, "LOADER_REGISTRY", {})
        monkeypatch.setattr(registry, "FALLBACK_CHAINS", {})
        with pytest.raises(ValueError, match="at least 2 assets"):
            compute_regime_timeline(codes=["AAA", "BBB"])


# ---------------------------------------------------------------------------
# /correlation/regime route (mirrors test_system_routes.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def local_client(monkeypatch: pytest.MonkeyPatch):
    """Loopback client with no API key configured (dev-mode: auth passes)."""
    import api_server
    from fastapi.testclient import TestClient

    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


@pytest.fixture(autouse=True)
def _reset_correlation_limiter():
    """Clear the module-level rate limiter so tests never leak hits into each other."""
    from src.api import system_routes

    system_routes._correlation_rate_limiter.reset()


_STUB_RESULT = {
    "labels": ["AAPL", "SPY"],
    "dates": ["2024-01-01"],
    "density": [0.5],
    "smoothed": [0.5],
    "fused": [0],
    "episodes": [],
    "params": {},
}


def test_regime_route_returns_computation_result(local_client, monkeypatch):
    import backtest.regime as regime

    monkeypatch.setattr(regime, "compute_regime_timeline", lambda **_kwargs: _STUB_RESULT)
    resp = local_client.get("/correlation/regime", params={"codes": "AAPL,SPY"})
    assert resp.status_code == 200
    assert resp.json() == _STUB_RESULT


def test_regime_route_requires_auth_for_remote_client(monkeypatch):
    import api_server
    from fastapi.testclient import TestClient

    monkeypatch.setattr(api_server, "_API_KEY", "server-secret")
    remote = TestClient(api_server.app, client=("203.0.113.9", 51000))
    resp = remote.get("/correlation/regime", params={"codes": "AAPL,SPY"})
    assert resp.status_code == 401


def test_regime_route_validates_code_count(local_client):
    too_few = local_client.get("/correlation/regime", params={"codes": "AAPL"})
    assert too_few.status_code == 400
    too_many = local_client.get(
        "/correlation/regime", params={"codes": ",".join(f"S{i}" for i in range(21))}
    )
    assert too_many.status_code == 400


def test_regime_route_rejects_inverted_thresholds(local_client):
    resp = local_client.get(
        "/correlation/regime",
        params={"codes": "AAPL,SPY", "enter_threshold": 0.5, "exit_threshold": 0.6},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "exit_threshold must be below enter_threshold"


def test_regime_route_rejects_days_below_floor(local_client):
    # days < 30 with a 60-bar correlation window yields an empty timeline, so
    # the route floors days at 30 (FastAPI validation → 422).
    resp = local_client.get(
        "/correlation/regime", params={"codes": "AAPL,SPY", "days": 20}
    )
    assert resp.status_code == 422


def test_regime_route_value_error_surfaces_and_generic_is_masked(
    local_client, monkeypatch
):
    import backtest.regime as regime

    def _bad(**_kwargs):
        raise ValueError("Not enough overlapping history")

    monkeypatch.setattr(regime, "compute_regime_timeline", _bad)
    resp = local_client.get("/correlation/regime", params={"codes": "AAPL,SPY"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Not enough overlapping history"

    def _boom(**_kwargs):
        raise RuntimeError("sensitive internal detail: db=prod host=10.0.0.5")

    monkeypatch.setattr(regime, "compute_regime_timeline", _boom)
    resp = local_client.get("/correlation/regime", params={"codes": "AAPL,SPY"})
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Regime timeline computation failed"


def test_regime_route_shares_correlation_rate_limit_budget(local_client, monkeypatch):
    """One budget across /correlation and /correlation/regime, per maintainer ask."""
    import backtest.correlation as corr
    from src.api import system_routes

    monkeypatch.setattr(
        corr,
        "compute_correlation_matrix",
        lambda **_kwargs: {"labels": ["AAPL", "SPY"], "matrix": [[1.0, 0.5], [0.5, 1.0]]},
    )
    monkeypatch.setattr(
        system_routes,
        "_correlation_rate_limiter",
        system_routes._SlidingWindowRateLimiter(max_requests=1, window_seconds=60.0),
    )

    ok = local_client.get("/correlation", params={"codes": "AAPL,SPY"})
    blocked = local_client.get("/correlation/regime", params={"codes": "AAPL,SPY"})
    assert ok.status_code == 200
    assert blocked.status_code == 429
