"""One-time migration of code-relative state into the runtime root (issue #904)."""

from __future__ import annotations

from pathlib import Path

from src.config.migrate import migrate_legacy_state


def _seed(directory: Path, filename: str = "record.json") -> Path:
    directory.mkdir(parents=True)
    marker = directory / filename
    marker.write_text("{}", encoding="utf-8")
    return marker


def test_moves_all_legacy_dirs_into_runtime_root(tmp_path: Path) -> None:
    legacy = tmp_path / "install"
    root = tmp_path / "runtime"
    _seed(legacy / "sessions")
    _seed(legacy / "runs")
    _seed(legacy / ".swarm" / "runs")
    _seed(legacy / "uploads")

    moved = migrate_legacy_state(legacy_root=legacy, runtime_root=root)

    assert (root / "sessions" / "record.json").is_file()
    assert (root / "runs" / "record.json").is_file()
    assert (root / "swarm" / "runs" / "record.json").is_file()
    assert (root / "uploads" / "record.json").is_file()
    assert not (legacy / "sessions").exists()
    assert not (legacy / "runs").exists()
    assert not (legacy / ".swarm" / "runs").exists()
    assert not (legacy / "uploads").exists()
    assert len(moved) == 4


def test_noop_when_legacy_dirs_missing_or_empty(tmp_path: Path) -> None:
    legacy = tmp_path / "install"
    root = tmp_path / "runtime"
    (legacy / "sessions").mkdir(parents=True)  # empty dir: nothing to migrate

    moved = migrate_legacy_state(legacy_root=legacy, runtime_root=root)

    assert moved == []
    assert not root.exists()


def test_merges_non_colliding_children_when_both_locations_have_data(
    tmp_path: Path,
) -> None:
    """Destination data (e.g. autopilot runs) must not block migrating the rest."""
    legacy = tmp_path / "install"
    root = tmp_path / "runtime"
    (legacy / "sessions" / "sess-old").mkdir(parents=True)
    (legacy / "sessions" / "sess-old" / "messages.jsonl").write_text("{}")
    (root / "sessions" / "sess-new").mkdir(parents=True)
    (root / "sessions" / "sess-new" / "messages.jsonl").write_text("{}")

    moved = migrate_legacy_state(legacy_root=legacy, runtime_root=root)

    assert (root / "sessions" / "sess-old" / "messages.jsonl").is_file()
    assert (root / "sessions" / "sess-new" / "messages.jsonl").is_file()
    assert not (legacy / "sessions").exists()
    assert len(moved) == 1


def test_colliding_children_are_left_in_place(tmp_path: Path) -> None:
    """A same-named child on both sides is never overwritten or merged."""
    legacy = tmp_path / "install"
    root = tmp_path / "runtime"
    (legacy / "runs" / "run-a").mkdir(parents=True)
    (legacy / "runs" / "run-a" / "metrics.json").write_text("old")
    (legacy / "runs" / "run-b").mkdir(parents=True)
    (legacy / "runs" / "run-b" / "metrics.json").write_text("{}")
    (root / "runs" / "run-a").mkdir(parents=True)
    (root / "runs" / "run-a" / "metrics.json").write_text("new")

    migrate_legacy_state(legacy_root=legacy, runtime_root=root)

    assert (root / "runs" / "run-a" / "metrics.json").read_text() == "new"
    assert (legacy / "runs" / "run-a" / "metrics.json").read_text() == "old"
    assert (root / "runs" / "run-b" / "metrics.json").is_file()
    assert (legacy / "runs").exists()  # collision child keeps the dir alive


def test_skips_directories_that_are_python_packages(tmp_path: Path) -> None:
    """site-packages/runs may be an unrelated installed distribution."""
    legacy = tmp_path / "site-packages"
    root = tmp_path / "runtime"
    _seed(legacy / "runs", "__init__.py")
    _seed(legacy / "sessions")

    moved = migrate_legacy_state(legacy_root=legacy, runtime_root=root)

    assert (legacy / "runs" / "__init__.py").is_file()
    assert not (root / "runs").exists()
    assert (root / "sessions" / "record.json").is_file()
    assert len(moved) == 1


