"""Integration boundaries found while reviewing the October 5 UX batch."""

import numpy as np
import pandas as pd
import pytest
import json

from src.memory.persistent import PersistentMemory
from src.quantlib.crossvalidation import detect_boundary_leakage, group_purged_kfold_splits
from src.shadow_account.extractor import _compute_rsi as extracted_rsi
from src.shadow_account.scanner import _compute_rsi as scanned_rsi
from src.tools.remember_tool import RememberTool


def test_group_split_preserves_legacy_positional_arguments():
    groups = np.repeat(np.arange(10), 2)
    legacy = list(group_purged_kfold_splits(groups, 5, 0.1))
    named = list(group_purged_kfold_splits(groups, n_folds=5, embargo_fraction=0.1))
    for left, right in zip(legacy, named, strict=True):
        np.testing.assert_array_equal(left.train, right.train)
        np.testing.assert_array_equal(left.test, right.test)


def test_group_split_purges_future_groups_inside_the_test_label_horizon():
    groups = np.repeat(np.arange(10), 2)
    ends = np.minimum(np.arange(20) + 5, 19)
    for split in group_purged_kfold_splits(groups, label_end_times=ends, n_folds=5, embargo_fraction=0):
        assert detect_boundary_leakage(split, ends, n_samples=20).clean
        for group in set(groups[split.train]):
            assert np.isin(np.flatnonzero(groups == group), split.train).all()


def test_group_split_accepts_a_label_horizon_past_the_last_sample():
    groups = np.repeat(np.arange(10), 2)
    ends = np.arange(20)
    ends[-1] = 25
    splits = list(group_purged_kfold_splits(groups, label_end_times=ends, n_folds=5, embargo_fraction=0))
    assert all(detect_boundary_leakage(split, ends, n_samples=20).clean for split in splits)


def test_group_embargo_starts_after_the_test_label_horizon():
    groups = np.repeat(np.arange(10), 2)
    ends = np.arange(20)
    ends[2:4] = 7
    first = next(group_purged_kfold_splits(groups, label_end_times=ends, n_folds=5, embargo_fraction=0.1))
    assert not np.isin([8, 9], first.train).any()
    assert first.purged == 4
    assert first.embargoed == 2


@pytest.mark.parametrize("name", ["project_q2_planning", "q2_planning", " Q2 Planning "])
def test_memory_forget_resolves_the_same_trimmed_names_as_find(tmp_path, name):
    memory = PersistentMemory(memory_dir=tmp_path)
    memory.add("Q2 Planning", "planning notes", "project")
    assert memory.find(name) is not None
    assert memory.remove(name)
    assert memory.list_entries() == []


def test_memory_forget_ambiguous_stem_preserves_both_entries(tmp_path):
    memory = PersistentMemory(memory_dir=tmp_path)
    memory.add("Q2 Planning", "project notes", "project")
    memory.add("Q2 Planning", "feedback notes", "feedback")
    with pytest.raises(ValueError, match="memory_type"):
        memory.remove("q2_planning")
    assert len(memory.list_entries()) == 2
    assert memory.remove("q2_planning", memory_type="project")
    assert memory.find("feedback_q2_planning") is not None


def test_remember_tool_forgets_by_filename_stem(tmp_path):
    memory = PersistentMemory(memory_dir=tmp_path)
    memory.add("Q2 Planning", "project notes", "project")
    result = json.loads(RememberTool(memory=memory).execute(action="forget", title="project_q2_planning"))
    assert result["status"] == "ok"
    assert memory.list_entries() == []


def test_shadow_rsi_keeps_positional_warmup_with_duplicate_index_labels():
    closes = pd.Series([100, 101, 99, 102, 98, 104, 103], index=["bar"] * 7, dtype=float)
    expected = extracted_rsi(closes.reset_index(drop=True), period=3)
    for calculate in (extracted_rsi, scanned_rsi):
        actual = calculate(closes, period=3)
        np.testing.assert_allclose(actual.to_numpy(), expected.to_numpy(), equal_nan=True)
        assert actual.iloc[:3].isna().all()


def test_shadow_scanning_and_extraction_share_seeded_rsi_and_gap_policy():
    closes = pd.Series([100, 101, 99, 102, 98, 104, np.nan, 103, 102, 105], dtype=float)
    pd.testing.assert_series_equal(extracted_rsi(closes, period=3), scanned_rsi(closes, period=3))
    assert extracted_rsi(closes, period=3).iloc[6:8].isna().all()
