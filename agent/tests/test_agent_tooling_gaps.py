"""Tests for the three harness-gap fixes.

1. Token budget derivation from MODEL_CONTEXT_WINDOW (loop._token_threshold).
2. check_code static preflight tool.
3. parallel_lookup concurrent lookup tool.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from src.config.accessor import reset_env_config


# ---------------------------------------------------------------------------
# Token budget derivation (gap 2)
# ---------------------------------------------------------------------------


@pytest.fixture()
def _clean_budget_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TOKEN_THRESHOLD", raising=False)
    monkeypatch.delenv("MODEL_CONTEXT_WINDOW", raising=False)
    reset_env_config()
    yield
    reset_env_config()


class TestDerivedTokenBudget:
    def test_uses_60_percent_of_window(self):
        from src.agent.loop import _derived_token_budget

        assert _derived_token_budget(200_000) == 120_000

    def test_clamped_to_ceiling(self):
        from src.agent.loop import _derived_token_budget

        assert _derived_token_budget(1_000_000) == 400_000

    def test_clamped_to_floor(self):
        from src.agent.loop import _derived_token_budget

        assert _derived_token_budget(50_000) == 40_000

    def test_default_unchanged_without_any_env(self, _clean_budget_env):
        from src.agent.loop import _token_threshold

        assert _token_threshold() == 40_000

    def test_window_derived_when_only_window_set(self, _clean_budget_env, monkeypatch):
        monkeypatch.setenv("MODEL_CONTEXT_WINDOW", "200000")
        reset_env_config()

        from src.agent.loop import _token_threshold

        assert _token_threshold() == 120_000

    def test_explicit_token_threshold_wins_over_window(self, _clean_budget_env, monkeypatch):
        monkeypatch.setenv("TOKEN_THRESHOLD", "30000")
        monkeypatch.setenv("MODEL_CONTEXT_WINDOW", "200000")
        reset_env_config()

        from src.agent.loop import _token_threshold

        assert _token_threshold() == 30_000

    def test_explicit_threshold_equal_to_default_still_wins(self, _clean_budget_env, monkeypatch):
        monkeypatch.setenv("TOKEN_THRESHOLD", "40000")
        monkeypatch.setenv("MODEL_CONTEXT_WINDOW", "200000")
        reset_env_config()

        from src.agent.loop import _token_threshold

        assert _token_threshold() == 40_000


# ---------------------------------------------------------------------------
# check_code preflight (gap 1)
# ---------------------------------------------------------------------------


@pytest.fixture()
def _run_root(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    reset_env_config()
    yield tmp_path
    reset_env_config()


def _check(**kwargs):
    from src.tools.check_code_tool import CheckCodeTool

    return json.loads(CheckCodeTool().execute(**kwargs))


class TestCheckCode:
    def test_syntax_error_reports_line(self, _run_root):
        target = _run_root / "signal_engine.py"
        target.write_text("def broken(:\n    pass\n", encoding="utf-8")

        result = _check(path="signal_engine.py", run_dir=str(_run_root))

        assert result["status"] == "error"
        assert result["checks"]["syntax"] == "error"
        assert result["errors"][0]["line"] == 1

    def test_valid_file_is_ok(self, _run_root):
        target = _run_root / "helper.py"
        target.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

        result = _check(path="helper.py", run_dir=str(_run_root))

        assert result["status"] == "ok"
        assert result["checks"]["syntax"] == "ok"

    def test_inline_code(self):
        result = _check(code="x = 1\n")

        assert result["status"] == "ok"
        assert result["path"] == "<inline>"

    def test_path_and_code_are_mutually_exclusive(self):
        result = _check(path="a.py", code="x = 1\n")

        assert result["status"] == "error"
        assert "exactly one" in result["error"]

    def test_missing_file(self, _run_root):
        result = _check(path="nope.py", run_dir=str(_run_root))

        assert result["status"] == "error"
        assert "not found" in result["error"].lower()

    def test_signal_engine_contract_missing(self, _run_root):
        target = _run_root / "signal_engine.py"
        target.write_text("class NotTheContract:\n    pass\n", encoding="utf-8")

        result = _check(path="signal_engine.py", run_dir=str(_run_root))

        assert result["status"] == "error"
        assert result["checks"]["contract"] == "error"
        assert "SignalEngine" in result["errors"][0]["message"]

    def test_signal_engine_contract_present(self, _run_root):
        target = _run_root / "signal_engine.py"
        target.write_text(
            "class SignalEngine:\n    def generate_signals(self, df):\n        return df\n",
            encoding="utf-8",
        )

        result = _check(path="signal_engine.py", run_dir=str(_run_root))

        assert result["status"] == "ok"
        assert result["checks"]["contract"] == "ok"


# ---------------------------------------------------------------------------
# parallel_lookup (gap 3)
# ---------------------------------------------------------------------------


class _FakeChat:
    def __init__(self, behavior):
        self._behavior = behavior

    def chat(self, messages, tools=None, timeout=None):
        query = messages[0]["content"].split("Query: ", 1)[1]
        outcome = self._behavior(query)
        time.sleep(outcome.get("delay", 0))
        if outcome.get("raise"):
            raise outcome["raise"]
        return SimpleNamespace(content=outcome.get("content", f"ans for {query}"))


@pytest.fixture()
def _patched_chat(monkeypatch: pytest.MonkeyPatch):
    def _install(behavior):
        import src.tools.parallel_lookup_tool as mod

        monkeypatch.setattr(mod, "_build_chat_llm", lambda: _FakeChat(behavior))

    return _install


def _lookup(**kwargs):
    from src.tools.parallel_lookup_tool import ParallelLookupTool

    return json.loads(ParallelLookupTool().execute(**kwargs))


class TestParallelLookup:
    def test_three_queries_ok_and_ordered(self, _patched_chat):
        _patched_chat(lambda q: {"content": f"answer:{q}"})

        result = _lookup(queries=["alpha", "beta", "gamma"])

        assert result["status"] == "ok"
        assert result["ok"] == 3
        assert [r["content"] for r in result["results"]] == [
            "answer:alpha",
            "answer:beta",
            "answer:gamma",
        ]

    def test_single_failure_is_isolated(self, _patched_chat):
        _patched_chat(
            lambda q: {"raise": RuntimeError("provider down")} if q == "boom" else {}
        )

        result = _lookup(queries=["boom", "fine"])

        assert result["status"] == "ok"
        assert result["ok"] == 1
        assert result["failed"] == 1
        assert result["results"][0]["status"] == "error"
        assert "provider down" in result["results"][0]["error"]
        assert result["results"][1]["status"] == "ok"

    def test_requires_two_queries(self, _patched_chat):
        _patched_chat(lambda q: {})

        result = _lookup(queries=["only-one"])

        assert result["status"] == "error"
        assert "at least 2" in result["error"]

    def test_rejects_more_than_eight(self, _patched_chat):
        _patched_chat(lambda q: {})

        result = _lookup(queries=[f"q{i}" for i in range(9)])

        assert result["status"] == "error"
        assert "At most 8" in result["error"]

    def test_non_list_queries_rejected(self, _patched_chat):
        _patched_chat(lambda q: {})

        result = _lookup(queries="not-a-list")

        assert result["status"] == "error"

    def test_hung_lookup_flagged_as_timeout(self, _patched_chat, monkeypatch):
        import src.tools.parallel_lookup_tool as mod

        monkeypatch.setattr(mod, "_JOIN_GRACE_S", 0.1)
        _patched_chat(lambda q: {"delay": 2.0} if q == "slow" else {})

        result = _lookup(queries=["slow", "fast"], timeout_s=1)

        assert result["status"] == "ok"
        assert result["results"][0]["status"] == "timeout"
        assert result["results"][1]["status"] == "ok"

    def test_oversized_content_truncated(self, _patched_chat):
        _patched_chat(lambda q: {"content": "x" * 10_000})

        result = _lookup(queries=["a", "b"])

        assert result["status"] == "ok"
        assert len(result["results"][0]["content"]) <= 4_100
        assert "TRUNCATED" in result["results"][0]["content"]


# ---------------------------------------------------------------------------
# Registry discovery
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_both_tools_are_discovered(self):
        from src.tools import _discover_subclasses

        names = {cls.name for cls in _discover_subclasses()}
        assert "check_code" in names
        assert "parallel_lookup" in names
