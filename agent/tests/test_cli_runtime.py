"""Tests for the live-runtime CLI surface + discoverability (parcel R7).

Covers SPEC.md §7.5 (persistent runner control) + §9 Decision 1 (CLI surface
table) + the §9 audit discoverability fix:

* ``live run`` / ``live start`` / ``live stop`` dispatch to their handlers and
  relay to the R6 surface endpoints (``POST /live/runner/start|stop``).
* ``live status`` surfaces runner liveness + last-tick from the liveness
  contract (``src.live.runtime.liveness``), degrading cleanly when the runtime
  module is not yet present.
* The slash registry / ``/help`` / typeahead completer now include
  ``live`` / ``halt`` / ``resume`` (previously undiscoverable surface actions),
  and ``/stop`` resolves as the kill-switch alias of ``/halt``.
* The REPL intercepts ``/resume`` (clear halt) and ``/live ...`` (bridge to the
  live subcommand group) in the input path — neither is dispatched to the model.

The API client is stubbed (``httpx``) and the liveness module is injected into
``sys.modules`` so no server / concurrent runtime parcel is needed.
"""

from __future__ import annotations

import importlib
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

import src.live.paths as live_paths

# ``cli/__init__.py`` re-exports ``main`` as a function, shadowing the submodule
# for attribute access; import the module object directly (mirrors test_cli_live).
main = importlib.import_module("cli.main")
InteractiveContext = main.InteractiveContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def live_root(tmp_path: Path):
    """Redirect the live-channel runtime root to a tmp dir for the test."""
    with patch.object(live_paths, "get_runtime_root", return_value=tmp_path):
        yield tmp_path


@pytest.fixture()
def fake_liveness():
    """Inject a stub ``src.live.runtime.liveness`` module (R1 lands concurrently).

    Yields a dict the test can mutate to control ``is_runner_alive`` /
    ``last_tick`` return values. The real module is restored on teardown.
    """
    state: Dict[str, Any] = {"alive": True, "tick": datetime.now(timezone.utc)}
    mod = types.ModuleType("src.live.runtime.liveness")
    mod.is_runner_alive = lambda runner_id: bool(state["alive"])  # type: ignore[attr-defined]
    mod.last_tick = lambda runner_id: state["tick"]  # type: ignore[attr-defined]

    saved = sys.modules.get("src.live.runtime.liveness")
    sys.modules["src.live.runtime.liveness"] = mod
    try:
        yield state
    finally:
        if saved is not None:
            sys.modules["src.live.runtime.liveness"] = saved
        else:
            sys.modules.pop("src.live.runtime.liveness", None)


@pytest.fixture()
def no_liveness():
    """Force ``src.live.runtime.liveness`` import to fail (module absent)."""
    saved = sys.modules.get("src.live.runtime.liveness")
    sys.modules["src.live.runtime.liveness"] = None  # type: ignore[assignment]
    try:
        yield
    finally:
        if saved is not None:
            sys.modules["src.live.runtime.liveness"] = saved
        else:
            sys.modules.pop("src.live.runtime.liveness", None)


class _FakeResp:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Dict[str, Any]:
        return self._payload


# ---------------------------------------------------------------------------
# Subcommand dispatch (run / start / stop) — argparse + _dispatch_live
# ---------------------------------------------------------------------------


class TestRunnerDispatch:
    def _dispatch(self, argv: List[str]) -> int:
        from cli._legacy import _build_parser, _dispatch_live

        args = _build_parser().parse_args(argv)
        return _dispatch_live(args)

    def test_run_routes_to_handler(self) -> None:
        with patch("cli._legacy.cmd_live_run", return_value=0) as m:
            assert self._dispatch(["live", "run", "robinhood"]) == 0
        m.assert_called_once_with("robinhood")

    def test_run_default_broker_none(self) -> None:
        with patch("cli._legacy.cmd_live_run", return_value=0) as m:
            self._dispatch(["live", "run"])
        m.assert_called_once_with(None)

    def test_start_routes_to_handler(self) -> None:
        with patch("cli._legacy.cmd_live_start", return_value=0) as m:
            self._dispatch(["live", "start", "robinhood"])
        m.assert_called_once_with("robinhood")

    def test_stop_routes_to_handler(self) -> None:
        with patch("cli._legacy.cmd_live_stop", return_value=0) as m:
            self._dispatch(["live", "stop"])
        m.assert_called_once_with(None)

    def test_subparsers_registered(self) -> None:
        """run/start/stop parse without error (the parser knows them)."""
        from cli._legacy import _build_parser

        parser = _build_parser()
        for verb in ("run", "start", "stop"):
            parsed = parser.parse_args(["live", verb])
            assert parsed.live_command == verb


