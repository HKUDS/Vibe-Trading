"""Figures read back from a backtest an earlier turn finished are grounded; forged or edited ones are not.

Every value is synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.grounding import GroundingLedger
from src.tools.run_artifact_tool import read_run_artifact
from tests.test_grounding_backtest_outputs import EW, RP, _declared, _write_backtest

PRIOR = "20261026_230021_46_a7d6f2"
CURRENT = "20261026_231424_12_64857f"
REF = f"{PRIOR}/rp"


@pytest.fixture()
def reuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A finished earlier turn with two backtests, and a ledger for the next turn."""
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    monkeypatch.delenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", raising=False)
    prior = tmp_path / "runs" / PRIOR
    prior.mkdir(parents=True)
    (prior / "req.json").write_text(
        json.dumps({"prompt": "first", "context": {}}), encoding="utf-8"
    )
    _write_backtest(prior / "rp", RP)
    _write_backtest(
        prior / "ew", EW, weights=[("2024-01-02", 0.333333, 0.333333, 0.333334)]
    )
    current = tmp_path / "runs" / CURRENT
    current.mkdir()
    return (
        GroundingLedger(
            run_dir=current, user_message="profundizá el backtest anterior"
        ),
        prior,
    )


def _read(
    ledger: GroundingLedger, run_dir: Path, artifact: str, call_id: str, **kwargs
) -> dict:
    result = read_run_artifact(str(run_dir), artifact, **kwargs)
    ledger.ingest_tool_result(
        tool_name="read_run_artifact",
        arguments={"run_dir": str(run_dir), "artifact": artifact},
        result=result,
        call_id=call_id,
        success=True,
    )
    return json.loads(result)


def _observed(ledger: GroundingLedger, call_id: str) -> bool:
    return any(r.call_id == call_id and r.tool == "backtest" for r in ledger._evidence)


@pytest.mark.parametrize(
    "ref", [REF, f"{REF}/artifacts/metrics.csv", f"backtest::{REF}"]
)
def test_metrics_of_a_prior_backtest_ground_only_its_own_values(
    reuse, ref: str
) -> None:
    ledger, prior = reuse
    _read(ledger, prior / "rp", "metrics", "read-rp")
    _read(ledger, prior / "ew", "metrics", "read-ew")

    own = ledger.validate_final_answer(
        _declared("Sortino 1.133.", f"1.133 | observed | Sortino | {ref}")
    )
    invented = ledger.validate_final_answer(
        _declared("Sortino 1.190.", f"1.190 | observed | Sortino | {ref}")
    )
    other_run = ledger.validate_final_answer(
        _declared("Sortino 1.212.", f"1.212 | observed | Sortino | {ref}")
    )

    assert own.valid, own.issues
    assert not invented.valid and not other_run.valid


def test_unread_prior_run_grounds_nothing(reuse) -> None:
    ledger, _ = reuse
    assert not ledger.validate_final_answer(
        _declared("Sortino 1.133.", f"1.133 | observed | Sortino | {REF}")
    ).valid


def test_rows_read_from_a_prior_table_ground_only_what_was_shown(reuse) -> None:
    ledger, prior = reuse
    page = _read(
        ledger,
        prior / "rp",
        "target_positions",
        "read-w",
        max_rows=2,
        columns=["timestamp", "000001.SZ"],
    )
    assert page["returned_rows"] == 2
    table = f"{REF}/artifacts/target_positions.csv"
    shown = _declared("Peso inicial 38.97%.", f"38.97% | observed | peso | {table}")
    unseen = _declared("Peso 29.79%.", f"29.79% | observed | peso | {table}")
    assert ledger.validate_final_answer(shown).valid
    assert not ledger.validate_final_answer(unseen).valid


def test_edited_metrics_or_card_are_refused(reuse) -> None:
    ledger, prior = reuse
    metrics = prior / "rp" / "artifacts" / "metrics.csv"
    metrics.write_text(
        metrics.read_text(encoding="utf-8").replace("1.1329", "9.9999"),
        encoding="utf-8",
    )
    _read(ledger, prior / "rp", "metrics", "read-edited")
    assert not _observed(ledger, "read-edited")
    assert not ledger.validate_final_answer(
        _declared("Sortino 9.9999.", f"9.9999 | observed | Sortino | {REF}")
    ).valid


