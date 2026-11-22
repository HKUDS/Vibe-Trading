"""Spending, restart and scheduling boundaries use real isolated SQLite state."""

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from src.live.runtime.decision_budget import DecisionBudget, DecisionBudgetError, DecisionSettings

NOW = datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc)


def _store(tmp_path):
    return DecisionBudget("robinhood", path=tmp_path / "budget.sqlite3")


def _usage(iteration=1, tokens_in=100, tokens_out=10):
    return {"iter": iteration, "input_tokens": tokens_in, "output_tokens": tokens_out, "total_tokens": tokens_in + tokens_out}


def test_cadence_survives_restart_and_keeps_prior_spend(tmp_path):
    budget = _store(tmp_path)
    settings = DecisionSettings()
    decision = budget.begin(settings, NOW)
    budget.record(decision, _usage(), settings, NOW)
    budget.finish(decision, settings, NOW)
    restarted = _store(tmp_path)
    assert restarted.begin(settings, NOW + timedelta(minutes=1)) is None
    assert restarted.begin(settings, NOW + timedelta(minutes=15))
    assert restarted.snapshot(NOW)["usage"]["tokens"] == 110


def test_token_stop_persists_even_when_record_raises(tmp_path):
    budget = _store(tmp_path)
    settings = DecisionSettings(max_daily_tokens=100)
    decision = budget.begin(settings, NOW)
    with pytest.raises(DecisionBudgetError, match="token budget"):
        budget.record(decision, _usage(), settings, NOW)
    with pytest.raises(DecisionBudgetError):
        budget.finish(decision, settings, NOW)
    assert _store(tmp_path).snapshot(NOW)["usage"]["tokens"] == 110
    with pytest.raises(DecisionBudgetError, match="token budget"):
        _store(tmp_path).begin(settings, NOW + timedelta(hours=1))


def test_dollar_stop_and_usage_idempotence(tmp_path):
    budget = _store(tmp_path)
    settings = DecisionSettings(input_usd_per_million=10, output_usd_per_million=20, max_daily_cost_usd=0.002)
    budget.save_settings(settings)
    decision = budget.begin(settings, NOW)
    budget.record(decision, _usage(), settings, NOW)
    budget.record(decision, _usage(), settings, NOW)
    assert budget.snapshot(NOW)["usage"]["estimated_cost_usd"] == pytest.approx(0.0012)
    with pytest.raises(DecisionBudgetError, match="cost budget"):
        budget.record(decision, _usage(iteration=2), settings, NOW)
    assert budget.snapshot(NOW)["usage"]["tokens"] == 220


def test_missing_usage_and_crash_do_not_reset_budget(tmp_path):
    budget = _store(tmp_path)
    settings = DecisionSettings()
    decision = budget.begin(settings, NOW)
    with pytest.raises(DecisionBudgetError, match="unfinished"):
        _store(tmp_path).begin(settings, NOW + timedelta(days=1))
    with pytest.raises(DecisionBudgetError, match="unavailable"):
        budget.finish(decision, settings, NOW)
    with pytest.raises(DecisionBudgetError, match="unavailable"):
        _store(tmp_path).begin(settings, NOW + timedelta(hours=1))


def test_compaction_calls_share_iteration_without_being_deduplicated(tmp_path):
    budget = _store(tmp_path)
    settings = DecisionSettings(max_daily_tokens=300)
    decision = budget.begin(settings, NOW)
    first = {**_usage(), "purpose": "compaction", "call_index": 1}
    second = {**_usage(), "purpose": "compaction", "call_index": 2}
    budget.record(decision, first, settings, NOW)
    budget.record(decision, first, settings, NOW)  # SSE replay is still idempotent.
    budget.record(decision, second, settings, NOW)
    with pytest.raises(DecisionBudgetError, match="token budget"):
        budget.record(decision, {**_usage(), "call_index": 3}, settings, NOW)
    assert budget.snapshot(NOW)["usage"]["tokens"] == 330


