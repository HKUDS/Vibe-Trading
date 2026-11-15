"""Self-update support: ``vibe-trading update``.

Checks PyPI for a newer ``vibe-trading-ai`` release than the currently
installed one and, when one exists, upgrades in place through ``pip`` using the
same interpreter that is running the CLI (``sys.executable -m pip``, never a
bare ``pip`` — the upgrade must target the interpreter that owns this CLI).

Scope decision (see ``.trellis/tasks/08-07-add-update/prd.md``): v1 handles the
PyPI-wheel install path only. Editable / git-checkout / Docker installs are
detected and answered with the right manual instruction instead of a pip
upgrade that would silently change the install type — ``pip install -U`` over
an ``pip install -e .`` install replaces the editable dev install with a
released wheel, which is a surprise nobody wants.

Design rules:
- Invoking ``vibe-trading update`` means "upgrade me": there is deliberately no
  confirmation prompt (user decision, 2026-08-07).
- Never downgrade: only upgrade when the latest PyPI version is strictly
  greater than the installed one (PEP 440).
- The upgrade runs in a subprocess; the current process has already imported
  the old code, so success is verified by re-reading installed metadata from a
  *fresh* subprocess.
- On any check failure the local install is left untouched.
- Docker is deliberately out of scope (user decision, 2026-08-07): inside a
  container the answer would be `git pull && docker compose up --build`, but
  detection is deferred.
"""

from __future__ import annotations

import subprocess
import sys

import requests
from packaging.version import InvalidVersion, Version
from rich.markup import escape as rich_escape

from cli._version import __version__ as CURRENT_VERSION
from cli.theme import get_console
from src.update import (
    KIND_CHECKOUT, KIND_EDITABLE, KIND_VCS, KIND_WHEEL as KIND_WHEEL, PACKAGE_NAME,
    detect_install_kind, fetch_latest_version,
)

console = get_console()

VERIFY_TIMEOUT_SECONDS = 60
EXIT_OK = 0
EXIT_FAILED = 1


def cmd_update() -> int:
    """Check PyPI and upgrade when a newer release exists. Returns exit code."""
    try:
        latest = fetch_latest_version()
    except (requests.RequestException, KeyError, ValueError) as exc:
        console.print(f"[red]Could not check for updates on PyPI:[/red] {rich_escape(str(exc))}")
        return EXIT_FAILED

    try:
        newer = Version(latest) > Version(CURRENT_VERSION)
    except InvalidVersion:
        console.print(
            f"[red]Could not compare versions[/red] (installed: {CURRENT_VERSION}, latest: {latest})."
        )
        return EXIT_FAILED

    if not newer:
        console.print(f"Already up to date ({CURRENT_VERSION}).")
        return EXIT_OK

    kind = detect_install_kind()
    if kind == KIND_EDITABLE:
        console.print(
            f"[yellow]Editable/development install detected[/yellow] "
            f"({CURRENT_VERSION} -> {latest} is available on PyPI).\n"
            "This checkout is installed with `pip install -e .`, so a pip "
            "upgrade would replace your dev install with the released wheel.\n"
            "Update the checkout instead: run `git pull` in the repo and reinstall "
            "(`pip install -e .`)."
        )
        return EXIT_OK
    if kind == KIND_VCS:
        console.print(
            f"[yellow]Version-control source install detected[/yellow] "
            f"({CURRENT_VERSION} -> {latest} is available on PyPI).\n"
            "A PyPI upgrade would replace your source revision with a released wheel.\n"
            "Update or reinstall from your original version-control source instead."
        )
        return EXIT_OK
    if kind == KIND_CHECKOUT:
        console.print(
            f"[yellow]Running from an uninstalled checkout[/yellow] "
            f"({CURRENT_VERSION} -> {latest} is available on PyPI).\n"
            "No pip-managed install found — update the checkout with `git pull`."
        )
        return EXIT_OK

    return _pip_upgrade(latest)


def _pip_upgrade(latest: str) -> int:
    """Upgrade the wheel install in place via pip, then verify. Returns exit code."""
    console.print(f"Upgrading {PACKAGE_NAME} {CURRENT_VERSION} -> {latest} ...")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            f"{PACKAGE_NAME}=={latest}",
        ],
        text=True,
    )
    if proc.returncode != 0:
        console.print(
            "[red]Upgrade failed.[/red] Re-run `vibe-trading update` or inspect the pip output above."
        )
        return EXIT_FAILED
    return _verify_upgrade(latest)


def _verify_upgrade(expected: str) -> int:
    """Re-read the installed version from a fresh process to confirm the upgrade."""
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "from importlib.metadata import version; print(version('vibe-trading-ai'))",
            ],
            capture_output=True,
            text=True,
            timeout=VERIFY_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        console.print(f"[yellow]Upgrade ran but verification failed:[/yellow] {exc}")
        return EXIT_FAILED

    installed = proc.stdout.strip()
    try:
        confirmed = bool(installed) and Version(installed) == Version(expected)
    except InvalidVersion:
        confirmed = False
    if not confirmed:
        console.print(
            f"[yellow]Upgrade verification mismatch[/yellow] — expected {expected}, "
            f"reported {rich_escape(installed or 'unknown')}. Check `vibe-trading --version`."
        )
        return EXIT_FAILED

    console.print(f"Updated to {installed}. Run `vibe-trading --version` to confirm.")
    return EXIT_OK
