"""A backtest's own output grounds the report written about it.

Regression history (2026-09-29): a reporter's risk-parity vs equal-weight
backtest came back as the canned refusal. Replaying the 15 DeepSeek runs of that
prompt through the gate showed why: 4 of 5 rejected figures were values the
backtest itself wrote — Sortino, Calmar, turnover, final value, Monte Carlo
p-values, the optimiser's weights — because only kind-named metrics (Sharpe,
return, drawdown …) ever became evidence, and a ref naming the run
(``rp/artifacts/metrics.csv``, ``risk_parity target_positions.csv``) resolved to
nothing. Declared figures: 196 ``value_mismatch`` and 167
``not_in_referenced_call`` became 1 and 7. And naming 600519.SH in the request
made it a market answer, so a report with no fetched price could never be
released with its failing figures cut: 12 of 15 runs ended in the refusal.

What stays closed is pinned beside each change: an undeclared figure is still
checked only against prices and metric kinds (widening it to the whole metrics
row let 16% of invented decimals through, measured on the same runs), a file
the model wrote is never evidence, a table counts only for the rows the model
was shown, and a value from one backtest does not ground a figure declared from
another.

Every value here is synthetic; no market data lives in the repository.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evals.grounding import GroundingLedger
from evals.grounding.evidence import ARCHIVE_MANIFEST
from evals.grounding.figures import parse_figures_block, scan_figures
from src.agent.tool_results import _archive_backtest_result

RP = {
    "final_value": 1129817.32,
    "total_return": 0.129817,
    "annual_return": 0.135530,
    "max_drawdown": -0.211044,
    "sharpe": 0.693563,
    "calmar": 0.6422,
    "sortino": 1.1329,
    "trade_count": 10,
    "total_turnover": 1.366493,
    "max_consecutive_loss": 2,
}
EW = {
    "final_value": 1132804.94,
    "total_return": 0.132805,
    "annual_return": 0.138657,
    "max_drawdown": -0.214919,
    "sharpe": 0.704341,
    "calmar": 0.6452,
    "sortino": 1.2115,
    "trade_count": 8,
    "total_turnover": 1.045117,
}
RP_WEIGHTS = [
    ("2024-01-02", 0.389729, 0.300167, 0.310103),
    ("2024-01-03", 0.389840, 0.297964, 0.312195),
    ("2024-01-04", 0.390124, 0.297953, 0.311923),
    ("2024-01-05", 0.371544, 0.286110, 0.342346),
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_backtest(
    run_dir: Path,
    metrics: dict[str, float],
    *,
    weights: list[tuple[str, float, float, float]] | None = None,
    xray_drawdown: float = -0.218469,
    manifest_skips: tuple[str, ...] = (),
) -> None:
    """Write the files a completed backtest leaves behind, run card last."""
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    names = list(metrics)
    (artifacts / "metrics.csv").write_text(
        ",".join(names) + "\n" + ",".join(str(metrics[name]) for name in names) + "\n",
        encoding="utf-8",
    )
    (artifacts / "risk_xray.json").write_text(
        json.dumps(
            {
                "concentration": {"hhi": 0.340460, "effective_n": 2.937202},
                "drawdown": {"max_drawdown": xray_drawdown},
                "tail_risk": {"var_95": 0.022701, "expected_shortfall_95": 0.031423},
                "correlation": {"avg_pairwise_abs": 0.696128},
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "validation.json").write_text(
        json.dumps(
            {
                "monte_carlo": {
                    "p_value_sharpe": 0.304,
                    "p_value_max_dd": 0.439,
                    # A series: 1,000 samples would match any Sharpe-sized figure.
                    "sharpe_samples": [round(0.001 * index, 3) for index in range(1000)],
                }
            }
        ),
        encoding="utf-8",
    )
    rows = weights or RP_WEIGHTS
    (artifacts / "target_positions.csv").write_text(
        "timestamp,000001.SZ,000858.SZ,600519.SH\n"
        + "".join(f"{day},{a},{b},{c}\n" for day, a, b, c in rows),
        encoding="utf-8",
    )
    (artifacts / "trades.csv").write_text(
        "timestamp,code,side,price,qty,pnl\n"
        "2024-03-01,000001.SZ,sell,9.81,1000,11488.33\n"
        "2024-06-03,600519.SH,sell,1602.5,100,-17998.19\n",
        encoding="utf-8",
    )
    listed = [
        f"artifacts/{name}"
        for name in ("metrics.csv", "risk_xray.json", "validation.json", "target_positions.csv", "trades.csv")
        if f"artifacts/{name}" not in manifest_skips
    ]
    card = {
        "backtest": {"initial_cash": 1000000, "start_date": "2024-01-01"},
        "metrics": dict(metrics),
        "artifacts": [{"path": name, "sha256": _sha(run_dir / name)} for name in listed],
        "citations": [{"row": 1, "metric": "sharpe"}],
    }
    (run_dir / "run_card.json").write_text(json.dumps(card), encoding="utf-8")


def _backtest(ledger: GroundingLedger, run_dir: Path, call_id: str) -> None:
    ledger.ingest_tool_result(
        tool_name="backtest",
        arguments={"run_dir": str(run_dir)},
        result=json.dumps({"status": "ok", "exit_code": 0, "run_dir": str(run_dir)}),
        call_id=call_id,
        success=True,
    )


def _read(ledger: GroundingLedger, path: Path, call_id: str, *, limit: int | None = None) -> None:
    text = path.read_text(encoding="utf-8")
    if limit:
        text = "".join(text.splitlines(keepends=True)[:limit])
    ledger.ingest_tool_result(
        tool_name="read_file",
        arguments={"path": str(path)},
        result=json.dumps({"status": "ok", "path": str(path), "content": text}),
        call_id=call_id,
        success=True,
    )


def _declared(prose: str, *lines: str) -> str:
    return prose + "\n\n```figures\n" + "\n".join(lines) + "\n```"


def _figure_reasons(result) -> list[str]:
    return [issue["reason"] for issue in result.issues if issue.get("value") is not None]


@pytest.fixture()
def two_runs(tmp_path: Path) -> GroundingLedger:
    """A risk-parity run in ``rp/`` and an equal-weight run in ``ew/``."""
    _write_backtest(tmp_path / "rp", RP)
    _write_backtest(
        tmp_path / "ew",
        EW,
        weights=[("2024-01-02", 0.333333, 0.333333, 0.333334)],
        xray_drawdown=-0.227175,
    )
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="用000001.SZ、600519.SH、000858.SZ构建风险平价组合，回测2024全年，与等权基准对比",
    )
    _backtest(ledger, tmp_path / "rp", "bt-rp")
    _backtest(ledger, tmp_path / "ew", "bt-ew")
    return ledger


def test_every_scalar_a_backtest_reports_is_observed_under_its_run_directory(
    two_runs: GroundingLedger,
) -> None:
    """Sortino, Calmar, turnover, p-values, X-ray and config echo, not just Sharpe."""
    result = two_runs.validate_final_answer(
        _declared(
            "风险平价 Sortino 1.133，Calmar 0.6422，累计换手 1.366，有效持仓 2.937，"
            "HHI 0.3405，蒙特卡洛 Sharpe p 值 0.304，平均两两相关 0.696。",
            "1.133 | observed | Sortino | rp",
            "0.6422 | observed | Calmar | rp",
            "1.366 | observed | 累计换手 | rp",
            "2.937 | observed | 有效持仓 | rp",
            "0.3405 | observed | HHI | rp",
            "0.304 | observed | p 值 | rp",
            "0.696 | observed | 相关 | rp",
        )
    )

    assert result.valid, result.issues


@pytest.mark.parametrize(
    "ref",
    [
        "rp",
        "rp/artifacts/metrics.csv",
        "rp/metrics.csv",
        "rp metrics.csv",
        "backtest::rp",
        "rp::sortino",
        "backtest rp",
    ],
)
def test_every_spelling_of_a_run_names_that_run_and_no_other(
    two_runs: GroundingLedger, ref: str
) -> None:
    """The run directory is what makes a ref exact: EW's Sortino is not RP's."""
    own = two_runs.validate_final_answer(
        _declared("风险平价 Sortino 1.133。", f"1.133 | observed | Sortino | {ref}")
    )
    other = two_runs.validate_final_answer(
        _declared("风险平价 Sortino 1.212。", f"1.212 | observed | Sortino | {ref}")
    )

    assert own.valid, own.issues
    assert not other.valid
    assert {issue["reason"] for issue in other.issues} == {"not_in_referenced_call"}


def test_an_invented_value_declared_from_a_real_run_is_rejected(
    two_runs: GroundingLedger,
) -> None:
    """Naming the run is not a pass: the value must be one it wrote."""
    result = two_runs.validate_final_answer(
        _declared("风险平价 Sortino 1.190。", "1.190 | observed | Sortino | rp")
    )
    # 0.512 is one of the 1,000 Monte Carlo samples: a series is not a result.
    sampled = two_runs.validate_final_answer(
        _declared("模拟 Sharpe 0.512。", "0.512 | observed | Sharpe | rp")
    )

    assert not result.valid
    assert [issue["value"] for issue in result.issues] == ["1.190"]
    assert not sampled.valid




def test_a_wrong_call_ref_hints_only_refs_that_then_ground_the_figure(
    two_runs: GroundingLedger,
) -> None:
    """The hint for a backtest's value names the call that wrote it, and each ref it lists validates."""
    wrong = two_runs.validate_final_answer(
        _declared("风险平价 Sortino 1.133。", "1.133 | observed | Sortino | bt-ew::sortino")
    )

    assert not wrong.valid
    (issue,) = wrong.issues
    assert issue["reason"] == "not_in_referenced_call"
    assert issue["field_ref_candidates"]
    for ref in issue["field_ref_candidates"]:
        assert ref.startswith("bt-rp::")
        assert two_runs.validate_final_answer(
            _declared("风险平价 Sortino 1.133。", f"1.133 | observed | Sortino | {ref}")
        ).valid, ref


