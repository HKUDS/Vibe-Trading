"""Entry-point contracts for the scheduled-research playbook catalogue.

The templates themselves are covered by ``tests/test_research_playbooks.py``.
This module covers the three surfaces a user actually reaches them through, and
the properties that are easy to break from any of them:

* REST — ``GET /scheduled-runs/playbooks``, ``GET /scheduled-runs/playbooks/{slug}``
  and ``POST /scheduled-runs/playbooks/{slug}``, including the structural claim
  that EVERY route under ``/scheduled-runs`` carries ``require_auth``.
* CLI — ``vibe-trading playbook list | show | create``, driven through
  ``cli._legacy.main`` so the argparse wiring is exercised, not just the handler.
* Slash — ``/playbook`` registration plus its list / show / run / schedule paths.

The decoupling assertion runs on all three: a queued or persisted prompt must be
``ResearchPlaybook.render()`` byte for byte. An entry point that "helpfully"
appended tool names would fail here.

No network is involved. The job store is redirected to ``tmp_path`` by pointing
``VIBE_TRADING_HOME`` at it (CLI/slash, which construct their own store) and by
patching the route module's singleton (REST).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Tuple

import pytest
from fastapi.testclient import TestClient

import api_server
from cli.commands import research_playbook, slash_router
from src.api import scheduled_routes
from src.scheduled_research.playbooks import get_playbook, list_playbooks
from src.scheduled_research.store import ScheduledResearchJobStore

BUNDLED_SLUGS = {
    "a-share-money-flow",
    "earnings-season-tracker",
    "institutional-holdings-diff",
    "portfolio-checkup",
    "premarket-brief",
}

# A template with declared variables and a timezone-carrying cron cadence, so
# the variable-substitution and first-fire branches both get exercised.
SAMPLE = "premarket-brief"


class _Ctx:
    """Minimal stand-in for ``cli.main.InteractiveContext``."""

    def __init__(self) -> None:
        self.pending_prompt: str | None = None


class _NoQueueCtx:
    """A context that cannot hold a queued prompt (stub / non-interactive)."""


@pytest.fixture(autouse=True)
def _hermetic_catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ignore any user playbook directory on the developer's machine."""
    monkeypatch.delenv("VIBE_TRADING_PLAYBOOK_DIR", raising=False)


