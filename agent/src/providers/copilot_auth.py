"""GitHub Copilot authentication.

Copilot's OpenAI-compatible endpoint accepts a long-lived GitHub OAuth token
(``gho_``) or GitHub App user token (``ghu_``) directly as the Bearer
credential. The ``copilot_internal/v2/token`` JWT exchange used by some editor
integrations is deliberately NOT used here: it returns 403 for individual
accounts, and skipping it means there is no ~30-minute token to refresh.

Credential resolution order (first hit wins):

1. ``COPILOT_GITHUB_TOKEN`` -- set by ``vibe-trading provider login copilot``
   or by the user directly.
2. ``gh auth token`` -- the GitHub CLI, when installed and logged in.
3. ``~/.config/github-copilot/apps.json`` -- written by the VS Code Copilot
   extension and the ``copilot`` CLI.

When none of those exist, ``login_copilot()`` runs GitHub's OAuth device code
flow using only the standard library, so the GitHub CLI is never a hard
requirement.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

# The VS Code Copilot Chat OAuth app. Public by design (device flow uses no
# client secret) and shared by every editor integration.
COPILOT_OAUTH_CLIENT_ID = "Iv1.b507a08c87ecfe98"

COPILOT_TOKEN_ENV = "COPILOT_GITHUB_TOKEN"
_COPILOT_APPS_JSON = Path.home() / ".config" / "github-copilot" / "apps.json"

# Classic PATs (ghp_) are rejected by the Copilot API, so they are not
# accepted here either -- failing early beats a confusing 401 later.
_SUPPORTED_TOKEN_PREFIXES = ("gho_", "ghu_", "github_pat_")

_DEVICE_CODE_DEFAULT_INTERVAL = 5
_DEVICE_CODE_TIMEOUT_SECONDS = 300.0


def is_supported_token(token: str) -> bool:
    """Return whether ``token`` is a token type the Copilot API accepts."""
    return bool(token) and token.startswith(_SUPPORTED_TOKEN_PREFIXES)


def _gh_cli_path() -> Optional[str]:
    """Return a usable ``gh`` executable path, or None when unavailable."""
    for candidate in ("gh", "/opt/homebrew/bin/gh", "/usr/local/bin/gh"):
        found = shutil.which(candidate)
        if found:
            return found
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def gh_cli_token() -> str:
    """Return a GitHub token from the ``gh`` CLI, or ``""`` when unavailable."""
    exe = _gh_cli_path()
    if not exe:
        return ""
    try:
        proc = subprocess.run(
            [exe, "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    token = proc.stdout.strip()
    return token if proc.returncode == 0 and is_supported_token(token) else ""


def copilot_apps_json_token() -> str:
    """Return a token from the editor Copilot config, or ``""`` when absent.

    The VS Code Copilot extension and the ``copilot`` CLI persist a ``ghu_``
    token in ``~/.config/github-copilot/apps.json``. Reading it means a user
    who already uses Copilot in an editor needs neither the GitHub CLI nor a
    device login.
    """
    try:
        data = json.loads(_COPILOT_APPS_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        token = str(entry.get("oauth_token", "") or "").strip()
        if is_supported_token(token):
            return token
    return ""


def resolve_copilot_token() -> tuple[str, str]:
    """Resolve a Copilot credential from the first available source.

    Returns:
        ``(token, source)``. Both are ``""`` when no credential is available;
        callers surface that as "not authenticated" rather than falling back
        to an unrelated provider's key.
    """
    env_token = os.getenv(COPILOT_TOKEN_ENV, "").strip()  # noqa: env-gate — provider credential
    if is_supported_token(env_token):
        return env_token, COPILOT_TOKEN_ENV

    token = gh_cli_token()
    if token:
        return token, "gh auth token"

    token = copilot_apps_json_token()
    if token:
        return token, "~/.config/github-copilot/apps.json"

    return "", ""


def get_copilot_login_status() -> Optional[str]:
    """Return the resolved Copilot token, or None when not authenticated."""
    token, _source = resolve_copilot_token()
    return token or None


def login_copilot(
    *,
    host: str = "github.com",
    timeout_seconds: float = _DEVICE_CODE_TIMEOUT_SECONDS,
    print_fn: Callable[[str], None] | None = None,
) -> Optional[str]:
    """Run GitHub's OAuth device code flow and return the access token.

    Uses only the standard library, so authenticating never requires the
    GitHub CLI to be installed.

    Args:
        host: GitHub host, for GitHub Enterprise deployments.
        timeout_seconds: Overall deadline for the user to authorize.
        print_fn: Sink for user-facing instructions; defaults to ``print``.

    Returns:
        The OAuth access token, or None when the flow fails, is denied, or
        times out.
    """
    emit = print_fn or print
    domain = host.rstrip("/")

    payload = urllib.parse.urlencode(
        {"client_id": COPILOT_OAUTH_CLIENT_ID, "scope": "read:user"}
    ).encode()
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Vibe-Trading",
    }

    try:
        request = urllib.request.Request(
            f"https://{domain}/login/device/code", data=payload, headers=headers
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            device = json.loads(response.read().decode())
    except Exception:  # noqa: BLE001 - network/parse failures are all "no token"
        emit("  Failed to start GitHub device authorization.")
        return None

    device_code = device.get("device_code", "")
    user_code = device.get("user_code", "")
    verification_uri = device.get(
        "verification_uri", f"https://{domain}/login/device"
    )
    interval = max(int(device.get("interval", _DEVICE_CODE_DEFAULT_INTERVAL)), 1)

    if not device_code or not user_code:
        emit("  GitHub did not return a device code.")
        return None

    emit("")
    emit(f"  Open this URL in your browser: {verification_uri}")
    emit(f"  Enter this code: {user_code}")
    emit("")
    emit("  Waiting for authorization...")

    poll_payload = {
        "client_id": COPILOT_OAUTH_CLIENT_ID,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        time.sleep(interval)
        try:
            request = urllib.request.Request(
                f"https://{domain}/login/oauth/access_token",
                data=urllib.parse.urlencode(poll_payload).encode(),
                headers=headers,
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                result = json.loads(response.read().decode())
        except Exception:  # noqa: BLE001 - transient poll failure, keep waiting
            continue

        token = str(result.get("access_token", "") or "").strip()
        if token:
            if not is_supported_token(token):
                emit("  GitHub returned a token type the Copilot API rejects.")
                return None
            emit("  Authorized.")
            return token

        error = result.get("error", "")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += int(result.get("interval", 5))
            continue
        if error:
            emit(f"  Authorization failed: {error}")
            return None

    emit("  Timed out waiting for authorization.")
    return None