# ---------------------------------------------------------------------------
# Runner control relays to the R6 surface endpoints
# ---------------------------------------------------------------------------


class TestRunnerControlEndpoints:
    def test_start_posts_to_runner_start(self) -> None:
        from cli._legacy import EXIT_SUCCESS, cmd_live_start

        captured: Dict[str, Any] = {}

        def _post(url: str, json: Dict[str, Any], timeout: float) -> _FakeResp:  # noqa: A002
            captured["url"] = url
            captured["body"] = json
            return _FakeResp({"runner_id": "live-robinhood", "status": "started"})

        with patch("httpx.post", _post):
            assert cmd_live_start("robinhood") == EXIT_SUCCESS
        assert captured["url"].endswith("/live/runner/start")
        assert captured["body"]["broker"] == "robinhood"
        assert captured["body"]["foreground"] is False

    def test_stop_posts_to_runner_stop(self) -> None:
        from cli._legacy import EXIT_SUCCESS, cmd_live_stop

        captured: Dict[str, Any] = {}

        def _post(url: str, json: Dict[str, Any], timeout: float) -> _FakeResp:  # noqa: A002
            captured["url"] = url
            captured["body"] = json
            return _FakeResp({"status": "stopped"})

        with patch("httpx.post", _post):
            assert cmd_live_stop("robinhood") == EXIT_SUCCESS
        assert captured["url"].endswith("/live/runner/stop")
        assert captured["body"]["broker"] == "robinhood"

    def test_start_server_unreachable_is_run_failed(self) -> None:
        from cli._legacy import EXIT_RUN_FAILED, cmd_live_start

        def _boom(url: str, json: Dict[str, Any], timeout: float) -> _FakeResp:  # noqa: A002
            raise OSError("connection refused")

        with patch("httpx.post", _boom):
            assert cmd_live_start("robinhood") == EXIT_RUN_FAILED

    def test_run_foreground_starts_then_stops(self, fake_liveness: Dict[str, Any]) -> None:
        """`live run` relays a foreground start, tails liveness, then stops."""
        from cli._legacy import EXIT_SUCCESS, cmd_live_run

        calls: List[str] = []

        def _post(url: str, json: Dict[str, Any], timeout: float) -> _FakeResp:  # noqa: A002
            calls.append(url)
            if url.endswith("/live/runner/start"):
                assert json["foreground"] is True
                # Make the tail loop exit immediately: runner reports stopped.
                fake_liveness["alive"] = False
            return _FakeResp({"runner_id": "live-robinhood", "status": "ok"})

        import cli._legacy as legacy

        # _legacy uses its own ``time`` import; patch that one so the tail loop
        # does not actually sleep.
        with patch("httpx.post", _post), patch.object(legacy.time, "sleep", lambda *_: None):
            assert cmd_live_run("robinhood") == EXIT_SUCCESS

        assert any(u.endswith("/live/runner/start") for u in calls)
        assert any(u.endswith("/live/runner/stop") for u in calls)


# ---------------------------------------------------------------------------
# live status surfaces runner liveness
# ---------------------------------------------------------------------------


