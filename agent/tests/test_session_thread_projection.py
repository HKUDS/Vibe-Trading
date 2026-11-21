"""project_turn(): one finished turn -> the legacy messages.jsonl row fields."""

from __future__ import annotations

import json
from pathlib import Path

from src.session.thread import INTERRUPTED_RESULT_CONTENT, ThreadLog, project_turn


def _call(call_id: str, name: str, arguments: dict) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def _clock(values):
    iterator = iter(values)
    return lambda: next(iterator)


def test_projection_matches_the_live_tool_trail_shape(tmp_path: Path) -> None:
    log = ThreadLog(tmp_path / "thread.jsonl", clock=_clock([100.0, 100.5, 101.25, 102.0, 103.0, 104.0, 105.0, 106.0]))
    log.append("turn_start", "t1", prompt="q")
    log.append("user", "t1", content="q", llm_content="q")
    log.append(
        "assistant", "t1", content="Fetching.", phase="commentary",
        tool_calls=[
            _call("c1", "get_market_data", {"codes": ["AAPL.US"], "api_key": "sk-secret", "note": "x" * 300}),
            _call("c2", "write_file", {"path": "report.md"}),
        ],
    )
    log.append("tool_result", "t1", tool_call_id="c1", name="get_market_data",
               content="P" * 250, status="ok", elapsed_ms=17.9)
    artifact = {"report_id": "r1", "filename": "report.md", "download_url": "/api/reports/r1"}
    log.append("tool_result", "t1", tool_call_id="c2", name="write_file",
               content='{"status": "ok"}', status="ok", elapsed_ms=3, artifact=artifact)
    log.append("assistant", "t1", content="The answer.", phase="final")
    log.append("turn_end", "t1", status="completed", usage={"input_tokens": 5}, elapsed_ms=900)

    projection = project_turn(log.read(), "t1")

    assert projection.status == "completed"
    assert projection.content == "The answer."
    assert projection.usage == {"input_tokens": 5}
    assert projection.elapsed_ms == 900
    assert projection.tool_trail == [
        {
            "tool": "get_market_data",
            "status": "ok",
            "arguments": {"codes": "['AAPL.US']", "api_key": "[redacted]", "note": "x" * 200},
            "timestamp": 101250,
            "call_id": "c1",
            "elapsed_ms": 17,
            "preview": "P" * 200,
        },
        {
            "tool": "write_file",
            "status": "ok",
            "arguments": {"path": "report.md"},
            "timestamp": 101250,
            "call_id": "c2",
            "elapsed_ms": 3,
            "preview": '{"status": "ok"}',
            "artifact": artifact,
        },
    ]


def test_projection_matches_the_retired_live_trail_recorder(tmp_path: Path) -> None:
    """The keys and values the live-event trail recorder produced, fixed.

    ``SessionService._record_tool_trail_event`` built the trail from SSE
    events until the trail was projected from the thread; these are the
    values it produced for the same call and result.
    """
    log = ThreadLog(tmp_path / "thread.jsonl")
    log.append("assistant", "t1", content="", tool_calls=[_call("c1", "search_symbol", {"query": "苹果"})])
    log.append("tool_result", "t1", tool_call_id="c1", name="search_symbol",
               content='{"status": "error"}', status="error", elapsed_ms=4)
    log.append("turn_end", "t1", status="completed")

    projected = project_turn(log.read(), "t1").tool_trail

    strip = lambda entries: [{k: v for k, v in e.items() if k != "timestamp"} for e in entries]  # noqa: E731
    assert strip(projected) == [
        {
            "tool": "search_symbol",
            "status": "error",
            "arguments": {"query": "苹果"},
            "call_id": "c1",
            "elapsed_ms": 4,
            "preview": '{"status": "error"}',
        }
    ]
    assert isinstance(projected[0]["timestamp"], int)


def test_run_dir_argument_is_shown_as_the_live_event_showed_it(tmp_path: Path) -> None:
    run_dir = str(tmp_path / "runs" / "r1")
    log = ThreadLog(tmp_path / "thread.jsonl")
    log.append("assistant", "t1", content="", tool_calls=[
        _call("c1", "backtest", {"run_dir": "."}),
        _call("c2", "read_file", {"path": "a"}),
    ])

    trail = project_turn(log.read(), "t1", run_dir=run_dir).tool_trail

    assert trail[0]["arguments"] == {"run_dir": str(Path(run_dir).resolve())}
    assert trail[1]["arguments"] == {"path": "a", "run_dir": run_dir}


def test_cancelled_turn_projection_has_no_final_text_and_no_running_entries(tmp_path: Path) -> None:
    log = ThreadLog(tmp_path / "thread.jsonl")
    log.append("turn_start", "t1", prompt="q")
    log.append("assistant", "t1", content="Fetching.", phase="commentary",
               tool_calls=[_call("c1", "get_market_data", {}), _call("c2", "get_market_data", {})])
    log.append("tool_result", "t1", tool_call_id="c1", name="get_market_data", content="R", status="ok")
    log.append("tool_result", "t1", tool_call_id="ghost", name="other_tool", content="E", status="error")
    log.append("turn_end", "t1", status="cancelled")
    log.append("turn_start", "t2", prompt="next")

    projection = project_turn(log.read(), "t1")

    assert projection.status == "cancelled"
    assert projection.content is None
    assert [(e["call_id"], e["status"]) for e in projection.tool_trail] == [
        ("c1", "ok"), ("c2", "error"), ("ghost", "error"),
    ]
    assert projection.tool_trail[1]["preview"] == INTERRUPTED_RESULT_CONTENT[:200]
    assert projection.tool_trail[2]["arguments"] == {}
    # A turn still running keeps its calls running.
    assert project_turn(log.read(), "t2").status is None


def test_plain_final_answer_without_phase_is_the_content(tmp_path: Path) -> None:
    log = ThreadLog(tmp_path / "thread.jsonl")
    log.append("assistant", "t1", content="Only text.")
    log.append("turn_end", "t1", status="completed")

    assert project_turn(log.read(), "t1").content == "Only text."
