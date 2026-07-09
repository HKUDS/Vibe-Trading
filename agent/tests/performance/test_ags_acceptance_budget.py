from __future__ import annotations

import time
from datetime import datetime, timezone

import pandas as pd

from src.alpha_foundry.dsl.operators import evaluate_formula
from src.alpha_quality.model import FactorOutputFrame, SplitConfig
from src.alpha_quality.scorecard import compute_scorecard
from src.research_ledger.trial_ledger import TrialLedger, TrialLedgerEntry


def _panel(n_dates: int = 32, n_symbols: int = 8) -> dict[str, pd.DataFrame]:
    dates = pd.date_range("2024-01-01", periods=n_dates, freq="D")
    symbols = [f"S{i}" for i in range(n_symbols)]
    close = pd.DataFrame(
        [[100.0 + day * (idx + 1) * 0.1 for idx in range(n_symbols)] for day in range(n_dates)],
        index=dates,
        columns=symbols,
    )
    false = pd.DataFrame(False, index=dates, columns=symbols)
    return {
        "close": close,
        "volume": pd.DataFrame(1_000.0, index=dates, columns=symbols),
        "factor": close.rank(axis=1),
        "st_flag": false.copy(),
        "suspended": false.copy(),
        "limit_up": false.copy(),
        "limit_down": false.copy(),
        "listed_days": pd.DataFrame(90, index=dates, columns=symbols),
        "amount": pd.DataFrame(50_000.0, index=dates, columns=symbols),
    }


def _factor_output(panel: dict[str, pd.DataFrame]) -> FactorOutputFrame:
    factor = panel["factor"]
    mask = pd.DataFrame(True, index=factor.index, columns=factor.columns)
    return FactorOutputFrame(
        factor_id="perf",
        formula="rank(close)",
        factor=factor,
        valid_mask=mask,
        tradable_mask=mask,
        universe_mask=mask,
        metadata={},
        factor_definition_hash="sha256:perf",
    )


def _entry(index: int) -> TrialLedgerEntry:
    return TrialLedgerEntry(
        trial_id=f"trial-{index}",
        trial_group_id="perf",
        parent_trial_id=None,
        candidate_id=f"candidate-{index}",
        parent_seed_id=None,
        formula="rank(close)",
        formula_hash=f"sha256:formula-{index}",
        data_snapshot_hash="sha256:snapshot",
        universe_hash="sha256:universe",
        split_id="train-valid",
        data_scope="train",
        search_space_hash="sha256:space",
        objective="rank_ic",
        random_seed=index,
        n_candidates_seen_so_far=index + 1,
        status="success",
        decision="research_only",
        reason_codes=[],
        metrics_summary={"rank_ic": 0.01},
        previous_entry_hash=None,
        entry_hash="",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat(),
    )


def test_dsl_validation_fixture_stays_under_acceptance_budget() -> None:
    panel = _panel()
    start = time.perf_counter()

    for _ in range(250):
        evaluate_formula("rank(close)", panel)

    assert time.perf_counter() - start < 2.0


def test_scorecard_fixture_stays_under_acceptance_budget() -> None:
    panel = _panel()
    split = SplitConfig(
        train=("2024-01-01", "2024-01-12"),
        valid=("2024-01-13", "2024-01-22"),
        test=("2024-01-23", "2024-01-31"),
    )
    start = time.perf_counter()

    scorecard = compute_scorecard(
        _factor_output(panel),
        panel,
        split,
        horizons=(1, 5),
        scope="final_quality_decision",
        data_snapshot_ref="sha256:perf-snapshot",
        trial_ledger_ref="sqlite:perf-ledger",
    )

    assert time.perf_counter() - start < 3.0
    assert len(scorecard.to_json().encode("utf-8")) < 100_000


def test_trial_ledger_fixture_stays_under_acceptance_budget(tmp_path) -> None:  # noqa: ANN001
    ledger = TrialLedger(tmp_path / "perf-ledger.sqlite")
    start = time.perf_counter()

    for index in range(80):
        ledger.append(_entry(index))

    assert time.perf_counter() - start < 6.0
    assert ledger.verify_hash_chain()
