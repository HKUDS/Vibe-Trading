from src.quantlib.crossvalidation import (
    purged_walk_forward_splits,
    detect_boundary_leakage,
)


def test_walkforward_skips_fold_whose_training_labels_all_overlap():
    ends = [3, 3, 3, 3, 7, 7, 7, 7]
    splits = list(purged_walk_forward_splits(8, ends, n_folds=4))
    assert [split.test.tolist() for split in splits] == [[4, 5], [6, 7]]
    assert all(split.train.size for split in splits)
    assert all(detect_boundary_leakage(split, ends).clean for split in splits)


def test_walkforward_can_have_no_usable_folds():
    assert list(purged_walk_forward_splits(8, [7] * 8, n_folds=4)) == []
