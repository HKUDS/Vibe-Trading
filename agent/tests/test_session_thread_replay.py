"""replay(): thread items -> the OpenAI-format history the next turn sends."""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages.utils import convert_to_messages

from src.session.thread import (
    INTERRUPTED_RESULT_CONTENT,
    STOPPED_TURN_NOTES,
    ThreadLog,
    replay,
)


def _call(call_id: str, name: str = "get_market_data", arguments: dict | None = None) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments or {"codes": ["AAPL.US"]})},
    }


def _assert_provider_valid(messages: list[dict]) -> None:
    """OpenAI's rule: each tool-call message is followed directly by exactly
    one result per call, and no tool message appears anywhere else."""
    index = 0
    while index < len(messages):
        message = messages[index]
        assert message["role"] != "tool", f"tool message without a call at {index}"
        index += 1
        expected = [call["id"] for call in message.get("tool_calls", [])]
        seen = []
        while index < len(messages) and messages[index]["role"] == "tool":
            seen.append(messages[index]["tool_call_id"])
            index += 1
        assert sorted(seen) == sorted(expected), (expected, seen)
    convert_to_messages(messages)


def _turn(log: ThreadLog, turn_id: str, prompt: str, *, end: str | None = "completed") -> None:
    log.append("turn_start", turn_id, prompt=prompt)
    log.append("user", turn_id, content=prompt, llm_content=f"<agent-state>x</agent-state>\n{prompt}")
    log.append("assistant", turn_id, content=f"answer to {prompt}", phase="final")
    if end is not None:
        log.append("turn_end", turn_id, status=end)


def test_replay_rebuilds_each_item_verbatim_and_skips_bookkeeping(tmp_path: Path) -> None:
    log = ThreadLog(tmp_path / "thread.jsonl")
    log.append("turn_start", "t1", prompt="q")
    log.append("user", "t1", content="q", llm_content="LLM q")
    log.append("state", "t1", loaded_tools=["x"])
    log.append(
        "assistant", "t1", content=None,
        tool_calls=[_call("c1")], reasoning_content="why", provider_items=[{"type": "reasoning", "id": "r"}],
        phase="commentary",
    )
    log.append("tool_result", "t1", tool_call_id="c1", name="get_market_data", content="R1", status="ok")
    log.append("inject", "t1", content="<system>Continue.</system>")
    log.append("assistant", "t1", content="done", phase="final")
    log.append("turn_end", "t1", status="completed")

    assert replay(log.read()) == [
        {"role": "user", "content": "LLM q"},
        {
            "role": "assistant", "content": None, "tool_calls": [_call("c1")],
            "reasoning_content": "why", "provider_items": [{"type": "reasoning", "id": "r"}],
        },
        {"role": "tool", "tool_call_id": "c1", "name": "get_market_data", "content": "R1"},
        {"role": "user", "content": "<system>Continue.</system>"},
        {"role": "assistant", "content": "done"},
    ]


def test_assistant_key_order_matches_the_loop_formatter(tmp_path: Path) -> None:
    from src.agent.context import ContextBuilder
    from types import SimpleNamespace

    tc = SimpleNamespace(id="c1", name="get_market_data", arguments={"codes": ["AAPL.US"]},
                         extra_content={"google": {"thought_signature": "sig"}})
    sent = ContextBuilder.format_assistant_tool_calls(
        [tc], content="x", reasoning_content="r", provider_items=[{"a": 1}],
    )
    log = ThreadLog(tmp_path / "thread.jsonl")
    log.append(
        "assistant", "t1", content=sent["content"], tool_calls=sent["tool_calls"],
        reasoning_content=sent["reasoning_content"], provider_items=sent["provider_items"],
    )
    log.append("tool_result", "t1", tool_call_id="c1", name="get_market_data", content="R", status="ok")

    replayed = replay(log.read())[0]

    assert json.dumps(replayed, ensure_ascii=False) == json.dumps(sent, ensure_ascii=False)


def test_llm_content_is_replayed_byte_for_byte_and_history_is_prefix_stable(tmp_path: Path) -> None:
    log = ThreadLog(tmp_path / "thread.jsonl")
    llm_content = (
        "<agent-state>\nsymbols: 苹果 AAPL.US\n</agent-state>\n"
        "<recalled-memory>  trailing spaces  \t\n​ zero width, emoji 📈, \"quotes\" \\ back</recalled-memory>\n"
        "苹果这三个月最大回撤多少？  "
    )
    log.append("turn_start", "t1", prompt="苹果这三个月最大回撤多少？")
    log.append("user", "t1", content="苹果这三个月最大回撤多少？", llm_content=llm_content)
    log.append("assistant", "t1", content="8.1%", phase="final")
    log.append("turn_end", "t1", status="completed")

    first = replay(ThreadLog(log.path).read())
    assert first[0]["content"] == llm_content
    assert json.dumps(first[0], ensure_ascii=False) == json.dumps(
        {"role": "user", "content": llm_content}, ensure_ascii=False
    )

    _turn(log, "t2", "继续")
    second = replay(ThreadLog(log.path).read())

    assert json.dumps(second[: len(first)], ensure_ascii=False) == json.dumps(first, ensure_ascii=False)
    assert second[len(first)]["content"].endswith("继续")