def test_extra_unmanifested_metric_cannot_enter_prior_run_evidence(reuse) -> None:
    ledger, prior = reuse
    metrics = prior / "rp" / "artifacts" / "metrics.csv"
    lines = metrics.read_text().splitlines()
    metrics.write_text(lines[0] + ",invented_metric\n" + lines[1] + ",7.654321\n")
    _read(ledger, prior / "rp", "metrics", "extra-metric")
    assert not _observed(ledger, "extra-metric")
    assert not ledger.validate_final_answer(
        _declared("Metric 7.654321.", f"7.654321 | observed | metric | {REF}")
    ).valid


def test_identically_named_runs_in_other_allowed_roots_keep_distinct_scopes(reuse, tmp_path, monkeypatch):
    ledger, prior = reuse
    other = tmp_path / "other" / PRIOR / "rp"
    _write_backtest(other, EW)
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path / "other"))
    _read(ledger, prior / "rp", "metrics", "original-root")
    _read(ledger, other, "metrics", "other-root")
    assert ledger.validate_final_answer(
        _declared("Sortino 1.133.", f"1.133 | observed | Sortino | {REF}")
    ).valid
    assert not ledger.validate_final_answer(
        _declared("Sortino 1.212.", f"1.212 | observed | Sortino | {REF}")
    ).valid
    assert ledger.validate_final_answer(
        _declared("Sortino 1.212.", f"1.212 | observed | Sortino | {other}")
    ).valid


def test_table_changed_or_unlisted_in_the_manifest_is_not_registered(reuse) -> None:
    ledger, prior = reuse
    changed = prior / "rp" / "artifacts" / "target_positions.csv"
    changed.write_text("timestamp,000001.SZ\n2024-01-02,0.4567\n", encoding="utf-8")
    card = json.loads((prior / "ew" / "run_card.json").read_text(encoding="utf-8"))
    card["artifacts"] = [
        e for e in card["artifacts"] if e["path"] != "artifacts/target_positions.csv"
    ]
    (prior / "ew" / "run_card.json").write_text(json.dumps(card), encoding="utf-8")
    _read(ledger, prior / "rp", "target_positions", "read-changed")
    _read(ledger, prior / "ew", "target_positions", "read-unlisted")
    assert not any("target_positions" in path for path in ledger._engine_tables)


def test_run_without_card_symlinked_card_or_outside_the_roots_is_not_adopted(
    reuse, tmp_path_factory: pytest.TempPathFactory
) -> None:
    ledger, prior = reuse
    (prior / "ew" / "run_card.json").unlink()
    foreign = tmp_path_factory.mktemp("foreign")
    _write_backtest(foreign / "rp", RP)
    (prior / "rp" / "run_card.json").unlink()
    (prior / "rp" / "run_card.json").symlink_to(foreign / "rp" / "run_card.json")
    _read(ledger, prior / "ew", "metrics", "no-card")
    _read(ledger, prior / "rp", "metrics", "linked-card")
    ledger._adopt_prior_backtest(str(foreign / "rp"), "outside-roots")
    assert not any(
        _observed(ledger, call) for call in ("no-card", "linked-card", "outside-roots")
    )


@pytest.mark.parametrize(
    "target",
    ["run_card.json", "artifacts/metrics.csv", "artifacts/target_positions.csv"],
)
@pytest.mark.parametrize("tool", ["write_file", "edit_file"])
def test_a_file_the_model_wrote_in_the_prior_run_is_never_evidence(
    reuse, tool: str, target: str
) -> None:
    ledger, prior = reuse
    path = prior / "rp" / target
    ledger.ingest_tool_result(
        tool_name=tool,
        arguments={"path": str(path)},
        result=json.dumps({"status": "ok", "path": str(path)}),
        call_id="model-wrote",
        success=True,
    )
    _read(ledger, prior / "rp", "target_positions", "read-after-write")
    if target.endswith("target_positions.csv"):
        assert str(path.resolve()) not in ledger._engine_tables
    else:
        assert not _observed(ledger, "read-after-write")
