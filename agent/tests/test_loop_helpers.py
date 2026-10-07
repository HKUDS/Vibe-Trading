"""Tests for AgentLoop pure helper functions (zero LLM dependency)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from src.agent.loop import (
    KEEP_RECENT,
    COLLAPSE_PRESERVE_RECENT,
    COLLAPSE_TEXT_MIN,
    MICROCOMPACT_THRESHOLD,
    estimate_tokens,
    _microcompact,
    _context_collapse,
    _fix_tool_pairs,
    _is_tool_success,
    _normalize_tool_run_dir,
    _archive_backtest_result,
    _llm_timeout_seconds,
    _stall_timeout_seconds,
    _cleared_text,
)


def _apply_microcompact_gate(messages: list, called_ok: set | None = None) -> None:
    """Mirror AgentLoop layer-1 gate (``loop.py`` ~572-573)."""
    if estimate_tokens(messages) > MICROCOMPACT_THRESHOLD:
        unreadable = _microcompact(messages)
        if called_ok is not None:
            called_ok.difference_update(unreadable)


# ---------------------------------------------------------------------------
# estimate_tokens
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_empty(self) -> None:
        assert estimate_tokens([]) == len("[]") // 4

    def test_proportional(self) -> None:
        short = [{"role": "user", "content": "hi"}]
        long = [{"role": "user", "content": "x" * 4000}]
        assert estimate_tokens(long) > estimate_tokens(short)

    def test_rough_accuracy(self) -> None:
        # ~4 chars per token
        msg = [{"role": "user", "content": "a" * 400}]
        tokens = estimate_tokens(msg)
        # Should be roughly 100 tokens for 400 chars of content (plus overhead)
        assert 80 < tokens < 200


# ---------------------------------------------------------------------------
# _microcompact
# ---------------------------------------------------------------------------


class TestMicrocompact:
    def test_clears_old_tool_messages(self) -> None:
        messages = [
            {"role": "system", "content": "system"},
        ]
        # Add KEEP_RECENT + 5 tool messages with long content
        for i in range(KEEP_RECENT + 5):
            messages.append({"role": "tool", "content": f"{'x' * 200} result_{i}", "tool_call_id": f"tc_{i}"})

        _microcompact(messages)

        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        # Old ones should be [cleared]
        cleared = [
            m for m in tool_msgs if m["content"].startswith("[CLEARED FROM CONTEXT:")
        ]
        preserved = [
            m
            for m in tool_msgs
            if not m["content"].startswith("[CLEARED FROM CONTEXT:")
        ]
        assert len(cleared) == 5
        assert len(preserved) == KEEP_RECENT

    def test_preserves_short_content(self) -> None:
        messages = [
            {"role": "tool", "content": "short", "tool_call_id": "tc_0"},
            {"role": "tool", "content": "also short", "tool_call_id": "tc_1"},
            {"role": "tool", "content": "short too", "tool_call_id": "tc_2"},
            {"role": "tool", "content": "x" * 200, "tool_call_id": "tc_3"},
            {"role": "tool", "content": "x" * 200, "tool_call_id": "tc_4"},
            {"role": "tool", "content": "x" * 200, "tool_call_id": "tc_5"},
            {"role": "tool", "content": "x" * 200, "tool_call_id": "tc_6"},
        ]
        _microcompact(messages)
        # First tool msg is old and long enough → cleared
        # But "short" is ≤100 chars → not cleared even if old
        short_msgs = [m for m in messages if m["content"] in ("short", "also short")]
        assert len(short_msgs) == 2

    def test_no_op_when_few_messages(self) -> None:
        messages = [
            {"role": "tool", "content": "x" * 200, "tool_call_id": "tc_0"},
        ]
        _microcompact(messages)
        assert not messages[0]["content"].startswith("[CLEARED FROM CONTEXT:")

    def test_does_not_touch_non_tool(self) -> None:
        messages = [
            {"role": "user", "content": "x" * 500},
            {"role": "assistant", "content": "x" * 500},
            {"role": "tool", "content": "x" * 200, "tool_call_id": "tc_0"},
            {"role": "tool", "content": "x" * 200, "tool_call_id": "tc_1"},
            {"role": "tool", "content": "x" * 200, "tool_call_id": "tc_2"},
            {"role": "tool", "content": "x" * 200, "tool_call_id": "tc_3"},
        ]
        _microcompact(messages)
        assert messages[0]["content"] == "x" * 500
        assert messages[1]["content"] == "x" * 500


class TestMicrocompactThresholdGate:
    """Layer 1 only runs once transcript size crosses MICROCOMPACT_THRESHOLD."""

    def test_no_op_at_or_below_threshold(self) -> None:
        messages = [{"role": "system", "content": "sys"}]
        for i in range(KEEP_RECENT + 5):
            messages.append(
                {"role": "tool", "content": f"{'x' * 200} result_{i}", "tool_call_id": f"tc_{i}"}
            )

        assert estimate_tokens(messages) <= MICROCOMPACT_THRESHOLD

        originals = [m["content"] for m in messages]
        _apply_microcompact_gate(messages)
        assert [m["content"] for m in messages] == originals

    def test_prunes_above_threshold(self) -> None:
        messages = [{"role": "system", "content": "sys"}]
        messages.append({"role": "user", "content": "x" * (MICROCOMPACT_THRESHOLD * 4 + 1000)})
        for i in range(KEEP_RECENT + 5):
            messages.append(
                {"role": "tool", "content": f"{'y' * 200} result_{i}", "tool_call_id": f"tc_{i}"}
            )

        assert estimate_tokens(messages) > MICROCOMPACT_THRESHOLD

        _apply_microcompact_gate(messages)

        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        cleared = [
            m for m in tool_msgs if m["content"].startswith("[CLEARED FROM CONTEXT:")
        ]
        preserved = [
            m
            for m in tool_msgs
            if not m["content"].startswith("[CLEARED FROM CONTEXT:")
        ]
        assert len(cleared) == 5
        assert len(preserved) == KEEP_RECENT


class TestMicrocompactDedupLedger:
    """#1343: a cleared result cannot back "use the previous result", so the
    tools it came from must leave the dedup ledger and become callable again."""

    @staticmethod
    def _tool(name: str, content: str) -> dict:
        return {"role": "tool", "name": name, "content": content, "tool_call_id": f"tc_{name}_{len(content)}"}

    def test_cleared_tool_is_returned_for_unblocking(self) -> None:
        messages = [
            self._tool("get_fund_flow", "x" * 200),
            self._tool("get_stock_news", "y" * 200),
            self._tool("recent_a", "a" * 200),
            self._tool("recent_b", "b" * 200),
            self._tool("recent_c", "c" * 200),
        ]
        assert _microcompact(messages) == ["get_fund_flow", "get_stock_news"]

    def test_tool_with_surviving_result_stays_blocked(self) -> None:
        # Same name has an old cleared result AND a result inside KEEP_RECENT:
        # the model can still read one, so the dedup block must stay.
        messages = [
            self._tool("get_fund_flow", "x" * 200),
            self._tool("other", "y" * 200),
            self._tool("get_fund_flow", "fresh" + "z" * 200),
            self._tool("recent_b", "b" * 200),
            self._tool("recent_c", "c" * 200),
        ]
        assert _microcompact(messages) == ["other"]

    def test_short_old_result_still_counts_as_readable(self) -> None:
        messages = [
            self._tool("get_fund_flow", "x" * 200),
            self._tool("get_fund_flow", "ok"),
            self._tool("recent_a", "a" * 200),
            self._tool("recent_b", "b" * 200),
            self._tool("recent_c", "c" * 200),
        ]
        assert _microcompact(messages) == []

    def test_unnamed_messages_clear_without_unblocking(self) -> None:
        messages = [{"role": "tool", "content": "x" * 200, "tool_call_id": f"tc_{i}"} for i in range(KEEP_RECENT + 2)]
        assert _microcompact(messages) == []

    def test_second_pass_reports_nothing_new(self) -> None:
        messages = [
            self._tool("get_fund_flow", "x" * 200),
            self._tool("recent_a", "a" * 200),
            self._tool("recent_b", "b" * 200),
            self._tool("recent_c", "c" * 200),
        ]
        assert _microcompact(messages) == ["get_fund_flow"]
        assert _microcompact(messages) == []

    def test_gate_updates_dedup_ledger(self) -> None:
        messages = [{"role": "system", "content": "sys"}]
        messages.append({"role": "user", "content": "x" * (MICROCOMPACT_THRESHOLD * 4 + 1000)})
        messages.append(self._tool("get_fund_flow", "y" * 200))
        for name in ("recent_a", "recent_b", "recent_c"):
            messages.append(self._tool(name, "z" * 200))

        called_ok = {"get_fund_flow", "recent_a"}
        _apply_microcompact_gate(messages, called_ok)
        assert called_ok == {"recent_a"}


# ---------------------------------------------------------------------------
# _context_collapse
# ---------------------------------------------------------------------------


class TestContextCollapse:
    def test_collapses_long_content(self) -> None:
        messages = [{"role": "system", "content": "sys"}]
        # Add enough messages to exceed COLLAPSE_PRESERVE_RECENT
        for i in range(COLLAPSE_PRESERVE_RECENT + 5):
            messages.append({"role": "user", "content": f"{'z' * (COLLAPSE_TEXT_MIN + 500)} msg_{i}"})

        _context_collapse(messages)

        # Early messages should be collapsed
        assert "collapsed" in messages[1]["content"]
        # Recent messages should be intact
        assert "collapsed" not in messages[-1]["content"]

    def test_skips_short_content(self) -> None:
        messages = [{"role": "system", "content": "sys"}]
        for i in range(COLLAPSE_PRESERVE_RECENT + 3):
            messages.append({"role": "user", "content": f"short msg {i}"})
        originals = [m["content"] for m in messages]
        _context_collapse(messages)
        # Nothing should change because all content is short
        for orig, msg in zip(originals, messages):
            assert msg["content"] == orig

    def test_skips_cleared_content(self) -> None:
        marker = _cleared_text(5000)
        messages = [{"role": "system", "content": "sys"}]
        for _ in range(COLLAPSE_PRESERVE_RECENT + 3):
            messages.append({"role": "tool", "content": marker})
        _context_collapse(messages)
        # A cleared marker must survive layer 2 untouched.
        for m in messages[1:]:
            assert m["content"] == marker

    def test_no_op_when_too_few_messages(self) -> None:
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "x" * 5000},
        ]
        _context_collapse(messages)
        assert "collapsed" not in messages[1]["content"]

    def test_preserves_head_and_tail(self) -> None:
        messages = [{"role": "system", "content": "sys"}]
        for i in range(COLLAPSE_PRESERVE_RECENT + 3):
            messages.append({"role": "user", "content": f"HEAD_MARKER{'x' * COLLAPSE_TEXT_MIN}TAIL_MARKER msg_{i}"})

        _context_collapse(messages)

        collapsed_msg = messages[1]["content"]
        assert "HEAD_MARKER" in collapsed_msg
        assert "TAIL_MARKER" in collapsed_msg
        assert "collapsed" in collapsed_msg


# ---------------------------------------------------------------------------
# _fix_tool_pairs
# ---------------------------------------------------------------------------


class TestFixToolPairs:
    def test_removes_orphan_result(self) -> None:
        messages = [
            {"role": "assistant", "content": "thinking", "tool_calls": [
                {"id": "tc_1", "function": {"name": "bash"}},
            ]},
            {"role": "tool", "tool_call_id": "tc_1", "name": "bash", "content": "ok"},
            # Orphan: no matching tool_call
            {"role": "tool", "tool_call_id": "tc_orphan", "name": "ghost", "content": "orphan"},
        ]
        _fix_tool_pairs(messages)
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "tc_1"

    def test_inserts_stub_for_orphan_call(self) -> None:
        messages = [
            {"role": "assistant", "content": "thinking", "tool_calls": [
                {"id": "tc_1", "function": {"name": "bash"}},
                {"id": "tc_2", "function": {"name": "read_file"}},
            ]},
            # Only result for tc_1, tc_2 is missing
            {"role": "tool", "tool_call_id": "tc_1", "name": "bash", "content": "ok"},
        ]
        _fix_tool_pairs(messages)
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 2
        stub = [m for m in tool_msgs if m["tool_call_id"] == "tc_2"]
        assert len(stub) == 1
        assert "earlier context" in stub[0]["content"]

    def test_no_op_when_balanced(self) -> None:
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "tc_1", "function": {"name": "bash"}},
            ]},
            {"role": "tool", "tool_call_id": "tc_1", "name": "bash", "content": "ok"},
        ]
        before = len(messages)
        _fix_tool_pairs(messages)
        assert len(messages) == before

    def test_handles_empty_messages(self) -> None:
        messages = []
        _fix_tool_pairs(messages)
        assert messages == []

    def test_multiple_orphans(self) -> None:
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "tc_1", "function": {"name": "a"}},
                {"id": "tc_2", "function": {"name": "b"}},
                {"id": "tc_3", "function": {"name": "c"}},
            ]},
            # No results at all
        ]
        _fix_tool_pairs(messages)
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 3


# ---------------------------------------------------------------------------
# _is_tool_success
# ---------------------------------------------------------------------------


class TestIsToolSuccess:
    def test_success_plain_text(self) -> None:
        assert _is_tool_success("some output text") is True

    def test_success_json_ok(self) -> None:
        assert _is_tool_success('{"status": "ok", "data": 42}') is True

    def test_failure_json_error(self) -> None:
        assert _is_tool_success('{"status": "error", "error": "boom"}') is False

    def test_success_non_dict_json(self) -> None:
        assert _is_tool_success("[1, 2, 3]") is True

    def test_success_empty_string(self) -> None:
        assert _is_tool_success("") is True

    def test_success_invalid_json(self) -> None:
        assert _is_tool_success("{not json}") is True


# ---------------------------------------------------------------------------
# _normalize_tool_run_dir
# ---------------------------------------------------------------------------


class TestNormalizeToolRunDir:
    def test_injects_memory_run_dir_when_missing(self) -> None:
        args = {"path": "config.json"}
        out = _normalize_tool_run_dir(args, "/tmp/run_123")
        assert out["run_dir"] == "/tmp/run_123"

    def test_resolves_relative_dot_to_memory_run_dir(self) -> None:
        args = {"run_dir": "."}
        out = _normalize_tool_run_dir(args, "/tmp/run_123")
        assert out["run_dir"] == str(Path("/tmp/run_123").resolve())

    def test_resolves_relative_child_to_memory_run_dir(self) -> None:
        args = {"run_dir": "risk_parity_run"}
        out = _normalize_tool_run_dir(args, "/tmp/run_123")
        assert out["run_dir"] == str((Path("/tmp/run_123") / "risk_parity_run").resolve())

    def test_preserves_absolute_run_dir(self) -> None:
        # ``os.path.abspath`` produces a platform-correct absolute path: on
        # POSIX it stays ``/var/tmp/custom_run``; on Windows it becomes
        # ``C:\var\tmp\custom_run``. ``Path.is_absolute()`` only treats the
        # latter as absolute on Windows, so the bare Unix-style literal would
        # otherwise be classified as relative and resolved against
        # ``memory_run_dir`` — defeating the point of the test.
        absolute_run_dir = os.path.abspath("/var/tmp/custom_run")
        args = {"run_dir": absolute_run_dir}
        out = _normalize_tool_run_dir(args, "/tmp/run_123")
        assert out["run_dir"] == absolute_run_dir


class TestArchiveBacktestResult:
    def test_copies_detached_backtest_into_active_run(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
        source = tmp_path / "detached"
        active = tmp_path / "active"
        (source / "artifacts").mkdir(parents=True)
        (source / "code").mkdir()
        (source / "artifacts" / "metrics.csv").write_text(
            "total_return,sharpe\n0.12,1.1\n", encoding="utf-8"
        )
        (source / "artifacts" / "equity.csv").write_text(
            "timestamp,equity\n2026-01-01,1\n", encoding="utf-8"
        )
        (source / "code" / "signal_engine.py").write_text("pass\n", encoding="utf-8")
        (source / "config.json").write_text("{}\n", encoding="utf-8")

        archived = _archive_backtest_result(
            json.dumps({"status": "ok", "run_dir": str(source)}), str(active)
        )

        assert archived is True
        assert (active / "artifacts" / "metrics.csv").is_file()
        assert (active / "artifacts" / "equity.csv").is_file()
        assert (active / "code" / "signal_engine.py").is_file()
        assert (active / "config.json").is_file()

    def test_two_backtests_in_one_turn_do_not_mix_artifacts(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The active run must describe ONE backtest, not the union of two (#1094).

        The archive used to be a plain merge, so a file only the first backtest
        produced survived next to the second one's output, and ``/runs/{id}``
        listed it as an artifact of the current run.
        """
        monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
        active = tmp_path / "active"
        (active / "code").mkdir(parents=True)
        # Written by the agent into the ACTIVE run before backtest is called;
        # it is the reason a blanket wipe of the target is not the fix.
        (active / "code" / "signal_engine.py").write_text("own\n", encoding="utf-8")

        def _backtest(name: str, extra: str | None) -> Path:
            source = tmp_path / name
            (source / "artifacts").mkdir(parents=True)
            (source / "artifacts" / "metrics.csv").write_text(
                f"total_return\n{name}\n", encoding="utf-8"
            )
            if extra:
                (source / "artifacts" / extra).write_text("stale\n", encoding="utf-8")
            return source

        first = _backtest("run-a", "extra.csv")
        assert _archive_backtest_result(
            json.dumps({"status": "ok", "run_dir": str(first)}), str(active)
        )
        assert (active / "artifacts" / "extra.csv").is_file()

        second = _backtest("run-b", None)
        assert _archive_backtest_result(
            json.dumps({"status": "ok", "run_dir": str(second)}), str(active)
        )

        # run-a's file is gone; run-b's output is what the run reports.
        assert not (active / "artifacts" / "extra.csv").exists()
        assert (active / "artifacts" / "metrics.csv").read_text(
            encoding="utf-8"
        ) == "total_return\nrun-b\n"
        # The active run's own code survives — only prior ARCHIVE output is dropped.
        assert (active / "code" / "signal_engine.py").read_text(encoding="utf-8") == "own\n"
        # Provenance records which backtest the artifacts describe.
        manifest = json.loads(
            (active / ".archived_backtest.json").read_text(encoding="utf-8")
        )
        assert manifest["source_run"] == "run-b"
        assert "artifacts/metrics.csv" in manifest["files"]

    def test_manifest_cannot_delete_outside_the_active_run(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A manifest is read back off disk, so its names must stay contained.

        Without the containment check the delete step is an arbitrary-file-unlink
        primitive driven by a file inside a run directory.
        """
        monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
        victim = tmp_path / "victim.txt"
        victim.write_text("keep me\n", encoding="utf-8")
        active = tmp_path / "active"
        active.mkdir()
        (active / ".archived_backtest.json").write_text(
            json.dumps({"source_run": "spoofed", "files": ["../victim.txt"]}),
            encoding="utf-8",
        )
        source = tmp_path / "detached"
        (source / "artifacts").mkdir(parents=True)
        (source / "artifacts" / "metrics.csv").write_text(
            "total_return\n0.1\n", encoding="utf-8"
        )

        assert _archive_backtest_result(
            json.dumps({"status": "ok", "run_dir": str(source)}), str(active)
        )

        assert victim.read_text(encoding="utf-8") == "keep me\n"

    def test_ignores_result_without_metrics(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
        source = tmp_path / "not-a-backtest"
        source.mkdir()

        archived = _archive_backtest_result(
            json.dumps({"status": "ok", "run_dir": str(source)}), str(tmp_path / "active")
        )

        assert archived is False

    def test_refuses_a_source_outside_the_allowed_run_roots(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The copy loop validates the path itself, not just upstream.

        ``run_dir`` is read back out of a tool result here, so the check that
        makes it safe must live in this function rather than in the tool that
        produced the string.
        """
        allowed = tmp_path / "allowed"
        outside = tmp_path / "outside"
        (outside / "artifacts").mkdir(parents=True)
        (outside / "artifacts" / "metrics.csv").write_text(
            "total_return\n0.5\n", encoding="utf-8"
        )
        active = allowed / "active"
        active.mkdir(parents=True)
        monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(allowed))

        archived = _archive_backtest_result(
            json.dumps({"status": "ok", "run_dir": str(outside)}), str(active)
        )

        assert archived is False
        assert not (active / "artifacts").exists()