def test_one_failing_directory_does_not_block_the_rest(tmp_path: Path) -> None:
    legacy = tmp_path / "install"
    root = tmp_path / "runtime"
    _seed(legacy / "sessions")
    _seed(legacy / "uploads")
    root.mkdir()
    (root / "sessions").write_text("a file where a directory belongs")

    moved = migrate_legacy_state(legacy_root=legacy, runtime_root=root)

    assert (root / "uploads" / "record.json").is_file()
    assert (legacy / "sessions" / "record.json").is_file()  # failed entry untouched
    assert len(moved) == 1


def test_symlinked_destination_receives_children(tmp_path: Path) -> None:
    legacy = tmp_path / "install"
    root = tmp_path / "runtime"
    target = tmp_path / "bigdisk-runs"
    target.mkdir()
    root.mkdir()
    (root / "runs").symlink_to(target)
    _seed(legacy / "runs")
    _seed(legacy / "uploads")

    moved = migrate_legacy_state(legacy_root=legacy, runtime_root=root)

    assert (target / "record.json").is_file()
    assert (root / "uploads" / "record.json").is_file()  # later entries unaffected
    assert len(moved) == 2


def test_stale_partial_tmp_is_discarded_and_move_redone(tmp_path: Path) -> None:
    """A crash mid-copy leaves .migrating-*; source intact means redo cleanly."""
    legacy = tmp_path / "install"
    root = tmp_path / "runtime"
    (legacy / "sessions" / "sess-1").mkdir(parents=True)
    (legacy / "sessions" / "sess-1" / "messages.jsonl").write_text("full")
    partial = root / "sessions" / ".migrating-99999-sess-1"
    partial.mkdir(parents=True)
    (partial / "messages.jsonl").write_text("par")

    migrate_legacy_state(legacy_root=legacy, runtime_root=root)

    assert (root / "sessions" / "sess-1" / "messages.jsonl").read_text() == "full"
    assert not partial.exists()


def test_stale_complete_tmp_is_promoted_when_source_is_gone(tmp_path: Path) -> None:
    """A crash after the copy but before the rename must not lose the data."""
    legacy = tmp_path / "install"
    root = tmp_path / "runtime"
    _seed(legacy / "uploads")  # unrelated entry so migration has work to do
    (legacy / "sessions").mkdir()
    orphan = root / "sessions" / ".migrating-99999-sess-1"
    orphan.mkdir(parents=True)
    (orphan / "messages.jsonl").write_text("full")

    migrate_legacy_state(legacy_root=legacy, runtime_root=root)

    assert (root / "sessions" / "sess-1" / "messages.jsonl").read_text() == "full"
    assert not orphan.exists()


def test_empty_swarm_shell_is_removed_after_migration(tmp_path: Path) -> None:
    legacy = tmp_path / "install"
    root = tmp_path / "runtime"
    _seed(legacy / ".swarm" / "runs")

    migrate_legacy_state(legacy_root=legacy, runtime_root=root)

    assert (root / "swarm" / "runs" / "record.json").is_file()
    assert not (legacy / ".swarm").exists()


def test_replaces_empty_destination_directory(tmp_path: Path) -> None:
    legacy = tmp_path / "install"
    root = tmp_path / "runtime"
    _seed(legacy / "runs")
    (root / "runs").mkdir(parents=True)  # pre-created but empty

    moved = migrate_legacy_state(legacy_root=legacy, runtime_root=root)

    assert (root / "runs" / "record.json").is_file()
    assert not (legacy / "runs").exists()
    assert len(moved) == 1


def test_second_run_is_a_noop(tmp_path: Path) -> None:
    legacy = tmp_path / "install"
    root = tmp_path / "runtime"
    _seed(legacy / "sessions")

    first = migrate_legacy_state(legacy_root=legacy, runtime_root=root)
    second = migrate_legacy_state(legacy_root=legacy, runtime_root=root)

    assert len(first) == 1
    assert second == []


def test_default_legacy_root_matches_pre_904_agent_dir() -> None:
    """The default legacy root must equal the old AGENT_DIR expression."""
    import cli._legacy as legacy

    from src.config.migrate import default_legacy_root

    assert default_legacy_root() == Path(legacy.__file__).resolve().parents[1]


def test_skips_when_legacy_root_equals_runtime_root(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    _seed(root / "sessions")

    moved = migrate_legacy_state(legacy_root=root, runtime_root=root)

    assert moved == []
    assert (root / "sessions" / "record.json").is_file()
