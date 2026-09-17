"""Focused tests for per-run tool progress and no-progress recovery."""

from __future__ import annotations

from src.agent.tool_progress import (
    FAILURE_BLOCK_THRESHOLD,
    NO_PROGRESS_LIMIT,
    ToolProgress,
)


def test_new_readonly_observation_resets_stall_chain() -> None:
    progress = ToolProgress()
    assert progress.finish_iteration() is False
    assert progress.stalled_iterations == 1

    progress.record(
        "read_url",
        ("read_url", '{"url":"https://example.test"}'),
        '{"status":"ok","body":"new"}',
        success=True,
        is_readonly=True,
    )
    assert progress.finish_iteration() is False
    assert progress.stalled_iterations == 0


def test_identical_readonly_observation_is_not_new_progress() -> None:
    progress = ToolProgress()
    key = ("read_url", '{"url":"https://example.test"}')
    result = '{"status":"ok","body":"same"}'

    progress.record("read_url", key, result, success=True, is_readonly=True)
    assert progress.finish_iteration() is False
    assert progress.stalled_iterations == 0

    progress.record("read_url", key, result, success=True, is_readonly=True)
    assert progress.finish_iteration() is False
    assert progress.stalled_iterations == 1


def test_context_restore_grants_one_grace_without_resetting_stall_history() -> None:
    progress = ToolProgress()
    assert progress.finish_iteration() is False
    assert progress.stalled_iterations == 1

    progress.mark_context_restored()
    assert progress.finish_iteration() is False
    assert progress.stalled_iterations == 1

    assert progress.finish_iteration() is False
    assert progress.stalled_iterations == 2


def test_context_restore_does_not_create_external_observation() -> None:
    progress = ToolProgress()
    progress.mark_context_restored()
    assert progress._observations == set()
    assert progress.finish_iteration() is False
    assert progress.stalled_iterations == 0


def test_repeated_context_restore_cannot_make_no_progress_unbounded() -> None:
    progress = ToolProgress()
    # The first restore may hold the counter for one iteration. Every later
    # replay-only iteration must consume the ordinary no-progress budget.
    for iteration in range(NO_PROGRESS_LIMIT + 1):
        progress.mark_context_restored()
        stopped = progress.finish_iteration()
        if stopped:
            break
    assert stopped is True
    assert progress.stalled_iterations == NO_PROGRESS_LIMIT
    assert iteration <= NO_PROGRESS_LIMIT


def test_exact_failure_is_blocked_only_after_threshold() -> None:
    progress = ToolProgress()
    key = ("read_url", '{"url":"https://example.test/missing"}')

    for attempt in range(FAILURE_BLOCK_THRESHOLD):
        assert progress.is_blocked(key) is (attempt >= FAILURE_BLOCK_THRESHOLD)
        progress.record(
            "read_url",
            key,
            '{"status":"error","message":"missing"}',
            success=False,
            is_readonly=True,
        )

    assert progress.is_blocked(key) is True


def test_successful_mutation_clears_failed_call_ledger() -> None:
    progress = ToolProgress()
    key = ("read_url", '{"url":"https://example.test/missing"}')
    for _ in range(FAILURE_BLOCK_THRESHOLD):
        progress.record(
            "read_url",
            key,
            '{"status":"error"}',
            success=False,
            is_readonly=True,
        )
    assert progress.is_blocked(key) is True

    progress.record(
        "write_file",
        ("write_file", '{"path":"note.md"}'),
        '{"status":"ok"}',
        success=True,
        is_readonly=False,
    )
    assert progress.is_blocked(key) is False


def test_no_progress_limit_remains_bounded() -> None:
    progress = ToolProgress()
    for _ in range(NO_PROGRESS_LIMIT - 1):
        assert progress.finish_iteration() is False
    assert progress.finish_iteration() is True
    assert progress.stalled_iterations == NO_PROGRESS_LIMIT
