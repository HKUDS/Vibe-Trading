"""Regression tests: ``read_file`` resolves skill-relative reference links.

Background:
    A ``references/`` or ``scripts/`` link inside a SKILL.md is written relative
    to the document, which is the form GitHub resolves for a human reader.
    ``read_file`` roots at the bundled ``skills/`` directory, so historically
    only the ``<skill>/references/...`` form was reachable by the agent and the
    two consumers could not be satisfied by one string. Both forms now resolve.

No live API is touched: ``read_file`` performs local filesystem reads of the
bundled skill docs only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Tuple

import pytest

from src.tools import read_file_tool
from src.tools.read_file_tool import ReadFileTool, _skill_relative_matches

_SKILLS_DIR = Path(__file__).resolve().parents[1] / "src" / "skills"


def _body(raw: str) -> dict:
    """Parse a JSON tool response."""
    return json.loads(raw)


def _unique_link(subdir: str, suffix: str) -> Tuple[str, str]:
    """Find a bundled file under ``subdir`` that exactly one skill owns.

    Deriving the fixture from the corpus keeps the test from rotting when a
    skill is renamed or its references are reorganised.

    Args:
        subdir: ``references`` or ``scripts``.
        suffix: File extension to look for, e.g. ``.md``.

    Returns:
        ``(skill_name, skill_relative_path)``.
    """
    owners: dict[str, list[str]] = {}
    for skill_dir in sorted(p for p in _SKILLS_DIR.iterdir() if p.is_dir()):
        base = skill_dir / subdir
        if not base.is_dir():
            continue
        for path in base.rglob(f"*{suffix}"):
            if path.is_file():
                rel = path.relative_to(skill_dir).as_posix()
                owners.setdefault(rel, []).append(skill_dir.name)
    for rel, skills in sorted(owners.items()):
        if len(skills) == 1:
            return skills[0], rel
    pytest.fail(f"no bundled skill owns a unique {subdir}/*{suffix} file")


@pytest.mark.parametrize("subdir,suffix", [("references", ".md"), ("scripts", ".py")])
def test_bare_link_resolves_to_the_owning_skill(subdir: str, suffix: str) -> None:
    """A bare link resolves to the same file as its skill-prefixed form."""
    skill, rel = _unique_link(subdir, suffix)

    bare = _body(ReadFileTool().execute(path=rel))
    prefixed = _body(ReadFileTool().execute(path=f"{skill}/{rel}"))

    assert bare["status"] == "ok", bare
    assert prefixed["status"] == "ok", prefixed
    assert bare["path"] == prefixed["path"]
    assert bare["content"] == prefixed["content"]


def test_skills_rooted_form_still_resolves() -> None:
    """The explicit ``skills/`` namespace keeps working unchanged."""
    skill, rel = _unique_link("references", ".md")

    body = _body(ReadFileTool().execute(path=f"skills/{skill}/{rel}"))

    assert body["status"] == "ok", body
    assert body["content"]


def test_bare_link_does_not_shadow_run_dir(tmp_path: Path, monkeypatch) -> None:
    """A file the agent wrote into run_dir still wins over the skills tree.

    The fallback is a last resort, so existing resolution order is unchanged.
    """
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    _, rel = _unique_link("references", ".md")
    local = tmp_path / rel
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text("RUN DIR CONTENT", encoding="utf-8")

    body = _body(ReadFileTool().execute(path=rel, run_dir=str(tmp_path)))

    assert body["status"] == "ok", body
    assert body["content"] == "RUN DIR CONTENT"


def test_unknown_bare_link_is_still_an_error() -> None:
    """A references/ path no skill owns reports not-found, not a wrong file."""
    body = _body(ReadFileTool().execute(path="references/no_such_document.md"))

    assert body["status"] == "error"
    assert "not found" in body["error"]


def test_bare_link_cannot_climb_out_of_the_skill(tmp_path: Path, monkeypatch) -> None:
    """``..`` inside a bare link is refused rather than followed.

    Without this the fallback would widen the boundary the ``skills/`` prefix
    already enforces: a path only has to *start* with ``references/``.
    """
    monkeypatch.setattr(read_file_tool, "_bundled_skills_dir", lambda: _SKILLS_DIR)
    secret = _SKILLS_DIR.parent.parent.parent / "pyproject.toml"
    assert secret.is_file(), "fixture assumes pyproject.toml sits above skills/"

    for attempt in (
        "references/../SKILL.md",
        "references/../../tushare/SKILL.md",
        "references/../../../../pyproject.toml",
        "scripts/../../../../../etc/passwd",
    ):
        body = _body(ReadFileTool().execute(path=attempt))
        assert body["status"] == "error", f"{attempt} resolved: {body}"


def test_ambiguous_bare_link_names_the_candidates(tmp_path: Path, monkeypatch) -> None:
    """Two skills owning one path is reported, never silently resolved.

    Picking one would hand the agent a document from the wrong skill and read
    as a correct answer.
    """
    for skill in ("alpha-skill", "beta-skill"):
        target = tmp_path / skill / "references" / "overview.md"
        target.parent.mkdir(parents=True)
        target.write_text(f"content from {skill}", encoding="utf-8")
    monkeypatch.setattr(read_file_tool, "_bundled_skills_dir", lambda: tmp_path)

    body = _body(ReadFileTool().execute(path="references/overview.md"))

    assert body["status"] == "error"
    assert "Ambiguous" in body["error"]
    assert "alpha-skill" in body["error"] and "beta-skill" in body["error"]


def test_skill_relative_matches_rejects_traversal(tmp_path: Path) -> None:
    """The matcher itself drops climbing and absolute paths."""
    target = tmp_path / "one-skill" / "references" / "doc.md"
    target.parent.mkdir(parents=True)
    target.write_text("body", encoding="utf-8")
    (tmp_path / "one-skill" / "SKILL.md").write_text("root doc", encoding="utf-8")

    outside = tmp_path.parent / "outside.md"
    outside.write_text("outside", encoding="utf-8")

    assert len(_skill_relative_matches("references/doc.md", tmp_path)) == 1
    assert _skill_relative_matches("references/../SKILL.md", tmp_path) == []
    assert _skill_relative_matches("references/..\\SKILL.md", tmp_path) == []
    assert _skill_relative_matches(str(outside), tmp_path) == []
