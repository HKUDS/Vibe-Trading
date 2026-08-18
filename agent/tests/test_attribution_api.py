"""API tests for GET /runs/{run_id}/attribution.

Synthetic run directories are built under a temporary RUNS_ROOT following the
artifact layout of real runs: equity.csv (timestamp, ret, equity, drawdown,
benchmark_equity, active_ret), positions.csv (timestamp + per-symbol weights),
ohlcv_<SYMBOL>.csv (trade_date, open, high, low, close, volume), metrics.csv
(single wide row), and config.json.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pytest
from fastapi.testclient import TestClient

import api_server

SYMBOL_A = "SYMA.US"
SYMBOL_B = "SYMB.US"
N_BARS = 120


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(api_server, "RUNS_DIR", tmp_path / "runs")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _write_csv(path: Path, header: List[str], rows: List[List[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _trading_dates(count: int, start: str = "2024-01-01") -> List[str]:
    import pandas as pd

    return [day.strftime("%Y-%m-%d") for day in pd.bdate_range(start, periods=count)]


def _write_ohlcv(run_dir: Path, symbol: str, dates: List[str], first_close: float, last_close: float) -> None:
    span = len(dates) - 1
    rows = []
    for index, day in enumerate(dates):
        close = first_close + (last_close - first_close) * index / span
        rows.append([day, f"{close:.4f}", f"{close + 1:.4f}", f"{close - 1:.4f}", f"{close:.4f}", "1000"])
    _write_csv(run_dir / "artifacts" / f"ohlcv_{symbol}.csv", ["trade_date", "open", "high", "low", "close", "volume"], rows)


def _write_equity(run_dir: Path, dates: List[str], portfolio_returns: np.ndarray, benchmark_returns: np.ndarray) -> None:
    rows = []
    equity = 1_000_000.0
    benchmark_equity = 1_000_000.0
    for index, day in enumerate(dates):
        equity *= 1.0 + portfolio_returns[index]
        benchmark_equity *= 1.0 + benchmark_returns[index]
        rows.append(
            [
                day,
                f"{portfolio_returns[index]:.12f}",
                f"{equity:.6f}",
                "0.0",
                f"{benchmark_equity:.12f}",
                f"{portfolio_returns[index] - benchmark_returns[index]:.12f}",
            ]
        )
    _write_csv(
        run_dir / "artifacts" / "equity.csv",
        ["timestamp", "ret", "equity", "drawdown", "benchmark_equity", "active_ret"],
        rows,
    )


def _write_config(run_dir: Path, codes: List[str], benchmark: Any = None) -> None:
    config: Dict[str, Any] = {
        "codes": codes,
        "interval": "1D",
        "source": "yfinance",
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
    }
    if benchmark is not None:
        config["benchmark"] = benchmark
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")


def _write_metrics(run_dir: Path, extra: Dict[str, str] | None = None) -> None:
    header = ["total_return", "sharpe", "benchmark_return", "excess_return"]
    values = ["0.1", "1.0", "0.05", "0.05"]
    if extra:
        header.extend(extra.keys())
        values.extend(extra.values())
    _write_csv(run_dir / "artifacts" / "metrics.csv", header, [values])


def _build_auto_run(tmp_path: Path, run_id: str, n_bars: int = N_BARS) -> Path:
    """Auto-benchmark run: portfolio ret = 0.001 + 1.2 * benchmark ret exactly."""
    run_dir = tmp_path / "runs" / run_id
    rng = np.random.default_rng(7)
    benchmark = rng.normal(0.0005, 0.01, n_bars)
    benchmark[0] = 0.0
    portfolio = 0.001 + 1.2 * benchmark
    dates = _trading_dates(n_bars)

    _write_equity(run_dir, dates, portfolio, benchmark)
    _write_csv(
        run_dir / "artifacts" / "positions.csv",
        ["timestamp", SYMBOL_A, SYMBOL_B],
        [[day, "0.7", "0.3"] for day in dates],
    )
    # Exact cumulative returns: SYMA +10%, SYMB +5%, so the symbol-mode Brinson
    # numbers are clean decimals that survive 6-decimal response rounding.
    _write_ohlcv(run_dir, SYMBOL_A, dates, 100.0, 110.0)
    _write_ohlcv(run_dir, SYMBOL_B, dates, 100.0, 105.0)
    _write_config(run_dir, [SYMBOL_A, SYMBOL_B])
    _write_metrics(run_dir)
    return run_dir


def _build_explicit_run(tmp_path: Path, run_id: str) -> Path:
    """Explicit-benchmark run across two asset classes with weights < 1 (cash)."""
    run_dir = tmp_path / "runs" / run_id
    benchmark = np.array([0.001 if i % 2 else -0.001 for i in range(N_BARS)])
    benchmark[0] = 0.0
    portfolio = 0.0005 + 0.8 * benchmark
    dates = _trading_dates(N_BARS)

    _write_equity(run_dir, dates, portfolio, benchmark)
    _write_csv(
        run_dir / "artifacts" / "positions.csv",
        ["timestamp", "600519.SH", "AAPL.US"],
        [[day, "0.4", "0.3"] for day in dates],
    )
    _write_ohlcv(run_dir, "600519.SH", dates, 100.0, 120.0)
    _write_ohlcv(run_dir, "AAPL.US", dates, 100.0, 90.0)
    _write_config(run_dir, ["600519.SH", "AAPL.US"], benchmark="000300.SH")
    _write_metrics(run_dir, extra={"benchmark_ticker": "000300.SH"})
    return run_dir


def test_attribution_auto_mode_factor_and_symbol_brinson(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _build_auto_run(tmp_path, "attr-auto")

    response = client.get("/runs/attr-auto/attribution")

    assert response.status_code == 200
    data = response.json()
    assert data["exists"] is True
    assert data["benchmark"] == {"ticker": None, "mode": "auto_equal_weight"}

    factor = data["factor"]
    assert factor is not None
    assert factor["beta"] == pytest.approx(1.2, abs=1e-8)
    assert factor["alpha_per_period"] == pytest.approx(0.001, abs=1e-8)
    assert factor["alpha_annualized"] == pytest.approx(0.001 * 252, abs=1e-6)
    assert factor["r_squared"] == pytest.approx(1.0, abs=1e-9)
    assert factor["n_obs"] == N_BARS
    assert factor["rolling_window"] == 60
    assert factor["rolling"] is not None
    assert len(factor["rolling"]) == N_BARS - 60 + 1
    assert len(factor["cumulative"]) == N_BARS
    assert factor["cumulative"][-1]["date"] == _trading_dates(N_BARS)[-1]

    brinson = data["brinson"]
    assert brinson is not None
    assert brinson["mode"] == "symbol"
    assert brinson["portfolio_return"] == pytest.approx(0.085, abs=1e-9)
    assert brinson["benchmark_return"] == pytest.approx(0.075, abs=1e-9)
    assert brinson["active_return"] == pytest.approx(0.01, abs=1e-9)
    assert brinson["allocation"] == pytest.approx(0.01, abs=1e-9)
    # Symbol mode: per-symbol portfolio and benchmark sector returns coincide,
    # so selection and interaction vanish by construction.
    assert brinson["selection"] == pytest.approx(0.0, abs=1e-12)
    assert brinson["interaction"] == pytest.approx(0.0, abs=1e-12)
    assert abs(brinson["allocation"] + brinson["selection"] + brinson["interaction"] - brinson["active_return"]) < 1e-9
    sectors = {sector["sector"]: sector for sector in brinson["sectors"]}
    assert set(sectors) == {SYMBOL_A, SYMBOL_B}
    assert sectors[SYMBOL_A]["portfolio_weight"] == pytest.approx(0.7, abs=1e-9)
    assert sectors[SYMBOL_A]["benchmark_weight"] == pytest.approx(0.5, abs=1e-9)
    assert sectors[SYMBOL_A]["portfolio_return"] == pytest.approx(0.10, abs=1e-9)
    assert all(sector["selection"] == pytest.approx(0.0, abs=1e-12) for sector in brinson["sectors"])
    assert any("symbol-mode" in note for note in data["notes"])


def test_attribution_explicit_mode_asset_class_with_cash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _build_explicit_run(tmp_path, "attr-explicit")

    response = client.get("/runs/attr-explicit/attribution")

    assert response.status_code == 200
    data = response.json()
    assert data["exists"] is True
    assert data["benchmark"] == {"ticker": "000300.SH", "mode": "explicit"}
    assert data["factor"] is not None
    assert data["factor"]["beta"] == pytest.approx(0.8, abs=1e-6)

    brinson = data["brinson"]
    assert brinson is not None
    assert brinson["mode"] == "asset_class"
    sectors = {sector["sector"]: sector for sector in brinson["sectors"]}
    assert "Cash" in sectors
    assert sectors["Cash"]["portfolio_weight"] == pytest.approx(0.3, abs=1e-9)
    assert sectors["Cash"]["benchmark_weight"] == pytest.approx(0.0, abs=1e-9)
    assert sectors["a_share"]["benchmark_weight"] == pytest.approx(1.0, abs=1e-9)
    assert sectors["a_share"]["portfolio_return"] == pytest.approx(0.20, abs=1e-9)
    assert sectors["us_equity"]["portfolio_return"] == pytest.approx(-0.10, abs=1e-9)
    # Response floats are rounded to 6 decimals, so the exact tie-out identity
    # holds here within combined rounding error rather than machine epsilon.
    assert (
        abs(brinson["allocation"] + brinson["selection"] + brinson["interaction"] - brinson["active_return"]) < 1e-5
    )
    assert any("buy-and-hold approximation" in note for note in data["notes"])


def test_attribution_exists_false_without_equity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    run_dir = tmp_path / "runs" / "attr-no-equity"
    _write_config(run_dir, [SYMBOL_A])

    response = client.get("/runs/attr-no-equity/attribution")

    assert response.status_code == 200
    data = response.json()
    assert data["exists"] is False
    assert data["benchmark"] is None
    assert data["factor"] is None
    assert data["brinson"] is None
    assert any("equity.csv" in note for note in data["notes"])


def test_attribution_unknown_run_returns_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)

    response = client.get("/runs/does-not-exist/attribution")

    assert response.status_code == 404


def test_attribution_traversal_run_id_returns_400(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)

    response = client.get("/runs/foo.bar/attribution")

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid run_id"


def test_attribution_degrades_without_positions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    run_dir = tmp_path / "runs" / "attr-no-positions"
    rng = np.random.default_rng(11)
    benchmark = rng.normal(0.0004, 0.008, N_BARS)
    benchmark[0] = 0.0
    portfolio = 0.0002 + 0.9 * benchmark
    dates = _trading_dates(N_BARS)
    _write_equity(run_dir, dates, portfolio, benchmark)
    _write_config(run_dir, [SYMBOL_A])
    _write_metrics(run_dir)

    response = client.get("/runs/attr-no-positions/attribution")

    assert response.status_code == 200
    data = response.json()
    assert data["exists"] is True
    assert data["factor"] is not None
    assert data["factor"]["beta"] == pytest.approx(0.9, abs=1e-6)
    assert data["brinson"] is None
    assert any("positions.csv" in note for note in data["notes"])


def test_attribution_long_series_downsampled_with_last_point_pinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    long_bars = 900
    _build_auto_run(tmp_path, "attr-long", n_bars=long_bars)

    response = client.get("/runs/attr-long/attribution")

    assert response.status_code == 200
    factor = response.json()["factor"]
    assert factor is not None
    assert factor["n_obs"] == long_bars
    assert len(factor["rolling"]) <= 500
    assert len(factor["cumulative"]) <= 500
    last_date = _trading_dates(long_bars)[-1]
    assert factor["rolling"][-1]["date"] == last_date
    assert factor["cumulative"][-1]["date"] == last_date
    rng = np.random.default_rng(7)
    benchmark = rng.normal(0.0005, 0.01, long_bars)
    benchmark[0] = 0.0
    expected_total = float(np.prod(1.0 + (0.001 + 1.2 * benchmark)) - 1.0)
    assert factor["cumulative"][-1]["portfolio"] == pytest.approx(expected_total, abs=1e-6)


def _build_market_neutral_run(tmp_path: Path, run_id: str) -> Path:
    """Explicit-benchmark run whose only asset class nets to zero (+0.5/-0.5 pair)."""
    run_dir = tmp_path / "runs" / run_id
    benchmark = np.array([0.001 if i % 2 else -0.001 for i in range(N_BARS)])
    benchmark[0] = 0.0
    portfolio = 0.0005 + 0.8 * benchmark
    dates = _trading_dates(N_BARS)

    _write_equity(run_dir, dates, portfolio, benchmark)
    _write_csv(
        run_dir / "artifacts" / "positions.csv",
        ["timestamp", SYMBOL_A, SYMBOL_B],
        [[day, "0.5", "-0.5"] for day in dates],
    )
    _write_ohlcv(run_dir, SYMBOL_A, dates, 100.0, 110.0)
    _write_ohlcv(run_dir, SYMBOL_B, dates, 100.0, 95.0)
    _write_config(run_dir, [SYMBOL_A, SYMBOL_B], benchmark="SPY.US")
    _write_metrics(run_dir, extra={"benchmark_ticker": "SPY.US"})
    return run_dir


def test_attribution_market_neutral_pair_degrades_instead_of_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A +0.5/-0.5 pair nets its asset-class weight to zero: the class return
    would divide by zero, so asset-class mode must degrade, not 500."""
    client = _client(tmp_path, monkeypatch)
    _build_market_neutral_run(tmp_path, "attr-pair")

    response = client.get("/runs/attr-pair/attribution")

    assert response.status_code == 200
    data = response.json()
    assert data["exists"] is True
    assert data["factor"] is not None
    assert data["factor"]["beta"] == pytest.approx(0.8, abs=1e-6)
    brinson = data["brinson"]
    assert brinson is not None
    assert brinson["mode"] == "invested_cash"
    sectors = {sector["sector"]: sector for sector in brinson["sectors"]}
    assert sectors["invested"]["portfolio_weight"] == pytest.approx(1.0, abs=1e-9)
    assert any("invested/cash" in note for note in data["notes"])


