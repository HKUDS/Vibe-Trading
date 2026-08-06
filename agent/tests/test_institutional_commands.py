"""Tests for the institutional research workflow slash commands.

Covers the four things that can silently break:

1. Registration — all six commands reach ``SLASH_COMMANDS``, without
   duplicating or displacing anything already there, and idempotently.
2. Aliases — never shadow an existing command, never steal a key another
   alias already owns.
3. Argument handling — a missing argument produces the playbook card and a
   follow-up question (exit code 0, nothing queued), while a supplied
   argument queues a prompt carrying the skeleton, the worked example, the
   missing-data policy and the not-advice notice.
4. Playbook data integrity — every tool name referenced by a playbook is a
   real registered tool (checked against the ``src/tools`` sources rather
   than against any document), and the two worked examples that claim to
   reconcile actually do when recomputed from first principles.

No network is touched anywhere in this module.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

import pytest

from cli.commands import slash_router
from cli.commands.institutional import runner
from cli.commands.institutional.playbooks import (
    GAP_POLICY,
    NOT_ADVICE,
    PLAYBOOKS,
    PLAYBOOKS_BY_SLUG,
)

_SLUGS = ("comps", "dcf", "attrib", "memo", "earnings", "screen")

_AGENT_DIR = Path(__file__).resolve().parent.parent


class _Ctx:
    """Minimal stand-in for ``cli.main.InteractiveContext``."""

    def __init__(self) -> None:
        self.pending_prompt: str | None = None


class _NoQueueCtx:
    """A context that cannot hold a queued prompt (legacy / stub caller)."""


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_all_six_commands_are_registered(self) -> None:
        names = {cmd.name for cmd in slash_router.SLASH_COMMANDS}
        assert set(_SLUGS) <= names

    def test_registry_has_no_duplicate_names(self) -> None:
        names = [cmd.name for cmd in slash_router.SLASH_COMMANDS]
        assert len(names) == len(set(names))

    def test_pre_existing_commands_survive(self) -> None:
        """Appending must not displace or rewrite the base registry."""
        names = {cmd.name for cmd in slash_router.SLASH_COMMANDS}
        assert {"help", "model", "memory", "history", "goal", "quit"} <= names

    def test_quit_stays_last(self) -> None:
        assert slash_router.SLASH_COMMANDS[-1].name == "quit"

    def test_registration_is_idempotent(self) -> None:
        before = list(slash_router.SLASH_COMMANDS)
        before_aliases = dict(slash_router._ALIASES)
        slash_router._register_institutional_slash_commands()
        assert list(slash_router.SLASH_COMMANDS) == before
        assert dict(slash_router._ALIASES) == before_aliases

    def test_registration_skips_names_already_taken(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A pre-existing ``/memo`` must win; we never overwrite it."""
        squatter = slash_router.Command("memo", "someone else's memo", "cli.commands.help")
        base = tuple(
            cmd for cmd in slash_router.SLASH_COMMANDS if cmd.name not in _SLUGS
        )
        monkeypatch.setattr(slash_router, "SLASH_COMMANDS", base + (squatter,))
        slash_router._register_institutional_slash_commands()
        memo_rows = [c for c in slash_router.SLASH_COMMANDS if c.name == "memo"]
        assert len(memo_rows) == 1
        assert memo_rows[0].handler_module == "cli.commands.help"

    def test_descriptions_are_one_line_and_non_empty(self) -> None:
        for cmd in slash_router.SLASH_COMMANDS:
            if cmd.name in _SLUGS:
                assert cmd.description.strip()
                assert "\n" not in cmd.description
                assert len(cmd.description) <= 70


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------


class TestAliases:
    def test_declared_aliases_resolve(self) -> None:
        for alias, expected in (("peers", "comps"), ("attribution", "attrib"), ("screener", "screen")):
            cmd = slash_router.find_exact(alias)
            assert cmd is not None, alias
            assert cmd.name == expected

    def test_no_alias_shadows_a_command_name(self) -> None:
        names = {cmd.name for cmd in slash_router.SLASH_COMMANDS}
        assert not (set(slash_router._ALIASES) & names)

    def test_alias_targets_all_exist(self) -> None:
        names = {cmd.name for cmd in slash_router.SLASH_COMMANDS}
        for alias, target in slash_router._ALIASES.items():
            assert target in names, f"{alias} -> {target}"

    def test_pre_existing_aliases_untouched(self) -> None:
        for alias, target in (("q", "quit"), ("exit", "quit"), (":q", "quit"), ("?", "help")):
            assert slash_router._ALIASES[alias] == target

    def test_registration_does_not_steal_a_claimed_alias(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            slash_router, "_ALIASES", {**slash_router._ALIASES, "peers": "help"}
        )
        slash_router._register_institutional_slash_commands()
        assert slash_router._ALIASES["peers"] == "help"


