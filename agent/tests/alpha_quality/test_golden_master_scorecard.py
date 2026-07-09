from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.alpha_quality.model import FactorOutputFrame, SplitConfig
from src.alpha_quality.scorecard import compute_scorecard


GOLDEN_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "alpha_quality" / "scorecard_golden.v1.json"


def _fixture_panel() -> dict[str, pd.DataFrame]:
    dates = pd.date_range("2024-01-02", periods=18, freq="D")
    symbols = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    close = pd.DataFrame(
        [
            [100.0 + day * (idx + 1) * 0.25 + idx for idx in range(len(symbols))]
            for day in range(len(dates))
        ],
        index=dates,
        columns=symbols,
    )
    factor = pd.DataFrame(
        [[float((idx + day) % len(symbols)) for idx in range(len(symbols))] for day in range(len(dates))],
        index=dates,
        columns=symbols,
    )
    false = pd.DataFrame(False, index=dates, columns=symbols)
    return {
        "close": close,
        "factor": factor,
        "st_flag": false.copy(),
        "suspended": false.copy(),
        "limit_up": false.copy(),
        "limit_down": false.copy(),
        "listed_days": pd.DataFrame(90, index=dates, columns=symbols),
        "amount": pd.DataFrame(25_000.0, index=dates, columns=symbols),
    }


def _factor_output(panel: dict[str, pd.DataFrame]) -> FactorOutputFrame:
    factor = panel["factor"]
    valid = pd.DataFrame(True, index=factor.index, columns=factor.columns)
    return FactorOutputFrame(
        factor_id="golden_scorecard_signal",
        formula="rank(golden_fixture)",
        factor=factor,
        valid_mask=valid,
        tradable_mask=valid,
        universe_mask=valid,
        metadata={"fixture": "golden"},
        factor_definition_hash="sha256:golden-scorecard",
    )


def _split() -> SplitConfig:
    return SplitConfig(
        train=("2024-01-02", "2024-01-07"),
        valid=("2024-01-08", "2024-01-13"),
        test=("2024-01-14", "2024-01-18"),
    )


def _build_scorecard_payload() -> dict[str, object]:
    panel = _fixture_panel()
    scorecard = compute_scorecard(
        _factor_output(panel),
        panel,
        _split(),
        horizons=(1, 3),
        scope="final_quality_decision",
        data_snapshot_ref="sha256:golden-snapshot",
        trial_ledger_ref="sqlite:golden-ledger",
    )
    return json.loads(scorecard.to_json())


def test_scorecard_golden_master_contract_is_stable() -> None:
    expected = json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))

    assert _build_scorecard_payload() == expected
