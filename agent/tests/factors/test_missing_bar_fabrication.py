"""No value may be computed from a window that holds a missing input (#1463).

``Registry.compute`` masks the bar a dependency is missing on, not the bars
after it. An alpha that turns a comparison into 0/1, calls ``.where(cond, 0)``
or takes ``np.fmax`` over a missing side substitutes a constant for the missing
input, and every later bar whose window reaches back to the gap then carries a
value that bar never supported.

Oracle: remove one symbol's dependencies on one bar, then perturb the same bar
up and down. A later cell of that symbol whose value moves with the perturbation
depends on the bar, so it must be NaN when the bar is missing. The panel is
dyadic (prices in sixteenths, integer volume) and differences are compared with a
tight tolerance, so pandas' online rolling sums carry no rounding residue that
would read as a dependence.

The recursive smoothers are held to a different rule, decided on #1463: a
statistic that carries state — the GTJA ``SMA(A, n, m)`` written as
``.ewm(alpha=m/n, adjust=False)``, a running product — skips the missing
observation and continues from its last state, so the bars after a gap carry a
value computed from the observations it saw. ``test_a_smoother_skips_the_gap``
pins that: the gap bar itself is NaN (the registry masks it), the next bar is
not, and the later values are not the gap-free ones.

Four alphas the sweep still flags — ``alpha101_013``, ``alpha101_016``,
``gtja191_083``, ``gtja191_099``, all ``rank(ts_cov(rank(x), rank(y), 5))`` —
are the oracle's own artifact, not a dependence: their flagged cells sit 10 to
241 bars past a 5-bar window, every one is a cross-sectional rank moving by
exactly 1/48 or 1/24, and the covariances agree to twelve decimals between the
two perturbed runs. Percentile ranks (k/24) are not dyadic, so the rolling
covariance carries a rounding residue that breaks a tie differently.

The perturbation oracle has a blind spot, found on 2026-09-21: a comparison
gate (``m20 < h``, ``(lhs < rhs).astype(float)``) does not move when the gap bar
moves by a tick, so a gate that reads a missing operand as "not less" looked
independent of the bar while it emitted a constant for the whole window. The
second oracle compares the gapped run with the gap-free one instead: a cell after
the gap that is finite and differs from its gap-free value was computed from the
gap. It found 22 more alphas; three more flagged cells (``alpha101_094``,
``alpha101_098``, ``gtja191_121``) sit 70 to 210 bars past every window and
come from correlations that differ by 1e-15 to 1e-12 between the two runs, the
same tie-breaking residue as the four above.

Those gates mask on their inputs' reach (``base.observed_over``), not on their
operands' NaN, so that a correlation that is undefined on complete data (a
constant window, common in a small universe) keeps the verdict it always had
(#1452). ``test_a_gate_keeps_its_verdict_on_complete_data`` pins that side.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.factors.registry import get_default_registry

FIXED = [
    "alpha101_065",
    "alpha101_071",
    "alpha101_073",
    "alpha101_076",
    "alpha101_082",
    "alpha101_087",
    "alpha101_092",
    "gtja191_043",
    "gtja191_049",
    "gtja191_050",
    "gtja191_051",
    "gtja191_053",
    "gtja191_058",
    "gtja191_084",
    "gtja191_094",
    "gtja191_098",
    "gtja191_112",
    "gtja191_128",
    "gtja191_129",
    "gtja191_148",
]

# 24 symbols: with fewer, a one-tick perturbation rarely flips a cross-sectional
# rank comparison, and the oracle would see no dependence at all.
_N, _T, _GAP, _SYMBOL = 24, 330, 250, 7
_PRICES = ("close", "open", "high", "low", "vwap")


def _base() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(1463)
    ticks = np.maximum(320 + np.cumsum(rng.integers(-6, 7, (_T, _N)), axis=0), 40)
    close = ticks / 16.0
    open_ = (ticks + rng.integers(-3, 4, (_T, _N))) / 16.0
    high = np.maximum(close, open_) + rng.integers(0, 4, (_T, _N)) / 16.0
    low = np.minimum(close, open_) - rng.integers(0, 4, (_T, _N)) / 16.0
    volume = rng.integers(1000, 50000, (_T, _N)).astype(float)
    vwap = (high + low + 2 * close) / 4.0
    base = {"close": close, "open": open_, "high": high, "low": low, "volume": volume, "vwap": vwap}
    # Drawn last so the price arrays above stay what they were.
    for name in ("fund:asset_growth", "fund:net_income", "fund:shares_diluted", "fund:gross_profitability", "fund:roe"):
        base[name] = rng.integers(32, 96, (_T, _N)) / 64.0
    return base


def _panel(
    base: dict[str, np.ndarray], deps: set[str], mode: str, symbol: int = _SYMBOL
) -> dict[str, pd.DataFrame]:
    index = pd.bdate_range("2020-01-01", periods=_T)
    columns = [f"S{i}" for i in range(_N)]
    panel = {}
    for name, values in base.items():
        array = values.copy()
        if name in deps and mode == "missing":
            array[_GAP, symbol] = np.nan
        elif name in deps and mode in ("up", "down"):
            # Eight ticks, still dyadic: large enough to flip a comparison with the
            # neighbouring bars, so up/down comparisons actually depend on the gap.
            step = 0.5 if name in _PRICES else (1.0 / 8.0 if name.startswith("fund:") else 4096.0)
            array[_GAP, symbol] += step if mode == "up" else -step
        panel[name] = pd.DataFrame(array, index=index, columns=columns)
    panel["amount"] = panel["vwap"] * panel["volume"]
    panel["sector"] = pd.DataFrame(np.tile(np.arange(_N) % 3, (_T, 1)), index=index, columns=columns)
    return panel


@pytest.mark.parametrize("alpha_id", FIXED)
def test_no_value_after_a_missing_bar_depends_on_it(alpha_id: str) -> None:
    registry = get_default_registry()
    deps = set(registry.get(alpha_id).meta.get("columns_required", []))
    base = _base()
    out = {
        mode: registry.compute(alpha_id, _panel(base, deps, mode)).iloc[_GAP:, _SYMBOL].to_numpy(dtype=float)
        for mode in ("missing", "up", "down")
    }

    moved = np.isfinite(out["up"]) != np.isfinite(out["down"])
    both = np.isfinite(out["up"]) & np.isfinite(out["down"])
    # A tolerance, not !=: a typical price divided by 3 is not dyadic, so a rolling
    # sum still carries a rounding residue far past the window (gtja191_128).
    moved[both] = ~np.isclose(out["up"][both], out["down"][both], rtol=1e-9, atol=1e-12)
    fabricated = np.flatnonzero(moved & np.isfinite(out["missing"]))

    assert moved.any(), "the perturbation reached no later bar; the oracle proves nothing"
    assert fabricated.size == 0, f"bars after the gap computed from it: {fabricated.tolist()}"


# The recursive statistics: 32 GTJA SMA(A, n, m) / EMA smoothers and one running product.
SMOOTHERS = [
    "gtja191_009",
    "gtja191_022",
    "gtja191_023",
    "gtja191_024",
    "gtja191_028",
    "gtja191_047",
    "gtja191_057",
    "gtja191_063",
    "gtja191_067",
    "gtja191_068",
    "gtja191_072",
    "gtja191_079",
    "gtja191_081",
    "gtja191_082",
    "gtja191_089",
    "gtja191_096",
    "gtja191_102",
    "gtja191_109",
    "gtja191_111",
    "gtja191_122",
    "gtja191_135",
    "gtja191_143",
    "gtja191_146",
    "gtja191_151",
    "gtja191_152",
    "gtja191_155",
    "gtja191_160",
    "gtja191_162",
    "gtja191_164",
    "gtja191_169",
    "gtja191_173",
    "gtja191_174",
    "gtja191_188",
]


@pytest.mark.parametrize("alpha_id", SMOOTHERS)
def test_a_smoother_skips_the_gap(alpha_id: str) -> None:
    """Skip and continue, not NaN until rewarmed: the policy set on #1463."""
    registry = get_default_registry()
    deps = set(registry.get(alpha_id).meta.get("columns_required", []))
    base = _base()
    clean = registry.compute(alpha_id, _panel(base, deps, "base")).iloc[:, _SYMBOL].to_numpy(dtype=float)
    gapped = registry.compute(alpha_id, _panel(base, deps, "missing")).iloc[:, _SYMBOL].to_numpy(dtype=float)

    assert np.isnan(gapped[_GAP]), "the registry masks the bar whose input is missing"
    # gtja191_146 averages the smoothed residual over a full 20-bar window, which
    # is NaN while it holds the gap; the smoother underneath it never stops.
    first = _GAP + (21 if alpha_id == "gtja191_146" else 1)
    assert np.isfinite(gapped[first:]).all(), "the smoother continued from its last state"
    both = np.isfinite(clean[first:]) & np.isfinite(gapped[first:])
    assert not np.allclose(clean[first:][both], gapped[first:][both], rtol=1e-9, atol=1e-12), (
        "the values after the gap were computed from the observations the smoother saw, not copied"
    )


