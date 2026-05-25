"""Unit + integration tests for ``bench_runner_strict``.

The companion module adds a same-universe random control gate plus an
optional train/test OOS split on top of the existing IC bench math. These
tests pin the contract end-to-end: helpers, categorisation rules, the
keyword-only ``random_control`` rail, and a small registry-injected
integration test that exercises the full pipeline.

The integration test side-steps the network-bound ``_load_universe_panel``
and ``_compute_forward_returns`` helpers via ``monkeypatch`` so the suite
stays hermetic and CI-friendly.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from src.factors.bench_runner_strict import (
    StrictThresholds,
    _shuffle_within_rows,
    alpha_series_paired,
    categorise_strict,
    compute_random_ic_series,
    run_bench_strict,
    t_stat,
)


# ── Helper builders ─────────────────────────────────────────────────────────


def _panel(n_rows: int = 60, n_cols: int = 8, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n_rows, freq="D")
    cols = [f"S{i}" for i in range(n_cols)]
    return pd.DataFrame(rng.normal(size=(n_rows, n_cols)), index=idx, columns=cols)


# ── _shuffle_within_rows ────────────────────────────────────────────────────


def test_shuffle_within_rows_preserves_row_values() -> None:
    df = _panel(seed=0)
    shuffled = _shuffle_within_rows(df, seed=1)
    # Each row's multiset of values is unchanged; only positions move.
    for date in df.index:
        assert sorted(df.loc[date].tolist()) == sorted(shuffled.loc[date].tolist())


def test_shuffle_within_rows_respects_nan() -> None:
    df = _panel(seed=0)
    df.iloc[0, 0] = np.nan
    df.iloc[3, 2] = np.nan
    shuffled = _shuffle_within_rows(df, seed=42)
    # NaN cells stay NaN — only non-NaN values are permuted within the row.
    assert pd.isna(shuffled.iloc[0, 0])
    assert pd.isna(shuffled.iloc[3, 2])


def test_shuffle_within_rows_different_seeds_differ() -> None:
    df = _panel(seed=0)
    a = _shuffle_within_rows(df, seed=1)
    b = _shuffle_within_rows(df, seed=2)
    # At least some rows must differ between seeds (probability of full match
    # under independent permutations of 8 elements is ~1/40320 per row, with
    # 60 rows the chance of all-rows-equal is astronomically small).
    assert not a.equals(b)


# ── compute_random_ic_series ───────────────────────────────────────────────


def test_compute_random_ic_series_returns_dated_series() -> None:
    factor = _panel(seed=0)
    returns = _panel(seed=1)
    ic = compute_random_ic_series(factor, returns, n_seeds=3, base_seed=7)
    assert isinstance(ic, pd.Series)
    assert ic.index.is_monotonic_increasing
    # Random IC should be small in magnitude — within ±0.5 sanity bound.
    assert ic.abs().mean() < 0.5


def test_compute_random_ic_series_handles_empty() -> None:
    empty = pd.DataFrame()
    returns = _panel(seed=1)
    assert compute_random_ic_series(empty, returns).empty


# ── alpha_series_paired + t_stat ───────────────────────────────────────────


def test_alpha_series_paired_aligns_indices() -> None:
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    sig = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5], index=idx)
    rnd = pd.Series([0.0, 0.1, 0.1, 0.0, 0.2], index=idx)
    alpha = alpha_series_paired(sig, rnd)
    assert len(alpha) == 5
    assert alpha.iloc[0] == pytest.approx(0.1)
    assert alpha.iloc[4] == pytest.approx(0.3)


def test_t_stat_zero_for_short_or_constant_input() -> None:
    assert t_stat(pd.Series([], dtype=float)) == 0.0
    assert t_stat(pd.Series([0.5])) == 0.0
    assert t_stat(pd.Series([0.5, 0.5, 0.5])) == 0.0


def test_t_stat_matches_hand_computation() -> None:
    # mean=0.1, std (ddof=1) of evenly spaced values is well defined.
    s = pd.Series([0.05, 0.1, 0.15])
    n = len(s)
    expected = s.mean() / (s.std(ddof=1) / np.sqrt(n))
    assert t_stat(s) == pytest.approx(expected)


# ── categorise_strict ──────────────────────────────────────────────────────


def _row(**overrides: Any) -> dict[str, Any]:
    base = {
        "alpha_t_full": 0.0,
        "alpha_t_train": None,
        "alpha_t_test": None,
        "ic_count": 60,
    }
    base.update(overrides)
    return base


def test_categorise_noise_when_alpha_t_in_corridor() -> None:
    assert categorise_strict(_row(alpha_t_full=1.5)) == "noise"
    assert categorise_strict(_row(alpha_t_full=-1.9)) == "noise"


def test_categorise_reversed_when_alpha_t_strongly_negative() -> None:
    assert categorise_strict(_row(alpha_t_full=-2.5)) == "reversed_strict"


def test_categorise_confirmed_alive_full_sample_only() -> None:
    # No OOS provided → full-sample t > threshold is enough.
    row = _row(alpha_t_full=3.0)
    assert categorise_strict(row) == "confirmed_alive"


def test_categorise_train_only_when_oos_fails() -> None:
    row = _row(alpha_t_full=2.5, alpha_t_train=3.0, alpha_t_test=0.5)
    assert categorise_strict(row) == "train_only"


def test_categorise_confirmed_alive_when_oos_also_passes() -> None:
    row = _row(alpha_t_full=2.5, alpha_t_train=3.0, alpha_t_test=2.4)
    assert categorise_strict(row) == "confirmed_alive"


def test_categorise_short_ic_count_is_noise() -> None:
    # Below min_ic_count even strong t-stats are downgraded.
    row = _row(alpha_t_full=10.0, ic_count=10)
    assert categorise_strict(row) == "noise"


def test_categorise_respects_custom_threshold() -> None:
    # Harvey-Liu-Zhu (2016) multiple-testing recommendation.
    thresh = StrictThresholds(alpha_t_threshold=3.5)
    assert categorise_strict(_row(alpha_t_full=3.0), thresh) == "noise"
    assert categorise_strict(_row(alpha_t_full=3.6), thresh) == "confirmed_alive"


# ── run_bench_strict integration ───────────────────────────────────────────


class _StubRegistry:
    """Mimic the slice of ``Registry`` interface ``run_bench_strict`` uses."""

    def __init__(self, panel: dict[str, pd.DataFrame]) -> None:
        self._panel = panel

    def list(self, *, zoo: str) -> list[str]:  # noqa: ARG002
        return ["test_signal", "test_noise"]

    def get(self, aid: str) -> Any:
        class _Handle:
            meta = {"theme": ["test"], "formula_latex": f"stub_{aid}"}

        return _Handle()

    def compute(self, aid: str, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
        close = panel["close"]
        if aid == "test_signal":
            # Strong, persistent signal: copy of close itself
            # (cross-sectionally informative for "more recent close" semantics).
            return close
        return pd.DataFrame(
            np.random.default_rng(0).normal(size=close.shape),
            index=close.index,
            columns=close.columns,
        )


def _stub_panel(monkeypatch: pytest.MonkeyPatch, n_rows: int = 80, n_cols: int = 8) -> None:
    rng = np.random.default_rng(0)
    idx = pd.date_range("2024-01-01", periods=n_rows, freq="D")
    cols = [f"S{i}" for i in range(n_cols)]
    close = pd.DataFrame(
        100.0 + np.cumsum(rng.normal(size=(n_rows, n_cols)), axis=0),
        index=idx,
        columns=cols,
    )
    panel = {"close": close, "high": close * 1.01, "low": close * 0.99,
             "open": close, "volume": close * 0 + 1_000_000,
             "vwap": close, "amount": close * 1_000_000}
    monkeypatch.setattr(
        "src.factors.bench_runner_strict._load_universe_panel",
        lambda universe, period: panel,  # noqa: ARG005
    )

    def _fwd(panel_in: dict[str, pd.DataFrame]) -> pd.DataFrame:
        c = panel_in["close"]
        return c.pct_change().shift(-1)

    monkeypatch.setattr(
        "src.factors.bench_runner_strict._compute_forward_returns",
        _fwd,
    )


def test_run_bench_strict_returns_expected_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_panel(monkeypatch)
    reg = _StubRegistry(panel={})  # panel kwarg ignored by stub

    result = run_bench_strict(
        zoo="alpha101",
        universe="csi300",
        period="2024-2024",
        random_control=True,
        n_random_seeds=3,
        registry=reg,
    )

    assert result["status"] == "ok"
    assert result["random_control"] is True
    assert result["n_random_seeds"] == 3
    for key in ("confirmed_alive", "train_only", "reversed_strict", "noise"):
        assert key in result
    assert result["alpha_t_threshold"] == pytest.approx(2.0)
    assert "rows" in result and len(result["rows"]) == 2
    for row in result["rows"]:
        assert "alpha_t_full" in row
        assert "random_ic_mean" in row
        # OOS not requested in this test, so train/test stats are absent.
        assert row["alpha_t_train"] is None
        assert row["alpha_t_test"] is None


def test_run_bench_strict_respects_oos_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_panel(monkeypatch, n_rows=120)
    reg = _StubRegistry(panel={})
    result = run_bench_strict(
        zoo="alpha101",
        universe="csi300",
        period="2024-2024",
        random_control=True,
        n_random_seeds=2,
        oos_split="2024-03-01",
        registry=reg,
    )
    assert result["status"] == "ok"
    for row in result["rows"]:
        assert row["alpha_t_train"] is not None
        assert row["alpha_t_test"] is not None


def test_run_bench_strict_random_control_is_keyword_only() -> None:
    # Positional call should fail with TypeError because random_control is
    # keyword-only by construction. This locks the rail at the signature
    # level — exactly the pattern from Soli22de/Bili_Stock's foundation
    # Backtest(random_control=...) constructor.
    with pytest.raises(TypeError):
        run_bench_strict("alpha101", "csi300", "2024-2024", True)  # type: ignore[misc]


def test_run_bench_strict_random_control_false_is_explicit_opt_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Explicit False should run (degenerate baseline used for diagnostic
    # comparisons); just must be passed by name.
    _stub_panel(monkeypatch)
    reg = _StubRegistry(panel={})
    result = run_bench_strict(
        zoo="alpha101",
        universe="csi300",
        period="2024-2024",
        random_control=False,
        registry=reg,
    )
    assert result["status"] == "ok"
    assert result["random_control"] is False
    # When random_control is False, random_ic_mean degenerates to 0.
    for row in result["rows"]:
        assert row["random_ic_mean"] == pytest.approx(0.0)
