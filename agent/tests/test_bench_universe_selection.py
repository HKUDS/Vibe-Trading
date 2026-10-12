"""Universe-support selection: fund:* alphas exclude with disclosure off sp500.

``--zoo fundamental --universe csi300`` used to hard-fail the whole bench
("Choose the S&P 500 universe") because the SEC-fed ``fund:*`` alphas cannot
be served there, while the mirror case — CN ``val:*`` alphas on sp500 —
skips cleanly per alpha. The runners now exclude the unservable alphas up
front, disclose them in the result envelope, and only error when nothing is
left to bench. ``_validate_bench_data_requirements`` stays as the backstop
for direct callers (its own pinned tests are untouched).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import numpy as np
import pandas as pd
import pytest

from src.tools.alpha_bench_tool import _split_alphas_by_universe_support

_SPECS = {
    "fund_us": {"columns_required": ["fund:roe"], "theme": ["quality"], "formula_latex": ""},
    "fund_cn": {"columns_required": ["val:pb"], "theme": ["value"], "formula_latex": ""},
    "px": {"columns_required": ["close"], "theme": ["momentum"], "formula_latex": ""},
}


def _registry(specs: dict[str, dict]) -> MagicMock:
    reg = MagicMock()
    reg.list.return_value = list(specs)
    reg.get.side_effect = lambda aid: SimpleNamespace(meta=specs[aid])
    return reg


# ── splitter ─────────────────────────────────────────────────────────────────


def test_splitter_keeps_everything_on_sp500() -> None:
    kept, excluded = _split_alphas_by_universe_support(_registry(_SPECS), list(_SPECS), "sp500")

    assert kept == list(_SPECS)
    assert excluded == []


@pytest.mark.parametrize("universe", ["csi300", "btc-usdt"])
def test_splitter_excludes_fund_alphas_off_sp500(universe: str) -> None:
    kept, excluded = _split_alphas_by_universe_support(_registry(_SPECS), list(_SPECS), universe)

    assert kept == ["fund_cn", "px"]
    assert excluded == ["fund_us"]


def test_splitter_treats_missing_columns_required_as_benchable() -> None:
    reg = _registry({"bare": {"theme": ["test"], "formula_latex": ""}})

    kept, excluded = _split_alphas_by_universe_support(reg, ["bare"], "csi300")

    assert kept == ["bare"]
    assert excluded == []


# ── run_bench ────────────────────────────────────────────────────────────────


def _panel() -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(7)
    dates = pd.date_range("2020-01-01", periods=120, freq="B")
    close = pd.DataFrame(
        np.cumsum(rng.standard_normal((120, 6)), axis=0) + 100.0,
        index=dates,
        columns=[f"SYM{i}" for i in range(6)],
    )
    return {"close": close}


def test_run_bench_excludes_with_disclosure_and_benches_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.factors.bench_runner import run_bench

    panel = _panel()
    monkeypatch.setattr("src.factors.bench_runner._load_universe_panel", lambda u, p: panel)
    monkeypatch.setattr(
        "src.factors.bench_runner._prepare_bench_panel", lambda reg, ids, pnl, u, p: pnl
    )
    monkeypatch.setenv("VIBE_TRADING_BENCH_WORKERS", "1")
    reg = _registry(_SPECS)
    rng = np.random.default_rng(11)
    reg.compute.side_effect = lambda aid, p: pd.DataFrame(
        rng.standard_normal(p["close"].shape), index=p["close"].index, columns=p["close"].columns
    )

    result = run_bench(zoo="fundamental", universe="csi300", period="2020-2021", registry=reg)

    assert result["status"] == "ok"
    assert result["universe_excluded"] == ["fund_us"]
    assert result["n_alphas_tested"] == 2


def test_run_bench_all_excluded_errors_before_loading_the_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.factors.bench_runner import run_bench

    fetch = Mock()
    monkeypatch.setattr("src.factors.bench_runner._load_universe_panel", fetch)
    reg = _registry({"fund_us": _SPECS["fund_us"]})

    result = run_bench(zoo="fundamental", universe="csi300", period="2020-2021", registry=reg)

    assert result["status"] == "error"
    assert "SEC US filings" in result["error"]
    assert result["universe_excluded"] == ["fund_us"]
    fetch.assert_not_called()


def test_run_bench_sp500_selection_is_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.factors.bench_runner import run_bench

    panel = _panel()
    monkeypatch.setattr("src.factors.bench_runner._load_universe_panel", lambda u, p: panel)
    monkeypatch.setattr(
        "src.factors.bench_runner._prepare_bench_panel", lambda reg, ids, pnl, u, p: pnl
    )
    monkeypatch.setenv("VIBE_TRADING_BENCH_WORKERS", "1")
    reg = _registry(_SPECS)
    rng = np.random.default_rng(13)
    reg.compute.side_effect = lambda aid, p: pd.DataFrame(
        rng.standard_normal(p["close"].shape), index=p["close"].index, columns=p["close"].columns
    )

    result = run_bench(zoo="fundamental", universe="sp500", period="2020-2021", registry=reg)

    assert result["status"] == "ok"
    assert "universe_excluded" not in result
    assert result["n_alphas_tested"] == 3


# ── tool path ────────────────────────────────────────────────────────────────


def test_tool_all_excluded_returns_error_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    import src.tools.alpha_bench_tool as tool

    reg = _registry({"fund_us": _SPECS["fund_us"]})
    monkeypatch.setattr("src.factors.registry.get_default_registry", lambda: reg)
    monkeypatch.setattr(tool, "_default_output_dir", lambda: tmp_path)
    load = Mock()
    monkeypatch.setattr(tool, "_load_universe_panel", load)

    result = tool.run_alpha_bench(universe="csi300", period="2020-2021", zoo="fundamental")

    assert result["status"] == "error"
    assert "SEC US filings" in result["error"]
    assert result["universe_excluded"] == ["fund_us"]
    load.assert_not_called()
