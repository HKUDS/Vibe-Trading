"""Configuration contract for stream retry limits."""

from __future__ import annotations

import src.agent.loop as loop


def test_stream_max_retries_honors_runtime_override(monkeypatch) -> None:
    monkeypatch.setattr(loop, "STREAM_MAX_RETRIES", 5, raising=False)
    assert loop._stream_max_retries() == 5