def test_one_run_holding_two_drawdowns_is_still_one_source(tmp_path: Path) -> None:
    """Engine and risk X-ray both report a max_drawdown; a ref cannot be ambiguous
    between two numbers the same run wrote."""
    _write_backtest(tmp_path / "rp", RP)
    ledger = GroundingLedger(run_dir=tmp_path, user_message="回测风险平价")
    _backtest(ledger, tmp_path / "rp", "bt-rp")

    for written in ("−21.10%", "−21.85%"):
        result = ledger.validate_final_answer(
            _declared(f"最大回撤 {written}。", f"{written} | observed | 最大回撤 | max_drawdown")
        )
        assert result.valid, (written, result.issues)


def test_a_table_grounds_only_the_rows_the_model_was_shown(two_runs: GroundingLedger) -> None:
    table = two_runs.run_dir / "rp" / "artifacts" / "target_positions.csv"
    shown = _declared(
        "2024-01-02 风险平价权重：000001.SZ 38.97%。",
        "38.97% | observed | 初始权重 | rp/artifacts/target_positions.csv",
    )
    unseen = _declared(
        "2024-01-05 风险平价权重：600519.SH 34.23%。",
        "34.23% | observed | 权重 | rp/artifacts/target_positions.csv",
    )

    assert not two_runs.validate_final_answer(shown).valid  # not read yet
    _read(two_runs, table, "read-1", limit=3)

    assert two_runs.validate_final_answer(shown).valid
    assert not two_runs.validate_final_answer(unseen).valid