def test_llm_timeout_seconds_default_and_override(monkeypatch) -> None:
    """The LLM call timeout reads config and honors a module-level override."""
    import src.agent.loop as loop_module

    assert _llm_timeout_seconds() > 0
    monkeypatch.setattr(loop_module, "LLM_TIMEOUT_SECONDS", 42.0, raising=False)
    assert _llm_timeout_seconds() == 42.0
    monkeypatch.delattr(loop_module, "LLM_TIMEOUT_SECONDS", raising=False)
    assert _llm_timeout_seconds() > 0

def test_pending_write_directive_tracks_written_targets(tmp_path: Path) -> None:
    """A named target file that was not written yields a write directive.

    Regression for runs that ended "success" without delivering a file
    (2026-08-15 mutual-fund update): the loop must remind the model to write
    the task target before the forced-text final iteration. The directive
    clears once the file is written directly (write_file/edit_file) or by
    any process with a newer mtime (the bash workaround), and only fires for
    messages with create/update intent.
    """
    import os
    import time

    import src.agent.loop as loop_module
    from src.agent.loop import AgentLoop
    from src.agent.tools import ToolRegistry

    agent = AgentLoop(registry=ToolRegistry(), llm=None)
    now = time.time()
    target = str(tmp_path / "plan.md")
    msg = f"please update {target}"

    assert loop_module._TARGET_ACTION_RE.search(msg)
    assert not loop_module._TARGET_ACTION_RE.search("what is the weather?")

    unwritten = agent._pending_write_directive(msg, now)
    assert "NOT been written" in unwritten and "plan.md" in unwritten

    agent._record_written_target({"path": target})
    assert agent._pending_write_directive(msg, now) == ""

    # A bash-style write (mtime newer than run start) also counts.
    agent2 = AgentLoop(registry=ToolRegistry(), llm=None)
    p = tmp_path / "bash_plan.md"
    p.write_text("x", encoding="utf-8")
    os.utime(p, (now, now))
    assert agent2._pending_write_directive(
        f"please update {p}", now - 10,
    ) == ""
    # An old file not written this run still fires.
    old = tmp_path / "old_plan.md"
    old.write_text("x", encoding="utf-8")
    os.utime(old, (now - 100, now - 100))
    assert "old_plan.md" in agent2._pending_write_directive(
        f"please update {old}", now - 10,
    )


