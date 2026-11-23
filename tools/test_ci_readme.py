"""Cover both CI routes and local links in real Git worktrees."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ci_readme import change_scope, check_readmes


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=True, text=True
    )
    return result.stdout.strip()


def _commit(root: Path) -> str:
    _git(root, "add", ".")
    _git(root, "-c", "user.name=CI test", "-c", "user.email=ci@example.test",
         "-c", "commit.gpgsign=false", "commit", "-qm", "Test tree")
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Create a repository with a README and one source file."""
    _git(tmp_path, "init", "-q")
    (tmp_path / "README.md").write_text("# Initial README\n")
    (tmp_path / "source.py").write_text("value = 1\n")
    _commit(tmp_path)
    return tmp_path


@pytest.mark.parametrize(("filename", "expected"), [
    ("README_zh.md", "readme"),
    ("assets/stargazers/new logo.gif", "readme"),
    ("assets/icon.png", "full"),
    ("frontend/public/assets/icon.png", "full"),
    ("assets/mock.py", "full"),
    (".github/workflows/test.yml", "full"),
    ("pyproject.toml", "full"),
])
def test_classify_readme_with_another_change(repo: Path, filename: str, expected: str) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "README.md").write_text("# Updated README\n")
    other = repo / filename
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_bytes(b"new file")
    _commit(repo)

    assert change_scope(repo, base) == expected


def test_classify_entire_push_and_moves(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "assets").mkdir()
    (repo / "source.py").rename(repo / "assets/drawing.png")
    earlier = _commit(repo)
    (repo / "README.md").write_text("# Updated README\n")
    _commit(repo)

    assert change_scope(repo, base) == "full"
    assert change_scope(repo, earlier) == "readme"
    assert change_scope(repo, "a" * 40) == "full"
    assert change_scope(repo, "") == "full"


def test_image_only_is_lightweight_but_executable_assets_are_not(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "assets").mkdir()
    image = repo / "assets/cover.png"
    image.write_bytes(b"image")
    still = _commit(repo)
    assert change_scope(repo, base) == "readme"

    _git(repo, "update-index", "--chmod=+x", "assets/cover.png")
    _git(repo, "-c", "user.name=CI test", "-c", "user.email=ci@example.test",
         "-c", "commit.gpgsign=false", "commit", "-qm", "Executable file")
    assert change_scope(repo, still) == "full"


def test_link_check_covers_markdown_and_picture_sources(tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/logo 1.png").touch()
    (tmp_path / "assets/fallback.png").touch()
    (tmp_path / "README.md").write_text(
        "# README\n\n"
        "![Logo][brand] [Remote](https://example.com/a) [Section](#readme)\n\n"
        "[brand]: <assets/logo 1.png>\n\n"
        '<picture><source srcset="assets/fallback.png 1x, assets/logo%201.png 2x">'
        '<img src="assets/logo%201.png" alt="Logo"></picture>\n'
    )
    (tmp_path / "README_zh.md").write_text("[English](README.md#readme)\n")
    assert check_readmes(tmp_path) == []

    (tmp_path / "assets/fallback.png").unlink()
    assert check_readmes(tmp_path) == [
        "README.md: missing or invalid local reference 'assets/fallback.png'",
    ]
