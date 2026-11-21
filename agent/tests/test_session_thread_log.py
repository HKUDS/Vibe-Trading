"""thread.jsonl: append-only items, seq assignment and tolerant reads."""

from __future__ import annotations

import json
import multiprocessing
import threading
from pathlib import Path

import pytest

from src.session.store import SessionStore
from src.session.thread import ThreadItemError, ThreadLog, open_turns


def _tool_call(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _write_full_turn(log: ThreadLog, turn_id: str) -> None:
    log.append("turn_start", turn_id, prompt="AAPL drawdown?", model="m", provider="p")
    log.append("user", turn_id, content="AAPL drawdown?", llm_content="<agent-state/>AAPL drawdown?")
    log.append(
        "assistant",
        turn_id,
        content="Fetching.",
        tool_calls=[_tool_call("c1", "get_market_data", {"codes": ["AAPL.US"]})],
        reasoning_content="think",
        phase="commentary",
    )
    log.append(
        "tool_result",
        turn_id,
        tool_call_id="c1",
        name="get_market_data",
        content='{"status": "ok"}',
        status="ok",
        elapsed_ms=12,
    )
    log.append("assistant", turn_id, content="Max drawdown was 8%.", phase="final")
    log.append("state", turn_id, loaded_tools=["get_market_data"])
    log.append("turn_end", turn_id, status="completed", usage={"input_tokens": 10}, elapsed_ms=40)


def _append_from_process(path: str, worker_id: int, count: int) -> None:
    log = ThreadLog(Path(path))
    for index in range(count):
        log.append("inject", f"process-{worker_id}", content=f"{worker_id}-{index}")


def test_round_trip_keeps_every_field_and_type(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    log = store.thread_log("s1")
    assert log.path == tmp_path / "sessions" / "s1" / "thread.jsonl"
    _write_full_turn(log, "t1")
    log.append("inject", "t1", content="<system>go on</system>")
    log.append("compaction", "t1", summary="sum", replaces_through_seq=3)

    items = ThreadLog(log.path).read()

    assert [item.type for item in items] == [
        "turn_start", "user", "assistant", "tool_result", "assistant",
        "state", "turn_end", "inject", "compaction",
    ]
    assert [item.seq for item in items] == list(range(1, 10))
    assert all(item.turn_id == "t1" for item in items)
    assert items[1].data == {"content": "AAPL drawdown?", "llm_content": "<agent-state/>AAPL drawdown?"}
    assert items[2].data == {
        "content": "Fetching.",
        "tool_calls": [_tool_call("c1", "get_market_data", {"codes": ["AAPL.US"]})],
        "reasoning_content": "think",
        "provider_items": None,
        "phase": "commentary",
    }
    assert items[3].data == {
        "tool_call_id": "c1", "name": "get_market_data", "content": '{"status": "ok"}',
        "status": "ok", "elapsed_ms": 12, "artifact": None,
    }
    assert items[4].get("tool_calls") == []
    assert items[5].data == {"loaded_tools": ["get_market_data"]}
    assert items[6].data == {"status": "completed", "usage": {"input_tokens": 10}, "elapsed_ms": 40}
    assert items[7].data == {"content": "<system>go on</system>", "role": "user"}
    assert items[8].data == {"summary": "sum", "replaces_through_seq": 3}
    # On disk each line is the flat shape, one object per line.
    lines = log.path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["prompt"] == "AAPL drawdown?"
    assert set(json.loads(lines[6])) == {"seq", "ts", "turn_id", "type", "status", "usage", "elapsed_ms"}


@pytest.mark.parametrize(
    ("item_type", "payload"),
    [
        ("nonsense", {}),
        ("user", {"content": "x"}),
        ("assistant", {"phase": "draft"}),
        ("assistant", {"tool_calls": [{"function": {"name": "x"}}]}),
        ("tool_result", {"tool_call_id": "c", "name": "n", "content": "x", "status": "running"}),
        ("turn_end", {"status": "done"}),
        ("turn_end", {"status": "completed", "seq": 5}),
        ("compaction", {"summary": "s", "replaces_through_seq": "3"}),
        ("inject", {"content": "x", "extra": 1}),
    ],
)
def test_append_rejects_items_that_do_not_match_the_schema(tmp_path: Path, item_type, payload) -> None:
    log = ThreadLog(tmp_path / "thread.jsonl")
    with pytest.raises(ThreadItemError):
        log.append(item_type, "t1", **payload)
    assert not log.path.exists()
    # A rejected item does not consume a seq.
    assert log.append("turn_start", "t1", prompt="p").seq == 1


def test_seq_is_recovered_from_the_file_after_reopen(tmp_path: Path) -> None:
    path = tmp_path / "s" / "thread.jsonl"
    _write_full_turn(ThreadLog(path), "t1")
    # Forget this process's writer state, as a restart would.
    from src.session import thread as thread_module

    thread_module._PATH_STATES.clear()

    reopened = ThreadLog(path)
    item = reopened.append("turn_start", "t2", prompt="next")

    assert item.seq == 8
    assert [i.seq for i in reopened.read()] == list(range(1, 9))


def test_seq_follows_an_append_made_outside_this_writer(tmp_path: Path) -> None:
    path = tmp_path / "thread.jsonl"
    log = ThreadLog(path)
    log.append("turn_start", "t1", prompt="p")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"seq": 41, "ts": 1.0, "turn_id": "t1", "type": "turn_end", "status": "completed"}) + "\n")

    assert log.append("turn_start", "t2", prompt="q").seq == 42


