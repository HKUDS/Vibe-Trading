"""Tests for the multiple-testing block wired into run_bench.

`n_alphas_tested` has been carried in the bench result since it was written and
has only ever been displayed. These tests pin the correction that now uses it,
and pin that adding it changed nothing else about the result.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from src.factors.bench_runner import run_bench
from src.quantlib.multipletesting import MIN_OBSERVATIONS, expected_maximum_sharpe


def _make_panel(n_symbols: int = 10, n_days: int = 120):
    rng = np.random.default_rng(42)
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
    symbols = [f"SYM{i:03d}" for i in range(n_symbols)]
    close = pd.DataFrame(
        np.cumsum(rng.standard_normal((n_days, n_symbols)), axis=0) + 100,
        index=dates,
        columns=symbols,
    )
    return {"close": close, "open": close, "high": close, "low": close, "volume": close}


def _setup(monkeypatch, n_alphas=8, n_days=120):
    panel = _make_panel(n_days=n_days)
    return_df = panel["close"].pct_change().shift(-1).iloc[:-1]
    rng = np.random.default_rng(7)

    reg = MagicMock()
    reg.list.return_value = [f"alpha_{i}" for i in range(n_alphas)]
    reg.get.return_value = MagicMock(meta={"theme": ["test"], "formula_latex": ""})
    reg.compute.side_effect = lambda aid, p: pd.DataFrame(
        rng.standard_normal(p["close"].shape), index=p["close"].index, columns=p["close"].columns
    )

    monkeypatch.setattr("src.factors.bench_runner._load_universe_panel", lambda u, p: panel)
    monkeypatch.setattr("src.factors.bench_runner._compute_forward_returns", lambda p: return_df)
    monkeypatch.setattr("src.factors.bench_runner.get_default_registry", lambda: reg)
    return reg


def test_bench_reports_a_multiple_testing_block(monkeypatch):
    reg = _setup(monkeypatch, n_alphas=8)
    result = run_bench("test_zoo", "mock", "2020-2021", registry=reg)

    assert result["status"] == "ok"
    block = result["multiple_testing"]
    assert block["applicable"] is True
    assert block["n_trials"] == result["n_alphas_tested"]
    assert block["statistic"] == "ic_information_ratio"


def test_the_haircut_is_exactly_the_expected_maximum_under_the_null(monkeypatch):
    reg = _setup(monkeypatch, n_alphas=10)
    result = run_bench("test_zoo", "mock", "2020-2021", registry=reg)
    block = result["multiple_testing"]

    irs = np.array([float(r["ir"]) for r in result["rows"]])
    expected = expected_maximum_sharpe(len(irs), float(irs.std(ddof=1)))

    assert block["expected_max_ir_under_null"] == pytest.approx(expected, abs=1e-6)
    assert block["ir_haircut"] == pytest.approx(block["best_ir"] - expected, abs=1e-6)


def test_the_best_alpha_named_by_the_block_is_the_best_alpha_in_the_rows(monkeypatch):
    reg = _setup(monkeypatch, n_alphas=12)
    result = run_bench("test_zoo", "mock", "2020-2021", registry=reg)
    block = result["multiple_testing"]

    best_by_ir = max(result["rows"], key=lambda r: r["ir"])
    assert block["best_id"] == best_by_ir["id"]
    assert block["best_ir"] == pytest.approx(best_by_ir["ir"])


def test_pure_noise_alphas_do_not_survive_deflation(monkeypatch):
    # Every alpha here is random noise against the returns, so the best IR of
    # the batch is the maximum of N draws and nothing more. The correction is
    # supposed to say so.
    reg = _setup(monkeypatch, n_alphas=16)
    result = run_bench("test_zoo", "mock", "2020-2021", registry=reg)
    block = result["multiple_testing"]

    assert block["deflated_probability"] is not None
    assert block["survives_deflation"] is False


def test_a_single_alpha_has_no_search_to_correct_for(monkeypatch):
    reg = _setup(monkeypatch, n_alphas=1)
    result = run_bench("test_zoo", "mock", "2020-2021", registry=reg)
    assert result["multiple_testing"]["applicable"] is False


def test_a_short_ic_sample_reports_no_deflated_statistic_rather_than_a_bad_one(monkeypatch):
    # Too few IC observations for the moments behind the statistic to mean
    # anything: the block must say so instead of returning a number.
    reg = _setup(monkeypatch, n_alphas=6, n_days=MIN_OBSERVATIONS + 2)
    result = run_bench("test_zoo", "mock", "2020-2021", registry=reg)
    block = result["multiple_testing"]

    if block["applicable"] and block["ic_observations"] < MIN_OBSERVATIONS:
        assert block["deflated_probability"] is None
        assert block["survives_deflation"] is None
        assert "note" in block


def test_wiring_the_block_in_did_not_change_any_existing_key(monkeypatch):
    reg = _setup(monkeypatch, n_alphas=5)
    result = run_bench("test_zoo", "mock", "2020-2021", registry=reg)

    # The keys the bench has always returned are all still present, and
    # `n_alphas_tested` still means what it always meant.
    for key in (
        "status", "n_alphas_tested", "n_skipped", "alive", "reversed", "dead",
        "by_theme", "top5_by_ir", "dead_examples", "rows", "skipped", "meta",
        "wall_seconds",
    ):
        assert key in result, f"existing key {key} disappeared"
    assert result["n_alphas_tested"] == len(result["rows"])
