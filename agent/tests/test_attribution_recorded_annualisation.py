"""Attribution uses the annualisation convention recorded by the real runner."""

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backtest.run_card import write_run_card
from src.api.attribution_core import _build_attribution_payload


@pytest.mark.parametrize("recorded_rate", [365, 8760, None])
def test_alpha_uses_recorded_run_rate(
    tmp_path: Path, recorded_rate: int | None
) -> None:
    config = {"codes": ["BTC-USDT"], "source": "okx", "interval": "1D"}
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    wealth = 1000.0
    with (artifacts / "equity.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "ret", "benchmark_equity"])
        for index in range(70):
            # Independent exact linear model: portfolio = 0.001 + 2 * benchmark.
            benchmark_return = (index % 7 - 3) / 1000 if index else 0.0
            wealth *= 1 + benchmark_return
            writer.writerow(
                [
                    (datetime(2024, 1, 1) + timedelta(days=index)).isoformat(),
                    0.001 + 2 * benchmark_return,
                    wealth,
                ]
            )
    if recorded_rate is not None:
        write_run_card(
            tmp_path, {**config, "_run_card_bars_per_year": recorded_rate}, {}
        )
    factor = _build_attribution_payload(tmp_path)["factor"]
    assert factor["alpha_per_period"] == pytest.approx(0.001, abs=1e-12)
    expected = 0.001 * (recorded_rate if recorded_rate is not None else 252)
    assert factor["alpha_annualized"] == pytest.approx(expected, abs=1e-12)
    assert factor["rolling"]
    for point in factor["rolling"]:
        assert point["alpha_annualized"] == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize(
    "annualisation",
    [
        None,
        "365",
        [],
        {},
        {"bars_per_year": 0},
        {"bars_per_year": -1},
        {"bars_per_year": float("inf")},
        {"bars_per_year": float("nan")},
        {"bars_per_year": "invalid"},
        {"bars_per_year": True},
    ],
)
def test_unusable_recorded_rates_keep_legacy_fallback(
    tmp_path: Path, annualisation
) -> None:
    test_alpha_uses_recorded_run_rate(tmp_path, None)
    (tmp_path / "run_card.json").write_text(
        json.dumps({"annualisation": annualisation}), encoding="utf-8"
    )
    factor = _build_attribution_payload(tmp_path)["factor"]
    assert factor["alpha_annualized"] == pytest.approx(0.252, abs=1e-12)
    assert all(
        point["alpha_annualized"] == pytest.approx(0.252, abs=1e-12)
        for point in factor["rolling"]
    )