def test_daily_schedule_follows_dst_and_fires_once(tmp_path):
    budget = _store(tmp_path)
    settings = DecisionSettings(daily_at="10:00")
    before = datetime(2026, 11, 2, 14, 59, tzinfo=timezone.utc)
    assert budget.begin(settings, before) is None
    at = before + timedelta(minutes=1)
    decision = budget.begin(settings, at)
    budget.record(decision, _usage(), settings, at)
    budget.finish(decision, settings, at)
    assert budget.begin(settings, at + timedelta(hours=3)) is None
    assert budget.begin(settings, at + timedelta(days=1))


def test_begin_is_atomic_across_connections(tmp_path):
    budget = _store(tmp_path)
    budget.save_settings(DecisionSettings())
    def reserve(_):
        try:
            return _store(tmp_path).begin(DecisionSettings(), NOW)
        except DecisionBudgetError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, range(2)))
    assert sum(bool(result) for result in results) == 1


@pytest.mark.parametrize("values", [
    {"interval_seconds": 0}, {"interval_seconds": True}, {"max_daily_tokens": -1},
    {"max_daily_cost_usd": 1}, {"input_usd_per_million": float("nan")},
    {"daily_at": "25:00"}, {"timezone": "Not/AZone"}, {"unknown": 1},
])
def test_invalid_settings_refused(values):
    with pytest.raises(ValidationError):
        DecisionSettings(**values)


def test_corrupt_database_is_not_an_empty_budget(tmp_path):
    budget = _store(tmp_path)
    budget.path.write_bytes(b"not sqlite")
    with pytest.raises(Exception):
        budget.begin(DecisionSettings(), NOW)


def test_response_crossing_midnight_is_charged_to_new_utc_day(tmp_path):
    budget = _store(tmp_path)
    settings = DecisionSettings()
    before = NOW.replace(hour=23, minute=59)
    after = before + timedelta(minutes=2)
    decision = budget.begin(settings, before)
    budget.record(decision, _usage(), settings, after)
    budget.finish(decision, settings, after)
    assert budget.snapshot(after)["usage"]["tokens"] == 110
    assert budget.snapshot(after)["usage"]["turns"] == 0


def test_missing_later_response_stays_unaccounted_after_restart(tmp_path):
    budget = _store(tmp_path)
    settings = DecisionSettings()
    decision = budget.begin(settings, NOW)
    budget.record(decision, _usage(), settings, NOW)
    with pytest.raises(DecisionBudgetError):
        budget.record(decision, {}, settings, NOW)
    with pytest.raises(DecisionBudgetError):
        budget.finish(decision, settings, NOW)
    assert budget.snapshot(NOW)["usage"]["estimated_cost_usd"] is None
    with pytest.raises(DecisionBudgetError, match="unavailable"):
        _store(tmp_path).begin(settings, NOW + timedelta(hours=1))


def test_uncategorized_tokens_use_the_higher_configured_price(tmp_path):
    budget = _store(tmp_path)
    settings = DecisionSettings(input_usd_per_million=10, output_usd_per_million=20)
    budget.save_settings(settings)
    decision = budget.begin(settings, NOW)
    budget.record(decision, {**_usage(), "total_tokens": 120}, settings, NOW)
    assert budget.snapshot(NOW)["usage"]["estimated_cost_usd"] == pytest.approx(0.0014)


@pytest.mark.parametrize("reported", [True, False])
def test_real_agent_stops_before_tools_when_usage_monitor_cancels(tmp_path, reported):
    from tests.test_agent_loop_no_progress import DiscoveryLLM, DiscoveryTool, build_loop

    tool = DiscoveryTool(['{"status":"ok"}'])
    llm = DiscoveryLLM(finish_after=1)
    original = llm.stream_chat
    def response(*args, **kwargs):
        result = original(*args, **kwargs)
        result.usage_metadata = {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110} if reported else None
        return result
    llm.stream_chat = response
    agent, _, _ = build_loop(tmp_path, tool, llm)
    seen = []
    def monitor(name, data):
        if name == "item.delta" and data.get("kind") in {"run.usage", "run.usage_unavailable"}:
            seen.append(data["kind"])
            agent.cancel()
    agent._event_callback = monitor
    result = agent.run(user_message="inspect the artifact")
    assert seen == ["run.usage" if reported else "run.usage_unavailable"]
    assert tool.calls == 0
    assert llm.calls == 1
    assert result["status"] == "cancelled"