def test_a_call_without_a_result_gets_an_interrupted_result_only_in_the_request(tmp_path: Path) -> None:
    log = ThreadLog(tmp_path / "thread.jsonl")
    log.append("turn_start", "t1", prompt="q")
    log.append("user", "t1", content="q", llm_content="q")
    log.append("assistant", "t1", content="", tool_calls=[_call("c1"), _call("c2", "search_symbol")])
    log.append("tool_result", "t1", tool_call_id="c1", name="get_market_data", content="R1", status="ok")
    log.append("inject", "t1", content="<system>held</system>")
    log.append("turn_end", "t1", status="completed")
    before = log.path.read_bytes()

    messages = replay(log.read())

    assert messages[1:5] == [
        {"role": "assistant", "content": "", "tool_calls": [_call("c1"), _call("c2", "search_symbol")]},
        {"role": "tool", "tool_call_id": "c1", "name": "get_market_data", "content": "R1"},
        {"role": "tool", "tool_call_id": "c2", "name": "search_symbol", "content": INTERRUPTED_RESULT_CONTENT},
        {"role": "user", "content": "<system>held</system>"},
    ]
    _assert_provider_valid(messages)
    assert log.path.read_bytes() == before
    assert all(item.type != "tool_result" or item.get("tool_call_id") != "c2" for item in log.read())


def test_a_result_without_a_call_is_dropped_only_in_the_request(tmp_path: Path) -> None:
    log = ThreadLog(tmp_path / "thread.jsonl")
    log.append("turn_start", "t1", prompt="q")
    log.append("user", "t1", content="q", llm_content="q")
    log.append("tool_result", "t1", tool_call_id="ghost", name="x", content="orphan", status="ok")
    log.append("assistant", "t1", content="", tool_calls=[_call("c1")])
    log.append("tool_result", "t1", tool_call_id="c1", name="get_market_data", content="R1", status="ok")
    log.append("tool_result", "t1", tool_call_id="c1", name="get_market_data", content="dup", status="ok")
    log.append("assistant", "t1", content="a", phase="final")
    log.append("tool_result", "t1", tool_call_id="c1", name="get_market_data", content="late", status="ok")
    log.append("turn_end", "t1", status="completed")
    before = log.path.read_bytes()

    messages = replay(log.read())

    assert [m.get("content") for m in messages if m["role"] == "tool"] == ["R1"]
    _assert_provider_valid(messages)
    assert log.path.read_bytes() == before
    assert sum(item.type == "tool_result" for item in log.read()) == 4


def test_pairing_is_positional_so_a_reused_call_id_pairs_with_its_own_turn(tmp_path: Path) -> None:
    log = ThreadLog(tmp_path / "thread.jsonl")
    for turn_id, result in (("t1", "first"), ("t2", None)):
        log.append("turn_start", turn_id, prompt="q")
        log.append("user", turn_id, content="q", llm_content="q")
        log.append("assistant", turn_id, content="", tool_calls=[_call("functions.get_market_data:0")])
        if result:
            log.append("tool_result", turn_id, tool_call_id="functions.get_market_data:0",
                       name="get_market_data", content=result, status="ok")
        log.append("turn_end", turn_id, status="completed")

    tool_messages = [m["content"] for m in replay(log.read()) if m["role"] == "tool"]

    assert tool_messages == ["first", INTERRUPTED_RESULT_CONTENT]


def test_replay_starts_after_the_last_compaction_with_its_summary_first(tmp_path: Path) -> None:
    log = ThreadLog(tmp_path / "thread.jsonl")
    _turn(log, "t1", "one")  # seq 1-4
    log.append("compaction", "t2", summary="old summary", replaces_through_seq=2)  # 5
    _turn(log, "t2", "two")  # 6-9
    log.append("turn_start", "t3", prompt="three")  # 10
    log.append("user", "t3", content="three", llm_content="three")  # 11
    log.append("assistant", "t3", content="", tool_calls=[_call("c1")])  # 12
    log.append("tool_result", "t3", tool_call_id="c1", name="get_market_data", content="R", status="ok")  # 13
    log.append("compaction", "t3", summary="new summary", replaces_through_seq=12)  # 14
    log.append("assistant", "t3", content="three done", phase="final")  # 15
    log.append("turn_end", "t3", status="completed")  # 16

    messages = replay(log.read())

    # The result whose call the summary replaced is an orphan and is dropped.
    assert messages == [
        {"role": "user", "content": "new summary"},
        {"role": "assistant", "content": "three done"},
    ]


