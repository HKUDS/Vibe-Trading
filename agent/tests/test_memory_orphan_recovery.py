"""Recovery of memory entries orphaned by the missing-suffix write bug."""
from pathlib import Path
import pytest
from src.memory.hierarchy import MemoryHierarchy

_ENTRY = "---\nname: alpha-note\ndescription: d\nmetadata:\n  type: project\n---\n\nbody\n"


def test_extensionless_entry_is_recovered_and_becomes_visible(tmp_path: Path) -> None:
    (tmp_path / "project").mkdir()
    orphan = tmp_path / "project" / "alpha-note"
    orphan.write_text(_ENTRY, encoding="utf-8")

    found = MemoryHierarchy(tmp_path).scan_all()

    assert not orphan.exists()
    assert (tmp_path / "project" / "alpha-note.md").is_file()
    assert (tmp_path / "project" / "alpha-note.md") in found


def test_recovery_never_overwrites_a_newer_entry(tmp_path: Path) -> None:
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "dup").write_text(_ENTRY, encoding="utf-8")
    keep = tmp_path / "project" / "dup.md"
    keep.write_text(_ENTRY.replace("body", "newer"), encoding="utf-8")

    MemoryHierarchy(tmp_path).recover_extensionless_entries()

    assert "newer" in keep.read_text(encoding="utf-8")
    assert (tmp_path / "project" / "dup").is_file()


@pytest.mark.parametrize(
    "name,content",
    [("notes.txt", _ENTRY), ("scratch", "just some text, no frontmatter\n")],
    ids=["has_suffix", "no_frontmatter"],
)
def test_unrelated_files_are_left_alone(tmp_path: Path, name, content) -> None:
    (tmp_path / "project").mkdir()
    other = tmp_path / "project" / name
    other.write_text(content, encoding="utf-8")

    MemoryHierarchy(tmp_path).recover_extensionless_entries()

    assert other.is_file()
    assert not (tmp_path / "project" / "scratch.md").exists()


def test_recovery_is_idempotent(tmp_path: Path) -> None:
    (tmp_path / "feedback").mkdir()
    (tmp_path / "feedback" / "lesson").write_text(_ENTRY, encoding="utf-8")
    h = MemoryHierarchy(tmp_path)

    assert len(h.recover_extensionless_entries()) == 1
    assert h.recover_extensionless_entries() == []