# Flagged by the value oracle for a reason other than the gap: a rounding residue
# in a correlation of ranks that breaks a later rank tie differently, or (the
# alpha101_021 / gtja191_004 twins, 37 bars past a 20-bar reach) a rolling mean
# minus a rolling std that equals the 2-bar mean exactly on the gap-free run and
# misses it by 1e-14 on the gapped one.
RESIDUE_ARTIFACTS = {
    "alpha101_013",
    "alpha101_016",
    "alpha101_021",
    "alpha101_094",
    "alpha101_098",
    "gtja191_004",
    "gtja191_083",
    "gtja191_099",
    "gtja191_121",
}
# Declared partial windows: rolling(60, min_periods=20/30) and a >=90% coverage rule.
PARTIAL_WINDOWS = {"gtja191_025", "gtja191_033", "academic_corr_rewire"}
# The fallback benchmark is the cross-sectional mean of the closes present that day,
# so one symbol's missing close moves every symbol's "benchmark down" flag on the
# next bar. The symbol's own inputs are masked; the benchmark is left as it is.
BENCHMARK_FROM_THE_PANEL = {"gtja191_075", "gtja191_182"}


_VALUE_ORACLE_SYMBOLS = (_SYMBOL, 16)


def _all_alpha_ids() -> list[str]:
    return list(get_default_registry().list())


