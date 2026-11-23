#!/usr/bin/env python3
"""Select the README fast path and check repository-relative README links."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
README_NAME = re.compile(r"README(?:_[a-z]{2}(?:-[A-Za-z]{2})?)?\.md")
IMAGE_SUFFIXES = frozenset({".avif", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".svg", ".webp"})
# Electron also uses this asset when building the application.
DESKTOP_ICON = PurePosixPath("assets/icon.png")
REGULAR_FILE_MODES = {b"000000", b"100644"}


def change_scope(root: Path, base: str) -> str:
    """Classify the tree diff from an event's base to the checked-out commit.

    Args:
        root: Git worktree to inspect.
        base: Full base commit ID from the workflow event.

    Returns:
        "readme" for a nonempty README and documentation image diff, otherwise "full".
    """
    if not re.fullmatch(r"[0-9a-f]{40}", base) or base == "0" * 40:
        return "full"
    diff = subprocess.run(
        ["git", "diff", "--raw", "-z", "--no-renames", "--no-ext-diff", base, "HEAD", "--"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if diff.returncode or not diff.stdout:
        return "full"

    # With renames disabled, a move includes both its old and new path.
    fields = iter(diff.stdout.rstrip(b"\0").split(b"\0"))
    for metadata, filename in zip(fields, fields, strict=True):
        before, after, *_ = metadata.removeprefix(b":").split()
        if before not in REGULAR_FILE_MODES or after not in REGULAR_FILE_MODES:
            return "full"
        path = PurePosixPath(os.fsdecode(filename))
        if len(path.parts) == 1 and README_NAME.fullmatch(path.name):
            continue
        if (path.parts[0] == "assets" and path != DESKTOP_ICON
                and path.suffix.lower() in IMAGE_SUFFIXES):
            continue
        return "full"
    return "readme"


class ReadmeLinks(HTMLParser):
    """Collect paths after Markdown and inline HTML have been rendered."""

    def __init__(self) -> None:
        super().__init__()
        self.links: set[tuple[str, bool]] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if not value:
                continue
            if tag == "a" and name == "href":
                self.links.add((value, False))
            elif tag in {"img", "source", "video"} and name in {"src", "poster"}:
                self.links.add((value, True))
            elif tag in {"img", "source"} and name == "srcset" and not value.lstrip().startswith("data:"):
                for candidate in value.split(","):
                    parts = candidate.split()
                    if parts:
                        self.links.add((parts[0], True))


def check_readmes(root: Path) -> list[str]:
    """Render the root READMEs and report missing local links and media.

    Args:
        root: Repository directory that contains README.md.

    Returns:
        Diagnostics for empty, missing, or broken README content.
    """
    from markdown_it import MarkdownIt

    root = root.resolve()
    markdown = MarkdownIt("commonmark", {"html": True}).enable(["table", "strikethrough"])
    errors = []
    for readme in sorted({root / "README.md", *root.glob("README_*.md")}):
        if not README_NAME.fullmatch(readme.name):
            continue
        if not readme.is_file() or not readme.resolve().is_relative_to(root):
            errors.append(f"{readme.name}: missing or outside the repository")
            continue
        content = readme.read_text(encoding="utf-8")
        if not content.strip():
            errors.append(f"{readme.name}: README is empty")
            continue
        parser = ReadmeLinks()
        parser.feed(markdown.render(content))
        parser.close()
        for link, requires_file in sorted(parser.links):
            url = urlsplit(link)
            if url.scheme or url.netloc or not url.path or url.path.startswith("/"):
                continue
            target = (readme.parent / unquote(url.path)).resolve()
            exists = target.is_file() if requires_file else target.exists()
            if not target.is_relative_to(root) or not exists:
                errors.append(f"{readme.name}: missing or invalid local reference {link!r}")
    return errors


def main() -> int:
    """Run the scope classifier or README check."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("scope").add_argument("base")
    commands.add_parser("check")
    args = parser.parse_args()

    if args.command == "scope":
        print(change_scope(ROOT, args.base))
        return 0

    errors = check_readmes(ROOT)
    if errors:
        print("\n".join(errors))
        return 1
    print("README local links and media references are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
