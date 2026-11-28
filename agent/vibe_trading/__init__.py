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
  ``POST /sessions/{id}/messages``, so all kernel guards apply, and the route's
  own checks (session id shape, 1 to ``MAX_MESSAGE_CHARS`` characters) are
  applied from the same definitions. Shell tools are off unless
  ``ClientSettings(include_shell_tools=True)`` AND the operator's
  ``VIBE_TRADING_ENABLE_SHELL_TOOLS``, the switch the HTTP API reads.
* One live session service per runtime root, across processes. A second
  :class:`Client`, or a ``vibe-trading serve`` on the same root, raises
  :class:`RuntimeRootInUseError`; close the first to release it.
  The runtime root is the kernel's (``VIBE_TRADING_HOME``, else
  ``~/.vibe-trading``), bound when the kernel is first imported.
* Events are a closed vocabulary (see :mod:`vibe_trading.events`); kernel
  events outside it are dropped. :attr:`RunResult.text` is the final answer —
  streamed text may be retracted by a ``TextDelta(reset=True)``.
* ``Client.register_tool`` and the module-level ``register_tool`` accept an
  explicit read-only ``BaseTool`` for that client. Names colliding with
  built-ins or another host registration are refused, and host tools cannot
  be trading tools.
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


def register_tool(client: Client, tool: object) -> str:
    """Register one explicit host tool on a :class:`Client`.

    The function form keeps embedding code concise while registration remains
    scoped to the supplied client and never participates in discovery.
    """
    return client.register_tool(tool)

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
    "register_tool",
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
