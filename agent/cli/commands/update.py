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

import json
import os
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, distribution

import requests
from packaging.version import InvalidVersion, Version
from rich.markup import escape as rich_escape

from cli._version import __version__ as CURRENT_VERSION
from cli.theme import get_console

console = get_console()

PACKAGE_NAME = "vibe-trading-ai"
PYPI_JSON_URL = "https://pypi.org/pypi/vibe-trading-ai/json"
PYPI_TIMEOUT_SECONDS = 15
VERIFY_TIMEOUT_SECONDS = 60

EXIT_OK = 0
EXIT_FAILED = 1

# Install-kind labels returned by :func:`detect_install_kind`.
KIND_WHEEL = "wheel"
KIND_EDITABLE = "editable"
KIND_CHECKOUT = "checkout"


def fetch_latest_version() -> str:
    """Return the newest published version of ``vibe-trading-ai`` on PyPI.

    Raises:
        requests.RequestException: network / HTTP failures — the caller turns
            this into a user-facing error and never touches the local install.
        (KeyError, ValueError): malformed PyPI payload.
    """
    resp = requests.get(PYPI_JSON_URL, timeout=PYPI_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return str(resp.json()["info"]["version"])


def detect_install_kind() -> str:
    """Classify how ``vibe-trading-ai`` is installed, cheapest signals first.

    Returns one of the ``KIND_*`` constants:

    - ``KIND_CHECKOUT``: not installed as a distribution at all — running from
      a clone with ``PYTHONPATH=agent`` (``importlib.metadata`` raises).
    - ``KIND_EDITABLE``: ``pip install -e .`` — either the modern marker
      (``direct_url.json`` in the metadata dir with ``dir_info.editable``) or
      the legacy marker (a source-tree ``*.egg-info`` dir on ``sys.path``).
    - ``KIND_WHEEL``: anything else that resolves through importlib.metadata.

    Why both markers? The metadata dir that ``distribution()`` resolves can be
    the venv ``dist-info`` OR a source-tree ``*.egg-info`` depending on the
    working directory (running ``python -m cli`` from ``agent/`` resolves to
    ``agent/vibe_trading_ai.egg-info``, which carries no ``direct_url.json``).
    ``read_text`` reads from whatever metadata dir was resolved, and the
    egg-info check catches the legacy editable style on top of it.
    """
    try:
        dist = distribution(PACKAGE_NAME)
    except PackageNotFoundError:
        return KIND_CHECKOUT

    # Modern editable marker: direct_url.json with dir_info.editable, read
    # straight from the resolved metadata dir (more reliable than dist.files,
    # which is a RECORD listing that some egg-info dirs omit entirely).
    direct_url = dist.read_text("direct_url.json")
    if direct_url:
        try:
            parsed = json.loads(direct_url)
            if isinstance(parsed, dict) and parsed.get("dir_info", {}).get("editable"):
                return KIND_EDITABLE
        except (ValueError, AttributeError):
            return KIND_WHEEL  # corrupt metadata; default to the pip path
        return KIND_WHEEL

    # Legacy editable marker: ``pip install -e .`` / ``python setup.py develop``
    # leave ``<name>.egg-info`` in the project tree; wheel installs never do.
    if _has_source_tree_egg_info():
        return KIND_EDITABLE
    return KIND_WHEEL


def _has_source_tree_egg_info() -> bool:
    """True if an egg-info dir for this package sits in a source tree on sys.path.

    Returns:
        Whether ``sys.path`` contains a directory holding ``<name>.egg-info``
        for :data:`PACKAGE_NAME`.
    """
    normalized = PACKAGE_NAME.replace("-", "_")
    for entry in sys.path:
        base = entry if entry else os.getcwd()
        if os.path.isdir(os.path.join(base, f"{normalized}.egg-info")):
            return True
    return False


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
        [sys.executable, "-m", "pip", "install", "--upgrade", PACKAGE_NAME],
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
        confirmed = installed and Version(installed) >= Version(expected)
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
