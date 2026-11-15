"""Read-only release checks shared by CLI and Web."""

import json
import os
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

import requests
from packaging.version import Version

PACKAGE_NAME = "vibe-trading-ai"
PYPI_JSON_URL = "https://pypi.org/pypi/vibe-trading-ai/json"
PYPI_TIMEOUT_SECONDS = 15


# Install-kind labels returned by :func:`detect_install_kind`.
KIND_WHEEL = "wheel"
KIND_EDITABLE = "editable"
KIND_CHECKOUT = "checkout"
KIND_VCS = "vcs"


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
    - ``KIND_VCS``: installed directly from a Git or other VCS source.
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
            if isinstance(parsed, dict) and isinstance(parsed.get("vcs_info"), dict):
                return KIND_VCS
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


def check_update(current_version: str) -> dict:
    """Check the release and identify the existing installation's update route.

    Args:
        current_version: Version of the running server, not another interpreter.

    Returns:
        Public version facts and an installation-specific guidance key.
    """
    latest = fetch_latest_version()
    kind = "container" if any(Path(p).exists() for p in ("/.dockerenv", "/run/.containerenv")) else detect_install_kind()
    return {
        "current_version": current_version,
        "latest_version": latest,
        "available": Version(latest) > Version(current_version),
        "method": kind,
    }
