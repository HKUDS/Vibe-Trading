#!/usr/bin/env python3
"""CI gate: reject raw os.getenv / os.environ reads outside config layer.

Scans Python files under the agent source tree and rejects any direct
environment-variable **read** that bypasses the centralized
``agent/src/config/`` accessor layer.

Detected patterns (READ calls):
    os.getenv("KEY")
    os.environ.get("KEY")
    os.environ["KEY"]          # subscript with Load context

Allowlisted (NOT flagged):
    os.environ.copy()
    os.environ.items()
    os.environ.setdefault(...)
    os.environ["KEY"] = value  # Store context in Assign / AugAssign targets
    os.environ.pop()           # only in src/api/settings_routes.py + src/config/

Warnings (non-blocking):
    os.environ.pop() outside src/api/settings_routes.py and src/config/

Usage::

    python tools/ci_env_var_gate.py              # scan, exit 0/1
    python tools/ci_env_var_gate.py --allowlist   # print allowlist and exit 0

Zero external dependencies — stdlib only (ast, os, sys, pathlib).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Directories / files to scan (relative to repo root).
SCAN_TARGETS: list[str] = [
    "agent/src/",
    "agent/backtest/",
    "agent/cli/",
    "agent/mcp_server.py",
    "agent/api_server.py",
    "agent/scripts/",
]

# Directories always skipped (relative prefixes).
SKIP_PREFIXES: tuple[str, ...] = ("agent/tests/",)

# The allowed zone — reads here are the *point* of the config layer.
ALLOWED_PREFIX: str = "agent/src/config/"

# File (relative) where os.environ.pop() is explicitly permitted.
POP_ALLOWLISTED_FILE: str = "agent/src/api/settings_routes.py"

# ---------------------------------------------------------------------------
# AST visitor
# ---------------------------------------------------------------------------


class _EnvReadVisitor(ast.NodeVisitor):
    """Walk a single file's AST and collect disallowed env-var reads."""

    def __init__(self, filepath: Path, repo_root: Path) -> None:
        self._filepath = filepath
        self._rel = str(filepath.relative_to(repo_root)).replace("\\", "/")
        self._violations: list[tuple[int, str]] = []
        self._warnings: list[tuple[int, str]] = []
        self._source_lines: list[str] | None = None

    # -- properties ---------------------------------------------------------

    @property
    def violations(self) -> list[tuple[int, str]]:
        return list(self._violations)

    @property
    def warnings(self) -> list[tuple[int, str]]:
        return list(self._warnings)

    # -- helpers ------------------------------------------------------------

    def _set_source(self, source: str) -> None:
        self._source_lines = source.splitlines()

    def _line_has_noqa(self, lineno: int) -> bool:
        """Return True when the source line contains ``# env-gate``."""
        if self._source_lines is None or lineno < 1 or lineno > len(self._source_lines):
            return False
        return "# env-gate" in self._source_lines[lineno - 1]

    def _is_os_environ(self, node: ast.expr) -> bool:
        """Return True when *node* is ``os.environ``."""
        return (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and node.attr == "environ"
        )

    def _is_os_getenv(self, node: ast.expr) -> bool:
        """Return True when *node* is ``os.getenv``."""
        return (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and node.attr == "getenv"
        )

    # -- visitors -----------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        func = node.func

        # os.getenv(...)
        if self._is_os_getenv(func):
            if self._line_has_noqa(node.lineno):
                self.generic_visit(node)
                return
            self._violations.append((node.lineno, "os.getenv() — use src.config accessor"))
            self.generic_visit(node)
            return

        # os.environ.<method>(...)
        if isinstance(func, ast.Attribute) and self._is_os_environ(func.value):
            method = func.attr

            # Allowlisted methods
            if method in ("copy", "items", "setdefault"):
                self.generic_visit(node)
                return

            # os.environ.get(...) — READ
            if method == "get":
                if self._line_has_noqa(node.lineno):
                    self.generic_visit(node)
                    return
                self._violations.append((node.lineno, "os.environ.get() — use src.config accessor"))
                self.generic_visit(node)
                return

            # os.environ.pop(...) — warning outside settings_routes / config
            if method == "pop":
                if self._rel != POP_ALLOWLISTED_FILE:
                    self._warnings.append(
                        (
                            node.lineno,
                            "os.environ.pop() outside settings_routes.py / config/",
                        )
                    )
                self.generic_visit(node)
                return

            # Any other os.environ.<method>() — flag as read
            if self._line_has_noqa(node.lineno):
                self.generic_visit(node)
                return
            self._violations.append(
                (
                    node.lineno,
                    f"os.environ.{method}() — use src.config accessor",
                )
            )

        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:  # noqa: N802
        # os.environ["KEY"] in a Load (read) context
        if self._is_os_environ(node.value) and isinstance(node.ctx, ast.Load):
            if not self._line_has_noqa(node.lineno):
                self._violations.append((node.lineno, 'os.environ["..."] read — use src.config accessor'))

        self.generic_visit(node)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def _collect_python_files(repo_root: Path) -> list[Path]:
    """Return all .py files under SCAN_TARGETS, minus SKIP_PREFIXES and ALLOWED_PREFIX."""
    results: list[Path] = []

    for target in SCAN_TARGETS:
        target_path = repo_root / target
        if target_path.is_file():
            # Single file target (e.g. agent/mcp_server.py)
            if target_path.suffix == ".py":
                rel = str(target_path.relative_to(repo_root)).replace("\\", "/")
                if not _should_skip(rel):
                    results.append(target_path)
        elif target_path.is_dir():
            for py_file in sorted(target_path.rglob("*.py")):
                rel = str(py_file.relative_to(repo_root)).replace("\\", "/")
                if _should_skip(rel):
                    continue
                results.append(py_file)

    return results


