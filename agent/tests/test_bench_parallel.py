"""Tests for parallel bench runner (ProcessPoolExecutor path)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from src.factors.bench_runner import _compute_single_alpha, _init_bench_worker


def _make_mock_panel(n_symbols: int = 10, n_days: int = 100):
    np.random.seed(42)
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
    symbols = [f"SYM{i:03d}" for i in range(n_symbols)]
    close = pd.DataFrame(
        np.cumsum(np.random.randn(n_days, n_symbols), axis=0) + 100,
        index=dates,
        columns=symbols,
    )
    return {"close": close, "open": close, "high": close, "low": close, "volume": close}


class TestComputeSingleAlpha:
    def test_returns_result_dict(self):
        panel = _make_mock_panel()
        close = panel["close"]
        return_df = close.pct_change().shift(-1).iloc[:-1]

        with patch("src.factors.bench_runner.get_default_registry") as mock_reg:
            reg = MagicMock()
            mock_reg.return_value = reg
            reg.compute.return_value = close * np.random.randn(*close.shape)
            reg.get.return_value = MagicMock(meta={"theme": ["test"]})

            result = _compute_single_alpha(("alpha_0", panel, return_df))
            assert "row" in result or "skip" in result

    def test_uses_initialized_worker_inputs(self):
        panel = _make_mock_panel()
        close = panel["close"]
        return_df = close.pct_change().shift(-1).iloc[:-1]
        _init_bench_worker(panel, return_df)

        with patch("src.factors.bench_runner.get_default_registry") as mock_reg:
            reg = MagicMock()
            mock_reg.return_value = reg
            reg.compute.return_value = close * np.random.randn(*close.shape)
            reg.get.return_value = MagicMock(meta={"theme": ["test"]})

            result = _compute_single_alpha("alpha_0")
            assert "row" in result or "skip" in result

    def test_returns_skip_on_exception(self):
        panel = _make_mock_panel()
        return_df = pd.DataFrame()

        with patch("src.factors.bench_runner.get_default_registry") as mock_reg:
            reg = MagicMock()
            mock_reg.return_value = reg
            reg.compute.side_effect = RuntimeError("test error")

            result = _compute_single_alpha(("alpha_0", panel, return_df))
            assert "skip" in result
            assert "test error" in result["skip"]["reason"]


class TestParallelBench:
    def _setup_mocks(self, monkeypatch, n_alphas=5):
        panel = _make_mock_panel()
        return_df = panel["close"].pct_change().shift(-1).iloc[:-1]
        alpha_ids = [f"alpha_{i}" for i in range(n_alphas)]

        mock_reg = MagicMock()
        mock_reg.list.return_value = alpha_ids
        mock_reg.get.return_value = MagicMock(meta={"theme": ["test"], "formula_latex": ""})
        mock_reg.compute.side_effect = lambda aid, p: p["close"] * np.random.randn(*p["close"].shape)

        monkeypatch.setattr("src.factors.bench_runner._load_universe_panel", lambda u, p: panel)
        monkeypatch.setattr("src.factors.bench_runner._compute_forward_returns", lambda p: return_df)
        monkeypatch.setattr("src.factors.bench_runner.get_default_registry", lambda: mock_reg)
        return mock_reg

    def test_parallel_matches_sequential(self, monkeypatch):
        from src.factors.bench_runner import run_bench

        mock_reg = self._setup_mocks(monkeypatch)

        monkeypatch.setenv("VIBE_TRADING_BENCH_WORKERS", "1")
        seq = run_bench("test_zoo", "mock", "2020-2021")

        monkeypatch.setenv("VIBE_TRADING_BENCH_WORKERS", "2")
        par = run_bench("test_zoo", "mock", "2020-2021")

        assert seq["status"] == "ok"
        assert par["status"] == "ok"
        assert seq["n_alphas_tested"] == par["n_alphas_tested"]

    def test_progress_callback_fires(self, monkeypatch):
        from src.factors.bench_runner import run_bench

        mock_reg = self._setup_mocks(monkeypatch, n_alphas=3)
        monkeypatch.setenv("VIBE_TRADING_BENCH_WORKERS", "2")

        calls = []
        result = run_bench(
            "test_zoo", "mock", "2020-2021",
            registry=mock_reg,
            on_progress=lambda n, t, a: calls.append((n, t, a)),
        )
        assert result["status"] == "ok"
        assert len(calls) == 3

    def test_only_filter_with_parallel(self, monkeypatch):
        from src.factors.bench_runner import run_bench

        mock_reg = self._setup_mocks(monkeypatch, n_alphas=5)
        monkeypatch.setenv("VIBE_TRADING_BENCH_WORKERS", "2")

        result = run_bench(
            "test_zoo", "mock", "2020-2021",
            registry=mock_reg,
            only=["alpha_0", "alpha_2"],
        )
        assert result["status"] == "ok"
        tested_ids = {r["id"] for r in result["rows"]}
        assert tested_ids <= {"alpha_0", "alpha_2"}

    def test_custom_registry_forces_sequential(self, monkeypatch):
        from src.factors.bench_runner import run_bench

        mock_reg = self._setup_mocks(monkeypatch, n_alphas=2)
        monkeypatch.setenv("VIBE_TRADING_BENCH_WORKERS", "2")

        result = run_bench("test_zoo", "mock", "2020-2021", registry=mock_reg)

        assert result["status"] == "ok"
        assert mock_reg.compute.call_count == 2

    def test_invalid_worker_env_falls_back(self, monkeypatch):
        from src.factors.bench_runner import run_bench

        mock_reg = self._setup_mocks(monkeypatch, n_alphas=2)
        monkeypatch.setenv("VIBE_TRADING_BENCH_WORKERS", "not-an-int")

        result = run_bench("test_zoo", "mock", "2020-2021", registry=mock_reg)

        assert result["status"] == "ok"
