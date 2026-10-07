"""Pin the re-export contract of the tool-results extraction (issue #1624).

``loop.py`` used to define these helpers inline; they now live in
``src.agent.tool_results`` and are re-exported by ``loop.py`` so every
existing ``from src.agent.loop import ...`` keeps resolving. These tests
fail if the two modules ever drift apart, e.g. someone deletes a re-export
or redefines a helper in ``loop.py`` instead of moving it.
"""

import pytest

import src.agent.loop as loop
import src.agent.tool_results as tool_results

MOVED_CONSTANTS = [
    "_FORCED_TEXT_TOOL_CALL_RE",
    "_DSML_BAR_TOOL_CALL_RE",
    "_TARGET_PATH_RE",
    "_TARGET_ACTION_RE",
]

MOVED_FUNCTIONS = [
    "_failure_code",
    "_is_tool_success",
    "_looks_like_tool_call_syntax",
    "_named_target_paths",
    "_normalize_tool_run_dir",
    "_previously_archived",
    "_archive_backtest_result",
]


@pytest.mark.parametrize("name", MOVED_CONSTANTS + MOVED_FUNCTIONS)
def test_loop_reexports_moved_name(name):
    assert getattr(loop, name) is getattr(tool_results, name)


def test_moved_surface_is_complete():
    public_helpers = [
        n
        for n in dir(tool_results)
        if not n.startswith("__") and getattr(tool_results, n) is not None
    ]
    # The new module must not silently grow an unmoved consumer surface.
    assert set(MOVED_CONSTANTS + MOVED_FUNCTIONS) <= set(public_helpers)