def test_attribution_benchmark_equity_starting_at_zero_skips_brinson(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """benchmark_equity[0] == 0 would divide by zero in the cumulative return;
    the endpoint must skip Brinson with a note instead of crashing."""
    client = _client(tmp_path, monkeypatch)
    run_dir = tmp_path / "runs" / "attr-zero-bench"
    dates = _trading_dates(N_BARS)
    rows = [
        [day, "0.001", f"{1_000_000.0 + index:.6f}", "0.0", f"{index:.6f}", "0.0005"]
        for index, day in enumerate(dates)
    ]
    _write_csv(
        run_dir / "artifacts" / "equity.csv",
        ["timestamp", "ret", "equity", "drawdown", "benchmark_equity", "active_ret"],
        rows,
    )
    _write_csv(
        run_dir / "artifacts" / "positions.csv",
        ["timestamp", SYMBOL_A],
        [[day, "0.6"] for day in dates],
    )
    _write_ohlcv(run_dir, SYMBOL_A, dates, 100.0, 110.0)
    _write_config(run_dir, [SYMBOL_A], benchmark="SPY.US")
    _write_metrics(run_dir, extra={"benchmark_ticker": "SPY.US"})

    response = client.get("/runs/attr-zero-bench/attribution")

    assert response.status_code == 200
    data = response.json()
    assert data["exists"] is True
    assert data["brinson"] is None
    assert any("non-positive" in note for note in data["notes"])


def test_attribution_artifact_symbol_path_traversal_is_contained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Symbols from positions.csv headers are interpolated into ohlcv file
    names; traversal-shaped symbols must be ignored, not resolved as paths.

    The fixture plants ``run_dir/target.csv`` plus an ``artifacts/ohlcv_x``
    directory so that on unpatched code the symbol ``x/../../target`` would
    resolve to ``ohlcv_x/../../target.csv`` == ``run_dir/target.csv`` and leak
    its return series into the Brinson sectors.
    """
    client = _client(tmp_path, monkeypatch)
    run_dir = tmp_path / "runs" / "attr-traversal"
    dates = _trading_dates(N_BARS)
    rng = np.random.default_rng(13)
    benchmark = rng.normal(0.0004, 0.008, N_BARS)
    benchmark[0] = 0.0
    portfolio = 0.0002 + 0.9 * benchmark
    _write_equity(run_dir, dates, portfolio, benchmark)
    (run_dir / "artifacts" / "ohlcv_x").mkdir(parents=True)
    _write_csv(run_dir / "target.csv", ["trade_date", "close"], [[dates[0], "100.0"], [dates[-1], "999.0"]])
    _write_csv(
        run_dir / "artifacts" / "positions.csv",
        ["timestamp", SYMBOL_A, "x/../../target"],
        [[day, "0.6", "0.4"] for day in dates],
    )
    _write_ohlcv(run_dir, SYMBOL_A, dates, 100.0, 110.0)
    _write_config(run_dir, [SYMBOL_A, "x/../../target"])
    _write_metrics(run_dir)

    response = client.get("/runs/attr-traversal/attribution")

    assert response.status_code == 200
    data = response.json()
    assert data["exists"] is True
    brinson = data["brinson"]
    assert brinson is not None
    assert brinson["mode"] == "symbol"
    sectors = {sector["sector"]: sector for sector in brinson["sectors"]}
    assert set(sectors) == {SYMBOL_A, "Cash"}
