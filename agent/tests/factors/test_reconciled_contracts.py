"""Original-window, selected-sample and initialization regression oracles."""

import importlib

import numpy as np
import pandas as pd
import pytest

from src.factors.audit import audit_factors, reference_panel
from src.factors.base import downside_beta, geometric_wma
from src.factors.registry import Registry, SkipAlpha


@pytest.fixture(scope="module")
def panel():
    return reference_panel(bars=1200, symbols=24)


@pytest.mark.parametrize(
    "number,bars",
    [
        (25, 251),
        (26, 235),
        (33, 241),
        (39, 240),
        (45, 164),
        (56, 70),
        (61, 103),
        (64, 88),
        (74, 65),
        (75, 51),
        (77, 47),
        (91, 44),
        (92, 210),
        (98, 200),
    ],
)
def test_restored_windows_require_original_history(number, bars, panel):
    module = importlib.import_module(f"src.factors.zoo.gtja191.alpha_{number:03}")
    out = module.compute(panel)
    assert module.__alpha_meta__["min_warmup_bars"] == bars
    assert out.iloc[: bars - 1].isna().all().all()
    assert out.iloc[bars - 1 : bars + 10].notna().any().any()


def test_long_return_sums_use_250_and_240_observations(panel):
    from src.factors.base import decay_linear, ts_rank

    c, v, low = (panel[key] for key in ("close", "volume", "low"))
    ret = c.pct_change(fill_method=None)
    term = -(c.diff(7) * (1 - decay_linear(v / v.rolling(20).mean(), 9).rank(axis=1, pct=True))).rank(axis=1, pct=True)
    expected25 = term * (1 + ret.rolling(250).sum().rank(axis=1, pct=True))
    out25 = importlib.import_module("src.factors.zoo.gtja191.alpha_025").compute(panel)
    pd.testing.assert_frame_equal(out25, expected25, rtol=1e-10, atol=1e-10)
    returns = (ret.rolling(240).sum() - ret.rolling(20).sum()) / 220
    expected33 = (
        (-low.rolling(5).min() + low.rolling(5).min().shift(5)) * returns.rank(axis=1, pct=True) * ts_rank(v, 5)
    )
    out33 = importlib.import_module("src.factors.zoo.gtja191.alpha_033").compute(panel)
    pd.testing.assert_frame_equal(out33, expected33, rtol=1e-10, atol=1e-10)


def test_filter_beta_counts_down_observations_not_calendar_zeros():
    rng = np.random.default_rng(149)
    x = rng.uniform(-0.03, 0.02, 1200)
    y = 0.002 + 1.7 * x + rng.normal(0, 0.003, len(x))
    index = pd.bdate_range("2020-01-01", periods=len(x))
    bench = pd.DataFrame({"A": 100 * np.cumprod(1 + x)}, index=index)
    close = pd.DataFrame({"A": 40 * np.cumprod(1 + y)}, index=index)
    out = downside_beta(close, bench)
    selected = np.flatnonzero(x[1:] < 0) + 1
    first = selected[251]
    assert out.iloc[:first].isna().all().all()
    for end in (first, first + 1, 900, 1199):
        chosen = selected[selected <= end][-252:]
        expected = np.polyfit(x[chosen], y[chosen], 1)[0]
        assert out.iloc[end, 0] == pytest.approx(expected, abs=1e-10)
    pd.testing.assert_frame_equal(out.iloc[:700], downside_beta(close.iloc[:700], bench.iloc[:700]))
    gap = close.copy()
    gap.iloc[500, 0] = np.nan
    gapped = downside_beta(gap, bench)
    affected = [i for i in (500, 501) if x[i] < 0]
    if affected:
        last = max(affected)
        restore = selected[np.searchsorted(selected, last) + 252]
        assert gapped.iloc[last:restore].isna().all().all()
        assert gapped.iloc[restore:].notna().all().all()


def test_geometric_weights_and_real_three_factor_residuals(panel):
    sample = panel["close"].iloc[:30]
    weights = 0.9 ** np.arange(11, -1, -1)
    weights /= weights.sum()
    expected = sample.iloc[-12:].to_numpy().T @ weights
    np.testing.assert_allclose(geometric_wma(sample, 12).iloc[-1], expected)
    module = importlib.import_module("src.factors.zoo.gtja191.alpha_030")
    out = module.compute(panel)
    y = panel["close"].pct_change(fill_method=None).iloc[:, 0].to_numpy()
    x = np.column_stack([np.ones(len(y)), *[panel[key].iloc[:, 0] for key in ("mkt_ret", "smb", "hml")]])
    residuals = []
    for end in range(len(y) - 19, len(y) + 1):
        fit = np.linalg.lstsq(x[end - 60 : end], y[end - 60 : end], rcond=None)[0]
        residuals.append((y[end - 1] - x[end - 1] @ fit) ** 2)
    weights = 0.9 ** np.arange(19, -1, -1)
    weights /= weights.sum()
    assert out.iloc[-1, 0] == pytest.approx(np.dot(residuals, weights), abs=1e-12)
    with pytest.raises(SkipAlpha, match="extras"):
        Registry().compute("gtja191_030", {"close": panel["close"]})


def test_all_registered_sources_and_history_contracts_pass():
    report = audit_factors()
    assert report["count"] == len(Registry().list())
    assert not report["finding_count"], [(row["id"], row["findings"]) for row in report["rows"] if not row["valid"]]
    policies = {row["id"]: row for row in report["rows"]}
    assert policies["gtja191_173"]["minimum_bars"] == 1
    assert policies["gtja191_173"]["policy"] == "recursive_seed"
    assert policies["gtja191_149"]["policy"] == "conditional_sample"
    assert policies["academic_corr_rewire"]["policy"] == "partial_window"
