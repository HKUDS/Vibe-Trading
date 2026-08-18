"""TraceWriter offload and path-safety tests."""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path

import pytest

import src.agent.trace as trace_mod
from src.agent.trace import TraceWriter
from tests.module_os_helpers import patch_module_os


def _raw_entries(trace_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (trace_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_tool_result_offload_uses_safe_name_and_resolves_only_on_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Large tool results should not trust provider-supplied call IDs as paths."""
    monkeypatch.setattr(trace_mod, "TOOL_RESULT_OFFLOAD_THRESHOLD", 8)
    trace = TraceWriter(tmp_path)

    trace.write_tool_result(
        call_id="../escape/token",
        result="large result body",
        tool_name="danger_tool",
        status="ok",
        elapsed_ms=12,
        iteration=3,
    )
    trace.close()

    [entry] = _raw_entries(tmp_path)
    assert "result" not in entry
    assert entry["preview"] == "large result body"[: trace_mod.OFFLOAD_PREVIEW_CHARS]
    assert entry["result_preview"] == entry["preview"]
    assert entry["result_size"] == len("large result body")
    assert entry["result_path"].startswith("tool-results/")
    assert ".." not in Path(entry["result_path"]).parts
    assert Path(entry["result_path"]).name == Path(entry["result_path"]).as_posix().split("/")[-1]
    assert not (tmp_path.parent / "escape" / "token").exists()

    unresolved = TraceWriter.read(tmp_path)
    assert "result" not in unresolved[0]

    resolved = TraceWriter.read(tmp_path, resolve_offloads=True)
    assert resolved[0]["result"] == "large result body"


def test_trace_reader_refuses_offload_path_escape(tmp_path: Path) -> None:
    """A malicious trace.jsonl must not make read() open files outside trace dir."""
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("do-not-read", encoding="utf-8")
    trace_dir = tmp_path / "trace"
    trace_dir.mkdir()
    (trace_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "type": "tool_result",
                "iter": 1,
                "tool": "ghost",
                "result_path": "../secret.txt",
                "result_preview": "x",
                "result_size": 11,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    [entry] = TraceWriter.read(trace_dir, resolve_offloads=True)

    assert "result" not in entry


def test_text_field_offload_round_trips_selected_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Long prompt/answer fields can be offloaded without forcing all blobs open."""
    monkeypatch.setattr(trace_mod, "TRACE_TEXT_OFFLOAD_THRESHOLD", 8)
    trace = TraceWriter(tmp_path)
    trace.write_text_entry(
        {"type": "answer", "iter": 1},
        field="content",
        value="long final answer",
        offload_kind="answer",
    )
    trace.close()

    unresolved = TraceWriter.read(tmp_path)
    assert "content" not in unresolved[0]
    assert unresolved[0]["content_preview"] == "long final answer"[: trace_mod.OFFLOAD_PREVIEW_CHARS]

    still_unresolved = TraceWriter.read(
        tmp_path,
        resolve_offloads=True,
        resolve_fields={"result"},
    )
    assert "content" not in still_unresolved[0]

    resolved = TraceWriter.read(
        tmp_path,
        resolve_offloads=True,
        resolve_fields={"content"},
    )
    assert resolved[0]["content"] == "long final answer"


def test_find_trace_dir_prefers_sessions_then_runs(tmp_path: Path) -> None:
    """Session traces are preferred while legacy run traces still work."""
    sessions = tmp_path / "sessions"
    runs = tmp_path / "runs"
    session_dir = sessions / "abc"
    run_dir = runs / "abc"
    session_dir.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    (session_dir / "trace.jsonl").write_text('{"type":"session"}\n', encoding="utf-8")
    (run_dir / "trace.jsonl").write_text('{"type":"run"}\n', encoding="utf-8")

    assert TraceWriter.find_trace_dir("abc", runs_dir=runs, sessions_dir=sessions) == session_dir
    assert TraceWriter.find_trace_dir("missing", runs_dir=runs, sessions_dir=sessions) is None


def test_write_calls_fsync_for_crash_safety(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``write`` flushes AND fsyncs so the last record survives a hard crash.

    Regression for the historical "crash-safe" docstring claim that only
    flushed. Without ``os.fsync`` the kernel page cache can lose the last
    record on a host kill / power event.
    """
    trace = TraceWriter(tmp_path)
    fsync_fds: list[int] = []
    real_fsync = os.fsync

    def _tracking_fsync(fd: int) -> None:
        fsync_fds.append(fd)
        real_fsync(fd)

    patch_module_os(monkeypatch, trace_mod, fsync=_tracking_fsync)
    try:
        trace.write({"type": "answer", "iter": 1, "content": "ok"})
        assert fsync_fds == [trace._file.fileno()]
    finally:
        trace.close()


def test_new_trace_file_fsyncs_parent_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Creating trace.jsonl durably records the new directory entry."""
    dir_fsyncs: list[int] = []
    real_fsync = os.fsync

    def _tracking_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            dir_fsyncs.append(fd)
        real_fsync(fd)

    patch_module_os(monkeypatch, trace_mod, fsync=_tracking_fsync)
    trace = TraceWriter(tmp_path)
    trace.close()
    assert len(dir_fsyncs) == 1

    dir_fsyncs.clear()
    reopened = TraceWriter(tmp_path)
    reopened.close()
    assert dir_fsyncs == []


def test_fsync_oserror_warns_once_and_keeps_writing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """fsync failure degrades to flush-only with one warning, never silence."""
    trace = TraceWriter(tmp_path)

    def _failing_fsync(fd: int) -> None:
        raise OSError("fsync unsupported")

    patch_module_os(monkeypatch, trace_mod, fsync=_failing_fsync)
    with caplog.at_level(logging.WARNING, logger="src.agent.trace"):
        trace.write({"type": "answer", "iter": 1, "content": "a"})
        trace.write({"type": "answer", "iter": 2, "content": "b"})
    trace.close()

    warnings = [rec for rec in caplog.records if "fsync" in rec.message]
    assert len(warnings) == 1
    assert [entry["iter"] for entry in _raw_entries(tmp_path)] == [1, 2]


def test_sidecar_write_is_atomic_and_leaves_no_temp_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Sidecars are written temp-file-then-rename with no leftover litter."""
    monkeypatch.setattr(trace_mod, "TOOL_RESULT_OFFLOAD_THRESHOLD", 8)
    replace_targets: list[str] = []
    real_replace = os.replace

    def _tracking_replace(src: object, dst: object) -> None:
        replace_targets.append(str(dst))
        real_replace(src, dst)

    patch_module_os(monkeypatch, trace_mod, replace=_tracking_replace)
    trace = TraceWriter(tmp_path)
    trace.write_tool_result(
        call_id="call-1",
        result="large result body",
        tool_name="tool",
        status="ok",
        elapsed_ms=1,
        iteration=1,
    )
    trace.close()

    [entry] = _raw_entries(tmp_path)
    sidecar = tmp_path / entry["result_path"]
    assert sidecar.read_text(encoding="utf-8") == "large result body"
    assert replace_targets == [str(sidecar)]
    assert [p.name for p in sidecar.parent.iterdir()] == [sidecar.name]


def test_record_never_references_missing_sidecar_on_crash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A failed sidecar rename must abort BEFORE the referencing record is written.

    Otherwise a crash could persist a durable record whose ``result_path``
    target is missing or truncated.
    """
    monkeypatch.setattr(trace_mod, "TOOL_RESULT_OFFLOAD_THRESHOLD", 8)
    trace = TraceWriter(tmp_path)

    def _failing_replace(src: object, dst: object) -> None:
        raise OSError("simulated crash before sidecar rename")

    patch_module_os(monkeypatch, trace_mod, replace=_failing_replace)
    with pytest.raises(OSError, match="simulated crash"):
        trace.write_tool_result(
            call_id="call-1",
            result="large result body",
            tool_name="tool",
            status="ok",
            elapsed_ms=1,
            iteration=1,
        )
    trace.close()

    assert _raw_entries(tmp_path) == []
    assert list((tmp_path / "tool-results").glob("*.txt")) == []


def test_sidecar_survives_a_partial_write(tmp_path, monkeypatch):
    """os.write can write fewer bytes than requested; the blob must still be whole."""
    import os as _os

    real_write = _os.write
    state = {"first": True}

    def _short_write(fd, data):
        if state["first"] and len(data) > 16:
            state["first"] = False
            return real_write(fd, data[:16])
        return real_write(fd, data)

    patch_module_os(monkeypatch, trace_mod, write=_short_write)

    writer = TraceWriter(tmp_path)
    body = "x" * 5000
    entry: dict = {}
    writer._attach_text_field(entry, field="result", value=body, offload_kind="result",
                              threshold=10, offload_dir_name="results")
    writer.write(entry)

    sidecar = tmp_path / entry["result_path"]
    assert sidecar.read_text(encoding="utf-8") == body


def test_failed_sidecar_write_leaves_no_temp_file(tmp_path, monkeypatch):
    """A write error must not strand a half-written temp blob."""

    def _boom(fd, data):
        raise OSError("disk exploded")

    patch_module_os(monkeypatch, trace_mod, write=_boom)
    writer = TraceWriter(tmp_path)
    with pytest.raises(OSError):
        writer._attach_text_field({}, field="result", value="y" * 5000,
                                  offload_kind="result", threshold=10,
                                  offload_dir_name="results")
    leftovers = list((tmp_path / "results").glob(".*tmp"))
    assert leftovers == []
