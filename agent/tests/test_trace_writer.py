"""The thread replaces trace blobs while retaining durability and path safety."""
from __future__ import annotations

import cli.commands.common as _cmd_common
import cli.commands.inspection as _cmd_inspection

import json
import os
import stat

import pytest

import src.session.thread as thread_module
from src.session.thread import ThreadLog, diagnostic_records
from tests.module_os_helpers import patch_module_os
from tests.recording_helpers import recorder_at, records_at


def test_tool_result_ids_are_data_not_paths(tmp_path):
    recorder = recorder_at(tmp_path)
    recorder.tool_result({"tool_call_id": "../escape/token", "name": "danger_tool", "content": "large result body"}, status="ok", elapsed_ms=12)
    [entry] = records_at(tmp_path)
    assert entry["result"] == "large result body"
    assert entry["call_id"] == "../escape/token"
    assert not (tmp_path.parent / "escape" / "token").exists()
    assert not list(tmp_path.rglob("*.txt"))


def test_reader_never_opens_paths_in_diagnostic_data(tmp_path):
    (tmp_path / "secret.txt").write_text("do-not-read")
    recorder = recorder_at(tmp_path)
    recorder.write({"type": "note", "result_path": "../secret.txt"})
    [entry] = records_at(tmp_path)
    assert "result" not in entry
    assert "do-not-read" not in json.dumps(entry)


def test_reader_keeps_unicode_line_separator_inside_record(tmp_path):
    recorder = recorder_at(tmp_path)
    recorder.write({"type": "note", "content": "before\u2028after\u2029end"})
    [entry] = records_at(tmp_path)
    assert entry["content"] == "before\u2028after\u2029end"


def test_long_answer_is_one_canonical_item_without_blob(tmp_path):
    recorder = recorder_at(tmp_path)
    body = "long final answer" * 10000
    recorder.assistant({"content": body}, phase="final")
    [item] = recorder._runtime.thread.read()
    assert item.type == "assistant"
    assert item.get("content") == body
    assert records_at(tmp_path)[0]["content"] == body
    assert not (tmp_path / "trace-blobs").exists()


def test_cli_record_lookup_prefers_session_then_run(tmp_path, monkeypatch):
    pass
    sessions, runs = tmp_path / "sessions", tmp_path / "runs"
    monkeypatch.setattr(_cmd_common, "SESSIONS_DIR", sessions)
    monkeypatch.setattr(_cmd_common, "RUNS_DIR", runs)
    recorder_at(sessions / "abc").assistant({"content": "session"}, phase="final")
    recorder_at(runs / "abc").assistant({"content": "run"}, phase="final")
    assert _cmd_inspection._thread_entries_for_run("abc")[0]["content"] == "session"
    assert _cmd_inspection._thread_entries_for_run("missing") == []


def test_append_fsyncs_each_record(tmp_path, monkeypatch):
    log = ThreadLog(tmp_path / "thread.jsonl")
    log.append("turn_start", "t", prompt="q")
    observed = []
    real_fsync = os.fsync
    def tracking(fd):
        observed.append(stat.S_ISREG(os.fstat(fd).st_mode))
        real_fsync(fd)
    patch_module_os(monkeypatch, thread_module, fsync=tracking)
    log.append("assistant", "t", content="ok")
    assert observed == [True]


@pytest.mark.skipif(os.name == "nt", reason="directory fsync is POSIX only")
def test_new_thread_fsyncs_parent_directory(tmp_path, monkeypatch):
    observed = []
    real_fsync = os.fsync
    def tracking(fd):
        observed.append(stat.S_ISDIR(os.fstat(fd).st_mode))
        real_fsync(fd)
    patch_module_os(monkeypatch, thread_module, fsync=tracking)
    ThreadLog(tmp_path / "thread.jsonl").append("turn_start", "t", prompt="q")
    assert observed.count(True) == 1
    observed.clear()
    ThreadLog(tmp_path / "thread.jsonl").append("assistant", "t", content="ok")
    assert observed == [False]


def test_fsync_failure_reports_degraded_recording(tmp_path, monkeypatch, caplog):
    recorder = recorder_at(tmp_path)
    def failing(fd):
        raise OSError("fsync unsupported")
    patch_module_os(monkeypatch, thread_module, fsync=failing)
    recorder.assistant({"content": "answer"}, phase="final")
    assert recorder.degraded
    assert "Could not record" in caplog.text


def test_large_tool_result_needs_no_second_file(tmp_path):
    recorder = recorder_at(tmp_path)
    body = "result" * 10000
    recorder.tool_result({"tool_call_id": "c", "name": "tool", "content": body}, status="ok")
    assert records_at(tmp_path)[0]["result"] == body
    assert [p.name for p in tmp_path.rglob("*") if p.is_file()] == ["thread.jsonl"]


def test_torn_record_does_not_swallow_next_answer(tmp_path):
    path = tmp_path / "thread.jsonl"
    path.write_bytes(b'{"seq":1,"type":')
    ThreadLog(path).append("assistant", "t", content="saved", phase="final")
    assert [r["content"] for r in diagnostic_records(ThreadLog(path).read())] == ["saved"]


def test_reopened_thread_preserves_whole_large_record(tmp_path):
    log = ThreadLog(tmp_path / "thread.jsonl")
    body = "x" * 100000
    log.append("assistant", "t", content=body, phase="final")
    assert ThreadLog(log.path).read()[0].get("content") == body


def test_failed_append_creates_no_sidecar_temp_file(tmp_path, monkeypatch):
    recorder = recorder_at(tmp_path)
    def failing(fd):
        raise OSError("disk exploded")
    patch_module_os(monkeypatch, thread_module, fsync=failing)
    recorder.tool_result({"tool_call_id": "c", "name": "tool", "content": "y" * 5000}, status="ok")
    assert recorder.degraded
    assert not list(tmp_path.rglob("*.tmp"))
    assert not (tmp_path / "tool-results").exists()