def test_model_written_metrics_are_not_backtest_evidence(tmp_path: Path) -> None:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="回测风险平价")
    run_dir = tmp_path / "rp"
    _write_backtest(run_dir, RP)
    _backtest(ledger, run_dir, "bt-rp")
    metrics = run_dir / "artifacts" / "metrics.csv"
    metrics.write_text("sharpe\n0.693563\n", encoding="utf-8")
    ledger.ingest_tool_result(
        tool_name="write_file",
        arguments={"path": str(metrics)},
        result=json.dumps({"status": "ok", "path": str(metrics)}),
        call_id="model-write-metrics",
        success=True,
    )
    _backtest(ledger, run_dir, "bt-after-write")

    assert not any(
        row.get("metric") == "sharpe" and row.get("call_id") == "bt-after-write"
        for row in ledger._analysis_metrics
    )


def test_a_file_the_model_wrote_is_never_engine_output(tmp_path: Path) -> None:
    """Neither a table written before the backtest nor one edited after it."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="回测风险平价")
    own = tmp_path / "rp" / "artifacts" / "my_weights.csv"
    own.parent.mkdir(parents=True)
    own.write_text("timestamp,000001.SZ\n2024-01-02,0.4567\n", encoding="utf-8")
    ledger.ingest_tool_result(
        tool_name="write_file",
        arguments={"path": str(own)},
        result=json.dumps({"status": "ok", "path": str(own)}),
        call_id="w1",
        success=True,
    )
    own.unlink()
    _write_backtest(tmp_path / "rp", RP)
    own.write_text("timestamp,000001.SZ\n2024-01-02,0.4567\n", encoding="utf-8")
    _backtest(ledger, tmp_path / "rp", "bt-rp")
    _read(ledger, own, "read-own")

    forged = _declared("权重 45.67%。", "45.67% | observed | 权重 | rp/artifacts/my_weights.csv")
    assert not ledger.validate_final_answer(forged).valid

    table = tmp_path / "rp" / "artifacts" / "target_positions.csv"
    table.write_text("timestamp,000001.SZ\n2024-01-02,0.4567\n", encoding="utf-8")
    _read(ledger, table, "read-edited")
    edited = _declared("权重 45.67%。", "45.67% | observed | 权重 | rp/artifacts/target_positions.csv")
    assert not ledger.validate_final_answer(edited).valid


def test_a_summary_file_the_run_card_does_not_vouch_for_is_ignored(tmp_path: Path) -> None:
    _write_backtest(tmp_path / "rp", RP, manifest_skips=("artifacts/risk_xray.json",))
    ledger = GroundingLedger(run_dir=tmp_path, user_message="回测风险平价")
    _backtest(ledger, tmp_path / "rp", "bt-rp")

    unvouched = ledger.validate_final_answer(
        _declared("平均两两相关 0.696。", "0.696 | observed | 相关 | rp")
    )
    vouched = ledger.validate_final_answer(
        _declared("Sortino 1.133。", "1.133 | observed | Sortino | rp")
    )

    assert not unvouched.valid
    assert vouched.valid, vouched.issues


def test_stale_active_metrics_are_not_attributed_to_a_detached_backtest(tmp_path: Path) -> None:
    """The active run's metrics file is an earlier run's until the archive names this one."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="回测")
    _write_backtest(tmp_path, EW)
    _write_backtest(tmp_path / "rp", RP)

    _backtest(ledger, tmp_path / "rp", "bt-rp")

    recorded = [
        item["value"] for item in ledger._analysis_metrics if item.get("call_id") == "bt-rp"
    ]
    assert RP["sharpe"] in recorded
    assert EW["sharpe"] not in recorded


@pytest.mark.parametrize("detached", [False, True])
def test_artifact_path_cannot_bypass_current_backtest_source(tmp_path: Path, detached: bool) -> None:
    active = tmp_path / "active"
    _write_backtest(active, EW)
    declared = tmp_path / "detached" if detached else active / "current"
    _write_backtest(declared, RP)
    ledger = GroundingLedger(run_dir=active, user_message="Compare backtests")
    ledger.ingest_tool_result(
        tool_name="backtest",
        arguments={"run_dir": str(declared)},
        result=json.dumps({
            "status": "ok", "run_dir": str(declared),
            "artifacts": {"metrics": str(active / "artifacts" / "metrics.csv")},
        }),
        call_id="bt-current", success=True,
    )
    recorded = [item["value"] for item in ledger._analysis_metrics]
    assert EW["sharpe"] not in recorded
    if not detached:
        assert RP["sharpe"] in recorded