# ---------------------------------------------------------------------------
# _verification_ledger
# ---------------------------------------------------------------------------


def test_verification_ledger_extracts_calc_results() -> None:
    """A successful financial_rigor calc result becomes a terse ledger line."""
    messages = [
        {"role": "tool", "name": "financial_rigor", "content": json.dumps({
            "status": "ok", "command": "calc",
            "expr": "92.13/101.65-1", "result": -0.0937, "result_exact": "-0.09365912",
        })},
        {"role": "tool", "name": "financial_rigor", "content": json.dumps({
            "status": "ok", "command": "calc",
            "expr": "85.4/108.8-1", "result": -0.2151, "result_exact": "-0.21507353",
        })},
    ]
    from src.agent.loop import _verification_ledger
    ledger = _verification_ledger(messages)
    assert "calc 92.13/101.65-1 = -0.09365912" in ledger
    assert "calc 85.4/108.8-1 = -0.21507353" in ledger


def test_verification_ledger_skips_errors_and_other_tools() -> None:
    """Failed results, non-financial_rigor tools, and non-JSON are skipped."""
    messages = [
        {"role": "tool", "name": "financial_rigor", "content": json.dumps({
            "status": "error", "command": "calc", "error": "malformed",
        })},
        {"role": "tool", "name": "get_market_data", "content": json.dumps({"status": "ok"})},
        {"role": "tool", "name": "financial_rigor", "content": "not json at all"},
        {"role": "user", "content": "hello"},
    ]
    from src.agent.loop import _verification_ledger
    assert _verification_ledger(messages) == ""