@pytest.fixture(autouse=True)
def _wide_console(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop Rich from ellipsizing slugs at the default 80-column test width."""
    from cli.theme import get_console

    monkeypatch.setattr(get_console(), "width", 200, raising=False)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the runtime root at ``tmp_path`` so the CLI writes a temp store."""
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def cli_store(home: Path) -> ScheduledResearchJobStore:
    """The store the CLI and slash surfaces write to under the temp home."""
    return ScheduledResearchJobStore()


@pytest.fixture
def rest_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ScheduledResearchJobStore:
    """Isolate the route module's store singleton onto a temp file."""
    isolated = ScheduledResearchJobStore(path=tmp_path / "scheduled_jobs.json")
    monkeypatch.setattr(scheduled_routes, "_scheduled_research_store", isolated)
    return isolated


@pytest.fixture
def client(rest_store: ScheduledResearchJobStore, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Keyless dev-mode client whose peer host counts as loopback."""
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _run_cli(argv: List[str]) -> int:
    """Drive the real argparse dispatcher, returning its exit code."""
    from cli import _legacy

    return int(_legacy.main(argv))


# ---------------------------------------------------------------------------
# REST — catalogue
# ---------------------------------------------------------------------------


class TestRestCatalogue:
    def test_list_returns_every_bundled_template(self, client: TestClient) -> None:
        response = client.get("/scheduled-runs/playbooks")

        assert response.status_code == 200
        rows = response.json()
        assert {row["slug"] for row in rows} >= BUNDLED_SLUGS
        assert [row["slug"] for row in rows] == sorted(row["slug"] for row in rows)

    def test_list_omits_bodies(self, client: TestClient) -> None:
        rows = client.get("/scheduled-runs/playbooks").json()

        assert rows
        assert all(row["body"] is None for row in rows)

    def test_list_carries_catalogue_metadata(self, client: TestClient) -> None:
        rows = {row["slug"]: row for row in client.get("/scheduled-runs/playbooks").json()}

        row = rows[SAMPLE]
        playbook = get_playbook(SAMPLE)
        assert row["suggested_schedule"] == playbook.suggested_schedule
        assert row["suggested_timezone"] == playbook.suggested_timezone
        assert row["data_capabilities"] == list(playbook.data_capabilities)
        assert row["variables"] == playbook.variables

    def test_get_one_includes_the_body_verbatim(self, client: TestClient) -> None:
        response = client.get(f"/scheduled-runs/playbooks/{SAMPLE}")

        assert response.status_code == 200
        assert response.json()["body"] == get_playbook(SAMPLE).body

    def test_get_unknown_slug_returns_404(self, client: TestClient) -> None:
        response = client.get("/scheduled-runs/playbooks/not-a-template")

        assert response.status_code == 404
        assert "not-a-template" in response.json()["detail"]

    def test_get_unsafe_slug_returns_400(self, client: TestClient) -> None:
        # Rejected by the shared path-param guard before any filesystem lookup.
        assert client.get("/scheduled-runs/playbooks/bad.slug").status_code == 400

    def test_user_directory_template_is_listed_and_readable(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        directory = tmp_path / "user-playbooks"
        directory.mkdir()
        (directory / "desk-open.md").write_text(
            "---\n"
            "name: Desk Open\n"
            "description: A user-authored template.\n"
            "suggested_schedule: '900000'\n"
            "data_capabilities:\n"
            "  - Recent daily bars for the desk's names\n"
            "---\n\nCheck the desk.\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("VIBE_TRADING_PLAYBOOK_DIR", str(directory))

        listed = {row["slug"] for row in client.get("/scheduled-runs/playbooks").json()}
        detail = client.get("/scheduled-runs/playbooks/desk-open")

        assert "desk-open" in listed
        assert detail.status_code == 200
        assert detail.json()["body"] == "Check the desk."


# ---------------------------------------------------------------------------
# REST — create from template
# ---------------------------------------------------------------------------


class TestRestCreate:
    def test_create_persists_the_rendered_body_unchanged(
        self, client: TestClient, rest_store: ScheduledResearchJobStore
    ) -> None:
        response = client.post(f"/scheduled-runs/playbooks/{SAMPLE}", json={})

        assert response.status_code == 201
        body = response.json()
        playbook = get_playbook(SAMPLE)
        # The decoupling contract: the natural-language body travels verbatim,
        # with no tool names spliced in by the entry layer.
        assert body["prompt"] == playbook.render()
        assert body["schedule"] == playbook.suggested_schedule
        assert body["timezone"] == playbook.suggested_timezone
        assert body["status"] == "pending"
        assert body["config"]["playbook"] == SAMPLE

        stored = rest_store.get(body["id"])
        assert stored is not None
        assert stored.prompt == playbook.render()

    def test_create_substitutes_declared_variables(self, client: TestClient) -> None:
        response = client.post(
            f"/scheduled-runs/playbooks/{SAMPLE}",
            json={"id": "tokyo-brief", "variables": {"home_market": "Japan equities"}},
        )

        assert response.status_code == 201
        prompt = response.json()["prompt"]
        assert "Japan equities" in prompt
        assert prompt == get_playbook(SAMPLE).render({"home_market": "Japan equities"})

    def test_create_rejects_undeclared_variable(
        self, client: TestClient, rest_store: ScheduledResearchJobStore
    ) -> None:
        response = client.post(
            f"/scheduled-runs/playbooks/{SAMPLE}",
            json={"id": "bad-var", "variables": {"not_a_variable": "x"}},
        )

        assert response.status_code == 422
        assert "not_a_variable" in response.json()["detail"]
        assert rest_store.list_jobs() == []

    def test_create_rejects_malformed_schedule(
        self, client: TestClient, rest_store: ScheduledResearchJobStore
    ) -> None:
        response = client.post(
            f"/scheduled-runs/playbooks/{SAMPLE}",
            json={"id": "bad-cron", "schedule": "0 99 * * *"},
        )

        assert response.status_code == 422
        assert "out of range" in response.json()["detail"]
        assert rest_store.list_jobs() == []

    def test_create_rejects_unresolvable_timezone(
        self, client: TestClient, rest_store: ScheduledResearchJobStore
    ) -> None:
        response = client.post(
            f"/scheduled-runs/playbooks/{SAMPLE}",
            json={"id": "bad-tz", "timezone": "Not/AZone"},
        )

        assert response.status_code == 422
        assert "IANA timezone" in response.json()["detail"]
        assert rest_store.list_jobs() == []

    def test_create_rejects_unsafe_job_id(
        self, client: TestClient, rest_store: ScheduledResearchJobStore
    ) -> None:
        # An id outside the safe pattern would persist but could never be
        # removed through DELETE /scheduled-runs/{job_id}.
        response = client.post(
            f"/scheduled-runs/playbooks/{SAMPLE}", json={"id": "../escape"}
        )

        assert response.status_code == 400
        assert rest_store.list_jobs() == []

    def test_create_unknown_slug_returns_404(
        self, client: TestClient, rest_store: ScheduledResearchJobStore
    ) -> None:
        response = client.post("/scheduled-runs/playbooks/not-a-template", json={})

        assert response.status_code == 404
        assert rest_store.list_jobs() == []

    def test_explicit_null_timezone_forces_utc_and_immediate_first_fire(
        self, client: TestClient
    ) -> None:
        import time

        before = int(time.time() * 1000)
        response = client.post(
            f"/scheduled-runs/playbooks/{SAMPLE}",
            json={"id": "utc-brief", "timezone": None},
        )
        after = int(time.time() * 1000)

        assert response.status_code == 201
        body = response.json()
        assert body["timezone"] is None
        assert before <= body["next_run_at"] <= after

    def test_suggested_timezone_defers_first_fire_to_an_authored_occurrence(
        self, client: TestClient
    ) -> None:
        import time

        after = int(time.time() * 1000)
        response = client.post(
            f"/scheduled-runs/playbooks/{SAMPLE}", json={"id": "tz-brief"}
        )

        assert response.status_code == 201
        body = response.json()
        assert body["timezone"] == get_playbook(SAMPLE).suggested_timezone
        # A weekday 08:30 cadence never fires at creation time.
        assert body["next_run_at"] > after

    def test_created_job_is_visible_through_the_plain_list_endpoint(
        self, client: TestClient
    ) -> None:
        client.post(f"/scheduled-runs/playbooks/{SAMPLE}", json={"id": "listed-brief"})

        rows = client.get("/scheduled-runs").json()

        assert "listed-brief" in {row["id"] for row in rows}


# ---------------------------------------------------------------------------
# REST — authentication
# ---------------------------------------------------------------------------


def _scheduled_routes_under_test() -> List[Any]:
    """Every mounted route whose path lives under ``/scheduled-runs``."""
    return [
        route
        for route in api_server.app.routes
        if getattr(route, "path", "").startswith("/scheduled-runs")
    ]


class TestRestAuth:
    def test_every_scheduled_route_declares_require_auth(self) -> None:
        """Structural guard: no route in this group may skip the dependency."""
        routes = _scheduled_routes_under_test()
        assert len(routes) >= 6  # 3 CRUD + 3 playbook routes

        for route in routes:
            calls = {dep.call for dep in route.dependant.dependencies}
            assert api_server.require_auth in calls, route.path

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/scheduled-runs/playbooks"),
            ("get", f"/scheduled-runs/playbooks/{SAMPLE}"),
            ("post", f"/scheduled-runs/playbooks/{SAMPLE}"),
        ],
    )
    def test_configured_key_rejects_uncredentialed_requests(
        self,
        method: str,
        path: str,
        rest_store: ScheduledResearchJobStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("API_AUTH_KEY", "secret")
        monkeypatch.setattr(api_server, "_API_KEY", "secret")
        keyed = TestClient(api_server.app)

        response = keyed.request(method.upper(), path, json={})

        assert response.status_code in {401, 403}
        assert rest_store.list_jobs() == []

    @pytest.mark.parametrize(
        ("method", "path", "expected"),
        [
            ("get", "/scheduled-runs/playbooks", 200),
            ("get", f"/scheduled-runs/playbooks/{SAMPLE}", 200),
            ("post", f"/scheduled-runs/playbooks/{SAMPLE}", 201),
        ],
    )
    def test_valid_bearer_is_accepted(
        self,
        method: str,
        path: str,
        expected: int,
        rest_store: ScheduledResearchJobStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("API_AUTH_KEY", "secret")
        monkeypatch.setattr(api_server, "_API_KEY", "secret")
        keyed = TestClient(api_server.app)

        response = keyed.request(
            method.upper(), path, json={}, headers={"Authorization": "Bearer secret"}
        )

        assert response.status_code == expected


# ---------------------------------------------------------------------------
# CLI subcommand
# ---------------------------------------------------------------------------


class TestCliSubcommand:
    def test_list_prints_every_slug(
        self, home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run_cli(["playbook", "list"])

        out = capsys.readouterr().out
        assert code == 0
        for slug in BUNDLED_SLUGS:
            assert slug in out

    def test_list_json_is_machine_readable(
        self, home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import json

        code = _run_cli(["playbook", "list", "--json"])

        rows = json.loads(capsys.readouterr().out)
        assert code == 0
        assert {row["slug"] for row in rows} >= BUNDLED_SLUGS

    def test_show_prints_the_body(
        self, home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run_cli(["playbook", "show", SAMPLE])

        out = capsys.readouterr().out
        assert code == 0
        assert "Pre-market brief" in out
        assert "Data gaps" in out

    def test_show_json_renders_variable_overrides(
        self, home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import json

        code = _run_cli(
            ["playbook", "show", SAMPLE, "--json", "--var", "home_market=Korea equities"]
        )

        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["body"] == get_playbook(SAMPLE).render(
            {"home_market": "Korea equities"}
        )

    def test_show_unknown_slug_fails(
        self, home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run_cli(["playbook", "show", "not-a-template"])

        assert code == 1
        assert "not-a-template" in capsys.readouterr().out

    def test_create_persists_a_job_with_the_verbatim_body(
        self, cli_store: ScheduledResearchJobStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run_cli(["playbook", "create", SAMPLE, "--id", "desk-brief"])
        capsys.readouterr()

        assert code == 0
        job = cli_store.get("desk-brief")
        assert job is not None
        assert job.prompt == get_playbook(SAMPLE).render()
        assert job.schedule == get_playbook(SAMPLE).suggested_schedule
        assert job.config["playbook"] == SAMPLE

    def test_create_applies_variables_and_schedule_override(
        self, cli_store: ScheduledResearchJobStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run_cli(
            [
                "playbook",
                "create",
                SAMPLE,
                "--id",
                "hourly-brief",
                "--schedule",
                "3600000",
                "--var",
                "watchlist=AAPL, MSFT",
            ]
        )
        capsys.readouterr()

        assert code == 0
        job = cli_store.get("hourly-brief")
        assert job is not None
        assert job.schedule == "3600000"
        assert "AAPL, MSFT" in job.prompt

    def test_create_utc_flag_drops_the_suggested_timezone(
        self, cli_store: ScheduledResearchJobStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run_cli(["playbook", "create", SAMPLE, "--id", "utc-brief", "--utc"])
        capsys.readouterr()

        assert code == 0
        job = cli_store.get("utc-brief")
        assert job is not None
        assert job.timezone is None

    def test_create_rejects_utc_together_with_timezone(
        self, cli_store: ScheduledResearchJobStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run_cli(
            ["playbook", "create", SAMPLE, "--utc", "--timezone", "Asia/Tokyo"]
        )

        assert code == 2
        assert "mutually exclusive" in capsys.readouterr().out
        assert cli_store.list_jobs() == []

    def test_create_rejects_malformed_schedule(
        self, cli_store: ScheduledResearchJobStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run_cli(["playbook", "create", SAMPLE, "--schedule", "0 99 * * *"])

        assert code == 1
        assert "out of range" in capsys.readouterr().out
        assert cli_store.list_jobs() == []

    def test_create_rejects_undeclared_variable(
        self, cli_store: ScheduledResearchJobStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run_cli(["playbook", "create", SAMPLE, "--var", "not_a_variable=x"])

        assert code == 1
        assert "not_a_variable" in capsys.readouterr().out
        assert cli_store.list_jobs() == []

    def test_create_unknown_slug_lists_what_is_available(
        self, cli_store: ScheduledResearchJobStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run_cli(["playbook", "create", "not-a-template"])

        out = capsys.readouterr().out
        assert code == 1
        assert "premarket-brief" in out
        assert cli_store.list_jobs() == []

    def test_dry_run_stores_nothing(
        self, cli_store: ScheduledResearchJobStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run_cli(["playbook", "create", SAMPLE, "--dry-run"])

        assert code == 0
        assert "Dry run" in capsys.readouterr().out
        assert cli_store.list_jobs() == []

    def test_bare_subcommand_prints_help_and_signals_usage_error(
        self, home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run_cli(["playbook"])

        assert code == 2
        assert "create" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Slash command
# ---------------------------------------------------------------------------


class TestSlashCommand:
    def test_registered_once_and_resolvable(self) -> None:
        names = [cmd.name for cmd in slash_router.SLASH_COMMANDS]

        assert names.count("playbook") == 1
        assert len(names) == len(set(names))
        command = slash_router.find_exact("/playbook")
        assert command is not None
        assert command.handler_module == "cli.commands.research_playbook"

    def test_registration_is_idempotent(self) -> None:
        before = slash_router.SLASH_COMMANDS
        slash_router._register_research_playbook_slash_command()

        assert slash_router.SLASH_COMMANDS == before

    def test_quit_stays_last(self) -> None:
        assert slash_router.SLASH_COMMANDS[-1].name == "quit"

    def test_typeahead_surfaces_it(self) -> None:
        matches = [cmd.name for cmd in slash_router.match_commands("/play")]

        assert "playbook" in matches

    def test_bare_command_lists_the_catalogue(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ctx = _Ctx()

        code = research_playbook.run(ctx)

        out = capsys.readouterr().out
        assert code == 0
        assert ctx.pending_prompt is None
        for slug in BUNDLED_SLUGS:
            assert slug in out

    def test_slug_alone_shows_the_card(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = research_playbook.run(_Ctx(), SAMPLE)

        out = capsys.readouterr().out
        assert code == 0
        assert "Pre-market Brief" in out
        assert "Data gaps" in out

    def test_run_queues_the_body_verbatim(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ctx = _Ctx()

        code = research_playbook.run(ctx, "run", SAMPLE)
        capsys.readouterr()

        assert code == 0
        # Byte-for-byte identical to what the scheduler would replay.
        assert ctx.pending_prompt == get_playbook(SAMPLE).render()

    def test_run_accepts_unquoted_multi_word_variables(self) -> None:
        ctx = _Ctx()

        research_playbook.run(ctx, "run", SAMPLE, "home_market=US", "equities")

        assert ctx.pending_prompt == get_playbook(SAMPLE).render(
            {"home_market": "US equities"}
        )

    def test_run_without_a_queueable_context_prints_the_prompt(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = research_playbook.run(_NoQueueCtx(), "run", SAMPLE)

        assert code == 0
        assert "paste this prompt" in capsys.readouterr().out

    def test_schedule_persists_a_job(
        self, cli_store: ScheduledResearchJobStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ctx = _Ctx()

        code = research_playbook.run(ctx, "schedule", SAMPLE)
        out = capsys.readouterr().out

        assert code == 0
        assert ctx.pending_prompt is None
        jobs = cli_store.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].prompt == get_playbook(SAMPLE).render()
        assert jobs[0].schedule == get_playbook(SAMPLE).suggested_schedule
        assert jobs[0].id in out

    def test_schedule_reports_a_bad_variable_without_storing(
        self, cli_store: ScheduledResearchJobStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = research_playbook.run(_Ctx(), "schedule", SAMPLE, "not_a_variable=x")

        assert code == 0  # a user mistake is answered, not raised
        assert "not_a_variable" in capsys.readouterr().out
        assert cli_store.list_jobs() == []

    def test_unknown_slug_lists_what_is_available(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ctx = _Ctx()

        code = research_playbook.run(ctx, "not-a-template")

        out = capsys.readouterr().out
        assert code == 0
        assert ctx.pending_prompt is None
        assert "premarket-brief" in out

    def test_missing_slug_is_answered_with_usage(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = research_playbook.run(_Ctx(), "run")

        out = capsys.readouterr().out
        assert code == 0
        assert "needs a template slug" in out

    def test_help_token_prints_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = research_playbook.run(_Ctx(), "help")

        assert code == 0
        assert "/playbook run" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Shared argument parsing
# ---------------------------------------------------------------------------


class TestVariableParsing:
    @pytest.mark.parametrize(
        ("tokens", "expected"),
        [
            ([], {}),
            (["a=1"], {"a": "1"}),
            (["a=1", "b=2"], {"a": "1", "b": "2"}),
            (["a=two", "words", "b=x"], {"a": "two words", "b": "x"}),
            (["a="], {"a": ""}),
            (["a=x", "a=y"], {"a": "y"}),
        ],
    )
    def test_accepted_forms(self, tokens: List[str], expected: dict) -> None:
        variables, error = research_playbook.parse_variable_tokens(tokens)

        assert error is None
        assert variables == expected

    def test_leading_bare_token_is_an_error(self) -> None:
        variables, error = research_playbook.parse_variable_tokens(["oops", "a=1"])

        assert variables == {}
        assert error is not None and "key=value" in error

    def test_variable_count_is_capped(self) -> None:
        tokens = [f"v{i}=1" for i in range(research_playbook._MAX_VARIABLES + 1)]

        variables, error = research_playbook.parse_variable_tokens(tokens)

        assert variables == {}
        assert error is not None and "too many" in error

    def test_option_form_requires_an_assignment(self) -> None:
        variables, error = research_playbook._parse_var_options(["nope"])

        assert variables == {}
        assert error is not None and "key=value" in error


# ---------------------------------------------------------------------------
# Cross-surface consistency
# ---------------------------------------------------------------------------


def test_all_three_surfaces_produce_the_same_prompt(
    client: TestClient,
    cli_store: ScheduledResearchJobStore,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """REST, CLI and slash must schedule byte-identical instruction text."""
    variables = {"home_market": "Hong Kong equities"}

    rest_prompt = client.post(
        f"/scheduled-runs/playbooks/{SAMPLE}",
        json={"id": "cross-rest", "variables": variables},
    ).json()["prompt"]

    _run_cli(
        ["playbook", "create", SAMPLE, "--id", "cross-cli", "--var", "home_market=Hong Kong equities"]
    )
    cli_job = cli_store.get("cross-cli")

    ctx = _Ctx()
    research_playbook.run(ctx, "run", SAMPLE, "home_market=Hong", "Kong", "equities")
    capsys.readouterr()

    assert cli_job is not None
    assert rest_prompt == cli_job.prompt == ctx.pending_prompt
    assert rest_prompt == get_playbook(SAMPLE).render(variables)


def test_catalogue_size_matches_the_loader(client: TestClient) -> None:
    """The REST catalogue is the loader's output, not a hand-maintained list."""
    rows = client.get("/scheduled-runs/playbooks").json()

    assert [row["slug"] for row in rows] == [pb.slug for pb in list_playbooks()]