def _should_skip(rel_path: str) -> bool:
    """Return True when *rel_path* falls in a skipped or allowed zone."""
    for prefix in SKIP_PREFIXES:
        if rel_path.startswith(prefix):
            return True
    if rel_path.startswith(ALLOWED_PREFIX):
        return True
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

ALLOWLIST_TEXT = """\
Allowlisted patterns (NOT flagged by this gate):
  1. os.environ.copy()          — snapshot of the full environment
  2. os.environ.items()         — iteration over env vars
  3. os.environ.setdefault(...) — conditional write
  4. os.environ["KEY"] = value  — explicit write (Store context)
  5. os.environ.pop()           — only in src/api/settings_routes.py + src/config/
  6. All reads inside agent/src/config/ — the config layer itself
  7. All files under agent/tests/ — test code is exempt
"""


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    if "--allowlist" in args:
        print(ALLOWLIST_TEXT)
        return 0

    repo_root = Path(__file__).resolve().parent.parent
    files = _collect_python_files(repo_root)

    all_violations: list[tuple[str, int, str]] = []
    all_warnings: list[tuple[str, int, str]] = []

    for filepath in files:
        try:
            source = filepath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        try:
            tree = ast.parse(source, filename=str(filepath))
        except SyntaxError:
            # Skip files that can't be parsed (e.g. generated stubs).
            continue

        visitor = _EnvReadVisitor(filepath, repo_root)
        visitor._set_source(source)
        visitor.visit(tree)

        rel = str(filepath.relative_to(repo_root)).replace("\\", "/")
        for lineno, msg in visitor.violations:
            all_violations.append((rel, lineno, msg))
        for lineno, msg in visitor.warnings:
            all_warnings.append((rel, lineno, msg))

    # Print warnings (non-blocking)
    for rel, lineno, msg in all_warnings:
        print(f"  WARN: {rel}:{lineno}: {msg}")

    # Print violations (blocking)
    if all_violations:
        print()
        print("FAIL: raw os.getenv / os.environ reads outside config layer:")
        for rel, lineno, msg in all_violations:
            print(f"  {rel}:{lineno}: {msg}")
        print()
        print("Use the centralized config accessor in agent/src/config/ instead.")
        print("Run with --allowlist to see permitted patterns.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