@pytest.mark.parametrize("alpha_id", _all_alpha_ids())
def test_no_finite_value_after_a_gap_differs_from_the_gap_free_one(alpha_id: str) -> None:
    """The value oracle: sees comparison gates the perturbation oracle cannot."""
    if alpha_id in set(SMOOTHERS) | RESIDUE_ARTIFACTS | PARTIAL_WINDOWS | BENCHMARK_FROM_THE_PANEL:
        pytest.skip("classified above: smoother, residue artifact, partial window or panel benchmark")
    registry = get_default_registry()
    deps = set(registry.get(alpha_id).meta.get("columns_required", []))
    base = _base()
    clean = registry.compute(alpha_id, _panel(base, deps, "base")).iloc[_GAP:].to_numpy(dtype=float)
    # A gate only shows when the substituted verdict differs from the true one, so
    # one symbol can miss it (alpha101_096's fmax is invisible on symbol 7).
    for symbol in _VALUE_ORACLE_SYMBOLS:
        gapped = registry.compute(alpha_id, _panel(base, deps, "missing", symbol))
        after = gapped.iloc[_GAP:, symbol].to_numpy(dtype=float)
        truth = clean[:, symbol]
        scale = np.maximum(1.0, np.abs(truth))
        moved = np.isfinite(after) & (~np.isfinite(truth) | (np.abs(after - truth) / scale > 1e-9))
        assert not moved.any(), (
            f"symbol {symbol}: finite bars after the gap that differ from the gap-free run: "
            f"{np.flatnonzero(moved).tolist()}"
        )


def test_the_value_oracle_exemptions_are_real_alphas() -> None:
    known = set(_all_alpha_ids())
    assert (RESIDUE_ARTIFACTS | PARTIAL_WINDOWS | BENCHMARK_FROM_THE_PANEL | set(SMOOTHERS)) <= known


# Each gate's longest input reach in bars (see the comment above its mask).
GATE_REACH = {
    "alpha101_061": 197,
    "alpha101_062": 50,
    "alpha101_064": 148,
    "alpha101_068": 36,
    "alpha101_074": 80,
    "alpha101_075": 61,
    "alpha101_079": 172,
    "alpha101_081": 80,
    "alpha101_086": 58,
    "alpha101_095": 81,
    "alpha101_099": 87,
    "gtja191_056": 60,
    "gtja191_101": 80,
    "gtja191_123": 87,
    "gtja191_154": 197,
}


def _small_float_panel(n_symbols: int = 5, n_rows: int = 400) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(5)
    index = pd.bdate_range("2021-01-01", periods=n_rows)
    columns = [f"S{i}" for i in range(n_symbols)]
    close = 50 * np.exp(np.cumsum(rng.normal(0, 0.02, (n_rows, n_symbols)), axis=0))
    open_ = close * np.exp(rng.normal(0, 0.005, (n_rows, n_symbols)))
    high = np.maximum(close, open_) * (1 + rng.uniform(0, 0.01, (n_rows, n_symbols)))
    low = np.minimum(close, open_) * (1 - rng.uniform(0, 0.01, (n_rows, n_symbols)))
    volume = rng.uniform(1e5, 1e6, (n_rows, n_symbols))
    frame = lambda values: pd.DataFrame(values, index=index, columns=columns)  # noqa: E731
    panel = {"close": frame(close), "open": frame(open_), "high": frame(high), "low": frame(low),
             "volume": frame(volume), "vwap": frame((high + low + 2 * close) / 4)}
    panel["amount"] = panel["vwap"] * panel["volume"]
    panel["sector"] = frame(np.tile(np.arange(n_symbols) % 3, (n_rows, 1)))
    return panel


@pytest.mark.parametrize("alpha_id", sorted(GATE_REACH))
def test_a_gate_keeps_its_verdict_on_complete_data(alpha_id: str) -> None:
    """#1452: masking on the operands' NaN would also blank constant-window correlations.

    Five symbols make a constant cross-sectional rank over a short window common,
    so a correlation of ranks is often undefined here although no input is missing.
    A gate masked on its inputs' reach is NaN for exactly its warmup and a 0/1
    verdict on every later bar.
    """
    out = get_default_registry().compute(alpha_id, _small_float_panel()).to_numpy(dtype=float)
    reach = GATE_REACH[alpha_id]

    assert np.isnan(out[: reach - 1]).all(), "a bar inside the inputs' reach produced a verdict"
    assert np.isfinite(out[reach - 1 :]).all(), "a verdict on complete data was blanked"
