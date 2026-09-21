"""Import stand-ins for the optional Slack SDK, shared by the Slack tests.

CI installs no channel extras, so ``src.channels.slack`` cannot import
``slack_sdk`` there. Each test file used to stub it its own way; one stubbed
``SocketModeResponse = object``, which then broke any later test that builds a
response (``object(envelope_id=...)`` raises TypeError) depending on import
order (#1524). The stand-ins here accept keyword arguments like the real
classes, and nothing is installed when the real package is present.
"""

from __future__ import annotations

import importlib.util
import sys
import types


def _module(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    sys.modules[name] = module
    return module


def install_slack_stubs() -> None:
    """Make ``src.channels.slack`` importable without the Slack extras."""
    if "slack_sdk" not in sys.modules and importlib.util.find_spec("slack_sdk") is None:
        for name in (
            "slack_sdk",
            "slack_sdk.socket_mode",
            "slack_sdk.socket_mode.request",
            "slack_sdk.socket_mode.response",
            "slack_sdk.socket_mode.websockets",
            "slack_sdk.web",
            "slack_sdk.web.async_client",
        ):
            _module(name)
        keyword_record = (types.SimpleNamespace,)
        sys.modules["slack_sdk.socket_mode.request"].SocketModeRequest = type("SocketModeRequest", keyword_record, {})
        sys.modules["slack_sdk.socket_mode.response"].SocketModeResponse = type("SocketModeResponse", keyword_record, {})
        sys.modules["slack_sdk.socket_mode.websockets"].SocketModeClient = object
        sys.modules["slack_sdk.web.async_client"].AsyncWebClient = object
    if "slackify_markdown" not in sys.modules and importlib.util.find_spec("slackify_markdown") is None:
        _module("slackify_markdown").slackify_markdown = lambda text: text
