"""Embeddable Python entry point to the Vibe-Trading agent kernel.

A thin, typed, async facade over the session service the HTTP API runs on::

    import asyncio
    from vibe_trading import Client, RunCompleted, TextDelta, ToolStarted

    async def main() -> None:
        async with Client() as client:
            # One call: new session, one message, final result.
            result = await client.run("Summarise AAPL's last quarter")
            print(result.status, result.model, result.usage)

            # Or stream a run in a session you keep.
            session = await client.create_session(title="research")
            stream = await client.send(session.session_id, "Backtest a 20/60 MA cross on SPY")
            async for event in stream:
                if isinstance(event, TextDelta):
                    if event.reset:
                        ...  # discard text shown so far
                    print(event.text, end="")
                elif isinstance(event, ToolStarted):
                    print(f"\\n[{event.tool}]")
            result = await stream.wait()

    asyncio.run(main())

Contract:

* Model, provider and data credentials come from the same configuration the
  CLI and server read (``agent/.env``, ``~/.vibe-trading``); the facade takes
  none and exposes none.
* Every send goes through ``SessionService.send_message``, exactly like
  ``POST /sessions/{id}/messages``, so all kernel guards apply. Shell tools are
  off unless ``ClientSettings(include_shell_tools=True)``.
* One :class:`Client` per runtime root per process. A second one on the same
  root raises :class:`RuntimeRootInUseError`; close the first to release it.
  The runtime root is the kernel's (``VIBE_TRADING_HOME``, else
  ``~/.vibe-trading``), bound when the kernel is first imported.
* Events are a closed vocabulary (see :mod:`vibe_trading.events`); kernel
  events outside it are dropped. :attr:`RunResult.text` is the final answer —
  streamed text may be retracted by a ``TextDelta(reset=True)``.
* There is no ``register_tool``: tools are discovered process-wide from
  ``src/tools`` and a same-named class replaces a real tool, so no safe
  per-client registration exists. Extra tools reach the agent through MCP
  servers in the operator's config file.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

# Editable installs can share an environment with another project named
# ``src`` (the CLI does the same, see ``cli/__init__.py``): resolve this
# package's sibling ``src`` before importing it.
_package_root = str(_Path(__file__).resolve().parents[1])
if not _sys.path or _sys.path[0] != _package_root:
    _sys.path.insert(0, _package_root)

from vibe_trading.client import (  # noqa: E402 — resolve sibling packages first
    Client,
    ClientClosedError,
    ClientSettings,
    MessageInfo,
    RuntimeRootInUseError,
    SessionBusyError,
    SessionInfo,
    SessionNotFoundError,
    Stream,
)
from vibe_trading.events import (  # noqa: E402
    Event,
    ReasoningDelta,
    RunCancelled,
    RunCompleted,
    RunFailed,
    RunResult,
    RunStarted,
    TextDelta,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)

__all__ = [
    "Client",
    "ClientClosedError",
    "ClientSettings",
    "Event",
    "MessageInfo",
    "ReasoningDelta",
    "RunCancelled",
    "RunCompleted",
    "RunFailed",
    "RunResult",
    "RunStarted",
    "RuntimeRootInUseError",
    "SessionBusyError",
    "SessionInfo",
    "SessionNotFoundError",
    "Stream",
    "TextDelta",
    "ToolCompleted",
    "ToolFailed",
    "ToolStarted",
]
