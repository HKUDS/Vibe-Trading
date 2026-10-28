"""Coverage for is_path_within, the containment check that gates workspace-
restricted file access (e.g. Matrix's outbound attachment upload). It had no
direct or indirect test anywhere in the suite before this file.
"""

from __future__ import annotations

from pathlib import Path

from src.channels.utils import is_path_within


class TestIsPathWithin:
    def test_nested_file_is_within_root(self, tmp_path: Path) -> None:
        root = tmp_path / "workspace"
        nested = root / "sub" / "file.txt"
        nested.parent.mkdir(parents=True)
        nested.write_text("x", encoding="utf-8")

        assert is_path_within(nested, root) is True

    def test_root_itself_is_within_root(self, tmp_path: Path) -> None:
        root = tmp_path / "workspace"
        root.mkdir()

        assert is_path_within(root, root) is True

    def test_sibling_directory_with_matching_prefix_is_not_within_root(self, tmp_path: Path) -> None:
        """A naive string-prefix check would wrongly accept this; relative_to must not."""
        root = tmp_path / "workspace"
        root.mkdir()
        sibling_file = tmp_path / "workspace-evil" / "file.txt"
        sibling_file.parent.mkdir()
        sibling_file.write_text("x", encoding="utf-8")

        assert is_path_within(sibling_file, root) is False

    def test_traversal_that_escapes_root_is_rejected(self, tmp_path: Path) -> None:
        root = tmp_path / "workspace"
        (root / "sub").mkdir(parents=True)
        escaped = root / "sub" / ".." / ".." / "outside.txt"

        assert is_path_within(escaped, root) is False

    def test_traversal_that_stays_inside_root_is_accepted(self, tmp_path: Path) -> None:
        root = tmp_path / "workspace"
        (root / "a").mkdir(parents=True)
        (root / "b").mkdir()
        (root / "b" / "file.txt").write_text("x", encoding="utf-8")
        wandering = root / "a" / ".." / "b" / "file.txt"

        assert is_path_within(wandering, root) is True

    def test_symlink_pointing_outside_root_is_rejected(self, tmp_path: Path) -> None:
        """resolve() follows the symlink before the containment check, so a
        link inside the workspace that targets something outside it must
        not be treated as contained.
        """
        root = tmp_path / "workspace"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret", encoding="utf-8")
        link = root / "link"
        link.symlink_to(outside, target_is_directory=True)

        assert is_path_within(link / "secret.txt", root) is False
