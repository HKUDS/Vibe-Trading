"""``list_backtest_runs``: find earlier runs and feed ``read_run_artifact``. All values are synthetic."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.tools import backtest_runs_tool
from src.tools.backtest_runs_tool import BacktestRunsTool, list_backtest_runs
from src.tools.run_artifact_tool import read_run_artifact

SESSION = "sessionaaaa1"


def _write_backtest(directory: Path, rejections: dict | None = None) -> None:
    artifacts = directory / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "metrics.csv").write_text(
        "total_return,sharpe\n0.1,1.25\n", encoding="utf-8"
    )
    card = {
        "backtest": {"start_date": "2024-01-01", "end_date": "2024-12-31"},
        "metrics": {"total_return": 0.1, "sharpe": 1.25},
        "structured_metrics": {"unfilled_plan_rejections_by_symbol": rejections or {}},
        "artifacts": [
            {
                "path": "artifacts/metrics.csv",
                "sha256": hashlib.sha256(
                    (artifacts / "metrics.csv").read_bytes()
                ).hexdigest(),
            }
        ],
    }
    (directory / "run_card.json").write_text(json.dumps(card), encoding="utf-8")


def _turn(
    runs: Path, name: str, session: str | None = SESSION, subs=("a", "b"), **kwargs
) -> Path:
    turn = runs / name
    turn.mkdir(parents=True)
    context = {"session_id": session} if session else {}
    (turn / "req.json").write_text(
        json.dumps({"prompt": "compare", "context": context}), encoding="utf-8"
    )
    for sub in subs:
        _write_backtest(turn / sub, **(kwargs if sub == "a" else {}))
    return turn


@pytest.fixture()
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    monkeypatch.delenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", raising=False)
    (tmp_path / "runs").mkdir()
    return tmp_path / "runs"


def _list(current: Path | None = None, **kwargs) -> dict:
    return json.loads(
        list_backtest_runs(current_run_dir=str(current) if current else None, **kwargs)
    )


def test_previous_turn_is_found_and_readable_without_rerun(runs: Path) -> None:
    first = _turn(
        runs, "20261026_230021_aaaaaa", rejections={"ZZZ": {"execution_blocked": 15}}
    )
    current = _turn(runs, "20261026_231424_bbbbbb", subs=())

    result = _list(current)

    run = result["runs"][0]
    assert [r["run_dir"] for r in result["runs"]] == [str(first)] and result[
        "next_offset"
    ] is None
    by_name = {b["name"]: b for b in run["backtests"]}
    assert set(by_name) == {"a", "b"}
    assert by_name["a"]["run_dir"] == str(first / "a")
    assert by_name["a"]["metrics"] == {"total_return": 0.1, "sharpe": 1.25}
    assert by_name["a"]["unfilled_plan_rejections_by_symbol"] == {
        "ZZZ": {"execution_blocked": 15}
    }
    assert "unfilled_plan_rejections_by_symbol" not in by_name["b"]
    # The returned run_dir is what read_run_artifact takes.
    assert json.loads(read_run_artifact(by_name["a"]["run_dir"], "metrics"))[
        "rows"
    ] == [[0.1, 1.25]]


def test_archived_copy_at_the_turn_root_is_not_listed_twice(runs: Path) -> None:
    turn = _turn(runs, "20261026_100000_aaaaaa", subs=("a",))
    (turn / "run_card.json").write_text(
        (turn / "a" / "run_card.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    assert {b["name"] for b in _list(scope="all")["runs"][0]["backtests"]} == {".", "a"}
    (turn / ".archived_backtest.json").write_text("{}", encoding="utf-8")
    assert {b["name"] for b in _list(scope="all")["runs"][0]["backtests"]} == {"a"}


def test_session_scope_excludes_other_sessions_and_the_active_run(runs: Path) -> None:
    mine = _turn(runs, "20261026_100000_aaaaaa")
    other = _turn(runs, "20261026_110000_bbbbbb", session="sessionbbbb2")
    current = _turn(runs, "20261026_120000_cccccc", subs=())

    assert [r["run_id"] for r in _list(current)["runs"]] == [mine.name]
    assert [r["run_id"] for r in _list(current, scope="all")["runs"]] == [
        other.name,
        mine.name,
    ]
    assert (
        len(_list(None)["runs"]) == 2
    )  # No session filter, but a turn with no backtest is not a backtest run.


def _walk(**kwargs) -> tuple[list[str], list[int]]:
    seen, sizes, offset = [], [], 0
    while offset is not None:
        page = _list(scope="all", offset=offset, **kwargs)
        assert page["runs"], "a page must make progress"
        seen += [r["run_id"] for r in page["runs"]]
        sizes.append(len(page["runs"]))
        offset = page["next_offset"]
    return seen, sizes


def test_pagination_never_skips_or_repeats_a_run(runs: Path, monkeypatch) -> None:
    names = [f"20261026_{hour:02d}0000_{hour:06d}" for hour in range(1, 8)]
    for name in names:
        _turn(runs, name, subs=("a",))
    expected = sorted(names, reverse=True)

    seen, sizes = _walk(limit=3)  # cut by the page limit
    assert seen == expected and sizes == [3, 3, 1]

    monkeypatch.setattr(
        backtest_runs_tool, "TOOL_RESULT_LIMIT", 2500
    )  # cut by the response budget instead
    seen, sizes = _walk(limit=20)
    assert seen == expected and len(sizes) > 1 and max(sizes) < len(names)

    monkeypatch.setattr(
        backtest_runs_tool, "TOOL_RESULT_LIMIT", 1
    )  # one oversized run per page still advances
    seen, sizes = _walk(limit=20)
    assert seen == expected and sizes == [1] * len(names)


def test_pagination_with_the_session_filter_counts_only_matching_runs(
    runs: Path, monkeypatch
) -> None:
    mine = [f"20261026_{h:02d}0000_{h:06d}" for h in (1, 3, 5, 7)]
    for h in range(1, 9):
        name = f"20261026_{h:02d}0000_{h:06d}"
        _turn(
            runs, name, session=SESSION if name in mine else "sessionother", subs=("a",)
        )
    current = _turn(runs, "20261026_235900_ffffff", subs=())
    monkeypatch.setattr(backtest_runs_tool, "TOOL_RESULT_LIMIT", 2500)
    seen, offset = [], 0
    while offset is not None:
        page = _list(current, offset=offset)
        seen += [r["run_id"] for r in page["runs"]]
        offset = page["next_offset"]
    assert seen == sorted(mine, reverse=True)


def test_run_id_filter_and_bad_arguments(runs: Path) -> None:
    target = _turn(runs, "20261026_110000_bbbbbb")
    _turn(runs, "20261026_100000_aaaaaa")
    assert [r["run_id"] for r in _list(scope="all", run_id=target.name)["runs"]] == [
        target.name
    ]
    for bad in ("does_not_exist", "../etc", "a/b", "..", "", "x\x00y"):
        assert _list(scope="all", run_id=bad)["status"] == "error"
    assert _list(scope="everything")["status"] == "error"
    assert _list(scope="all", limit="many")["status"] == "error"
    assert _list(scope="all", limit=10_000)["status"] == "ok"


def test_symlinks_and_unsafe_files_are_never_followed(
    runs: Path, tmp_path_factory
) -> None:
    foreign = _turn(tmp_path_factory.mktemp("outside"), "20261026_090000_evil00")
    (runs / "20261026_090000_evil00").symlink_to(foreign, target_is_directory=True)
    turn = _turn(runs, "20261026_100000_aaaaaa", subs=("ok", "broken", "huge"))
    (turn / "linked").symlink_to(foreign / "a", target_is_directory=True)
    (turn / "stolen").mkdir()
    (turn / "stolen" / "run_card.json").symlink_to(foreign / "a" / "run_card.json")
    (turn / "broken" / "run_card.json").write_text("{not json", encoding="utf-8")
    (turn / "huge" / "run_card.json").write_text(
        " " * (backtest_runs_tool._MAX_JSON_BYTES + 1), encoding="utf-8"
    )

    listed = _list(scope="all")["runs"]

    assert [r["run_id"] for r in listed] == [turn.name]
    assert [b["name"] for b in listed[0]["backtests"]] == ["ok"]


def test_run_outside_allowed_roots_is_skipped(runs: Path, monkeypatch) -> None:
    _turn(runs, "20261026_100000_aaaaaa")
    monkeypatch.setattr(
        backtest_runs_tool,
        "safe_run_dir",
        lambda p: (_ for _ in ()).throw(ValueError("outside")),
    )
    assert _list(scope="all")["runs"] == []


def test_tool_contract(runs: Path) -> None:
    tool = BacktestRunsTool()
    assert (
        tool.name == "list_backtest_runs"
        and tool.is_readonly
        and tool.parameters["required"] == []
    )
    _turn(runs, "20261026_100000_aaaaaa")
    current = _turn(runs, "20261026_110000_bbbbbb", subs=())
    assert len(json.loads(tool.execute(run_dir=str(current)))["runs"]) == 1


def test_a_large_rejection_map_cannot_overflow_the_first_page(runs: Path) -> None:
    _turn(runs, "20261026_100000_aaaaaa", rejections={f"SYMBOL{i}": {"blocked": 15} for i in range(2000)})
    output = list_backtest_runs(scope="all")
    assert len(output) <= backtest_runs_tool.TOOL_RESULT_LIMIT
    entry = json.loads(output)["runs"][0]["backtests"][0]
    assert entry["unfilled_plan_rejections_by_symbol_omitted"] is True