def test_seq_never_moves_backwards_when_the_file_shrinks(tmp_path: Path) -> None:
    path = tmp_path / "thread.jsonl"
    log = ThreadLog(path)
    for _ in range(3):
        log.append("turn_start", "t1", prompt="p")
    path.write_bytes(path.read_bytes().splitlines(keepends=True)[0])

    assert log.append("turn_end", "t1", status="completed").seq == 4


def test_concurrent_appends_from_two_logs_keep_seq_unique_and_ordered(tmp_path: Path) -> None:
    path = tmp_path / "thread.jsonl"
    writers = [ThreadLog(path), ThreadLog(path)]
    barrier = threading.Barrier(8)

    def write(index: int) -> None:
        log = writers[index % 2]
        barrier.wait()
        for n in range(50):
            log.append("inject", f"t{index}", content=f"{index}-{n}")

    threads = [threading.Thread(target=write, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    items = ThreadLog(path).read()
    seqs = [item.seq for item in items]
    assert len(items) == 400
    assert seqs == list(range(1, 401))
    assert len(path.read_bytes().splitlines()) == 400


def test_concurrent_appends_from_processes_keep_seq_unique_and_ordered(tmp_path: Path) -> None:
    path = tmp_path / "thread.jsonl"
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(target=_append_from_process, args=(str(path), worker_id, 30))
        for worker_id in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    items = ThreadLog(path).read()
    seqs = [item.seq for item in items]
    assert len(items) == 120
    assert seqs == list(range(1, 121))


def test_a_corrupt_line_costs_that_line_only(tmp_path: Path, caplog) -> None:
    path = tmp_path / "thread.jsonl"
    log = ThreadLog(path)
    log.append("turn_start", "t1", prompt="before")
    with path.open("ab") as handle:
        handle.write(b"{not json\n")
        handle.write(b"\xff\xfe\n")
        handle.write(b"[1, 2]\n")
        handle.write(json.dumps({"seq": 3, "ts": 1.0, "turn_id": "t1", "type": "user", "content": "no llm"}).encode() + b"\n")
        handle.write(json.dumps({"seq": 4, "ts": 1.0, "turn_id": "t1", "type": "assistant", "tool_calls": "x"}).encode() + b"\n")
    log.append("turn_end", "t1", status="completed")

    with caplog.at_level("WARNING"):
        items = ThreadLog(path).read()

    assert [(item.type, item.seq) for item in items] == [("turn_start", 1), ("turn_end", 5)]
    assert sum("Skipping corrupted thread record" in r.message for r in caplog.records) == 5


def test_a_torn_last_line_does_not_swallow_the_next_record(tmp_path: Path) -> None:
    path = tmp_path / "thread.jsonl"
    log = ThreadLog(path)
    log.append("turn_start", "t1", prompt="p")
    with path.open("ab") as handle:
        handle.write(b'{"seq": 2, "ts": 1.0, "turn_id": "t1", "type": "us')

    item = log.append("turn_end", "t1", status="interrupted")

    assert item.seq == 2
    assert [(i.type, i.seq) for i in log.read()] == [("turn_start", 1), ("turn_end", 2)]


def test_queries_items_after_last_compaction_and_open_turns(tmp_path: Path) -> None:
    log = ThreadLog(tmp_path / "thread.jsonl")
    _write_full_turn(log, "t1")
    log.append("compaction", "t2", summary="first", replaces_through_seq=2)
    log.append("turn_start", "t2", prompt="q")
    log.append("compaction", "t2", summary="second", replaces_through_seq=7)
    log.append("turn_start", "t3", prompt="r")

    assert [item.seq for item in log.items_after(9)] == [10, 11]
    assert log.last_compaction().get("summary") == "second"
    assert log.open_turns() == ["t2", "t3"]
    assert open_turns(log.read()) == ["t2", "t3"]
    assert [item.type for item in log.turn_items("t3")] == ["turn_start"]
    assert ThreadLog(tmp_path / "missing.jsonl").read() == []
    assert ThreadLog(tmp_path / "missing.jsonl").last_compaction() is None


def test_lone_surrogate_text_round_trips_exactly(tmp_path: Path) -> None:
    log = ThreadLog(tmp_path / "thread.jsonl")
    log.append("user", "t1", content="a\ud800b", llm_content="a\ud800b")

    assert log.read()[0].get("llm_content") == "a\ud800b"