def test_verification_ledger_deduplicates_and_caps() -> None:
    """Duplicate ledger lines collapse; the ledger is capped."""
    messages = [
        {"role": "tool", "name": "financial_rigor", "content": json.dumps({
            "status": "ok", "command": "calc",
            "expr": "a/b", "result": 1.0, "result_exact": "1.0",
        })},
        {"role": "tool", "name": "financial_rigor", "content": json.dumps({
            "status": "ok", "command": "calc",
            "expr": "a/b", "result": 1.0, "result_exact": "1.0",
        })},
    ]
    from src.agent.loop import _verification_ledger
    ledger = _verification_ledger(messages)
    assert ledger.count("calc a/b") == 1


def test_stall_timeout_seconds_default_and_override(monkeypatch) -> None:
    """The stall watchdog timeout reads config and honors a module override."""
    import src.agent.loop as loop_module

    assert _stall_timeout_seconds() > 0
    monkeypatch.setattr(loop_module, "STALL_TIMEOUT_SECONDS", 42.0, raising=False)
    assert _stall_timeout_seconds() == 42.0
    monkeypatch.delattr(loop_module, "STALL_TIMEOUT_SECONDS", raising=False)
    assert _stall_timeout_seconds() > 0


# ---------------------------------------------------------------------------
# tool_calls[].function.arguments must count toward compaction sizing/relief
# ---------------------------------------------------------------------------