@pytest.mark.parametrize("mismatch", ["directory", "call"])
def test_archive_identity_includes_full_directory_and_call(tmp_path: Path, mismatch: str) -> None:
    active = tmp_path / "active"
    _write_backtest(active, EW)
    declared = tmp_path / "new" / "same-name"
    old = tmp_path / "old" / "same-name"
    _write_backtest(declared, RP)
    (active / ARCHIVE_MANIFEST).write_text(json.dumps({
        "source_run": declared.name,
        "source_run_dir": str(old if mismatch == "directory" else declared),
        "source_call_id": "old-call" if mismatch == "call" else "new-call",
    }), encoding="utf-8")
    ledger = GroundingLedger(run_dir=active, user_message="Compare backtests")
    _backtest(ledger, declared, "new-call")
    assert not ledger._analysis_metrics


def test_real_engine_archive_is_accepted_only_for_its_own_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    source, active = tmp_path / "engine", tmp_path / "active"
    _write_backtest(source, RP)
    result = json.dumps({"status": "ok", "run_dir": str(source)})
    assert _archive_backtest_result(result, str(active), source_call_id="bt-engine")
    ledger = GroundingLedger(run_dir=active, user_message="Compare backtests")
    _backtest(ledger, source, "bt-stale")
    assert not ledger._analysis_metrics
    _backtest(ledger, source, "bt-engine")
    checked = ledger.validate_final_answer(_declared(
        "Sharpe 0.694。", "0.694 | observed | Sharpe | bt-engine::sharpe"
    ))
    assert checked.valid, checked.issues


def test_metrics_symlink_cannot_supply_another_runs_evidence(tmp_path: Path) -> None:
    active, sibling = tmp_path / "active", tmp_path / "sibling"
    _write_backtest(sibling, RP)
    (active / "artifacts").mkdir(parents=True)
    (active / "artifacts" / "metrics.csv").symlink_to(sibling / "artifacts" / "metrics.csv")
    ledger = GroundingLedger(run_dir=active, user_message="Compare backtests")
    _backtest(ledger, active, "bt-active")
    assert not ledger._analysis_metrics


def test_a_detached_backtest_cannot_inherit_the_active_runs_copy(tmp_path: Path) -> None:
    """A run dir outside the active run has no claim on what that dir holds.

    The tool declares a run_dir elsewhere on disk while the active run dir
    happens to hold an earlier run's metrics; the manifest names that earlier
    run, so none of its figures were produced by this call.
    """
    active = tmp_path / "active"
    active.mkdir(parents=True)
    _write_backtest(active, EW)
    (active / ARCHIVE_MANIFEST).write_text(
        json.dumps({"source_run": "an-earlier-run"}), encoding="utf-8"
    )
    detached = tmp_path / "detached-bt"
    _write_backtest(detached, RP)
    ledger = GroundingLedger(run_dir=active, user_message="回测")

    _backtest(ledger, detached, "bt-detached")

    recorded = [
        item["value"]
        for item in ledger._analysis_metrics
        if item.get("call_id") == "bt-detached"
    ]
    assert EW["sharpe"] not in recorded
    assert EW["total_return"] not in recorded


def test_a_detached_backtests_archived_copy_counts_once_vouched_for(tmp_path: Path) -> None:
    """The loop's archive into the active run counts once the manifest names the source."""
    active = tmp_path / "active"
    active.mkdir(parents=True)
    detached = tmp_path / "detached-bt"
    _write_backtest(detached, RP)
    for name in ("metrics.csv", "risk_xray.json", "validation.json"):
        target = active / "artifacts" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((detached / "artifacts" / name).read_bytes())
    (active / "run_card.json").write_bytes((detached / "run_card.json").read_bytes())
    (active / ARCHIVE_MANIFEST).write_text(
        json.dumps({"source_run": detached.name, "source_run_dir": str(detached.resolve()), "source_call_id": "bt-detached"}), encoding="utf-8"
    )
    ledger = GroundingLedger(run_dir=active, user_message="回测")

    _backtest(ledger, detached, "bt-detached")

    recorded = [
        item["value"]
        for item in ledger._analysis_metrics
        if item.get("call_id") == "bt-detached"
    ]
    assert RP["sharpe"] in recorded