# ---------------------------------------------------------------------------
# Discoverability: /help + typeahead
# ---------------------------------------------------------------------------


class TestDiscoverability:
    def test_help_module_sees_the_commands(self) -> None:
        from cli.commands import help as help_cmd

        assert set(_SLUGS) <= {c.name for c in help_cmd.SLASH_COMMANDS}

    def test_help_renders_them(self, capsys: pytest.CaptureFixture[str]) -> None:
        from cli.commands import help as help_cmd

        help_cmd.run(None)
        out = capsys.readouterr().out
        for slug in _SLUGS:
            assert f"/{slug}" in out

    def test_match_commands_surfaces_them(self) -> None:
        assert "comps" in {c.name for c in slash_router.match_commands("/comp")}
        assert "dcf" in {c.name for c in slash_router.match_commands("/dc")}
        assert "earnings" in {c.name for c in slash_router.match_commands("/earn")}

    def test_bare_slash_lists_them(self) -> None:
        names = {c.name for c in slash_router.match_commands("/")}
        assert set(_SLUGS) <= names

    def test_completer_yields_them(self) -> None:
        from prompt_toolkit.document import Document

        from cli.completer import SlashCompleter

        completions = list(
            SlashCompleter().get_completions(
                Document("/", cursor_position=1), complete_event=None
            )
        )
        assert set(_SLUGS) <= {c.text for c in completions}


# ---------------------------------------------------------------------------
# Handler modules
# ---------------------------------------------------------------------------


class TestHandlerModules:
    def test_handler_modules_import_and_expose_run(self) -> None:
        for slug in _SLUGS:
            module = importlib.import_module(f"cli.commands.institutional.{slug}")
            assert callable(module.run)

    def test_registry_points_at_the_right_modules(self) -> None:
        for cmd in slash_router.SLASH_COMMANDS:
            if cmd.name in _SLUGS:
                assert cmd.handler_module == f"cli.commands.institutional.{cmd.name}"

    def test_handlers_are_single_command_modules(self) -> None:
        """``cli.main`` only passes the keyword to modules it lists as multi-command.

        These are not listed, so ``run`` must take ``(ctx, *args)`` — if that
        ever changed the dispatcher would silently feed the keyword in as the
        first argument.
        """
        main = importlib.import_module("cli.main")

        for slug in _SLUGS:
            assert f"cli.commands.institutional.{slug}" not in main._MULTI_COMMAND_MODULES


# ---------------------------------------------------------------------------
# Argument handling
# ---------------------------------------------------------------------------


