"""Bench runner injects ``fund:*`` panels so fundamental alphas can be benched."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from src.factors.bench_runner import (
    _fund_columns_for,
    _inject_fund_panels,
    run_bench,
)


def _price_panel(n_symbols: int = 8, n_days: int = 80) -> dict[str, pd.DataFrame]:
    # compute_ic_series drops dates with < 5 valid instruments; stay above it.
    rng = np.random.default_rng(7)
    dates = pd.date_range("2022-01-03", periods=n_days, freq="B")
    symbols = [f"SYM{i}.US" for i in range(n_symbols)]
    close = pd.DataFrame(
        np.cumsum(rng.standard_normal((n_days, n_symbols)), axis=0) + 100.0,
        index=dates,
        columns=symbols,
    )
    return {
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": close.abs(),
    }


def _fake_registry(columns_required: list[str]) -> MagicMock:
    reg = MagicMock()
    reg.list.return_value = ["fund_fake"]
    alpha = MagicMock()
    alpha.meta = {
        "theme": ["quality"],
        "formula_latex": "test",
        "columns_required": columns_required,
    }
    alpha.zoo = "fundamental"
    reg.get.return_value = alpha
    return reg


class TestFundColumnsFor:
    def test_collects_and_dedups_fund_columns(self):
        reg = _fake_registry(["close", "fund:roe", "fund:roe", "fund:net_income"])
        assert _fund_columns_for(reg, ["fund_fake"]) == ["fund:roe", "fund:net_income"]

    def test_empty_for_price_only_zoo(self):
        reg = _fake_registry(["close", "volume"])
        assert _fund_columns_for(reg, ["fund_fake"]) == []


class TestInjectFundPanels:
    def test_adds_frames_aligned_to_close(self):
        panel = _price_panel()
        close = panel["close"]
        # Loader returns a sparser frame (fewer dates, missing one symbol).
        sparse = pd.DataFrame(
            0.15,
            index=close.index[10:50],
            columns=list(close.columns[:-1]),
        )
        with patch(
            "backtest.loaders.fundamentals_loader.load_fundamental_panel",
            return_value={"roe": sparse},
        ) as loader:
            _inject_fund_panels(panel, ["fund:roe"], "2022-2022")

        loader.assert_called_once()
        assert "fund:roe" in panel
        injected = panel["fund:roe"]
        assert injected.index.equals(close.index)
        assert list(injected.columns) == list(close.columns)
        assert injected[close.columns[-1]].isna().all()  # missing symbol stays NaN

    def test_noop_without_close(self):
        panel: dict[str, pd.DataFrame] = {}
        _inject_fund_panels(panel, ["fund:roe"], "2022-2022")
        assert panel == {}


class TestRunBenchWithFundamentalAlpha:
    def test_fund_alpha_benches_after_injection(self):
        panel = _price_panel()
        close = panel["close"]
        rng = np.random.default_rng(11)
        roe = pd.DataFrame(
            rng.standard_normal(close.shape), index=close.index, columns=close.columns
        )

        reg = _fake_registry(["fund:roe"])
        reg.compute.side_effect = lambda aid, p: p["fund:roe"]

        with patch(
            "src.factors.bench_runner._load_universe_panel", return_value=panel
        ), patch(
            "backtest.loaders.fundamentals_loader.load_fundamental_panel",
            return_value={"roe": roe},
        ):
            result = run_bench(
                zoo="fundamental",
                universe="sp500",
                period="2022-2022",
                top=5,
                registry=reg,  # forces the sequential path
            )

        assert result["status"] == "ok"
        assert result["n_alphas_tested"] == 1
        assert result["n_skipped"] == 0

    def test_fund_alpha_skips_when_loader_fails(self):
        panel = _price_panel()
        reg = _fake_registry(["fund:roe"])
        # Alpha computes from the missing key -> KeyError -> counted as skip.
        reg.compute.side_effect = lambda aid, p: p["fund:roe"]

        with patch(
            "src.factors.bench_runner._load_universe_panel", return_value=panel
        ), patch(
            "backtest.loaders.fundamentals_loader.load_fundamental_panel",
            side_effect=RuntimeError("edgar down"),
        ):
            result = run_bench(
                zoo="fundamental",
                universe="sp500",
                period="2022-2022",
                top=5,
                registry=reg,
            )

        assert result["status"] == "ok"
        assert result["n_alphas_tested"] == 0
        assert result["n_skipped"] == 1