@pytest.mark.parametrize("ref", ["artifacts/metrics.csv", "run_dir/artifacts/metrics.csv"])
def test_the_active_runs_copy_belongs_to_the_backtest_the_archive_names(
    tmp_path: Path, ref: str
) -> None:
    """The loop copies each finished backtest into the active run; a ref to that
    copy names the backtest it came from, and only once it has come. ``run_dir/``
    names that copy too, never the file of the same name in another run."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="回测")
    _write_backtest(tmp_path / "rp", RP)
    _write_backtest(tmp_path / "ew", EW)

    def archive(source: str, call_id: str) -> None:
        for name in ("metrics.csv", "risk_xray.json", "validation.json"):
            target = tmp_path / "artifacts" / name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes((tmp_path / source / "artifacts" / name).read_bytes())
        (tmp_path / "run_card.json").write_bytes((tmp_path / source / "run_card.json").read_bytes())
        (tmp_path / ARCHIVE_MANIFEST).write_text(json.dumps({"source_run": source, "source_run_dir": str((tmp_path / source).resolve()), "source_call_id": call_id}), encoding="utf-8")

    def copy_says(value: str) -> bool:
        return ledger.validate_final_answer(
            _declared(f"Sortino {value}。", f"{value} | observed | Sortino | {ref}")
        ).valid

    archive("ew", "earlier-call")  # an earlier archive: not rp's output, and not credited to rp
    _backtest(ledger, tmp_path / "rp", "bt-rp")
    assert not copy_says("1.133")
    assert not copy_says("1.212")

    archive("rp", "bt-rp-2")
    _backtest(ledger, tmp_path / "rp", "bt-rp-2")
    assert copy_says("1.133")

    archive("ew", "bt-ew")
    _backtest(ledger, tmp_path / "ew", "bt-ew")
    assert copy_says("1.212")
    assert not copy_says("1.133")


def test_an_undeclared_figure_is_checked_exactly_as_before(two_runs: GroundingLedger) -> None:
    """The undeclared path still accepts only prices and metric kinds.

    Widening it to the whole metrics row accepted 16% of invented decimals on
    the replayed runs, against 4.6% today; the model declares the rest.
    """
    sharpe = two_runs.validate_final_answer("风险平价 Sharpe 0.694。")
    sortino = two_runs.validate_final_answer("风险平价 Sortino 1.133。")

    assert sharpe.valid, sharpe.issues
    assert not sortino.valid
    assert [issue["value"] for issue in sortino.issues] == ["1.133"]




def test_a_drawdown_difference_anchors_on_magnitudes(two_runs: GroundingLedger) -> None:
    """Formula constants parse unsigned; a negative observation must still anchor them."""
    result = two_runs.validate_final_answer(
        _declared(
            "风险平价回撤浅 0.39pp。",
            "0.39pp | derived | (−0.211044) − (−0.214919) | rp, ew",
        )
    )

    assert result.valid, result.issues


def test_arithmetic_across_two_runs_anchors_on_a_field_ref_naming_both(
    two_runs: GroundingLedger,
) -> None:
    """For a derivation, a field both runs hold is two observations, not an ambiguity."""
    result = two_runs.validate_final_answer(
        _declared("等权 Sortino 高 0.079。", "0.079 | derived | 1.2115 − 1.1329 | sortino")
    )
    unanchored = two_runs.validate_final_answer(
        _declared("等权 Sortino 高 0.079。", "0.079 | derived | 1.2115 − 1.1329 | 索提诺差")
    )

    assert result.valid, result.issues
    assert not unanchored.valid


def test_a_named_derivation_survives_prices_of_several_symbols(two_runs: GroundingLedger) -> None:
    """Several instruments' bars bar the session pools, not the evidence a ref names."""
    two_runs.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["000001.SZ", "600519.SH"]},
        result=json.dumps(
            {
                "000001.SZ": [{"trade_date": "2024-12-31", "close": 11.2}],
                "600519.SH": [{"trade_date": "2024-12-31", "close": 1524.0}],
            }
        ),
        call_id="md",
        success=True,
    )
    named = two_runs.validate_final_answer(
        _declared("Sortino 差 0.079。", "0.079 | derived | 1.2115 − 1.1329 | rp, ew")
    )
    unnamed = two_runs.validate_final_answer(
        _declared("Sharpe 差 0.011。", "0.011 | derived | 0.704341 − 0.693563 | 夏普差")
    )

    # The prose names no symbol, source or currency, which the bars now ask
    # for; only the figures' own verdicts are under test.
    assert _figure_reasons(named) == [], named.issues
    assert _figure_reasons(unnamed) == ["no_symbol"]








