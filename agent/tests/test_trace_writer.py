"""Tests for TraceWriter with offload support."""

import json
import tempfile
from pathlib import Path

import pytest

from src.agent.trace import (
    OFFLOAD_PREVIEW_CHARS,
    TOOL_RESULT_OFFLOAD_THRESHOLD,
    TraceWriter,
)


class TestTraceWriterInline:
    """Tool results ≤ threshold are stored inline."""

    def test_write_basic_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tw = TraceWriter(Path(tmp))
            tw.write({"type": "start", "prompt": "hello"})
            tw.close()

            entries = TraceWriter.read(Path(tmp))
            assert len(entries) == 1
            assert entries[0]["type"] == "start"
            assert entries[0]["prompt"] == "hello"
            assert "ts" in entries[0]

    def test_write_tool_result_inline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tw = TraceWriter(Path(tmp))
            result = "small result"
            tw.write_tool_result(
                call_id="call-1",
                result=result,
                tool_name="test_tool",
                status="ok",
                elapsed_ms=42,
                iteration=1,
            )
            tw.close()

            entries = TraceWriter.read(Path(tmp))
            assert len(entries) == 1
            e = entries[0]
            assert e["type"] == "tool_result"
            assert e["tool"] == "test_tool"
            assert e["call_id"] == "call-1"
            assert e["status"] == "ok"
            assert e["elapsed_ms"] == 42
            assert e["iter"] == 1
            assert e["result"] == "small result"
            assert "result_path" not in e  # No offload

    def test_write_tool_result_inline_boundary(self) -> None:
        """Exactly at threshold — still inline."""
        with tempfile.TemporaryDirectory() as tmp:
            tw = TraceWriter(Path(tmp))
            result = "x" * TOOL_RESULT_OFFLOAD_THRESHOLD
            tw.write_tool_result(
                call_id="call-bnd",
                result=result,
                tool_name="test_tool",
                status="ok",
                elapsed_ms=10,
                iteration=2,
            )
            tw.close()

            entries = TraceWriter.read(Path(tmp))
            assert len(entries) == 1
            e = entries[0]
            assert e["result"] == result
            assert "result_path" not in e

    def test_multiple_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tw = TraceWriter(Path(tmp))
            for i in range(5):
                tw.write_tool_result(
                    call_id=f"call-{i}",
                    result=f"result-{i}",
                    tool_name="tool",
                    status="ok",
                    elapsed_ms=i,
                    iteration=i,
                )
            tw.close()

            entries = TraceWriter.read(Path(tmp))
            assert len(entries) == 5
            assert all(e["result"] for e in entries)


class TestTraceWriterOffload:
    """Tool results > threshold are offloaded to disk."""

    def test_offload_large_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tw = TraceWriter(Path(tmp))
            result = "y" * (TOOL_RESULT_OFFLOAD_THRESHOLD + 1)
            tw.write_tool_result(
                call_id="call-off",
                result=result,
                tool_name="big_tool",
                status="ok",
                elapsed_ms=999,
                iteration=3,
            )
            tw.close()

            # Check JSONL entry
            path = Path(tmp) / "trace.jsonl"
            raw = path.read_text(encoding="utf-8")
            lines = [l for l in raw.splitlines() if l.strip()]
            assert len(lines) == 1
            entry = json.loads(lines[0])
            assert entry["type"] == "tool_result"
            assert entry["tool"] == "big_tool"
            assert "result" not in entry  # Offloaded, not inline
            assert entry["result_path"] == "tool-results/call-off.txt"
            assert entry["result_preview"] == result[:OFFLOAD_PREVIEW_CHARS]
            assert entry["result_size"] == len(result)

            # Check offloaded file exists and is complete
            offload_file = Path(tmp) / "tool-results" / "call-off.txt"
            assert offload_file.exists()
            assert offload_file.read_text(encoding="utf-8") == result

    def test_read_resolves_offloaded_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tw = TraceWriter(Path(tmp))
            big_result = "BIG_DATA_" * 10000  # ~90K chars — above threshold
            tw.write_tool_result(
                call_id="call-resolve",
                result=big_result,
                tool_name="read_tool",
                status="ok",
                elapsed_ms=50,
                iteration=1,
            )
            tw.close()

            # TraceWriter.read should resolve the offloaded result
            entries = TraceWriter.read(Path(tmp))
            assert len(entries) == 1
            e = entries[0]
            assert e["result"] == big_result
            # Metadata still present
            assert e["result_path"] == "tool-results/call-resolve.txt"
            assert e["result_preview"] == big_result[:OFFLOAD_PREVIEW_CHARS]
            assert e["result_size"] == len(big_result)

    def test_mixed_inline_and_offload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tw = TraceWriter(Path(tmp))
            small = "small"
            big = "B" * (TOOL_RESULT_OFFLOAD_THRESHOLD + 100)
            tw.write_tool_result(
                call_id="small-1", result=small, tool_name="t",
                status="ok", elapsed_ms=1, iteration=1,
            )
            tw.write_tool_result(
                call_id="big-1", result=big, tool_name="t",
                status="ok", elapsed_ms=2, iteration=2,
            )
            tw.write_tool_result(
                call_id="small-2", result=small, tool_name="t",
                status="ok", elapsed_ms=3, iteration=3,
            )
            tw.close()

            entries = TraceWriter.read(Path(tmp))
            assert len(entries) == 3
            # Small results inline
            assert entries[0]["result"] == small
            assert "result_path" not in entries[0]
            # Big result offloaded but resolved
            assert entries[1]["result"] == big
            assert entries[1]["result_path"] == "tool-results/big-1.txt"
            # Second small also inline
            assert entries[2]["result"] == small
            assert "result_path" not in entries[2]

            # Offload file exists
            assert (Path(tmp) / "tool-results" / "big-1.txt").exists()

    def test_offload_file_content_complete(self) -> None:
        """Offloaded result must be byte-exact, not truncated."""
        with tempfile.TemporaryDirectory() as tmp:
            tw = TraceWriter(Path(tmp))
            # Use varied content to catch encoding issues
            result = "🎯 TRADE " * 6000 + "中文测试" * 2500 + "!\n" * 1000
            # Ensure it's above threshold
            assert len(result) > TOOL_RESULT_OFFLOAD_THRESHOLD
            tw.write_tool_result(
                call_id="unicode-test",
                result=result,
                tool_name="t",
                status="ok",
                elapsed_ms=10,
                iteration=1,
            )
            tw.close()

            offload_file = Path(tmp) / "tool-results" / "unicode-test.txt"
            assert offload_file.read_text(encoding="utf-8") == result

            entries = TraceWriter.read(Path(tmp))
            assert entries[0]["result"] == result