class TestArgumentHandling:
    @pytest.mark.parametrize("slug", _SLUGS)
    def test_missing_args_prints_the_card_and_asks(
        self, slug: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ctx = _Ctx()
        module = importlib.import_module(f"cli.commands.institutional.{slug}")
        assert module.run(ctx) == 0
        assert ctx.pending_prompt is None  # nothing dispatched to the model
        out = capsys.readouterr().out
        assert "Execution skeleton" in out
        assert "Worked example" in out
        # The friendly follow-up question, not a usage error.
        assert "?" in out
        assert "Error" not in out
        assert "Usage:" not in out

    @pytest.mark.parametrize("token", ["help", "--help", "-h", "?"])
    def test_help_token_prints_the_card_without_queueing(
        self, token: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ctx = _Ctx()
        from cli.commands.institutional import dcf

        assert dcf.run(ctx, token, "AAPL") == 0
        assert ctx.pending_prompt is None
        assert "Execution skeleton" in capsys.readouterr().out

    @pytest.mark.parametrize("slug", _SLUGS)
    def test_args_queue_a_prompt(self, slug: str) -> None:
        ctx = _Ctx()
        module = importlib.import_module(f"cli.commands.institutional.{slug}")
        assert module.run(ctx, "AAPL", "MSFT") == 0
        prompt = ctx.pending_prompt
        assert prompt is not None
        assert "AAPL MSFT" in prompt
        assert slug.upper() in prompt
        # Skeleton, worked example, gap policy and disclaimer all travel along.
        playbook = PLAYBOOKS_BY_SLUG[slug]
        for index, step in enumerate(playbook.steps, start=1):
            assert f"Step {index} — {step.title}" in prompt
        assert GAP_POLICY[0] in prompt
        assert NOT_ADVICE in prompt
        assert playbook.worked_example[0] in prompt

    def test_long_argument_is_truncated(self) -> None:
        ctx = _Ctx()
        from cli.commands.institutional import screen

        assert screen.run(ctx, "x" * 5000) == 0
        assert ctx.pending_prompt is not None
        assert "…(truncated)" in ctx.pending_prompt
        # The cap bounds the user's argument, not the (fixed-size) skeleton.
        request = next(
            line for line in ctx.pending_prompt.splitlines() if line.startswith("Request: ")
        )
        assert len(request) < runner._ARG_MAX_CHARS + 40
        assert request.count("x") == runner._ARG_MAX_CHARS

    def test_falls_back_to_printing_when_context_cannot_queue(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from cli.commands.institutional import comps

        assert comps.run(_NoQueueCtx(), "AAPL") == 0
        out = capsys.readouterr().out
        assert "paste this prompt" in out
        assert "Step 1" in out

    def test_none_context_does_not_raise(self, capsys: pytest.CaptureFixture[str]) -> None:
        from cli.commands.institutional import memo

        assert memo.run(None, "NVDA") == 0
        assert "paste this prompt" in capsys.readouterr().out

    def test_unknown_slug_is_reported_not_raised(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert runner.run_playbook("not-a-playbook", _Ctx()) == 1
        assert "Unknown research playbook" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# End-to-end through the real REPL dispatcher
# ---------------------------------------------------------------------------


class TestReplDispatch:
    def test_dispatch_slash_queues_the_prompt(self) -> None:
        main = importlib.import_module("cli.main")
        ctx = main.InteractiveContext()
        assert main._dispatch_slash("/dcf MSFT horizon=5", ctx) == 0
        assert ctx.pending_prompt is not None
        assert "Run the DCF research playbook." in ctx.pending_prompt
        assert "MSFT horizon=5" in ctx.pending_prompt

    def test_dispatch_slash_resolves_an_alias(self) -> None:
        main = importlib.import_module("cli.main")
        ctx = main.InteractiveContext()
        assert main._dispatch_slash("/peers AAPL", ctx) == 0
        assert ctx.pending_prompt is not None
        assert "Run the COMPS research playbook." in ctx.pending_prompt

    def test_bare_command_does_not_start_a_turn(self) -> None:
        main = importlib.import_module("cli.main")
        ctx = main.InteractiveContext()
        assert main._dispatch_slash("/memo", ctx) == 0
        assert ctx.pending_prompt is None


# ---------------------------------------------------------------------------
# Playbook data integrity
# ---------------------------------------------------------------------------


def _registered_tool_names() -> set[str]:
    """Scrape the tool ``name`` class attributes straight from ``src/tools``.

    Reads the sources instead of importing the registry so the check needs no
    optional dependency and no network, and instead of trusting any document.
    """
    pattern = re.compile(r"^\s{4}name(?:\s*:\s*str)?\s*=\s*[\"']([a-z0-9_]+)[\"']", re.M)
    found: set[str] = set()
    for path in (_AGENT_DIR / "src" / "tools").rglob("*.py"):
        found.update(pattern.findall(path.read_text(encoding="utf-8")))
    return found


class TestPlaybookData:
    def test_slugs_are_unique_and_lowercase(self) -> None:
        slugs = [pb.slug for pb in PLAYBOOKS]
        assert len(slugs) == len(set(slugs))
        assert all(s.islower() and s.isalpha() for s in slugs)

    def test_every_playbook_has_a_full_skeleton(self) -> None:
        for pb in PLAYBOOKS:
            assert len(pb.steps) >= 5, pb.slug
            for step in pb.steps:
                assert step.title.strip() and step.inputs.strip()
                assert step.compute.strip() and step.output.strip()

    def test_every_playbook_has_a_numeric_worked_example(self) -> None:
        for pb in PLAYBOOKS:
            assert len(pb.worked_example) >= 8, pb.slug
            digits = sum(ch.isdigit() for line in pb.worked_example for ch in line)
            assert digits >= 40, pb.slug

    def test_every_playbook_asks_a_question_when_args_are_missing(self) -> None:
        for pb in PLAYBOOKS:
            assert pb.ask.strip().endswith(("?", "?)")) or "?" in pb.ask, pb.slug
            assert pb.examples

    def test_referenced_tools_are_real(self) -> None:
        registered = _registered_tool_names()
        assert "get_financial_statements" in registered  # scraper sanity check
        for pb in PLAYBOOKS:
            for tool in pb.tools:
                assert tool in registered, f"{pb.slug} references unknown tool {tool}"

    def test_referenced_tools_are_real_live_classes(self) -> None:
        """Re-check the names against the LIVE tool classes, not the sources.

        The regex scraper above proves a string exists in ``src/tools``; it
        cannot prove the class is actually discovered. Anchor on the same
        discovery pass ``build_registry`` uses so a tool that stops being
        discovered fails here.
        """
        from src.tools import _discover_subclasses

        discovered = {cls.name for cls in _discover_subclasses()}
        for pb in PLAYBOOKS:
            for tool in pb.tools:
                assert tool in discovered, f"{pb.slug} references undiscovered tool {tool}"

    def test_key_gated_tools_are_covered_by_the_unavailable_tool_clause(self) -> None:
        """Some preferred tools are absent unless a key is configured.

        ``get_macro_series`` needs ``FRED_API_KEY`` and ``iwencai_search`` needs
        ``VIBE_TRADING_IWENCAI_KEY``; ``build_registry`` drops them via
        ``check_available()`` otherwise. The prompt must therefore tell the agent
        what to do when a preferred tool is missing, or the gap-filling ban has a
        hole exactly where the data is hardest to get.
        """
        from src.tools import _discover_subclasses

        by_name = {cls.name: cls for cls in _discover_subclasses()}
        gated = {
            tool
            for pb in PLAYBOOKS
            for tool in pb.tools
            if not by_name[tool].check_available()
        }
        if not gated:  # every key happens to be configured in this environment
            pytest.skip("no key-gated tool referenced in this environment")
        for pb in PLAYBOOKS:
            prompt = runner.build_prompt(pb, "SUBJ")
            assert "not registered in this session" in prompt
            assert "never fill that gap from memory" in prompt

    def test_earnings_bridge_reconciles(self) -> None:
        """Recompute the ``/earnings`` walkthrough; the steps must sum to the delta.

        Guards the documented arithmetic from rotting: consensus EPS 1.35 ->
        actual EPS 1.4911, walked one variable at a time.
        """

        def eps(revenue: float, gm: float, opex: float, tax: float, shares: float) -> float:
            pbt = revenue * gm - opex - 20.0
            return pbt * (1 - tax) / shares

        base = eps(1000.0, 0.600, 400.0, 0.25, 100.0)
        after_rev = eps(1050.0, 0.600, 400.0, 0.25, 100.0)
        after_gm = eps(1050.0, 0.585, 400.0, 0.25, 100.0)
        after_opex = eps(1050.0, 0.585, 405.0, 0.25, 100.0)
        after_tax = eps(1050.0, 0.585, 405.0, 0.22, 100.0)
        final = eps(1050.0, 0.585, 405.0, 0.22, 99.0)

        assert round(base, 4) == 1.3500
        assert round(final, 4) == 1.4911
        steps = [
            after_rev - base,
            after_gm - after_rev,
            after_opex - after_gm,
            after_tax - after_opex,
            final - after_tax,
        ]
        assert [round(s, 4) for s in steps] == [0.2250, -0.1181, -0.0375, 0.0568, 0.0149]
        assert round(sum(steps), 4) == round(final - base, 4) == 0.1411
        # Operating vs non-operating split quoted in the walkthrough.
        assert round(sum(steps[:3]), 4) == 0.0694
        assert round(sum(steps[3:]), 4) == 0.0717

        text = "\n".join(PLAYBOOKS_BY_SLUG["earnings"].worked_example)
        for token in ("1.4911", "+0.1411", "+0.0694", "+0.0717"):
            assert token in text

    def test_brinson_decomposition_reconciles(self) -> None:
        """Recompute the ``/attrib`` walkthrough; A + S + I must equal active return."""
        sectors = (
            # (wp, Rp, wb, Rb)
            (0.60, 12.0, 0.50, 10.0),
            (0.30, 3.0, 0.30, 4.0),
            (0.10, -1.0, 0.20, -2.0),
        )
        rp = sum(wp * r for wp, r, _wb, _rb in sectors)
        rb = sum(wb * r for _wp, _rp, wb, r in sectors)
        assert round(rp, 2) == 8.00
        assert round(rb, 2) == 5.80

        allocation = sum((wp - wb) * (rb_i - rb) for wp, _rp, wb, rb_i in sectors)
        selection = sum(wb * (rp_i - rb_i) for _wp, rp_i, wb, rb_i in sectors)
        interaction = sum((wp - wb) * (rp_i - rb_i) for wp, rp_i, wb, rb_i in sectors)
        assert round(allocation, 3) == 1.200
        assert round(selection, 3) == 0.900
        assert round(interaction, 3) == 0.100
        assert round(allocation + selection + interaction, 3) == round(rp - rb, 3) == 2.200

        text = "\n".join(PLAYBOOKS_BY_SLUG["attrib"].worked_example)
        for token in ("+1.200", "+0.900", "+0.100", "= 2.200 = active"):
            assert token in text

    def test_comps_worked_example_reconciles(self) -> None:
        """Recompute the ``/comps`` percentile ladder and implied per-share range."""
        peers = [8.00, 9.20, 10.40, 11.60]

        def percentile(values: list[float], q: float) -> float:
            pos = (len(values) - 1) * q
            low = int(pos)
            high = min(low + 1, len(values) - 1)
            return values[low] + (pos - low) * (values[high] - values[low])

        assert round(percentile(peers, 0.25), 2) == 8.90
        assert round(percentile(peers, 0.50), 2) == 9.80
        assert round(percentile(peers, 0.75), 2) == 10.70

        ebitda, net_debt, shares, price = 800.0, 500.0, 250.0, 22.00
        assert round((5500.0 + 900.0 - 400.0) / ebitda, 2) == 7.50
        implied = [
            round((percentile(peers, q) * ebitda - net_debt) / shares, 2)
            for q in (0.25, 0.50, 0.75)
        ]
        assert implied == [26.48, 29.36, 32.24]
        assert round(7.50 / 9.80 - 1, 3) == -0.235
        assert round(29.36 / price - 1, 3) == 0.335

        text = "\n".join(PLAYBOOKS_BY_SLUG["comps"].worked_example)
        for token in ("7.50x", "9.80x", "26.48", "29.36", "32.24", "-23.5%", "+33.5%"):
            assert token in text


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


class TestPromptConstruction:
    @pytest.mark.parametrize("slug", _SLUGS)
    def test_prompt_is_self_contained(self, slug: str) -> None:
        prompt = runner.build_prompt(PLAYBOOKS_BY_SLUG[slug], "TEST-SUBJECT")
        assert "TEST-SUBJECT" in prompt
        assert "Do not skip a step" in prompt
        assert "Preferred tools:" in prompt
        assert NOT_ADVICE in prompt
        for line in GAP_POLICY:
            assert line in prompt

    def test_prompt_flags_the_example_as_illustrative(self) -> None:
        prompt = runner.build_prompt(PLAYBOOKS_BY_SLUG["dcf"], "MSFT")
        assert "illustrative teaching" in prompt
        assert "must not be reused as facts" in prompt

    def test_arg_cap_is_env_configurable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VIBE_TRADING_SLASH_ARG_MAX", "40")
        reloaded: Any = importlib.reload(runner)
        try:
            assert reloaded._ARG_MAX_CHARS == 40
            ctx = _Ctx()
            assert reloaded.run_playbook("comps", ctx, "y" * 200) == 0
            assert "…(truncated)" in (ctx.pending_prompt or "")
        finally:
            monkeypatch.delenv("VIBE_TRADING_SLASH_ARG_MAX", raising=False)
            importlib.reload(runner)

    def test_malformed_arg_cap_falls_back_instead_of_killing_the_repl(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A junk override must not raise at import time.

        ``cli.main._dispatch_slash`` guards ``import_module`` with
        ``except ImportError`` only, so a ``ValueError`` from this module's body
        escapes the dispatcher and terminates the interactive loop.
        """
        monkeypatch.setenv("VIBE_TRADING_SLASH_ARG_MAX", "not-a-number")
        try:
            reloaded: Any = importlib.reload(runner)
            assert reloaded._ARG_MAX_CHARS == 600
        finally:
            monkeypatch.delenv("VIBE_TRADING_SLASH_ARG_MAX", raising=False)
            importlib.reload(runner)
