"""Pin tool-result ownership after removal of loop compatibility exports."""

import pytest

import src.agent.runtime as loop
import src.product.tool_results as tool_results
from src.tools import _arguments

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
    "_previously_archived",
    "_archive_backtest_result",
]


@pytest.mark.parametrize("name", MOVED_CONSTANTS + MOVED_FUNCTIONS)
def test_moved_name_is_owned_without_a_loop_compatibility_export(name):
    assert getattr(tool_results, name) is not None
    assert name not in vars(loop)


def test_moved_surface_is_complete():
    assert callable(_arguments.normalize_tool_run_dir)
    assert "_normalize_tool_run_dir" not in vars(tool_results)
    public_helpers = [
        n
        for n in dir(tool_results)
        if not n.startswith("__") and getattr(tool_results, n) is not None
    ]
    # The new module must not silently grow an unmoved consumer surface.
    assert set(MOVED_CONSTANTS + MOVED_FUNCTIONS) <= set(public_helpers)