def test_tail_cut_index_counts_tool_call_arguments() -> None:
    """#tail-budget: a fat tool_call (empty content, huge arguments) must be
    pushed into the folded head, not counted as ~10 tokens in the tail."""
    from src.agent.loop import _tail_cut_index  # new helper: absent on pre-fix code

    fat = "X" * 90_000  # ~22.5K tokens once arguments are counted
    body = [
        {"role": "user", "content": "old header"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "t", "arguments": fat}}
            ],
        },
    ]
    # Old content-only sizing: both messages fit the 20K budget -> cut at 0.
    # New sizing: the call alone exceeds it -> cut at len(body), tail empty,
    # the oversized call goes into the folded head.
    assert _tail_cut_index(body) == len(body)
    assert _tail_cut_index(body) != 0


def test_tail_cut_index_counts_reasoning_content() -> None:
    """#tail-budget: a thinking-model turn's huge reasoning_content must be
    pushed into the folded head too, not counted as ~10 tokens in the tail."""
    from src.agent.loop import _tail_cut_index

    fat = "X" * 90_000  # ~22.5K tokens once reasoning_content is counted
    body = [
        {"role": "user", "content": "old header"},
        {"role": "assistant", "content": "final answer", "reasoning_content": fat},
    ]
    # Old sizing (content only): both messages fit the 20K budget -> cut at 0.
    # New sizing: the reasoning turn alone exceeds it -> cut at len(body), tail
    # empty, the oversized turn goes into the folded head.
    assert _tail_cut_index(body) == len(body)
    assert _tail_cut_index(body) != 0