class TestTraceWriterRead:
    """Edge cases for read()."""

    def test_read_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entries = TraceWriter.read(Path(tmp))
            assert entries == []

    def test_read_missing_file(self) -> None:
        entries = TraceWriter.read(Path("/nonexistent/path"))
        assert entries == []

    def test_read_malformed_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            path.write_text(
                '{"type": "ok", "ts": 1}\n'
                'not json at all\n'
                '{"type": "also-ok", "ts": 2}\n',
                encoding="utf-8",
            )
            entries = TraceWriter.read(Path(tmp))
            assert len(entries) == 2
            assert entries[0]["type"] == "ok"
            assert entries[1]["type"] == "also-ok"

    def test_read_offloaded_missing_file(self) -> None:
        """When offload file is missing, result is not resolved but entry is kept."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            path.write_text(
                json.dumps({
                    "type": "tool_result",
                    "tool": "ghost",
                    "result_path": "tool-results/missing.txt",
                    "result_preview": "ghost...",
                    "result_size": 99999,
                }) + "\n",
                encoding="utf-8",
            )
            entries = TraceWriter.read(Path(tmp))
            assert len(entries) == 1
            e = entries[0]
            assert "result" not in e  # Could not be resolved
            assert e["result_path"] == "tool-results/missing.txt"


class TestTraceWriterFindTraceDir:
    """find_trace_dir resolves the correct directory for a run_id."""

    def test_finds_sessions_first(self, tmp_path: Path) -> None:
        sessions = tmp_path / "sessions"
        runs = tmp_path / "runs"
        # Create trace in sessions/
        session_dir = sessions / "test-run"
        session_dir.mkdir(parents=True)
        (session_dir / "trace.jsonl").write_text('{"type": "start"}')

        found = TraceWriter.find_trace_dir("test-run", runs_dir=runs, sessions_dir=sessions)
        assert found == session_dir

    def test_falls_back_to_runs(self, tmp_path: Path) -> None:
        sessions = tmp_path / "sessions"
        runs = tmp_path / "runs"
        # Create trace in runs/ only
        run_dir = runs / "test-run"
        run_dir.mkdir(parents=True)
        (run_dir / "trace.jsonl").write_text('{"type": "start"}')

        found = TraceWriter.find_trace_dir("test-run", runs_dir=runs, sessions_dir=sessions)
        assert found == run_dir

    def test_sessions_takes_priority(self, tmp_path: Path) -> None:
        """When trace exists in both sessions/ and runs/, sessions/ wins."""
        sessions = tmp_path / "sessions"
        runs = tmp_path / "runs"
        session_dir = sessions / "dual-run"
        run_dir = runs / "dual-run"
        session_dir.mkdir(parents=True)
        run_dir.mkdir(parents=True)
        (session_dir / "trace.jsonl").write_text('{"type": "session"}')
        (run_dir / "trace.jsonl").write_text('{"type": "run"}')

        found = TraceWriter.find_trace_dir("dual-run", runs_dir=runs, sessions_dir=sessions)
        assert found == session_dir

    def test_returns_none_when_missing(self, tmp_path: Path) -> None:
        sessions = tmp_path / "sessions"
        runs = tmp_path / "runs"
        sessions.mkdir(parents=True)
        runs.mkdir(parents=True)

        found = TraceWriter.find_trace_dir("nowhere", runs_dir=runs, sessions_dir=sessions)
        # Falls back to runs/ dir path even if trace.jsonl doesn't exist
        assert found == runs / "nowhere"


class TestTraceWriterSessionDir:
    """Session-based trace directory creation."""

    def test_creates_dir_if_missing(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "sessions" / "new-session"
        assert not session_dir.exists()

        tw = TraceWriter(session_dir)
        tw.write({"type": "start"})
        tw.close()

        assert session_dir.exists()
        assert (session_dir / "trace.jsonl").exists()

    def test_offload_creates_tool_results_dir(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "sessions" / "offload-test"
        tw = TraceWriter(session_dir)
        big = "X" * (TOOL_RESULT_OFFLOAD_THRESHOLD + 10)
        tw.write_tool_result(
            call_id="big-call",
            result=big,
            tool_name="t",
            status="ok",
            elapsed_ms=1,
            iteration=1,
        )
        tw.close()

        offload_dir = session_dir / "tool-results"
        assert offload_dir.exists()
        assert (offload_dir / "big-call.txt").exists()
