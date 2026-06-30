"""Route a broker request through the TAP proxy (Tool Authorization Protocol).

Credential-isolation hook. When TAP is configured (``TAP_PROXY_URL`` +
``TAP_AGENT_KEY`` present in the environment — e.g. loaded from the project
``.env``), outbound broker calls are sent to TAP's ``/forward`` endpoint
instead of hitting the broker directly. The real
broker secret lives inside TAP and is referenced only by
``<CREDENTIAL:name.field>`` placeholders; TAP substitutes the real value
server-side after policy enforcement + human approval, then forwards upstream.

Security properties this gives the agent process:
  * it never holds the broker API secret — only a policy-scoped TAP agent key;
  * writes (POST/PUT/PATCH/DELETE) block on human approval before reaching the
    broker, so a prompt-injected order cannot execute without a human;
  * ``allowed_hosts`` on the TAP credential pins where the secret may be sent,
    so a tampered target is rejected (403) before injection.

Additive and opt-in: if TAP is not configured, :func:`tap_enabled` returns
False and callers keep their existing direct-SDK path unchanged.

Stdlib only — no new dependencies.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

_DEFAULT_APPROVAL_TIMEOUT = 300  # seconds to wait for a human approval decision
_FORWARD_POST_TIMEOUT = 60  # the POST returns 202 fast; approval is polled async
_POLL_INTERVAL = 2


# Project .env locations, mirroring Vibe-Trading's own loader
# (src/providers/llm.py ``_ENV_CANDIDATES``): first existing file wins.
# tap_forward.py lives at agent/src/trading/ -> parents[2] is the agent dir.
_ENV_CANDIDATES = (
    Path.home() / ".vibe-trading" / ".env",
    Path(__file__).resolve().parents[2] / ".env",  # agent/.env
    Path.cwd() / ".env",
)


def _load_env_into_environ() -> None:
    """Populate ``os.environ`` from the first existing project ``.env``.

    Uses ``setdefault`` (never overrides a real environment variable), so an
    explicit env var — e.g. injected by docker-compose ``env_file`` — always
    wins over the file. This lets the TAP config live in the same ``.env`` as
    the rest of the app's settings. Secret values are not logged.
    """
    for candidate in _ENV_CANDIDATES:
        try:
            if not candidate.exists():
                continue
            for raw in candidate.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, value = line.split("=", 1)
                name = name.strip()
                if name:
                    os.environ.setdefault(name, value.strip().strip('"').strip("'"))
            return
        except OSError:
            continue


def _resolve_config() -> tuple[str, str]:
    """Return ``(base_url, agent_key)`` from the environment / project ``.env``.

    Reads ``TAP_PROXY_URL`` + ``TAP_AGENT_KEY`` from ``os.environ``. If they are
    not already present (e.g. when invoked outside the app's normal startup),
    the project ``.env`` is loaded once. The agent key is a secret — read here,
    never logged.
    """
    base = os.environ.get("TAP_PROXY_URL")
    key = os.environ.get("TAP_AGENT_KEY")
    if not (base and key):
        _load_env_into_environ()
        base = os.environ.get("TAP_PROXY_URL")
        key = os.environ.get("TAP_AGENT_KEY")
    return (base or "").rstrip("/"), (key or "")


def tap_enabled() -> bool:
    """True when a TAP proxy URL and agent key are both configured."""
    base, key = _resolve_config()
    return bool(base and key)


def forward(
    target_url: str,
    method: str,
    body: str | None,
    credential_headers: Mapping[str, str],
    *,
    extra_headers: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Send one request to upstream ``target_url`` via TAP ``/forward``.

    ``credential_headers`` carry ``<CREDENTIAL:name.field>`` placeholders (never
    real secrets) that TAP resolves server-side. Writes block on human approval;
    this polls until the request is forwarded, denied, timed out, or errors.

    Never raises for a broker/approval outcome — returns a structured result::

        {"ok": bool, "decision": str | None, "status": int | None,
         "body": str | dict | None, "error": str | None}

    ``ok`` is True only when TAP forwarded the request upstream AND the upstream
    returned a 2xx. Fail-closed otherwise.
    """
    base, key = _resolve_config()
    if not (base and key):
        return _result(False, error="TAP not configured")

    timeout = timeout if timeout is not None else _env_timeout()
    headers = {
        "X-TAP-Key": key,
        "X-TAP-Target": target_url,
        "X-TAP-Method": method.upper(),
        "Content-Type": "application/json",
    }
    headers.update(dict(credential_headers or {}))
    headers.update(dict(extra_headers or {}))

    data = body.encode("utf-8") if body else None
    code, text = _http("POST", f"{base}/forward", headers, data, _FORWARD_POST_TIMEOUT)
    parsed = _json(text)

    # Immediate result (auto-approved read) or an error from TAP itself.
    if code != 202:
        ok = 200 <= code < 300
        return _result(ok, decision="immediate", status=code, body=parsed,
                       error=None if ok else _err(parsed))

    # Write path: approval required -> poll until a terminal decision.
    # Build the poll URL against the CONFIGURED base only. We never send the
    # agent key (X-TAP-Key) to an absolute URL taken from the response body —
    # a tampered/malicious response could otherwise exfiltrate the key. We
    # accept a server-provided path only if it is relative (starts with "/").
    txn = parsed.get("txn_id") if isinstance(parsed, dict) else None
    poll = parsed.get("poll_url") if isinstance(parsed, dict) else None
    if isinstance(txn, str) and txn:
        poll_url = f"{base}/agent/approvals/{txn}"
    elif isinstance(poll, str) and poll.startswith("/"):
        poll_url = f"{base}{poll}"
    else:
        return _result(False, decision="pending", status=code, body=parsed,
                       error="approval response missing a usable txn_id / relative poll path")

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(_POLL_INTERVAL)
        _, ptext = _http("GET", poll_url, {"X-TAP-Key": key}, None, 30)
        pr = _json(ptext)
        state = (pr.get("status") if isinstance(pr, dict) else "") or ""
        if state == "forwarded":
            inner = (pr.get("response") if isinstance(pr, dict) else None) or {}
            up_status = inner.get("status")
            ok = isinstance(up_status, int) and 200 <= up_status < 300
            return _result(ok, decision="forwarded", status=up_status,
                           body=inner.get("body"), error=None if ok else "upstream error")
        if state in ("denied", "timed_out", "error"):
            return _result(False, decision=state, body=pr, error=_err(pr) or state)
    return _result(False, decision="timeout",
                   error=f"no approval decision within {int(timeout)}s")


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _http(method: str, url: str, headers: dict[str, str], data: bytes | None, timeout: float):
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        return 0, json.dumps({"error": f"connection failed: {exc.reason}"})


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def _result(ok: bool, *, decision: str | None = None, status: int | None = None,
            body: Any = None, error: str | None = None) -> dict[str, Any]:
    return {"ok": ok, "decision": decision, "status": status, "body": body, "error": error}


def _env_timeout() -> float:
    raw = os.environ.get("TAP_APPROVAL_TIMEOUT", "")
    try:
        return float(raw) if raw else float(_DEFAULT_APPROVAL_TIMEOUT)
    except ValueError:
        return float(_DEFAULT_APPROVAL_TIMEOUT)


def _err(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for k in ("error", "error_detail", "message", "detail"):
            value = payload.get(k)
            if isinstance(value, str) and value:
                return value
    return None