def test_context_collapse_stubs_args_of_cleared_paired_call() -> None:
    """#layer-2: a tool_call whose paired result was [cleared] gets its huge
    arguments folded to a valid JSON '{}' stub (call id/name preserved)."""
    fat = "Y" * (COLLAPSE_TEXT_MIN * 3)
    call_msg = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "c9", "type": "function", "function": {"name": "f", "arguments": fat}}],
    }
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u0"},
        call_msg,  # index 2 — inside the collapse window
        # The real layer-1 marker, not the old "[cleared]" literal: it embeds
        # the payload length, so _result_data_gone matches it by prefix.
        {"role": "tool", "tool_call_id": "c9", "content": _cleared_text(9000)},
        {"role": "assistant", "content": "a0"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
    ]
    _context_collapse(msgs)
    assert call_msg["tool_calls"][0]["function"]["arguments"] == "{}"
    assert call_msg["tool_calls"][0]["function"]["name"] == "f"


def test_context_collapse_keeps_args_when_result_intact_or_pending() -> None:
    """#layer-2 negative arm: arguments are NOT stubbed when the result still
    carries data, nor when the call is pending (no result in the transcript)."""
    fat = "Y" * (COLLAPSE_TEXT_MIN * 3)
    c1 = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "f", "arguments": fat}}],
    }
    c2 = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "c2", "type": "function", "function": {"name": "g", "arguments": fat}}],
    }
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u0"},
        c1,  # index 2 — inside the collapse window
        {"role": "tool", "tool_call_id": "c1", "content": "still have the data"},
        c2,  # pending — result never arrived
        {"role": "assistant", "content": "continue"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
    ]
    _context_collapse(msgs)
    assert c1["tool_calls"][0]["function"]["arguments"] == fat
    assert c2["tool_calls"][0]["function"]["arguments"] == fat


