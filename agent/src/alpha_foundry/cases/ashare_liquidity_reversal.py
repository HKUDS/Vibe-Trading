from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.alpha_foundry.dsl.parser import FormulaParser
from src.alpha_foundry.dsl.validator import validate_expression
from src.alpha_foundry.mechanisms import ASHARE_LIQUIDITY_REVERSAL_TEMPLATES
from src.research_ledger.hash_utils import canonical_json_hash
from src.research_ledger.trial_ledger import TrialLedger, TrialLedgerEntry


class TestSetAccessError(RuntimeError):
    """Raised if case search attempts to read the final test split."""

    __test__ = False


@dataclass(frozen=True)
class CaseCandidate:
    candidate_id: str
    formula: str
    formula_hash: str
    kind: str
    valid: bool
    validation_errors: list[str]
    rationale: str


@dataclass(frozen=True)
class AShareLiquidityReversalCaseResult:
    n_candidates: int
    candidate_ids: list[str]
    control_ids: list[str]
    candidates: list[CaseCandidate]
    ledger: TrialLedger
    artifact_root: str
    warnings: list[str]


def run_case_with_fixture(
    *,
    artifact_root: str | Path | None = None,
    force_test_access_in_search: bool = False,
) -> AShareLiquidityReversalCaseResult:
    if force_test_access_in_search:
        raise TestSetAccessError("search scope may not access final test data")

    root = Path(artifact_root) if artifact_root is not None else Path(tempfile.mkdtemp(prefix="ags_case_"))
    root.mkdir(parents=True, exist_ok=True)
    _fixture_panel()  # build fixture deterministically; search intentionally uses train/valid only.
    ledger = TrialLedger(root / "trial_ledger.sqlite")

    candidates: list[CaseCandidate] = []
    for ordinal, template in enumerate(ASHARE_LIQUIDITY_REVERSAL_TEMPLATES, start=1):
        ast = FormulaParser().parse(template.formula)
        validation = validate_expression(ast)
        formula_hash = canonical_json_hash({"formula": template.formula})
        candidate = CaseCandidate(
            candidate_id=template.candidate_id,
            formula=template.formula,
            formula_hash=formula_hash,
            kind=template.kind,
            valid=validation.ok,
            validation_errors=validation.errors,
            rationale=template.rationale,
        )
        candidates.append(candidate)
        ledger.append(_trial_record(candidate, ordinal))

    result = AShareLiquidityReversalCaseResult(
        n_candidates=len(candidates),
        candidate_ids=[c.candidate_id for c in candidates if c.kind == "candidate"],
        control_ids=[c.candidate_id for c in candidates if c.kind == "control"],
        candidates=candidates,
        ledger=ledger,
        artifact_root=str(root),
        warnings=[
            "fixture_only",
            "research case study only; not production-ready",
            "no final test split accessed during search",
        ],
    )
    _write_artifacts(root, result)
    return result


def _trial_record(candidate: CaseCandidate, ordinal: int) -> TrialLedgerEntry:
    status = "success" if candidate.valid else "reject"
    decision = "none" if candidate.valid else "reject"
    return TrialLedgerEntry(
        trial_id=f"ashare-liquidity-reversal-{ordinal:03d}",
        trial_group_id="ashare_liquidity_reversal",
        parent_trial_id=None,
        candidate_id=candidate.candidate_id,
        parent_seed_id="ashare_liquidity_reversal_templates",
        formula=candidate.formula,
        formula_hash=candidate.formula_hash,
        data_snapshot_hash="sha256:fixture",
        universe_hash="sha256:fixture_ashare",
        split_id="train_valid_fixture",
        data_scope="train_valid",
        search_space_hash=canonical_json_hash(
            {"case": "ashare_liquidity_reversal", "template_count": len(ASHARE_LIQUIDITY_REVERSAL_TEMPLATES)}
        ),
        objective="mechanism_first_fixture_case",
        random_seed=0,
        n_candidates_seen_so_far=ordinal,
        status=status,  # type: ignore[arg-type]
        decision=decision,  # type: ignore[arg-type]
        reason_codes=candidate.validation_errors,
        parameter_variant={"kind": candidate.kind, "rationale": candidate.rationale},
        metrics_summary={"valid": candidate.valid},
        previous_entry_hash=None,
        entry_hash="",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat(),
    )


def _write_artifacts(root: Path, result: AShareLiquidityReversalCaseResult) -> None:
    study = {
        "schema_version": "alpha_genesis_case_study.v1",
        "case_id": "ashare_liquidity_reversal",
        "n_candidates": result.n_candidates,
        "candidate_ids": result.candidate_ids,
        "control_ids": result.control_ids,
        "warnings": result.warnings,
        "trial_count": len(result.ledger.query()),
        "candidates": [asdict(candidate) for candidate in result.candidates],
    }
    (root / "alpha_genesis_case_study.json").write_text(
        json.dumps(study, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    with (root / "candidate_pool.jsonl").open("w", encoding="utf-8") as handle:
        for candidate in result.candidates:
            handle.write(json.dumps(asdict(candidate), sort_keys=True, ensure_ascii=False) + "\n")
    report = [
        "# A-share Liquidity Reversal Case",
        "",
        "This deterministic fixture case exercises mechanism-first candidate generation.",
        "It is not production-ready and is not live trading advice.",
        "",
        f"Candidates: {result.n_candidates}",
        f"Controls: {', '.join(result.control_ids)}",
        f"Trial records: {len(result.ledger.query())}",
        "",
        "Limitations: fixture-only data, no premium execution data, no final test split access during search.",
    ]
    (root / "alpha_genesis_comparison_report.md").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )


def _fixture_panel() -> dict[str, pd.DataFrame]:
    dates = pd.date_range("2024-01-01", periods=40, freq="D")
    symbols = [f"S{i}" for i in range(12)]
    base = pd.DataFrame(
        [[100.0 + day + symbol for symbol in range(len(symbols))] for day in range(len(dates))],
        index=dates,
        columns=symbols,
    )
    return {
        "close": base,
        "ret_1d": base.pct_change(fill_method=None),
        "volume": base * 1000.0,
        "amount": base * 10000.0,
    }
