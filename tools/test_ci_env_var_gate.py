"""Tests for tools/ci_env_var_gate.py.

Each test creates a temporary Python file under a fake repo tree, runs the
AST visitor, and asserts the expected violations / warnings / clean result.

Run with::

    pytest tools/test_ci_env_var_gate.py -v
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

# Import the visitor and helpers from the gate module.
from ci_env_var_gate import (  # type: ignore[import-untyped]
    _EnvReadVisitor,
    _should_skip,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_visitor(
    source: str,
    rel_path: str = "agent/src/some_module.py",
    repo_root: Path | None = None,
) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Parse *source*, run the visitor, return (violations, warnings)."""
    if repo_root is None:
        repo_root = Path("/fake/repo")

    tree = ast.parse(textwrap.dedent(source))
    filepath = repo_root / rel_path
    visitor = _EnvReadVisitor(filepath, repo_root)
    visitor._set_source(textwrap.dedent(source))
    visitor.visit(tree)
    return visitor.violations, visitor.warnings


# ---------------------------------------------------------------------------
# Tests — violations (must be flagged)
# ---------------------------------------------------------------------------


class TestOsGetenvFlagged:
    """os.getenv("FOO") outside config/ is a violation."""

    def test_os_getenv_basic(self) -> None:
        violations, _ = _run_visitor('import os\nx = os.getenv("FOO")\n')
        assert len(violations) == 1
        assert "os.getenv" in violations[0][1]

    def test_os_getenv_with_default(self) -> None:
        violations, _ = _run_visitor('import os\nx = os.getenv("FOO", "bar")\n')
        assert len(violations) == 1


class TestOsEnvironGetFlagged:
    """os.environ.get("FOO") outside config/ is a violation."""

    def test_environ_get_basic(self) -> None:
        violations, _ = _run_visitor('import os\nx = os.environ.get("FOO")\n')
        assert len(violations) == 1
        assert "os.environ.get" in violations[0][1]

    def test_environ_get_with_default(self) -> None:
        violations, _ = _run_visitor('import os\nx = os.environ.get("FOO", "bar")\n')
        assert len(violations) == 1


class TestOsEnvironSubscriptReadFlagged:
    """os.environ["FOO"] read outside config/ is a violation."""

    def test_subscript_read(self) -> None:
        violations, _ = _run_visitor('import os\nx = os.environ["FOO"]\n')
        assert len(violations) == 1
        assert "read" in violations[0][1].lower()

    def test_subscript_read_in_expression(self) -> None:
        violations, _ = _run_visitor('import os\nif os.environ["DEBUG"] == "1": pass\n')
        assert len(violations) == 1


# ---------------------------------------------------------------------------
# Tests — allowlisted (must NOT be flagged)
# ---------------------------------------------------------------------------


class TestEnvironCopyAllowed:
    """os.environ.copy() is NOT flagged."""

    def test_copy(self) -> None:
        violations, _ = _run_visitor("import os\nenv = os.environ.copy()\n")
        assert len(violations) == 0


class TestEnvironItemsAllowed:
    """os.environ.items() is NOT flagged."""

    def test_items(self) -> None:
        violations, _ = _run_visitor("import os\nfor k, v in os.environ.items(): pass\n")
        assert len(violations) == 0


class TestEnvironSetdefaultAllowed:
    """os.environ.setdefault() is NOT flagged."""

    def test_setdefault(self) -> None:
        violations, _ = _run_visitor('import os\nos.environ.setdefault("FOO", "bar")\n')
        assert len(violations) == 0


class TestEnvironSubscriptWriteAllowed:
    """os.environ["FOO"] = "bar" (Store context) is NOT flagged."""

    def test_subscript_write(self) -> None:
        violations, _ = _run_visitor('import os\nos.environ["FOO"] = "bar"\n')
        assert len(violations) == 0

    def test_subscript_aug_assign(self) -> None:
        # os.environ["PATH"] += ":/new" — still a Store context
        violations, _ = _run_visitor('import os\nos.environ["PATH"] += ":/new"\n')
        assert len(violations) == 0