def test_compaction_keeps_the_tail_after_its_cut(tmp_path: Path) -> None:
    log = ThreadLog(tmp_path / "thread.jsonl")
    _turn(log, "t1", "one")  # 1-4
    _turn(log, "t2", "two")  # 5-8
    log.append("compaction", "t3", summary="S", replaces_through_seq=4)

    messages = replay(log.read())

    assert messages == [
        {"role": "user", "content": "S"},
        {"role": "user", "content": "<agent-state>x</agent-state>\ntwo"},
        {"role": "assistant", "content": "answer to two"},
    ]


def _stopped_turn(log: ThreadLog, end: str | None) -> None:
    log.append("turn_start", "t1", prompt="compare")
    log.append("user", "t1", content="compare", llm_content="compare")
    log.append("assistant", "t1", content="Fetching.", tool_calls=[_call("c1"), _call("c2")], phase="commentary")
    log.append("tool_result", "t1", tool_call_id="c1", name="get_market_data", content="DATA", status="ok")
    if end is not None:
        log.append("turn_end", "t1", status=end)


def test_a_cancelled_turn_keeps_its_results_and_gets_one_note(tmp_path: Path) -> None:
    log = ThreadLog(tmp_path / "thread.jsonl")
    _stopped_turn(log, "cancelled")
    _turn(log, "t2", "continue")

    messages = replay(log.read())

    assert messages[2] == {"role": "tool", "tool_call_id": "c1", "name": "get_market_data", "content": "DATA"}
    assert messages[3]["content"] == INTERRUPTED_RESULT_CONTENT
    assert messages[4] == {"role": "user", "content": STOPPED_TURN_NOTES["cancelled"]}
    assert "user stopped" in messages[4]["content"]
    assert "still valid" in messages[4]["content"]
    assert "partly run" in messages[4]["content"]
    assert messages[5]["content"].endswith("continue")
    assert sum(m["content"] in STOPPED_TURN_NOTES.values() for m in messages) == 1
    _assert_provider_valid(messages)


def test_failed_and_interrupted_turns_get_their_own_note_and_completed_none(tmp_path: Path) -> None:
    for end, expected in (("failed", STOPPED_TURN_NOTES["failed"]),
                          ("interrupted", STOPPED_TURN_NOTES["interrupted"]),
                          ("completed", None)):
        log = ThreadLog(tmp_path / f"{end}.jsonl")
        _stopped_turn(log, end)
        notes = [m["content"] for m in replay(log.read()) if m["content"] in STOPPED_TURN_NOTES.values()]
        assert notes == ([expected] if expected else [])


def test_a_turn_with_no_end_followed_by_another_turn_is_treated_as_interrupted(tmp_path: Path) -> None:
    log = ThreadLog(tmp_path / "thread.jsonl")
    _stopped_turn(log, None)
    _turn(log, "t2", "again")

    messages = replay(log.read())

    assert messages[4] == {"role": "user", "content": STOPPED_TURN_NOTES["interrupted"]}
    _assert_provider_valid(messages)
    # A trailing turn with no end is the in-flight one: no note.
    log2 = ThreadLog(tmp_path / "trailing.jsonl")
    _stopped_turn(log2, None)
    assert all(m["content"] not in STOPPED_TURN_NOTES.values() for m in replay(log2.read()))


def test_a_stopped_turn_the_summary_covers_gets_no_note(tmp_path: Path) -> None:
    log = ThreadLog(tmp_path / "thread.jsonl")
    _stopped_turn(log, "cancelled")  # seq 1-5
    log.append("compaction", "t2", summary="S", replaces_through_seq=5)
    _turn(log, "t2", "next")

    messages = replay(log.read())

    assert messages[0] == {"role": "user", "content": "S"}
    assert all(m["content"] not in STOPPED_TURN_NOTES.values() for m in messages)


def test_replay_returns_copies(tmp_path: Path) -> None:
    log = ThreadLog(tmp_path / "thread.jsonl")
    _stopped_turn(log, "completed")
    items = log.read()

    messages = replay(items)
    messages[1]["tool_calls"][0]["function"]["name"] = "mutated"

    assert items[2].get("tool_calls")[0]["function"]["name"] == "get_market_data"