def test_a_code_and_name_cell_attributes_its_figure_to_the_code(tmp_path: Path) -> None:
    """"000001.SZ 平安银行" in the symbol column is 000001.SZ, not a mismatch."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="000001.SZ 和 600519.SH 最近收盘")
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["000001.SZ", "600519.SH"]},
        result=json.dumps(
            {
                "000001.SZ": [{"trade_date": "2024-12-31", "close": 11.2}],
                "600519.SH": [{"trade_date": "2024-12-31", "close": 1524.0}],
            }
        ),
        call_id="md",
        success=True,
    )
    result = ledger.validate_final_answer(
        "| 标的 | 收盘 |\n|---|---:|\n| 000001.SZ 平安银行 | 11.20 |\n\n"
        "数据来源 auto，人民币计价。\n\n```figures\n11.20 | observed | 000001.SZ 收盘 | md\n```"
    )

    assert not any(issue.get("reason") == "symbol_mismatch" for issue in result.issues), result.issues


def test_a_trade_price_read_back_is_not_a_market_print(two_runs: GroundingLedger) -> None:
    """An execution price is left out of the table evidence, or reading trades.csv
    would turn a backtest report into a price answer owing a source and currency."""
    _read(two_runs, two_runs.run_dir / "rp" / "artifacts" / "trades.csv", "read-trades")

    result = two_runs.validate_final_answer(
        _declared("风险平价 Sortino 1.133，平安银行一笔盈利 11488.33。",
                  "1.133 | observed | Sortino | rp",
                  "11488.33 | observed | 盈亏 | rp/artifacts/trades.csv")
    )

    assert result.valid, result.issues
    assert not two_runs._price_records()


# ---------------------------------------------------------------------------
# How comparison reports write their arithmetic (same replayed runs)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "note",
    [
        "等权 Sortino 1.2115 − 风险平价 1.1329",
        "1.2115 − 1.1329（Sortino 差，约 +0.079）",
        "Sortino 差 = 等权 1.2115 − 风险平价 1.1329（组合整体）",
        "1.2115 − 1.1329 Sortino差",
    ],
)
def test_a_labelled_formula_is_read_as_its_arithmetic(two_runs: GroundingLedger, note: str) -> None:
    """Words glued to operands, or an aside in brackets, used to make the note
    "not arithmetic"; the words are removed, never interpreted."""
    result = two_runs.validate_final_answer(
        _declared("等权 Sortino 高 0.079。", f"0.079 | derived | {note} | rp, ew")
    )

    assert result.valid, result.issues


def test_a_labelled_formula_with_the_wrong_arithmetic_still_fails(two_runs: GroundingLedger) -> None:
    result = two_runs.validate_final_answer(
        _declared("等权 Sortino 高 0.12。", "0.12 | derived | 等权 1.2115 − 风险平价 1.1329 | rp, ew")
    )

    assert [issue["reason"] for issue in result.issues] == ["derivation_result_mismatch"]


def test_percent_operands_are_the_fractions_the_evidence_holds(two_runs: GroundingLedger) -> None:
    """"13.28% − 12.98%" is 0.1328 − 0.1298, anchored on the two total returns."""
    result = two_runs.validate_final_answer(
        _declared("等权总收益高 0.30pp。", "0.30pp | derived | 13.28% − 12.98% | rp, ew")
    )

    assert result.valid, result.issues


def test_a_sum_of_squared_weights_is_arithmetic(two_runs: GroundingLedger) -> None:
    table = two_runs.run_dir / "rp" / "artifacts" / "target_positions.csv"
    _read(two_runs, table, "read-weights", limit=2)

    anchored = two_runs.validate_final_answer(
        _declared(
            "初始 HHI 0.3381。",
            "0.3381 | derived | 0.389729² + 0.300167² + 0.310103² | rp/artifacts/target_positions.csv",
        )
    )
    # The exponent is not an operand: squaring an invented weight anchors nothing.
    # The run observed a 2 (max_consecutive_loss), so an exponent that counted
    # as an operand would anchor the invented 0.4567.
    invented = two_runs.validate_final_answer(
        _declared("HHI 0.4135。", "0.4135 | derived | 0.4567² + 0.3002² + 0.3389² | rp")
    )

    assert anchored.valid, anchored.issues
    assert [issue["reason"] for issue in invented.issues] == ["additive_operand_not_observed"]


def test_a_fraction_or_a_multiple_is_a_readable_declaration(two_runs: GroundingLedger) -> None:
    """"1/3" and "5.5x" were unreadable lines, and one unreadable line fails the draft."""
    result = two_runs.validate_final_answer(
        _declared(
            "等权每只 1/3，即 0.333；换手是等权的 1.31 倍。",
            "1/3 | count | 等权权重 | ew",
            "1.31x | derived | 1.366 / 1.045 | rp, ew",
        )
    )

    assert not [issue for issue in result.issues if issue["code"] == "figures_block_malformed"]
    assert result.valid, result.issues


def test_only_a_literal_square_or_cube_is_evaluated() -> None:
    """``9^9^9`` would take the process down computing a number of 370 million digits."""
    from evals.grounding.policies import _formula_in_note

    assert _formula_in_note("9^9^9") is None
    assert _formula_in_note("2^10 + 1") is None
    assert _formula_in_note("0.3^2 + 0.4^2")[0] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# What the correction tells the model (live DeepSeek run, 2026-09-29)
# ---------------------------------------------------------------------------








@pytest.mark.parametrize("mode", ["rows", "downsample"])
def test_structured_artifact_reader_grounds_only_shown_rows(
    two_runs: GroundingLedger, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    from src.tools.run_artifact_tool import read_run_artifact

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(two_runs.run_dir))
    result = read_run_artifact(
        str(two_runs.run_dir / "rp"), "target_positions", format=mode,
        max_rows=2, columns=["timestamp", "000001.SZ"],
    )
    payload = json.loads(result)
    assert payload["returned_rows"] == 2
    two_runs.ingest_tool_result(
        tool_name="read_run_artifact", arguments={"run_dir": str(two_runs.run_dir / "rp")},
        result=result, call_id="structured-weights", success=True,
    )
    observed = [r for r in two_runs._evidence if r.call_id == "structured-weights"]
    assert {r.field for r in observed} == {"000001.SZ"}
    assert {r.value for r in observed} == {row[1] for row in payload["rows"]}
    shown = _declared("初始权重 38.97%。", "38.97% | observed | 权重 | rp/artifacts/target_positions.csv")
    assert two_runs.validate_final_answer(shown).valid
    unseen = _declared("未读取权重 29.79%。", "29.79% | observed | 权重 | rp/artifacts/target_positions.csv")
    assert not two_runs.validate_final_answer(unseen).valid


@pytest.mark.parametrize("changed", ["different_bytes", "same_bytes"])
def test_structured_reader_never_grounds_model_written_table(
    two_runs: GroundingLedger, monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    from src.tools.run_artifact_tool import read_run_artifact

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(two_runs.run_dir))
    table = two_runs.run_dir / "rp" / "artifacts" / "target_positions.csv"
    if changed == "different_bytes":
        table.write_text("timestamp,000001.SZ\n2024-01-02,0.4567\n", encoding="utf-8")
    two_runs.ingest_tool_result(
        tool_name="write_file", arguments={"path": str(table)},
        result=json.dumps({"status": "ok", "path": str(table)}),
        call_id="model-write-table", success=True,
    )
    result = read_run_artifact(str(table.parent.parent), "target_positions")
    two_runs.ingest_tool_result(
        tool_name="read_run_artifact", arguments={"run_dir": str(table.parent.parent)},
        result=result, call_id="read-model-table", success=True,
    )
    assert not any(r.call_id == "read-model-table" for r in two_runs._evidence)


def test_structured_reader_checks_engine_hash_and_scope(
    two_runs: GroundingLedger, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.tools.run_artifact_tool import read_run_artifact

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(two_runs.run_dir))
    table = two_runs.run_dir / "rp" / "artifacts" / "target_positions.csv"
    table.write_text("timestamp,000001.SZ\n2024-01-02,0.4567\n", encoding="utf-8")
    result = read_run_artifact(str(table.parent.parent), "target_positions")
    two_runs.ingest_tool_result(
        tool_name="read_run_artifact", arguments={"run_dir": str(table.parent.parent)},
        result=result, call_id="read-changed", success=True,
    )
    assert not any(r.call_id == "read-changed" for r in two_runs._evidence)
    result = read_run_artifact(str(two_runs.run_dir / "ew"), "target_positions")
    two_runs.ingest_tool_result(
        tool_name="read_run_artifact", arguments={"run_dir": str(two_runs.run_dir / "ew")},
        result=result, call_id="read-ew", success=True,
    )
    wrong = _declared("风险平价权重 33.33%。", "33.33% | observed | 权重 | rp/artifacts/target_positions.csv")
    assert not two_runs.validate_final_answer(wrong).valid


def test_external_symlink_is_not_registered_as_engine_table(tmp_path: Path) -> None:
    _write_backtest(tmp_path / "rp", RP)
    _write_backtest(tmp_path / "ew", EW)
    target = tmp_path / "rp" / "artifacts" / "target_positions.csv"
    target.unlink()
    target.symlink_to(tmp_path / "ew" / "artifacts" / "target_positions.csv")
    ledger = GroundingLedger(run_dir=tmp_path, user_message="回测风险平价")
    _backtest(ledger, tmp_path / "rp", "bt-rp")
    _read(ledger, target, "read-sibling")
    assert not any(r.call_id == "read-sibling" for r in ledger._evidence)


# ---------------------------------------------------------------------------
# The active run under a stand-in name (live DeepSeek run, 2026-10-21)
# ---------------------------------------------------------------------------

# How the engine names a run directory; the model copies it or writes ``run_dir``.
RUN_NAME = "20261021_195945_86_52d4e2"


@pytest.fixture()
def own_run(tmp_path: Path) -> GroundingLedger:
    """One backtest written into the active run directory itself, trades read back."""
    root = tmp_path / RUN_NAME
    _write_backtest(root, RP)
    ledger = GroundingLedger(run_dir=root, user_message="回测风险平价")
    _backtest(ledger, root, "bt-own")
    _read(ledger, root / "artifacts" / "trades.csv", "read-trades")
    return ledger


_STAND_INS = ["run_dir/artifacts/{file}", f"{RUN_NAME}/artifacts/{{file}}", "run_dir/{file}"]


@pytest.mark.parametrize("spelling", ["{file}", "artifacts/{file}", *_STAND_INS])
def test_the_active_run_named_by_a_stand_in_is_the_file_named_bare(
    own_run: GroundingLedger, spelling: str
) -> None:
    """``run_dir/artifacts/metrics.csv`` grounded nothing while ``metrics.csv`` grounded
    the same draft: the final value, trade count and trade PnL were all cut. The
    count sits in a table cell, where an integer is a measurement."""
    metrics, trades = spelling.format(file="metrics.csv"), spelling.format(file="trades.csv")
    result = own_run.validate_final_answer(
        _declared(
            "期末净值 1,129,817.32，Sortino 1.133，一笔盈利 11,488.33。\n\n"
            "| 指标 | 数值 |\n|---|---|\n| 交易笔数 | 10 |",
            f"1,129,817.32 | observed | 期末净值 | {metrics}",
            f"10 | observed | 交易笔数 | {metrics}",
            f"1.133 | observed | Sortino | {metrics}",
            f"11,488.33 | observed | 盈亏 | {trades}",
        )
    )

    assert result.valid, result.issues


@pytest.mark.parametrize("spelling", ["{file}", *_STAND_INS])
def test_a_value_the_file_does_not_hold_is_refused_under_every_stand_in(
    own_run: GroundingLedger, spelling: str
) -> None:
    metrics, trades = spelling.format(file="metrics.csv"), spelling.format(file="trades.csv")
    result = own_run.validate_final_answer(
        _declared(
            "期末净值 1,129,900.00，Sortino 1.190，一笔盈利 11,400.00。\n\n"
            "| 指标 | 数值 |\n|---|---|\n| 交易笔数 | 11 |",
            f"1,129,900.00 | observed | 期末净值 | {metrics}",
            f"11 | observed | 交易笔数 | {metrics}",
            f"1.190 | observed | Sortino | {metrics}",
            f"11,400.00 | observed | 盈亏 | {trades}",
        )
    )

    assert sorted(issue["value"] for issue in result.issues) == [
        "1,129,900.00", "1.190", "11", "11,400.00",
    ]
    assert set(_figure_reasons(result)) == {"not_in_referenced_call"}


@pytest.mark.parametrize(
    "ref",
    [
        "run_dir/config.json",
        f"{RUN_NAME}/config.json",
        "config.json",
        "run_dir/../outside/artifacts/metrics.csv",
        f"{RUN_NAME}/../outside/artifacts/metrics.csv",
        "../outside/artifacts/metrics.csv",
        "outside/artifacts/metrics.csv",
    ],
)
def test_a_stand_in_reaches_no_model_written_file_and_nothing_outside_the_run(
    own_run: GroundingLedger, ref: str
) -> None:
    """The model's own config.json stays non-evidence, and a sibling directory holding
    a metrics file of the same name is not the active run."""
    root = own_run.run_dir
    config = root / "config.json"
    config.write_text(json.dumps({"initial_cash": 777777}), encoding="utf-8")
    own_run.ingest_tool_result(
        tool_name="write_file",
        arguments={"path": str(config)},
        result=json.dumps({"status": "ok", "path": str(config)}),
        call_id="model-write-config",
        success=True,
    )
    _write_backtest(root.parent / "outside", {"sortino": 1.4567})

    assert own_run._artifact_scope(ref) is None
    for written in ("777,777.00", "1.4567"):
        result = own_run.validate_final_answer(
            _declared(f"数值 {written}。", f"{written} | observed | 数值 | {ref}")
        )
        assert not result.valid, (ref, written)


# ---------------------------------------------------------------------------
# A sign written before the currency mark (same live run: "−$1,847.78")
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "values"),
    [
        ("Trade three lost −$1,847.78.", [-1847.78]),
        ("-$3.20", [-3.2]),
        ("(−$5.00)", [-5.0]),
        ("PnL: -$3.20", [-3.2]),
        ("盈亏：−$3.20", [-3.2]),
        ("+$2.50", [2.5]),
        ("−HK$1.10", [-1.1]),
        # A hyphen joining two figures, or a spaced one, is a range, not a sign.
        ("$10-$20", [10.0, 20.0]),
        ("$10–$20", [10.0, 20.0]),
        ("$10 - $20", [10.0, 20.0]),
        ("a-$5", [5.0]),
        ("loss of $1,847.78", [1847.78]),
    ],
)
def test_a_sign_before_the_currency_mark_is_the_figures_sign(
    text: str, values: list[float]
) -> None:
    figures = scan_figures(text, parse_figures_block(text))

    assert [figure.value for figure in figures] == values
    for figure in figures:
        # The sign is cut with the figure, never left behind by a redaction.
        written = text[figure.extent[0] : figure.extent[1]]
        assert written[0] in "+-−" if figure.sign else written[0] not in "+-−", written


@pytest.mark.parametrize(
    ("value", "declared"),
    [
        ("−$1,847.78", -1847.78),
        ("-$3.20", -3.2),
        ("+$2.50", 2.5),
        ("−HK$1.10", -1.1),
        ("$10-$20", None),
        ("$10 - $20", None),
        ("x -$5", None),
    ],
)
def test_a_declaration_reads_the_sign_the_prose_reads(value: str, declared: float | None) -> None:
    """``−$1,847.78 | observed | …`` was ``unparseable_declaration``."""
    block = parse_figures_block(f"text\n\n```figures\n{value} | observed | trade PnL | trades.csv\n```")

    if declared is None:
        assert not block.declarations and block.malformed
    else:
        assert [item.value for item in block.declarations] == [declared]
        assert not block.malformed


@pytest.mark.parametrize("ref", ["trades.csv", "run_dir/artifacts/trades.csv"])
def test_a_loss_written_with_its_sign_before_the_mark_grounds(
    own_run: GroundingLedger, ref: str
) -> None:
    """The draft's trade loss was refused or cut although trades.csv holds it."""
    loss = own_run.validate_final_answer(
        _declared("一笔亏损 −$17,998.19。", f"−$17,998.19 | observed | 盈亏 | {ref}")
    )
    gain = own_run.validate_final_answer(
        _declared("一笔盈利 +$11,488.33。", f"+$11,488.33 | observed | 盈亏 | {ref}")
    )

    assert loss.valid, loss.issues
    assert gain.valid, gain.issues


@pytest.mark.parametrize("written", ["+$17,998.19", "$17,998.19"])
def test_a_loss_written_as_a_gain_is_refused(own_run: GroundingLedger, written: str) -> None:
    result = own_run.validate_final_answer(
        _declared(f"一笔交易 {written}。", f"{written} | observed | 盈亏 | trades.csv")
    )

    assert not result.valid
    assert _figure_reasons(result) == ["not_in_referenced_call"]