def test_context_collapse_stubs_args_for_fix_tool_pairs_stub_result() -> None:
    """#adversarial: layer-3's ``_fix_tool_pairs`` stub result marker must also
    count as 'result data gone' — a call that survived a layer-3 fold gets its
    huge arguments stubbed too, not only microcompact's ``[cleared]``."""
    from src.agent.loop import _STUB_RESULT_CONTENT

    fat = "Y" * (COLLAPSE_TEXT_MIN * 3)
    call_msg = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "c7", "type": "function", "function": {"name": "f", "arguments": fat}}],
    }
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u0"},
        call_msg,  # index 2 — inside the collapse window
        {"role": "tool", "tool_call_id": "c7", "content": _STUB_RESULT_CONTENT},
        {"role": "assistant", "content": "a0"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
    ]
    _context_collapse(msgs)
    assert call_msg["tool_calls"][0]["function"]["arguments"] == "{}"


def test_msg_estimate_chars_counts_dict_arguments() -> None:
    """#adversarial: dict (non-string) arguments must count toward sizing,
    consistent with ``estimate_tokens``' full serialization gate."""
    from src.agent.loop import _msg_estimate_chars

    big_dict = {"q": "X" * 4000}
    msg = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "f", "arguments": big_dict}}],
    }
    assert _msg_estimate_chars(msg) >= 4000
    assert _msg_estimate_chars({"role": "user", "content": "hi"}) >= 2


