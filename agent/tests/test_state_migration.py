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


def test_keeps_new_data_when_both_locations_are_non_empty(tmp_path: Path) -> None:
    legacy = tmp_path / "install"
    root = tmp_path / "runtime"
    _seed(legacy / "sessions", "old.json")
    _seed(root / "sessions", "new.json")

    moved = migrate_legacy_state(legacy_root=legacy, runtime_root=root)

    assert moved == []
    assert (root / "sessions" / "new.json").is_file()
    assert not (root / "sessions" / "old.json").exists()
    assert (legacy / "sessions" / "old.json").is_file()  # left for the user


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
