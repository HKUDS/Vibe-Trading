"""Final PM arithmetic and shell-free calculations from the real-review regression."""
import json

import pytest

from src.agent.tools import ToolRegistry
from src.providers.chat import LLMResponse
from src.swarm.models import SwarmAgentSpec, SwarmTask
from src.swarm.position_risk import TABLE_HEADER, validate_position_risk_report
from src.swarm.presets import build_run_from_preset
import src.swarm.worker as worker


def report(nav='-0.372', weight='3'):
    return ('The committee recommends a conditional position after considering the complete risk review. ' * 3
            + '\n' + TABLE_HEADER + '\n| --- | --- | --- | --- |\n'
            + f'| Stop | {weight} | -12.4 | {nav} |\n')


@pytest.mark.parametrize('nav', ['-0.372', '-0.37'])
def test_rounding_preserves_correct_nav(nav):
    assert validate_position_risk_report(report(nav)) is None


@pytest.mark.parametrize('text', [report('-0.50'), report('0.372'), report('NaN'),
    report() + '| Bear | 4 | -20 | -0.8 |', TABLE_HEADER + '\n| --- | --- | --- |',
    'A decision with no position table.'])
def test_stale_missing_or_invalid_risk_is_refused(text):
    assert validate_position_risk_report(text)


@pytest.mark.parametrize('correct,iterations,expected', [(True, 3, 'completed'), (False, 3, 'incomplete'), (True, 1, 'incomplete')])
def test_worker_requires_correct_final_basis(tmp_path, monkeypatch, correct, iterations, expected):
    calls = []
    class Model:
        def stream_chat(self, messages, **kwargs):
            calls.append(messages.copy())
            return LLMResponse(content=report('-0.372' if correct and len(calls) > 1 else '-0.50'))
        def close(self):
            pass
    monkeypatch.setattr(worker, 'ChatLLM', lambda **kwargs: Model())
    monkeypatch.setattr(worker, 'build_swarm_registry', lambda *a, **kw: ToolRegistry())
    result = worker.run_worker(
        agent_spec=SwarmAgentSpec(id='pm', role='PM', system_prompt='Decide.',
            require_position_risk_table=True, max_iterations=iterations),
        task=SwarmTask(id='decision', agent_id='pm', prompt_template='Review.'),
        upstream_summaries={}, user_vars={}, run_dir=tmp_path,
    )
    assert result.status == expected
    assert len(calls) == min(2, iterations)
    if len(calls) > 1:
        assert 'requires -0.372%' in calls[1][-1]['content']


def test_real_preset_tools_available_without_shell():
    run = build_run_from_preset('investment_committee', {'target': 'NVDA', 'market': 'US'})
    for spec in run.agents:
        registry = worker.build_swarm_registry(spec.tools, include_shell_tools=False)
        assert registry.get('bash') is None
        assert registry.get('quantlib_call') is not None
        assert registry.get('technical_indicators') is not None
        prompt = worker.build_worker_prompt(spec, {}, '', available_tools=set(registry.tool_names))
        assert 'bash python script.py' not in prompt
        if spec.id == 'portfolio_manager':
            assert spec.require_position_risk_table
            assert TABLE_HEADER in prompt
        result = json.loads(registry.execute('quantlib_call', {
            'action': 'call', 'module': 'risk', 'function': 'historical_var',
            'kwargs': {'returns': [-.03, .01, -.01, .02, -.02], 'confidence': .95},
        }))
        assert result['ok']
        assert result['result'] == pytest.approx(.03)


def test_mc_summary_reaches_shell_free_tool_without_large_matrix():
    from src.tools.quantlib_tool import QuantlibCallTool
    from src.quantlib.risk import monte_carlo_gbm, analyze_mc_results
    tool = QuantlibCallTool()
    args = dict(s0=100, mu=.03, sigma=.25, n_steps=63, n_paths=10000, seed=13)
    response = json.loads(tool.execute(action='call', module='risk', function='monte_carlo_summary', kwargs=args))
    assert response['ok'], response
    assert len(json.dumps(response)) < 3000
    expected = analyze_mc_results(monte_carlo_gbm(**args))
    assert response['result']['statistics'] == expected
    assert response['result']['n_paths'] == 10000
    assert response['result']['seed'] == 13
