"""Tests for the scheduled-research playbook catalogue.

Covers: bundled-template invariants (schedule/timezone validity, the
missing-data rule, no tool names in any body), the markdown+frontmatter loader
and its failure modes, variable rendering, the user-directory override, and
job construction against the real job store and the real cron evaluator.

No network is involved: playbooks are local files and job construction is pure.
"""

from __future__ import annotations

import re
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from src.scheduled_research.executor import next_due
from src.scheduled_research.models import JobStatus, validate_schedule
from src.scheduled_research.playbooks import (
    PlaybookError,
    PlaybookNotFoundError,
    ResearchPlaybook,
    build_job,
    get_playbook,
    list_playbooks,
    load_playbook_file,
    playbook_dirs,
)
from src.scheduled_research.store import ScheduledResearchJobStore

EXPECTED_SLUGS = {
    "a-share-money-flow",
    "earnings-season-tracker",
    "institutional-holdings-diff",
    "portfolio-checkup",
    "premarket-brief",
}

# 2026-08-04T12:00:00Z, fixed so first-fire assertions never depend on the clock.
NOW_MS = 1785585600000

_PLACEHOLDER_RE = re.compile(r"\{\{\s*[A-Za-z0-9_]+\s*\}\}")
_SNAKE_CASE_RE = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")


@pytest.fixture(autouse=True)
def _no_user_playbook_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the bundled-catalogue assertions hermetic on a developer machine."""
    monkeypatch.delenv("VIBE_TRADING_PLAYBOOK_DIR", raising=False)


def _write(directory: Path, slug: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{slug}.md"
    path.write_text(text, encoding="utf-8")
    return path


_MINIMAL = """---
name: Minimal
description: A minimal playbook.
suggested_schedule: "3600000"
data_capabilities:
  - Daily closing prices for one symbol
variables:
  symbol: AAPL
---

# Minimal

