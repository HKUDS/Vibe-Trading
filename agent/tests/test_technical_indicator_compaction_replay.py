from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from tests.test_readonly_replay_after_microcompact import _Context, _Registry, _Trace, _loop
from src.agent.grounding import GroundingLedger
from src.agent.loop import AgentLoop
from src.tools.technical_indicator_tool import TechnicalIndicatorTool


def test_technical_indicators_opt_into_readonly_compaction_replay() -> None:
    """The real technical-indicator tool can restore an identical lost result.

    Technical indicators are read-only but repeatable, so the generic replay
    gate requires the explicit replay_after_compaction opt-in added for this
    tool. Keep this test on the concrete class so that removing or renaming the
    contract cannot silently return identical post-compaction calls to a fresh
    market-data fetch.
    """
    tool = TechnicalIndicatorTool()
    loop = object.__new__(AgentLoop)

    assert tool.is_readonly is True
    assert tool.repeatable is True
    assert tool.replay_after_compaction is True
    assert (
        loop._readonly_replay_allowed(
            tool,
            {"symbol": "AAPL", "interval": "1d", "lookback": 200},
        )
        is True
    )


@pytest.mark.parametrize("refresh_args", [{"no_cache": True}, {"lookback": 100}])
def test_indicator_replay_preserves_dated_evidence_and_refreshes(monkeypatch, tmp_path, refresh_args):
    calls = []
    frame = pd.DataFrame(
        {"close": [100.0 + i for i in range(60)], "volume": [1000.0] * 60},
        index=pd.date_range("2026-06-01", periods=60),
    )

    def fetch(**kwargs):
        calls.append(kwargs)
        return {"AAPL.US": frame}

    monkeypatch.setattr("src.tools.technical_indicator_tool.fetch_market_data", fetch)
    registry = _Registry()
    registry.tool = TechnicalIndicatorTool()
    registry.execute = lambda name, args: registry.tool.execute(**args)
    loop = _loop(registry)
    args = {"symbol": "AAPL.US", "interval": "1d", "lookback": 200}
    messages, trace = [], _Trace()

    def run(arguments, number):
        call = SimpleNamespace(name="technical_indicators", arguments=arguments, id=f"call-{number}")
        loop._process_tool_calls([call], _Context(), messages, trace, [], number)
        return json.loads(messages[-1]["content"])

    original = run(args, 1)
    assert original["ok"] is True
    assert len(calls) == 1
    key = loop._identical_call_key("technical_indicators", args)
    messages.clear()  # Compaction discarded the tool result.
    assert loop._unblock_lost_readonly_results(messages, {key}) == ["technical_indicators"]
    restored = run(args, 2)
    assert len(calls) == 1
    assert restored["_vibe_replay"]["restored"] is True
    assert restored["latest_date"] == original["latest_date"]
    assert restored["indicators"] == original["indicators"]

    ledger = GroundingLedger(run_dir=tmp_path, user_message="Show AAPL.US prices by date")
    ledger.ingest_tool_result(tool_name="technical_indicators", arguments=args,
                              result=json.dumps(restored), call_id="call-2", success=True)
    evidence = json.loads((tmp_path / "artifacts" / "grounding_evidence.json").read_text())
    prices = [row for row in evidence["evidence"] if row["field"] == "latest_close"]
    assert len(prices) == 1
    assert prices[0]["timestamp"] == original["latest_date"]
    assert prices[0]["value"] == 159.0
    assert ledger.validate_final_answer("The latest observed price is 159.0.").valid

    fresh = run({**args, **refresh_args}, 3)
    assert fresh["ok"] is True
    assert "_vibe_replay" not in fresh
    assert len(calls) == 2