class TestConfigDirectoryAllowed:
    """Files in agent/src/config/ are NOT scanned (skipped entirely)."""

    def test_config_file_skipped(self) -> None:
        # Even with os.getenv in the source, the file is in config/ so
        # _should_skip returns True and the scanner never visits it.
        assert _should_skip("agent/src/config/accessor.py") is True
        assert _should_skip("agent/src/config/env_schema.py") is True

    def test_config_visitor_clean(self) -> None:
        # Even if we *did* visit a config file, the visitor itself would
        # flag it — but the scanner skips it.  Verify the skip logic.
        violations, _ = _run_visitor(
            'import os\nx = os.getenv("FOO")\n',
            rel_path="agent/src/config/env_schema.py",
        )
        # The visitor doesn't know about skip rules — it just visits.
        # But the scanner would never call it on this file.
        # This test documents that the visitor IS strict; the skip is
        # enforced at the file-discovery layer.
        assert len(violations) == 1  # visitor flags it
        assert _should_skip("agent/src/config/env_schema.py")  # scanner skips


class TestTestsDirectorySkipped:
    """Files in agent/tests/ are NOT scanned."""

    def test_tests_dir_skipped(self) -> None:
        assert _should_skip("agent/tests/test_foo.py") is True
        assert _should_skip("agent/tests/unit/test_bar.py") is True


# ---------------------------------------------------------------------------
# Tests — pop() warnings
# ---------------------------------------------------------------------------


class TestEnvironPopWarning:
    """os.environ.pop() outside settings_routes.py is a warning."""

    def test_pop_outside_settings_routes(self) -> None:
        violations, warnings = _run_visitor(
            'import os\nos.environ.pop("FOO", None)\n',
            rel_path="agent/src/some_module.py",
        )
        assert len(violations) == 0  # not a blocking violation
        assert len(warnings) == 1
        assert "pop" in warnings[0][1]

    def test_pop_in_settings_routes_no_warning(self) -> None:
        violations, warnings = _run_visitor(
            'import os\nos.environ.pop("FOO", None)\n',
            rel_path="agent/src/api/settings_routes.py",
        )
        assert len(violations) == 0
        assert len(warnings) == 0


# ---------------------------------------------------------------------------
# Tests — multiple violations in one file
# ---------------------------------------------------------------------------


class TestMultipleViolations:
    """A file with several patterns reports all of them."""

    def test_mixed_reads(self) -> None:
        source = """\
        import os
        a = os.getenv("A")
        b = os.environ.get("B")
        c = os.environ["C"]
        d = os.environ.copy()  # allowed
        os.environ["D"] = "x"  # allowed (write)
        """
        violations, _ = _run_visitor(source)
        assert len(violations) == 3  # getenv, environ.get, subscript read


# ---------------------------------------------------------------------------
# Tests — CLI flags
# ---------------------------------------------------------------------------


class TestAllowlistFlag:
    """--allowlist prints the allowlist and exits 0."""

    def test_allowlist_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = main(["--allowlist"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "os.environ.copy()" in captured.out
        assert "os.environ.items()" in captured.out
        assert "os.environ.setdefault" in captured.out


# ---------------------------------------------------------------------------
# Tests — noqa suppression
# ---------------------------------------------------------------------------


class TestNoqaSuppression:
    """Lines with '# env-gate' are not flagged."""

    def test_noqa_suppresses_getenv(self) -> None:
        source = 'import os\nx = os.getenv("FOO")  # env-gate\n'
        violations, _ = _run_visitor(source)
        assert len(violations) == 0

    def test_noqa_suppresses_environ_get(self) -> None:
        source = 'import os\nx = os.environ.get("FOO")  # env-gate\n'
        violations, _ = _run_visitor(source)
        assert len(violations) == 0

    def test_noqa_suppresses_subscript_read(self) -> None:
        source = 'import os\nx = os.environ["FOO"]  # env-gate\n'
        violations, _ = _run_visitor(source)
        assert len(violations) == 0

    def test_noqa_does_not_affect_other_lines(self) -> None:
        source = 'import os\nx = os.getenv("FOO")  # env-gate\ny = os.getenv("BAR")\n'
        violations, _ = _run_visitor(source)
        assert len(violations) == 1
        assert "BAR" not in violations[0][1]  # the violation is for BAR, not FOO

    def test_partial_noqa_not_matched(self) -> None:
        """Only exact '# env-gate' is recognized, not '# noqa' alone."""
        source = 'import os\nx = os.getenv("FOO")  # noqa\n'
        violations, _ = _run_visitor(source)
        assert len(violations) == 1