Look at {{symbol}}.
"""


# ---------------------------------------------------------------------------
# Bundled catalogue invariants
# ---------------------------------------------------------------------------


class TestBundledCatalogue:
    def test_module_wins_over_same_named_data_directory(self) -> None:
        """``playbooks.py`` and ``playbooks/`` coexist; the module must win."""
        import src.scheduled_research.playbooks as module

        assert module.__file__ is not None
        assert Path(module.__file__).name == "playbooks.py"

    def test_ships_the_expected_five(self) -> None:
        assert {p.slug for p in list_playbooks()} == EXPECTED_SLUGS

    def test_sorted_by_slug(self) -> None:
        slugs = [p.slug for p in list_playbooks()]
        assert slugs == sorted(slugs)

    def test_covers_more_than_us_markets(self) -> None:
        markets = {m for p in list_playbooks() for m in p.markets}
        assert "cn" in markets and "global" in markets

    @pytest.mark.parametrize("slug", sorted(EXPECTED_SLUGS))
    def test_suggested_schedule_is_valid(self, slug: str) -> None:
        validate_schedule(get_playbook(slug).suggested_schedule)

    @pytest.mark.parametrize("slug", sorted(EXPECTED_SLUGS))
    def test_suggested_timezone_resolves(self, slug: str) -> None:
        tz = get_playbook(slug).suggested_timezone
        if tz is None:
            return
        try:
            ZoneInfo(tz)
        except ZoneInfoNotFoundError:  # host without a full IANA database
            pytest.skip(f"host timezone database has no {tz!r}")

    @pytest.mark.parametrize("slug", sorted(EXPECTED_SLUGS))
    def test_declares_data_capabilities_not_tool_names(self, slug: str) -> None:
        playbook = get_playbook(slug)
        assert playbook.data_capabilities
        for capability in playbook.data_capabilities:
            assert not _SNAKE_CASE_RE.search(capability), capability

    @pytest.mark.parametrize("slug", sorted(EXPECTED_SLUGS))
    def test_body_names_no_tool(self, slug: str) -> None:
        """Bodies describe capabilities; every tool in this repo is snake_case."""
        body = _PLACEHOLDER_RE.sub("", get_playbook(slug).body)
        assert not _SNAKE_CASE_RE.findall(body)

    @pytest.mark.parametrize("slug", sorted(EXPECTED_SLUGS))
    def test_body_carries_the_missing_data_rule(self, slug: str) -> None:
        body = get_playbook(slug).body
        assert "## When data is missing" in body
        assert "Data gaps" in body
        assert "from memory" in body
        assert "third-party summary" in body

    @pytest.mark.parametrize("slug", sorted(EXPECTED_SLUGS))
    def test_body_states_output_and_boundaries(self, slug: str) -> None:
        body = get_playbook(slug).body
        assert "## Output" in body
        assert "## Boundaries" in body
        # Line wrapping must not decide whether the no-advice rule is present.
        unwrapped = " ".join(body.split())
        assert "No buy, sell, or hold calls" in unwrapped
        assert "no price targets" in unwrapped
        assert "Do not place, modify, or cancel any order" in unwrapped

    @pytest.mark.parametrize("slug", sorted(EXPECTED_SLUGS))
    def test_body_resolves_the_run_date_at_run_time(self, slug: str) -> None:
        """The prompt is stored once and replayed, so no date may be baked in."""
        body = get_playbook(slug).body
        assert "run environment" in body
        assert not re.search(r"\b20\d\d-\d\d-\d\d\b", body)

    @pytest.mark.parametrize("slug", sorted(EXPECTED_SLUGS))
    def test_renders_and_schedules(self, slug: str) -> None:
        job = build_job(slug, now_ms=NOW_MS)
        assert job.status is JobStatus.PENDING
        assert "{{" not in job.prompt
        assert job.next_run_at > NOW_MS  # cron + timezone => first authored fire


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


class TestLoader:
    def test_parses_block_sequence_capabilities(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "multi",
            "---\n"
            "name: Multi\n"
            "description: Two capabilities.\n"
            'suggested_schedule: "0 9 * * 1-5"\n'
            "suggested_timezone: Asia/Shanghai\n"
            "markets: [cn, hk]\n"
            "data_capabilities:\n"
            "  - Prices, volumes and turnover for one session\n"
            "  - Sector rankings, including the laggards\n"
            "---\n\nBody.\n",
        )
        playbook = load_playbook_file(path)
        assert playbook.data_capabilities == (
            "Prices, volumes and turnover for one session",
            "Sector rankings, including the laggards",
        )
        assert playbook.markets == ("cn", "hk")
        assert playbook.suggested_timezone == "Asia/Shanghai"

    def test_slug_comes_from_the_filename(self, tmp_path: Path) -> None:
        assert load_playbook_file(_write(tmp_path, "some-slug", _MINIMAL)).slug == "some-slug"

    def test_defaults_markets_when_absent(self, tmp_path: Path) -> None:
        assert load_playbook_file(_write(tmp_path, "m", _MINIMAL)).markets == ("global",)

    def test_rejects_file_without_frontmatter(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "bare", "# Just a heading\n")
        with pytest.raises(PlaybookError, match="frontmatter"):
            load_playbook_file(path)

    def test_rejects_non_mapping_frontmatter(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "seq", "---\n- a\n- b\n---\n\nBody.\n")
        with pytest.raises(PlaybookError, match="must be a mapping"):
            load_playbook_file(path)

    def test_rejects_invalid_yaml(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "bad", "---\nname: [unclosed\n---\n\nBody.\n")
        with pytest.raises(PlaybookError, match="not valid YAML"):
            load_playbook_file(path)

    def test_rejects_missing_required_key(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "nodesc", _MINIMAL.replace("description: A minimal playbook.\n", ""))
        with pytest.raises(PlaybookError, match="description"):
            load_playbook_file(path)

    def test_rejects_invalid_schedule(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "badcron", _MINIMAL.replace('"3600000"', '"99 * * * *"'))
        with pytest.raises(PlaybookError, match="out of range"):
            load_playbook_file(path)

    def test_rejects_empty_body(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "empty", _MINIMAL.split("# Minimal")[0].rstrip("\n") + "\n")
        with pytest.raises(PlaybookError, match="body is empty"):
            load_playbook_file(path)

    def test_rejects_undeclared_placeholder(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "typo", _MINIMAL.replace("{{symbol}}", "{{symbal}}"))
        with pytest.raises(PlaybookError, match="undeclared variables"):
            load_playbook_file(path)

    def test_rejects_empty_capability_entry(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "blank",
            _MINIMAL.replace("  - Daily closing prices for one symbol\n", '  - ""\n'),
        )
        with pytest.raises(PlaybookError, match="empty entry"):
            load_playbook_file(path)


# ---------------------------------------------------------------------------
# Lookup and directory precedence
# ---------------------------------------------------------------------------


class TestLookup:
    def test_unknown_slug_lists_available(self) -> None:
        with pytest.raises(PlaybookNotFoundError, match="premarket-brief"):
            get_playbook("does-not-exist")

    @pytest.mark.parametrize("slug", ["../models", "a/b", "Upper", "", "a b"])
    def test_rejects_malformed_slug(self, slug: str) -> None:
        with pytest.raises(PlaybookNotFoundError, match="invalid playbook slug"):
            get_playbook(slug)

    def test_env_directory_is_searched_first(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VIBE_TRADING_PLAYBOOK_DIR", str(tmp_path))
        assert playbook_dirs()[0] == tmp_path

    def test_user_file_shadows_bundled_slug(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write(tmp_path, "premarket-brief", _MINIMAL)
        monkeypatch.setenv("VIBE_TRADING_PLAYBOOK_DIR", str(tmp_path))
        assert get_playbook("premarket-brief").name == "Minimal"
        catalogue = {p.slug: p.name for p in list_playbooks()}
        assert catalogue["premarket-brief"] == "Minimal"
        assert set(catalogue) == EXPECTED_SLUGS  # override, not addition

    def test_missing_directory_is_not_an_error(self, tmp_path: Path) -> None:
        assert list_playbooks(directory=tmp_path / "nope") == []

    def test_broken_user_file_surfaces_instead_of_being_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(tmp_path, "broken", "no frontmatter here\n")
        monkeypatch.setenv("VIBE_TRADING_PLAYBOOK_DIR", str(tmp_path))
        with pytest.raises(PlaybookError, match="frontmatter"):
            list_playbooks()

    def test_every_listed_slug_is_retrievable(self) -> None:
        """The catalogue must never advertise an entry get_playbook refuses."""
        for playbook in list_playbooks():
            assert get_playbook(playbook.slug).slug == playbook.slug

    @pytest.mark.parametrize("stem", ["My_Playbook", "Upper", "has space", "under_score"])
    def test_badly_named_file_is_rejected_at_load(self, tmp_path: Path, stem: str) -> None:
        """A file whose stem is not a valid slug fails loudly instead of
        becoming a catalogue entry that get_playbook can never return."""
        path = _write(tmp_path, stem, _MINIMAL)
        with pytest.raises(PlaybookError, match="not a valid slug"):
            load_playbook_file(path)
        with pytest.raises(PlaybookError, match="not a valid slug"):
            list_playbooks(directory=tmp_path)

    def test_utf8_bom_does_not_hide_the_frontmatter(self, tmp_path: Path) -> None:
        """A BOM from a Windows editor must not read as 'missing frontmatter'."""
        path = tmp_path / "bom.md"
        path.write_text(_MINIMAL, encoding="utf-8-sig")
        assert load_playbook_file(path).name == "Minimal"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestRender:
    def _minimal(self, tmp_path: Path) -> ResearchPlaybook:
        return load_playbook_file(_write(tmp_path, "minimal", _MINIMAL))

    def test_uses_declared_defaults(self, tmp_path: Path) -> None:
        assert self._minimal(tmp_path).render() == "# Minimal\n\nLook at AAPL."

    def test_override_wins(self, tmp_path: Path) -> None:
        assert "600519.SH" in self._minimal(tmp_path).render({"symbol": "600519.SH"})

    def test_blank_override_falls_back_to_default(self, tmp_path: Path) -> None:
        assert "AAPL" in self._minimal(tmp_path).render({"symbol": "   "})

    def test_undeclared_variable_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(PlaybookError, match="has no variable"):
            self._minimal(tmp_path).render({"ticker": "AAPL"})

    def test_oversized_value_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(PlaybookError, match="the cap is"):
            self._minimal(tmp_path).render({"symbol": "A" * 4001})

    def test_braces_in_a_value_are_not_re_expanded(self, tmp_path: Path) -> None:
        rendered = self._minimal(tmp_path).render({"symbol": "{{symbol}}"})
        assert rendered.endswith("Look at {{symbol}}.")


# ---------------------------------------------------------------------------
# Job construction
# ---------------------------------------------------------------------------


class TestToJob:
    def test_defaults_to_the_suggested_cadence(self) -> None:
        playbook = get_playbook("premarket-brief")
        job = playbook.to_job(now_ms=NOW_MS)
        assert job.schedule == playbook.suggested_schedule
        assert job.timezone == playbook.suggested_timezone
        assert job.id.startswith("playbook-premarket-brief-")
        assert job.created_at == NOW_MS

    def test_first_fire_matches_the_cron_evaluator(self) -> None:
        playbook = get_playbook("a-share-money-flow")
        job = playbook.to_job(now_ms=NOW_MS)
        assert job.next_run_at == next_due(
            playbook.suggested_schedule, NOW_MS, playbook.suggested_timezone
        )

    def test_interval_schedule_fires_immediately(self) -> None:
        job = get_playbook("premarket-brief").to_job(schedule="3600000", now_ms=NOW_MS)
        assert job.schedule == "3600000"
        assert job.next_run_at == NOW_MS

    def test_explicit_none_timezone_means_utc_and_immediate_first_fire(self) -> None:
        job = get_playbook("premarket-brief").to_job(timezone=None, now_ms=NOW_MS)
        assert job.timezone is None
        assert job.next_run_at == NOW_MS

    def test_explicit_next_run_at_wins(self) -> None:
        job = get_playbook("premarket-brief").to_job(next_run_at=42, now_ms=NOW_MS)
        assert job.next_run_at == 42

    def test_rejects_a_malformed_schedule_override(self) -> None:
        with pytest.raises(ValueError, match="cron"):
            get_playbook("premarket-brief").to_job(schedule="not a schedule")

    def test_rejects_an_unresolvable_timezone_override(self) -> None:
        with pytest.raises(ValueError, match="not a recognized IANA timezone"):
            get_playbook("premarket-brief").to_job(timezone="Mars/Olympus")

    def test_prompt_is_the_rendered_body(self) -> None:
        playbook = get_playbook("portfolio-checkup")
        variables = {"holdings": "600519.SH 100; AAPL 50"}
        job = playbook.to_job(variables=variables, now_ms=NOW_MS)
        assert job.prompt == playbook.render(variables)
        assert "600519.SH 100; AAPL 50" in job.prompt

    def test_config_records_provenance_but_never_overwrites_the_caller(self) -> None:
        assert build_job("premarket-brief", now_ms=NOW_MS).config == {"playbook": "premarket-brief"}
        job = build_job("premarket-brief", now_ms=NOW_MS, config={"playbook": "mine", "model": "x"})
        assert job.config == {"playbook": "mine", "model": "x"}

    def test_caller_config_is_copied_not_aliased(self) -> None:
        supplied: dict = {}
        build_job("premarket-brief", now_ms=NOW_MS, config=supplied)
        assert supplied == {}

    @pytest.mark.parametrize("slug", sorted(EXPECTED_SLUGS))
    def test_job_survives_the_real_store(self, tmp_path: Path, slug: str) -> None:
        store = ScheduledResearchJobStore(tmp_path / "jobs.json")
        job = build_job(slug, now_ms=NOW_MS)
        store.upsert(job)
        loaded = store.get(job.id)
        assert loaded is not None
        assert loaded.prompt == job.prompt
        assert loaded.schedule == job.schedule
        assert loaded.timezone == job.timezone


# ---------------------------------------------------------------------------
# Catalogue serialization
# ---------------------------------------------------------------------------


class TestToDict:
    def test_omits_the_body_by_default(self) -> None:
        data = get_playbook("premarket-brief").to_dict()
        assert "body" not in data
        assert data["slug"] == "premarket-brief"
        assert isinstance(data["data_capabilities"], list)
        assert isinstance(data["markets"], list)
        assert data["variables"]["home_market"]

    def test_includes_the_body_on_request(self) -> None:
        assert get_playbook("premarket-brief").to_dict(include_body=True)["body"]

    def test_every_bundled_record_is_json_serializable(self) -> None:
        import json

        json.dumps([p.to_dict(include_body=True) for p in list_playbooks()])