def test_msg_estimate_chars_counts_reasoning_content() -> None:
    """#adversarial: reasoning_content must count toward sizing too, consistent
    with ``estimate_tokens``' full serialization gate."""
    from src.agent.loop import _msg_estimate_chars

    msg = {
        "role": "assistant",
        "content": "final answer",
        "reasoning_content": "X" * 4000,
    }
    assert _msg_estimate_chars(msg) >= 4000
    assert _msg_estimate_chars({"role": "user", "content": "hi"}) < 4000


class TestMicrocompactMarkerIsStable:
    """The cleared-result marker is >100 chars, i.e. longer than the pruning
    threshold itself, so microcompact must not treat it as prunable payload."""

    def _tool_msgs(self, payload_len: int) -> list:
        msgs = [
            {
                "role": "tool",
                "tool_call_id": "c0",
                "name": "get_fund_flow",
                "content": "x" * payload_len,
            }
        ]
        msgs += [
            {"role": "tool", "tool_call_id": f"p{i}", "name": "pad", "content": "y" * 200}
            for i in range(KEEP_RECENT + 1)
        ]
        return msgs

    def test_marker_keeps_the_original_payload_length(self) -> None:
        payload_len = 4321
        messages = self._tool_msgs(payload_len)
        _microcompact(messages)
        first = messages[0]["content"]
        assert str(payload_len) in first, first

        # A second pass must not rewrite the marker with the marker's own
        # length, which would report a fabricated original size to the model.
        _microcompact(messages)
        assert messages[0]["content"] == first
        assert str(payload_len) in messages[0]["content"]

    def test_second_pass_reports_no_new_unreadable_tools(self) -> None:
        messages = self._tool_msgs(4321)
        assert _microcompact(messages) == ["get_fund_flow"]
        assert _microcompact(messages) == [], (
            "a tool already reported unreadable must not be re-reported, or the "
            "ledger is re-opened and traced on every later iteration"
        )