class TestStatusLiveness:
    def test_status_shows_running(
        self, live_root: Path, fake_liveness: Dict[str, Any], capsys: pytest.CaptureFixture[str]
    ) -> None:
        from cli._legacy import cmd_live_status

        fake_liveness["alive"] = True
        fake_liveness["tick"] = datetime.now(timezone.utc) - timedelta(seconds=5)
        assert cmd_live_status("robinhood") == 0
        out = capsys.readouterr().out
        assert "Runner" in out
        assert "running" in out
        assert "ago" in out  # last-tick relative time rendered

    def test_status_shows_stopped(
        self, live_root: Path, fake_liveness: Dict[str, Any], capsys: pytest.CaptureFixture[str]
    ) -> None:
        from cli._legacy import cmd_live_status

        fake_liveness["alive"] = False
        cmd_live_status("robinhood")
        out = capsys.readouterr().out
        assert "stopped" in out

    def test_status_degrades_when_liveness_absent(
        self, live_root: Path, no_liveness: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Status must not crash if the runtime parcel hasn't landed yet."""
        from cli._legacy import cmd_live_status

        assert cmd_live_status("robinhood") == 0
        out = capsys.readouterr().out
        assert "Runner" in out
        assert "unknown" in out


# ---------------------------------------------------------------------------
# Discoverability: registry + help + completer now include live/halt/resume
# ---------------------------------------------------------------------------


class TestSlashDiscoverability:
    def test_registry_includes_live_group(self) -> None:
        from cli.commands.slash_router import SLASH_COMMANDS

        names = {c.name for c in SLASH_COMMANDS}
        assert {"live", "halt", "resume"} <= names

    def test_find_exact_resolves_new_commands(self) -> None:
        from cli.commands.slash_router import find_exact

        for name in ("live", "halt", "resume"):
            assert find_exact(name) is not None

    def test_stop_is_alias_of_halt(self) -> None:
        from cli.commands.slash_router import find_exact

        cmd = find_exact("stop")
        assert cmd is not None
        assert cmd.name == "halt"

    def test_match_commands_surfaces_in_typeahead(self) -> None:
        """The completer ranks via match_commands — the live group must appear."""
        from cli.commands.slash_router import match_commands

        names = {c.name for c in match_commands("/ha")}
        assert "halt" in names
        names = {c.name for c in match_commands("/li")}
        assert "live" in names

    def test_completer_yields_live_group(self) -> None:
        from prompt_toolkit.document import Document

        from cli.completer import SlashCompleter

        comp = SlashCompleter()
        completions = list(
            comp.get_completions(Document("/", cursor_position=1), complete_event=None)
        )
        texts = {c.text for c in completions}
        assert {"live", "halt", "resume"} <= texts

    def test_help_lists_live_group(self, capsys: pytest.CaptureFixture[str]) -> None:
        """``/help`` renders the registry — the live group must be present."""
        from cli.commands import help as help_cmd

        # help.py binds SLASH_COMMANDS at import; our registration runs at
        # cli.main import (already done above) so the bound tuple includes them.
        assert {"live", "halt", "resume"} <= {c.name for c in help_cmd.SLASH_COMMANDS}
        help_cmd.run(None)
        out = capsys.readouterr().out
        assert "/live" in out
        assert "/halt" in out
        assert "/resume" in out

    def test_registration_is_idempotent(self) -> None:
        from cli.commands.slash_router import SLASH_COMMANDS

        before = len(SLASH_COMMANDS)
        main._register_live_slash_commands()
        from cli.commands.slash_router import SLASH_COMMANDS as after_tuple

        assert len(after_tuple) == before  # no duplicate rows


# ---------------------------------------------------------------------------
# REPL intercepts: /resume clears halt, /live bridges to the subcommand group
# ---------------------------------------------------------------------------


class TestReplResumeIntercept:
    def test_resume_clears_halt(self, live_root: Path) -> None:
        from src.live.halt import halt_flag_set, trip_halt

        trip_halt(by="cli", reason="test")
        assert halt_flag_set("robinhood") is True

        console = main.get_console()
        main._clear_halt_from_repl(console)
        assert halt_flag_set("robinhood") is False

    def test_resume_when_not_halted_is_clean(
        self, live_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        console = main.get_console()
        main._clear_halt_from_repl(console)  # must not raise
        assert "No active global halt" in capsys.readouterr().out


class TestReplLiveBridge:
    def test_live_bridges_to_dispatch_live(self) -> None:
        console = main.get_console()
        with patch("cli._legacy._dispatch_live", return_value=0) as disp:
            main._run_live_command_from_repl(console, ["status", "robinhood"])
        disp.assert_called_once()
        parsed = disp.call_args.args[0]
        assert parsed.live_command == "status"
        assert parsed.live_broker == "robinhood"

    def test_bare_live_defaults_to_status(self) -> None:
        console = main.get_console()
        with patch("cli._legacy._dispatch_live", return_value=0) as disp:
            main._run_live_command_from_repl(console, [])
        parsed = disp.call_args.args[0]
        assert parsed.live_command == "status"

    def test_live_run_bridges_to_run_handler(self) -> None:
        console = main.get_console()
        with patch("cli._legacy.cmd_live_run", return_value=0) as run:
            main._run_live_command_from_repl(console, ["run"])
        run.assert_called_once_with(None)

    def test_invalid_live_subcommand_keeps_loop_alive(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        console = main.get_console()
        # Unknown subcommand → argparse SystemExit, caught, usage printed.
        main._run_live_command_from_repl(console, ["frobnicate"])
        assert "Usage: /live" in capsys.readouterr().out
