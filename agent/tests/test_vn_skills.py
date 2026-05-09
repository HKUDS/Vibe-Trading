"""Regression tests pinning the bundled Vietnam-market skills.

These tests guard against silent removal of the VN skills (per the
``Bundled-Skill Regression Coverage`` OpenSpec spec) and verify that:

* All three Sprint-1/2 VN SKILL.md files exist with valid frontmatter
* Each is registered to the correct category
* Body content covers the load-bearing concepts a strategy/research
  agent must rely on (exchanges, foreign-room caps, VAS account codes)

Aggregate filesystem-discovery tests catch additions of future
``vn-*`` skills without requiring a registry edit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.agent.frontmatter import parse_frontmatter


SKILLS_DIR = Path(__file__).resolve().parent.parent / "src" / "skills"

VALID_CATEGORIES = {
    "data-source",
    "risk-analysis",
    "analysis",
    "strategy",
    "asset-class",
    "crypto",
    "flow",
    "tool",
}

VN_SKILLS = (
    "vn-data-routing",
    "vn-foreign-room",
    "vn-financial-statements-vas",
)


def _parse_skill(skill_name: str) -> tuple[dict, str]:
    """Return ``(frontmatter_dict, body_text)`` for a bundled skill."""
    path = SKILLS_DIR / skill_name / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    assert meta, f"Skill {skill_name} missing YAML frontmatter"
    return meta, body


# ---------------------------------------------------------------------------
# Group A — Skill files exist with valid frontmatter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill_name", VN_SKILLS)
def test_vn_skill_exists(skill_name: str) -> None:
    """SKILL.md exists and is non-empty."""
    path = SKILLS_DIR / skill_name / "SKILL.md"
    assert path.is_file(), f"Missing {path}"
    assert path.stat().st_size > 0, f"Empty SKILL.md at {path}"


@pytest.mark.parametrize("skill_name", VN_SKILLS)
def test_vn_skill_frontmatter(skill_name: str) -> None:
    """Frontmatter has required fields with valid values."""
    meta, _ = _parse_skill(skill_name)

    assert meta.get("name") == skill_name, (
        f"Frontmatter name mismatch for {skill_name}: got {meta.get('name')!r}"
    )
    category = meta.get("category")
    assert category in VALID_CATEGORIES, (
        f"Skill {skill_name} has invalid category {category!r}; "
        f"expected one of {sorted(VALID_CATEGORIES)}"
    )
    description = meta.get("description", "")
    assert isinstance(description, str) and len(description) >= 20, (
        f"Skill {skill_name} description too short or missing: {description!r}"
    )


# ---------------------------------------------------------------------------
# Group B — Category assignments
# ---------------------------------------------------------------------------


def test_vn_data_routing_category() -> None:
    meta, _ = _parse_skill("vn-data-routing")
    assert meta["category"] == "data-source"


def test_vn_foreign_room_category() -> None:
    meta, _ = _parse_skill("vn-foreign-room")
    assert meta["category"] == "risk-analysis"


def test_vn_financial_statements_vas_category() -> None:
    meta, _ = _parse_skill("vn-financial-statements-vas")
    assert meta["category"] == "analysis"


# ---------------------------------------------------------------------------
# Group C — Body content sanity
# ---------------------------------------------------------------------------


def test_vn_data_routing_body_mentions_exchanges() -> None:
    """Routing skill must reference all three exchanges + the loader name."""
    _, body = _parse_skill("vn-data-routing")
    assert "HOSE" in body
    assert "HNX" in body
    assert ("UPCOM" in body) or ("UPCoM" in body)
    assert "vnstock" in body


def test_vn_foreign_room_body_mentions_caps() -> None:
    """Foreign-room skill must call out the 49% / 30% caps and banks."""
    _, body = _parse_skill("vn-foreign-room")
    assert ("49%" in body) or ("30%" in body)
    assert "room" in body.lower()
    assert ("Banking" in body) or ("bank" in body.lower())


def test_vn_financial_statements_vas_body_mentions_accounting() -> None:
    """VAS skill must mention VAS, IFRS, balance sheet, and ≥1 account code."""
    _, body = _parse_skill("vn-financial-statements-vas")
    assert "VAS" in body
    assert "IFRS" in body
    assert ("Balance Sheet" in body) or ("balance sheet" in body.lower())

    # At least one canonical 3-digit VAS account code (e.g. 131, 211, 421, 511)
    # should appear as a standalone token in the body.
    code_pattern = re.compile(r"(?<!\d)([1-9]\d{2})(?!\d)")
    codes_found = set(code_pattern.findall(body))
    expected_codes = {"131", "211", "421", "511"}
    assert codes_found & expected_codes, (
        "VAS skill body should reference at least one of the canonical "
        f"VAS account codes {sorted(expected_codes)}; found codes: {sorted(codes_found)}"
    )


# ---------------------------------------------------------------------------
# Group D — Aggregate VN skill discovery (filesystem-based)
# ---------------------------------------------------------------------------


def test_at_least_three_vn_skills() -> None:
    """The bundled skills directory ships ≥ 3 vn-* skills."""
    matches = list(SKILLS_DIR.glob("vn-*/SKILL.md"))
    assert len(matches) >= 3, (
        f"Expected ≥3 vn-* skills in {SKILLS_DIR}, found {len(matches)}: {matches}"
    )


def test_all_vn_skills_have_valid_frontmatter() -> None:
    """Every vn-* skill on disk has the required frontmatter fields."""
    matches = sorted(SKILLS_DIR.glob("vn-*/SKILL.md"))
    assert matches, f"No vn-* skills found under {SKILLS_DIR}"

    for path in matches:
        text = path.read_text(encoding="utf-8")
        meta, _ = parse_frontmatter(text)
        rel = path.relative_to(SKILLS_DIR)

        assert meta.get("name"), f"{rel}: frontmatter missing 'name'"
        assert meta.get("category"), f"{rel}: frontmatter missing 'category'"
        assert meta.get("category") in VALID_CATEGORIES, (
            f"{rel}: invalid category {meta.get('category')!r}"
        )
        description = meta.get("description")
        assert isinstance(description, str) and description.strip(), (
            f"{rel}: frontmatter missing non-empty 'description'"
        )
